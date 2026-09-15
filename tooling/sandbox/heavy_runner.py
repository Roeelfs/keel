"""One machine-wide heavy job, observed as its complete process tree."""
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

from heavy_resources import (account_home, ancestors, command_seconds, event, free_percent, job_members,
                             load_policy, processes, read_record, write_record)

QUEUE_PROGRESS_SECONDS = 30


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
    # A job outlives a killed supervisor as the live processes of its session, whatever their group.
    # A lease from an older runner has no leader identity; its pgid is still the session it started.
    return bool(lease and job_members(lease.get('pgid'), lease.get('leader_identity'), processes()))


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


class Interrupted(Exception):
    """A termination signal arrived while the job waited in the admission queue."""


def heartbeat(path):
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def live_tickets(queue):
    for temporary in queue.glob('*.tmp.*'):  # A writer interrupted mid-write leaves these behind.
        if time.time() - heartbeat(temporary) > 3600:
            temporary.unlink(missing_ok=True)
    # List tickets before sampling processes: every listed writer existed before the sample.
    paths = sorted(queue.glob('*.json'))
    table = processes()
    live = []
    for path in paths:
        try:
            ticket = read_record(path)
        except (OSError, ValueError):
            ticket = None
        pid = ticket.get('pid') if ticket else None
        owner = table.get(pid) if isinstance(pid, int) else None
        if owner and not owner.state.startswith('Z') and owner.identity == ticket.get('identity'):
            live.append(path)
        else:
            path.unlink(missing_ok=True)  # Dead waiter, reused pid, or unreadable ticket.
    return live


def holder_description(directory):
    try:
        lease = read_record(directory / 'lease.json')
    except (OSError, ValueError):  # The lease can vanish or change during a handoff.
        return 'slot holder unknown'
    if not lease:
        return 'no published slot holder'
    return 'slot held by ' + str(lease.get('executable')) + ' in ' + str(lease.get('cwd'))


def acquire(directory, policy, job_id):
    stream = (directory / 'slot.1').open('a')
    queue = directory / 'queue'
    queue.mkdir(exist_ok=True, mode=0o700)
    started = time.monotonic()
    deadline = started + policy.wait_seconds
    owner = processes()[os.getpid()]
    ticket = queue / f'{time.time_ns():020d}-{owner.pid}.json'
    record = {'pid': owner.pid, 'identity': owner.identity, 'job_id': job_id, 'enqueued': time.time()}
    event(directory, 'queued', job_id=job_id, pid=os.getpid())
    acquired = False
    progress_at = None
    handlers = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
    def interrupted(signum, _frame):
        raise Interrupted(signum)
    for sig in handlers:
        signal.signal(sig, interrupted)
    try:
        write_record(ticket, record)
        while True:
            try:
                os.utime(ticket)  # Heartbeat: a stopped or hung waiter stops refreshing its ticket.
            except FileNotFoundError:
                pass  # Restored below.
            live = live_tickets(queue)
            if ticket not in live:
                write_record(ticket, record)  # Restore a wrongly pruned ticket at its original place.
                live = sorted([*live, ticket])
            # Skip, never delete, a live waiter whose heartbeat stalled.
            fresh_after = time.time() - max(3, 6 * policy.poll_seconds)
            position = 1 + sum(1 for path in live if path < ticket and heartbeat(path) >= fresh_after)
            reason = 'resource_busy'
            if position == 1:  # Only the oldest live waiter may take the slot.
                try:
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    alive = lease_group_alive(read_record(directory / 'lease.json'))
                    reason = 'previous_job_alive' if alive else pressure_reason(policy)
                    if not reason:
                        acquired = True
                        return stream
                    fcntl.flock(stream, fcntl.LOCK_UN)
                except BlockingIOError:
                    reason = 'resource_busy'
            now = time.monotonic()
            if now >= deadline:
                event(directory, 'deferred', job_id=job_id, reason=reason)
                print('with-heavy-lock: DEFERRED (' + reason + '); no command started. '
                      'Do not retry unchanged or treat this as test success. No CI push is authorized.',
                      file=sys.stderr)
                return None
            if progress_at is None or now >= progress_at:
                label = 'QUEUED' if progress_at is None else 'still QUEUED'
                waited = '' if progress_at is None else f' after {now - started:.0f}s'
                print(f'with-heavy-lock: {label} at position {position}{waited}; '
                      f'{holder_description(directory)}; waiting up to {policy.wait_seconds:g}s.',
                      file=sys.stderr)
                progress_at = now + QUEUE_PROGRESS_SECONDS
            time.sleep(min(policy.poll_seconds, max(0, deadline - time.monotonic())))
    finally:
        ticket.unlink(missing_ok=True)
        if not acquired:
            stream.close()
        for sig, handler in handlers.items():
            signal.signal(sig, handler)


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


