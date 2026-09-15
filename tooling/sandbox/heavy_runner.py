"""One machine-wide heavy job, observed as a complete process group."""
from dataclasses import asdict
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

from heavy_resources import (account_home, ancestors, event, free_percent, group_members,
                             load_policy, processes, read_record, write_record)


def state_directory():
    path = account_home() / '.keel/heavy.slots'
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def lock_available(directory):
    with (directory / 'slot.1').open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            return False


def lease_group_alive(lease):
    # A job outlives a killed supervisor only as its recorded process group.
    return bool(lease and group_members(lease.get('pgid'), processes()))


def valid_lease(directory):
    lease = read_record(directory / 'lease.json')
    if not lease or lease.get('job_id') != os.environ.get('KEEL_HEAVY_JOB_ID'):
        return False
    table = processes()
    owner = table.get(lease.get('supervisor_pid'))
    return bool(owner and owner.identity == lease.get('supervisor_identity')
                and owner.pid in ancestors(os.getpid(), table)
                and not lock_available(directory))


def pressure_reason(policy):
    if policy.min_free_percent and free_percent() < policy.min_free_percent:
        return 'memory_pressure'
    return None


def acquire(directory, policy, job_id):
    stream = (directory / 'slot.1').open('a')
    deadline = time.monotonic() + policy.wait_seconds
    reason = 'resource_busy'
    event(directory, 'queued', job_id=job_id, pid=os.getpid())
    while True:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            live = lease_group_alive(read_record(directory / 'lease.json'))
            reason = 'previous_job_alive' if live else pressure_reason(policy)
            if not reason:
                return stream
            fcntl.flock(stream, fcntl.LOCK_UN)
        except BlockingIOError:
            reason = 'resource_busy'
        if time.monotonic() >= deadline:
            stream.close()
            event(directory, 'deferred', job_id=job_id, reason=reason)
            print('with-heavy-lock: DEFERRED (' + reason + '); no command started. '
                  'Do not retry unchanged or treat this as test success. No CI push is authorized.',
                  file=sys.stderr)
            return None
        time.sleep(min(policy.poll_seconds, max(0, deadline - time.monotonic())))


def child_environment(policy, job_id):
    preload = Path(__file__).resolve().with_name('heavy_node.cjs')
    if not preload.is_file():
        raise ValueError('worker-cap preload is missing; refusing an uncapped job')
    node_options = os.environ.get('NODE_OPTIONS', '')
    # This is a per-process heap aid. The supervisor enforces aggregate RSS.
    require = '--require=' + json.dumps(str(preload))
    options = node_options if require in node_options else node_options + ' --max-old-space-size=2048 ' + require
    return {**os.environ, 'KEEL_HEAVY_LOCK_HELD': '1', 'KEEL_HEAVY_JOB_ID': job_id,
            'KEEL_HEAVY_MAX_WORKERS': str(int(policy.max_workers)),
            'NODE_OPTIONS': options.strip()}


def stop_group(pgid):
    for sig in (signal.SIGTERM, signal.SIGKILL):
        if not group_members(pgid, processes()):
            return
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return
        if sig == signal.SIGTERM:
            time.sleep(0.3)


def supervise(child, policy, directory, job_id, interruption):
    started = time.monotonic()
    peak = 0.0
    while True:
        if interruption():
            raise InterruptedError(interruption())
        table = processes()
        members = group_members(child.pid, table)
        rss = sum(p.rss_mb for p in members)
        peak = max(peak, rss)
        reason = ('resource_limit' if rss > policy.max_rss_mb else
                  'wall_time_budget' if time.monotonic() - started > policy.max_seconds else None)
        if reason:
            stop_group(child.pid)
            child.wait(timeout=5)
            event(directory, 'completed', job_id=job_id, reason=reason,
                  peak_rss_mb=round(peak, 2), exit_code=137)
            print(f'with-heavy-lock: {reason}; job peak {peak:.1f} MiB '
                  f'(budget {policy.max_rss_mb:g} MiB). Only this job was stopped.', file=sys.stderr)
            return 137
        code = child.poll()
        if code is not None and not members:
            result = code if code >= 0 else 128 - code
            event(directory, 'completed', job_id=job_id, reason='exit',
                  peak_rss_mb=round(peak, 2), exit_code=result)
            return result
        time.sleep(policy.poll_seconds)


def run_job(command, directory, policy, job_id, stream):
    child = None
    gate_read, gate_write = os.pipe()
    received_signal = 0
    original_handlers = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
    def interrupted(signum, _frame):
        nonlocal received_signal
        received_signal = signum
    for sig in original_handlers:
        signal.signal(sig, interrupted)
    try:
        owner = processes()[os.getpid()]
        bootstrap = Path(__file__).resolve().with_name('heavy_child.py')
        if not bootstrap.is_file():
            raise ValueError('job startup gate is missing')
        # Only the supervisor holds the slot: a daemon that leaves the group must not inherit it.
        child = subprocess.Popen([sys.executable, str(bootstrap), str(gate_read), *command],
                                 env=child_environment(policy, job_id), start_new_session=True,
                                 pass_fds=(gate_read,))
        os.close(gate_read)
        gate_read = None
        lease = {'job_id': job_id, 'supervisor_pid': owner.pid,
                 'supervisor_identity': owner.identity, 'pgid': child.pid,
                 'cwd': os.getcwd(), 'executable': Path(command[0]).name}
        write_record(directory / 'lease.json', lease)
        event(directory, 'started', **lease, policy=asdict(policy))
        if received_signal:
            raise InterruptedError(received_signal)
        os.write(gate_write, b'1')  # The job cannot run before its lease is published.
        os.close(gate_write)
        gate_write = None
        return supervise(child, policy, directory, job_id, lambda: received_signal)
    except InterruptedError as error:
        event(directory, 'interrupted', job_id=job_id, reason='signal', signal=error.args[0])
        return 128 + int(error.args[0])
    finally:
        # Ignore repeated interruption during owned-process cleanup.
        for sig in original_handlers:
            signal.signal(sig, signal.SIG_IGN)
        for descriptor in (gate_read, gate_write):
            if descriptor is not None:
                os.close(descriptor)
        if child is not None:
            stop_group(child.pid)
            child.wait(timeout=5)
        (directory / 'lease.json').unlink(missing_ok=True)
        stream.close()
        for sig, handler in original_handlers.items():
            signal.signal(sig, handler)


def main():
    try:
        policy = load_policy()
        directory = state_directory()
        command = sys.argv[1:]
        if command == ['--status']:
            lease = read_record(directory / 'lease.json')
            live = not lock_available(directory) or lease_group_alive(lease)
            print(json.dumps({**asdict(policy), 'live': live,
                              'lease': lease, 'state_dir': str(directory)}))
            return 0
        if command == ['--check-lease']:
            return 0 if valid_lease(directory) else 75
        if command[:1] == ['--']:
            command = command[1:]
        if not command:
            print('usage: with-heavy-lock [--status|--check-lease] | COMMAND [ARGS...]', file=sys.stderr)
            return 64
        if valid_lease(directory):
            os.execvpe(command[0], command, child_environment(policy, os.environ['KEEL_HEAVY_JOB_ID']))
        job_id = uuid.uuid4().hex
        stream = acquire(directory, policy, job_id)
        return run_job(command, directory, policy, job_id, stream) if stream else 75
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print('with-heavy-lock: resource control unavailable; command refused: ' + str(error), file=sys.stderr)
        return 69


if __name__ == '__main__':
    raise SystemExit(main())