class Job:
    """The supervised command, observed as every live process of the session it leads."""

    def __init__(self, root, lease_path, lease):
        self.root = root
        self.lease_path = lease_path
        self.lease = lease
        self.recorded = None

    def members(self):
        table = processes()
        if 'leader_identity' not in self.lease:  # First sample: the child is still behind its gate.
            self.lease = {**self.lease, 'leader_identity': table[self.root].identity}
        members = job_members(self.root, self.lease['leader_identity'], table)
        recorded = sorted([p.pid, p.pgid, p.identity] for p in members)
        if recorded != self.recorded:
            self.recorded = recorded
            write_record(self.lease_path, {**self.lease, 'members': recorded})
        return members

    def stop(self):
        for sig in (signal.SIGTERM, signal.SIGKILL):
            members = self.members()  # Re-sampled: catches processes started during the grace period.
            if not members:
                return
            signal_members(members, self.root, sig)
            if sig == signal.SIGTERM:
                time.sleep(0.3)


def signal_members(members, root, sig):
    # A group is signalled whole only when it is the job's own or its leader is a member; any
    # other member is signalled by pid. Never this supervisor or its group.
    pids = {p.pid for p in members}
    groups = {p.pgid for p in members if p.pgid == root or p.pgid in pids} - {os.getpgrp()}
    targets = [(os.killpg, pgid) for pgid in sorted(groups)]
    targets += [(os.kill, p.pid) for p in members if p.pgid not in groups and p.pid != os.getpid()]
    for send, target in targets:
        try:
            send(target, sig)
        except (ProcessLookupError, PermissionError):
            pass  # Exited since the sample.


def observed_free_percent():
    # A failed sample counts as "not low": the observer must never stop a job or crash the supervisor.
    try:
        return free_percent()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError, OSError):
        return None


def supervise(child, job, policy, max_seconds, directory, job_id, interruption):
    started = time.monotonic()
    peak = 0.0
    low_since = None
    while True:
        if interruption():
            raise InterruptedError(interruption())
        members = job.members()
        rss = sum(p.rss_mb for p in members)
        peak = max(peak, rss)
        now = time.monotonic()
        # Admission checks free memory once; sustained host pressure during the run stops it too.
        sample = observed_free_percent() if members and policy.run_min_free_percent else None
        low = sample is not None and sample < policy.run_min_free_percent
        low_since = (now if low_since is None else low_since) if low else None
        reason = ('resource_limit' if rss > policy.max_rss_mb else
                  'wall_time_budget' if now - started > max_seconds else
                  'memory_pressure_during_run' if low and now - low_since >= policy.run_pressure_seconds
                  else None)
        if reason:
            job.stop()
            child.wait(timeout=5)
            budget = {'budget_seconds': max_seconds} if reason == 'wall_time_budget' else {}
            event(directory, 'completed', job_id=job_id, reason=reason,
                  peak_rss_mb=round(peak, 2), exit_code=137, **budget)
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
    job = None
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
        # The child is session and group leader: pgid and session id are both its pid.
        lease = {'job_id': job_id, 'supervisor_pid': owner.pid,
                 'supervisor_identity': owner.identity, 'pgid': child.pid,
                 'cwd': os.getcwd(), 'executable': Path(command[0]).name}
        job = Job(child.pid, directory / 'lease.json', lease)
        job.members()  # Publishes the lease with the gated child's identity.
        event(directory, 'started', **lease, policy=asdict(policy))
        if received_signal:
            raise InterruptedError(received_signal)
        os.write(gate_write, b'1')  # The job cannot run before its lease is published.
        os.close(gate_write)
        gate_write = None
        return supervise(child, job, policy, command_seconds(policy, command), directory, job_id,
                         lambda: received_signal)
    except InterruptedError as error:
        event(directory, 'interrupted', job_id=job_id, reason='signal', signal=error.args[0])
        return 128 + int(error.args[0])
    except Exception as error:
        if child is not None:  # The job started; close its record before the error propagates.
            event(directory, 'completed', job_id=job_id, reason='supervisor_error',
                  error=type(error).__name__ + ': ' + str(error))
        raise
    finally:
        # Ignore repeated interruption during owned-process cleanup.
        for sig in original_handlers:
            signal.signal(sig, signal.SIG_IGN)
        for descriptor in (gate_read, gate_write):
            if descriptor is not None:
                os.close(descriptor)
        if job is not None:
            job.stop()
        if child is not None:
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
        try:
            stream = acquire(directory, policy, job_id)
        except Interrupted as error:
            event(directory, 'interrupted', job_id=job_id, reason='signal', signal=error.args[0])
            return 128 + int(error.args[0])
        return run_job(command, directory, policy, job_id, stream) if stream else 75
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print('with-heavy-lock: resource control unavailable; command refused: ' + str(error), file=sys.stderr)
        return 69


if __name__ == '__main__':
    raise SystemExit(main())
