"""Up to `slots` machine-wide heavy jobs, each observed as its complete process tree."""
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

from heavy_resources import (MAX_SLOTS, account_home, ancestors, command_seconds, event, free_percent,
                             job_members, load_policy, processes, read_record, total_memory_mb, write_record)

QUEUE_PROGRESS_SECONDS = 30


def state_directory():
    path = account_home() / '.keel/heavy.slots'
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def slot_path(directory, slot):
    return directory / f'slot.{slot}'


def lease_path(directory, slot):
    return directory / f'lease.{slot}.json'


def lock_available(directory, slot):
    with slot_path(directory, slot).open('a') as stream:
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
    # Every possible slot, not only the policy's: a lowered policy must not orphan a nested call.
    for slot in range(1, MAX_SLOTS + 1):
        lease = read_record(lease_path(directory, slot))
        if lease and lease.get('job_id') == os.environ.get('KEEL_HEAVY_JOB_ID'):
            break
    else:
        return False
    table = processes()
    owner = table.get(lease.get('supervisor_pid'))
    return bool(owner and owner.identity == lease.get('supervisor_identity')
                and owner.pid in ancestors(os.getpid(), table)
                and not lock_available(directory, slot))


JEV_FLOOR_MARGIN_PERCENT = 2  # a JEV admit may never push free memory within this of the run floor
YIELD_MAX_SECONDS = 300  # a memory-refused waiter lets smaller jobs pass for at most this long


def pressure_reason(policy, others_held, budget_mb=None, jev_admit=False):
    """A job alone needs min_free_percent. Beside others it needs that much left after ITS budget.

    `budget_mb` is the job's own class p90 RSS (2026-09-30: a flat `max_rss_mb` of 6 GB for every
    job, including 1 GB vitest runs, left one slot usable on a 24 GB machine). When the fit test
    fails, a fresh JEV admit (`jev_admission=enforce`) may still admit -- but never past
    `run_min_free_percent + JEV_FLOOR_MARGIN_PERCENT`, the line below which running jobs are
    interrupted. Swap/disk floors are enforced by the caller before this point.
    """
    if not policy.min_free_percent:
        return None
    free = free_percent()
    if free < policy.min_free_percent:
        return 'memory_pressure'
    if not others_held:
        return None
    budget = min(budget_mb or policy.max_rss_mb, policy.max_rss_mb)
    after = free - 100 * budget / total_memory_mb()
    if after >= policy.min_free_percent:
        return None
    if jev_admit and after >= policy.run_min_free_percent + JEV_FLOOR_MARGIN_PERCENT:
        return None
    return 'memory_pressure'


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


def first_lease(directory, policy):
    for slot in range(1, policy.slots + 1):
        lease = read_record(lease_path(directory, slot))
        if lease:
            return lease
    return None


def holder_fields(directory, policy):
    try:
        lease = first_lease(directory, policy)
    except (OSError, ValueError):  # The lease can vanish or change during a handoff.
        return None
    return {'executable': lease.get('executable'), 'cwd': lease.get('cwd')} if lease else {}


def holder_description(directory, policy):
    holder = holder_fields(directory, policy)
    if holder is None:
        return 'slot holder unknown'
    if not holder:
        return 'no published slot holder'
    return 'slot held by ' + str(holder['executable']) + ' in ' + str(holder['cwd'])


def caller_runtime():
    # The nearest agent runtime above this process, so a deferral can be traced to the session that asked.
    try:
        result = subprocess.run(['ps', '-axo', 'pid=,ppid=,comm='], text=True, capture_output=True,
                                check=True, timeout=5, env={**os.environ, 'LC_ALL': 'C'})
    except (OSError, subprocess.SubprocessError):
        return None
    parents = {}
    for line in result.stdout.splitlines():
        fields = line.split(None, 2)
        if len(fields) == 3 and fields[0].isdigit() and fields[1].isdigit():
            parents[int(fields[0])] = (int(fields[1]), os.path.basename(fields[2]).lower())
    pid, seen = os.getppid(), set()
    while pid in parents and pid not in seen:
        seen.add(pid)
        parent, name = parents[pid]
        if name == 'claude':
            return 'claude'
        if name.startswith('codex'):
            return 'codex'
        pid = parent
    return None


def working_directory():
    try:
        return os.getcwd()
    except OSError:  # A deleted cwd; the job itself refuses later, the record must not.
        return None


def claim_slot(directory, policy, position, budget_mb=None, jev_admit=False):
    """Lock the first free slot when no more waiters are ahead than there are free slots.

    Returns (stream, slot) or (None, reason). A slot is free when its lock is available and no
    job from a killed supervisor still runs in it.
    """
    free = []
    orphaned = 0
    try:
        for slot in range(1, policy.slots + 1):
            stream = slot_path(directory, slot).open('a')
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                stream.close()
                continue
            free.append((stream, slot))  # Closed by the finally below if the lease cannot be read.
            if lease_group_alive(read_record(lease_path(directory, slot))):
                free.pop()[0].close()
                orphaned += 1
        if position > len(free):
            return None, 'previous_job_alive' if position <= len(free) + orphaned else 'resource_busy'
        others_held = len(free) < policy.slots  # Read while every free slot is still locked here.
        stream, slot = free.pop(0)
        for other, _ in free:
            other.close()
        free = []
        reason = pressure_reason(policy, others_held, budget_mb=budget_mb, jev_admit=jev_admit)
        if reason:
            stream.close()
            return None, reason
        return stream, slot
    finally:
        for stream, _ in free:
            stream.close()


def announce_governor_context(directory, reason, command, policy):
    """The whole reclaim interface (2026-09-29 founder rescope): a compact CONTEXT block to stderr

    plus one instruction line, on every deny/defer. Read-only and best-effort: any failure here
    (missing governor package, a slow probe, a permission error) is swallowed so a deferral is
    never turned into a crash. No kill or delete ever happens as a result of this call.
    """
    try:
        from governor import admission, context, registry as governor_registry
        from governor.state import governor_directory
        from governor.snapshot import take as take_snapshot
        governor_dir = governor_directory()
        snapshot = take_snapshot(governor_dir, directory)
        job_class = Path(command[0]).name if command else 'other-heavy'
        table = processes()
        try:
            registry = governor_registry.build(table=table)
        except Exception:  # noqa: BLE001 - the registry join is best-effort; bare pids still work
            registry = {}
        from governor import jev_client
        # The verdict the queued-time consult (consult_jev) cached for this class, if any.
        jev_decision = jev_client._cached_decision(governor_dir, job_class, time.time(), policy.wait_seconds)
        built = context.build(reason, job_class, snapshot, policy, jev_decision=jev_decision,
                              registry=registry, table=table, runtime=caller_runtime())
        print(context.render_stderr_block(built), file=sys.stderr)
        context.write_last_context(governor_dir, built)
        context.append_inbox(governor_dir, built)
        event(directory, 'governor_decision', job_id=None, reason=reason,
              floors_fired=built['floors_fired'], d_rule=built['d_rule'], jev=jev_decision, enforced=False)
    except Exception as error:  # noqa: BLE001 - this path must never turn a deferral into a crash
        print(f'with-heavy-lock: governor context unavailable ({type(error).__name__}: {error})',
              file=sys.stderr)


def consult_jev(directory, job_id, command, policy):
    """Ask JEV once, when a job first finds itself queued (the contended acquire).

    Records rule D's and JEV's verdicts side by side as a `governor_decision` event (stage
    `queued`) so shadow mode can be graded, and fills the per-class cache `admit_preview` and the
    deferral CONTEXT read. Never changes this job's admission: the slot loop above is the only
    arbiter until `jev_admission=enforce`. Best-effort; never raises. Runs on a daemon thread (see
    `start_jev_consult`) so a JEV call of up to `jev_deadline_ms` never stalls the ticket heartbeat.
    """
    try:
        from governor import admission, jev_client
        from governor.state import governor_directory
        from governor.snapshot import take as take_snapshot
        governor_dir = governor_directory()
        snapshot = take_snapshot(governor_dir, directory, persist=False)
        job_class = Path(command[0]).name if command else 'other-heavy'
        floors = admission.floors_fired(snapshot, policy)
        d_result = admission.rule_d(job_class, snapshot, policy)
        jev_decision = None
        if not floors:
            jev_client.refresh_credential(governor_dir)
            jev_decision = jev_client.decide(job_class, snapshot, policy, governor_dir)
        event(directory, 'governor_decision', job_id=job_id, reason='contended', stage='queued',
              job_class=job_class, floors_fired=floors, d_rule=d_result, jev=jev_decision,
              enforced=policy.jev_admission == 'enforce')
    except Exception as error:  # noqa: BLE001 - a failed consult must never touch the job
        print(f'with-heavy-lock: JEV consult unavailable ({type(error).__name__}: {error})',
              file=sys.stderr)


def queue_position(live, ticket, fresh_after):
    """1 + the live, fresh, NON-yielding tickets ahead. A yielding ticket (refused for memory,
    within YIELD_MAX_SECONDS) lets a smaller job behind it take the slot it cannot use."""
    return 1 + sum(1 for path in live if path < ticket and heartbeat(path) >= fresh_after
                   and not (read_record(path) or {}).get('yield'))


def job_budget_mb(command, policy):
    """This job's memory budget: its class's measured p90 RSS, capped at `max_rss_mb`.

    An unmodeled class (fewer than 10 completions; `class_row` falls back to `other-heavy`) or any
    read failure keeps the conservative flat `max_rss_mb`. Returns a number, never None, so the
    caller reads the event log at most once per job.
    """
    try:
        from governor import admission
        from governor.state import governor_directory
        from governor.snapshot import take as take_snapshot
        snapshot = take_snapshot(governor_directory(), state_directory(), persist=False)
        job_class = Path(command[0]).name if command else 'other-heavy'
        p90 = admission.class_row(snapshot.get('class_stats') or {}, job_class).get('rss_p90_mb')
        return min(float(p90), float(policy.max_rss_mb)) if p90 else float(policy.max_rss_mb)
    except Exception:  # noqa: BLE001 - a budget read failure must fall back, never block admission
        return float(policy.max_rss_mb)


def jev_admits(command, policy):
    """A fresh cached JEV admit for this job's class, honoured only under `jev_admission=enforce`."""
    if policy.jev_admission != 'enforce':
        return False
    try:
        from governor import jev_client
        from governor.state import governor_directory
        job_class = Path(command[0]).name if command else 'other-heavy'
        cached = jev_client._cached_decision(governor_directory(), job_class, time.time(), policy.decision_ttl_s)
        return bool(cached and cached.get('admit') and cached.get('source') == 'jev')
    except Exception:  # noqa: BLE001 - no verdict is simply no JEV admit
        return False


def start_jev_consult(directory, job_id, command, policy):
    import threading
    thread = threading.Thread(target=consult_jev, args=(directory, job_id, command, policy), daemon=True)
    thread.start()
    return thread


def acquire(directory, policy, job_id, command):
    queue = directory / 'queue'
    queue.mkdir(exist_ok=True, mode=0o700)
    started = time.monotonic()
    deadline = started + policy.wait_seconds
    owner = processes()[os.getpid()]
    ticket = queue / f'{time.time_ns():020d}-{owner.pid}.json'
    # 'class' lets admit_preview price the queue by what is actually waiting, not by the caller.
    record = {'pid': owner.pid, 'identity': owner.identity, 'job_id': job_id, 'enqueued': time.time(),
              'class': Path(command[0]).name if command else 'other-heavy'}
    event(directory, 'queued', job_id=job_id, pid=os.getpid(), cwd=working_directory(),
          executable=Path(command[0]).name, args=event_args(command),
          wait_seconds=policy.wait_seconds, caller=caller_runtime())
    progress_at = None
    budget_mb = None  # this job's class p90 RSS, read once on the first real claim attempt
    last_consult = time.monotonic()  # the first JEV consult starts with the first QUEUED line
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
            # Skip, never delete, a live waiter whose heartbeat stalled -- or one that is yielding
            # (refused for memory, so a smaller job behind it may use the slot it cannot).
            fresh_after = time.time() - max(3, 6 * policy.poll_seconds)
            position = queue_position(live, ticket, fresh_after)
            reason = 'resource_busy'
            if position <= policy.slots:  # A waiter behind every slot's worth of waiters cannot be next.
                if budget_mb is None:
                    budget_mb = job_budget_mb(command, policy)
                stream, claimed = claim_slot(directory, policy, position, budget_mb=budget_mb,
                                             jev_admit=jev_admits(command, policy))
                if stream:
                    return stream, claimed
                reason = claimed
                if reason == 'memory_pressure' and time.monotonic() - last_consult >= policy.decision_ttl_s:
                    start_jev_consult(directory, job_id, command, policy)  # refresh the grey-zone verdict
                    last_consult = time.monotonic()
            yielding = reason == 'memory_pressure' and time.monotonic() - started < YIELD_MAX_SECONDS
            if bool(record.get('yield')) != yielding:
                record = {**record, 'yield': yielding}
                write_record(ticket, record)
            now = time.monotonic()
            if now >= deadline:
                event(directory, 'deferred', job_id=job_id, reason=reason,
                      waited_seconds=round(now - started, 1), wait_seconds=policy.wait_seconds,
                      position=position, holder=holder_fields(directory, policy))
                print('with-heavy-lock: DEFERRED (' + reason + '); no command started. '
                      'Do not retry unchanged or treat this as test success. No CI push is authorized.',
                      file=sys.stderr)
                announce_governor_context(directory, reason, command, policy)
                return None
            if progress_at is None or now >= progress_at:
                if progress_at is None:
                    start_jev_consult(directory, job_id, command, policy)
                label = 'QUEUED' if progress_at is None else 'still QUEUED'
                waited = '' if progress_at is None else f' after {now - started:.0f}s'
                print(f'with-heavy-lock: {label} at position {position}{waited}; '
                      f'{holder_description(directory, policy)}; waiting up to {policy.wait_seconds:g}s.',
                      file=sys.stderr)
                progress_at = now + QUEUE_PROGRESS_SECONDS
            time.sleep(min(policy.poll_seconds, max(0, deadline - time.monotonic())))
    finally:
        ticket.unlink(missing_ok=True)
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
            'KEEL_HEAVY_TURBO_CONCURRENCY': str(int(policy.turbo_concurrency)),
            'NODE_OPTIONS': options.strip()}


class Job:
    """The supervised command, observed as every live process of the session it leads."""

    def __init__(self, root, lease_path, lease):
        self.root = root
        self.lease_path = lease_path
        self.lease = lease
        self.recorded = None  # The member list last written; None until the lease is published.
        self.lease_error = None

    def members(self):
        table = processes()
        if 'leader_identity' not in self.lease:  # First sample: the child is still behind its gate.
            self.lease = {**self.lease, 'leader_identity': table[self.root].identity}
        members = job_members(self.root, self.lease['leader_identity'], table)
        recorded = sorted([p.pid, p.pgid, p.identity] for p in members)
        if recorded != self.recorded:
            try:
                write_record(self.lease_path, {**self.lease, 'members': recorded})
            except OSError as error:
                # Best-effort: a lease that cannot be rewritten must never stop the job from being budgeted
                # or stopped. Liveness reads the session, so a stale member list still guards the slot.
                if str(error) != self.lease_error:
                    print('with-heavy-lock: lease update failed; still supervising: ' + str(error), file=sys.stderr)
                self.lease_error = str(error)
            else:
                self.recorded = recorded
                self.lease_error = None
        return members

    def sampled(self):
        try:
            return self.members()
        except (OSError, subprocess.SubprocessError, ValueError, KeyError):
            return None  # Unknown, never "gone".

    def stop(self):
        """TERM, a grace period, KILL, then up to 2 s for the job to vanish.

        Returns the members still alive afterwards, or None when sampling failed and survival is unknown.
        """
        for sig in (signal.SIGTERM, signal.SIGKILL):
            members = self.sampled()  # Re-sampled: catches processes started during the grace period.
            if members == []:
                return []
            if members is None:
                print('with-heavy-lock: process sample failed; signalling the job group', file=sys.stderr)
                try:
                    os.killpg(self.root, sig)
                except (ProcessLookupError, PermissionError):
                    pass
            else:
                signal_members(members, self.root, sig)
            if sig == signal.SIGTERM:
                time.sleep(0.3)
        # A process forked after the last sample, or stuck in uninterruptible I/O, can outlive KILL.
        deadline = time.monotonic() + 2
        while True:
            survivors = self.sampled()
            if survivors == [] or time.monotonic() >= deadline:
                return survivors
            time.sleep(0.1)


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


SAMPLE_BLIND_SECONDS = 60


def newer_job_running(directory, lease):
    """Whether a job started after this one still has a live supervisor to stop it under pressure."""
    try:
        table = processes()
        for slot in range(1, MAX_SLOTS + 1):
            other = read_record(lease_path(directory, slot))
            if not other or other.get('job_id') == lease['job_id']:
                continue
            supervisor = table.get(other.get('supervisor_pid'))
            if (supervisor and supervisor.identity == other.get('supervisor_identity')
                    and other.get('started_ns', 0) > lease['started_ns']):
                return True
    except (OSError, ValueError, subprocess.SubprocessError):
        return False  # Unknown: stop this job, as a single job would be stopped.
    return False


def supervise(child, job, policy, max_seconds, directory, job_id, interruption):
    started = time.monotonic()
    peak = 0.0
    low_since = None
    blind_since = None
    while True:
        if interruption():
            raise InterruptedError(interruption())
        # `ps` can time out or be signalled under load. That says nothing about the job, so a failed
        # sample keeps supervising; only sustained blindness means the job can no longer be budgeted.
        members = job.sampled()
        now = time.monotonic()
        if members is None:
            if blind_since is None:
                blind_since = now
                print('with-heavy-lock: process sample failed; still supervising', file=sys.stderr)
            if now - blind_since >= SAMPLE_BLIND_SECONDS:
                raise OSError('process sampling failed for '
                              f'{SAMPLE_BLIND_SECONDS:g}s; the job cannot be budgeted')
            time.sleep(policy.poll_seconds)
            continue
        blind_since = None
        rss = sum(p.rss_mb for p in members)
        peak = max(peak, rss)
        # Admission checks free memory once; sustained host pressure during the run stops it too.
        sample = observed_free_percent() if members and policy.run_min_free_percent else None
        low = sample is not None and sample < policy.run_min_free_percent
        low_since = (now if low_since is None else low_since) if low else None
        if low and now - low_since >= policy.run_pressure_seconds and newer_job_running(directory, job.lease):
            low_since = now  # The newest job is stopped first; this one gets a fresh window after it goes.
        reason = ('resource_limit' if rss > policy.max_rss_mb else
                  'wall_time_budget' if now - started > max_seconds else
                  'memory_pressure_during_run' if low and now - low_since >= policy.run_pressure_seconds
                  else None)
        if reason:
            survivors = job.stop()
            child.wait(timeout=5)
            budget = {'budget_seconds': max_seconds} if reason == 'wall_time_budget' else {}
            if survivors != []:
                budget['survivors'] = 'unknown' if survivors is None else len(survivors)
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


def event_args(command):
    # Enough to tell `verify --quick` from `verify`; an argument that may carry a secret is not recorded.
    return ['<redacted>' if '=' in arg or len(arg) > 120 else arg for arg in command[1:4]]


def run_job(command, directory, policy, job_id, stream, slot):
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
                 'cwd': os.getcwd(), 'executable': Path(command[0]).name, 'slot': slot}
        # The start time orders jobs for run-time pressure; the started event already has its own `ts`.
        job = Job(child.pid, lease_path(directory, slot), {**lease, 'started_ns': time.time_ns()})
        job.members()  # Publishes the lease with the gated child's identity.
        if job.recorded is None:
            raise OSError('the resource lease could not be published')  # Never run a job without one.
        event(directory, 'started', **lease, args=event_args(command), policy=asdict(policy))
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
        survivors = job.stop() if job is not None else []
        if child is not None:
            child.wait(timeout=5)
        if survivors == []:
            try:
                lease_path(directory, slot).unlink(missing_ok=True)
            except OSError as error:
                print('with-heavy-lock: lease could not be removed: ' + str(error), file=sys.stderr)
        else:
            # The session check keeps the slot busy until they exit; the next admission then reclaims it.
            count = 'an unknown number of' if survivors is None else str(len(survivors))
            print(f'with-heavy-lock: {count} job processes outlived SIGKILL; the lease is kept until they exit.',
                  file=sys.stderr)
        stream.close()
        for sig, handler in original_handlers.items():
            signal.signal(sig, handler)


def run_broker_if_wrapper(directory, policy, command):
    """Runs `command` with no slot when it is a top-level shell/`.sh` wrapper (spec §6).

    Only reached in `governor_mode=enforce` (§13's rollout marks the broker phase-1, not shadow).
    Returns the exit code, or None when `command` is not a wrapper (the caller falls through to
    the normal `acquire()` path).
    """
    from governor.broker import is_wrapper

    if not is_wrapper(command, policy, cwd=working_directory()):
        return None
    shim_dir = account_home() / '.keel' / 'resource-hooks' / 'shims'
    env = {**os.environ, 'PATH': str(shim_dir) + os.pathsep + os.environ.get('PATH', '')}
    started = time.monotonic()
    event(directory, 'broker_started', executable=Path(command[0]).name, args=event_args(command),
          cwd=working_directory())
    child = subprocess.Popen(command, env=env, start_new_session=True)
    try:
        code = child.wait(timeout=command_seconds(policy, command))
    except subprocess.TimeoutExpired:
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        code = child.wait(timeout=10)
    event(directory, 'broker_completed', executable=Path(command[0]).name, exit_code=code,
          duration_seconds=round(time.monotonic() - started, 1))
    return code


def admit_preview(directory, policy, job_class):
    """Read-only admission preview for cynap's `verify-route` (spec §7).

    Never queues (no ticket is written), never claims a slot (no flock is held past the read),
    and never makes a fresh live JEV call -- only a JEV verdict already cached by a real contended
    acquire informs it, so `verify-route`'s per-push preview volume can never drive JEV traffic.
    Any internal failure raises, so the caller (`main()`) fails closed to a non-zero exit -- that
    is what makes `verify-route`'s R4 ("preview unavailable") the safe default.

    Returns exactly the shape verify-route's `admitPreview()` consumes:
    `{decision, source, slots_now, running, queued, eta_wait_p90_s, eta_run_p50_s, eta_total_s}`.

    `job_class` may be a synthetic preview-only name (`cynap-verify-<mode>`) that never appears in
    a recorded lease/event; `admission.canonical_class()` is the one place that maps it to the
    executable it actually runs as (`cynap-sandbox`), so every `class_stats` lookup here goes
    through `admission.class_row()` rather than a raw dict `.get(job_class)`.
    """
    from governor import admission, jev_client
    from governor.state import governor_directory
    from governor.snapshot import take as take_snapshot

    governor_dir = governor_directory()
    snapshot = take_snapshot(governor_dir, directory, persist=False)
    running = len(snapshot.get('leases') or [])
    queued = snapshot.get('queued', 0)
    class_stats = snapshot.get('class_stats') or {}
    class_row = admission.class_row(class_stats, job_class)
    run_p50 = class_row.get('run_p50_s')
    run_p90 = class_row.get('run_p90_s')

    floors = admission.floors_fired(snapshot, policy)
    fast_reason = None if admission.any_unknown(snapshot) else pressure_reason(policy, running >= 1)

    cached_jev = None
    if not floors and running < policy.slots and fast_reason is None:
        decision, source, slots_now = 'admit', 'fast_path', policy.slots
    else:
        d_result = admission.cheap_class_bonus(
            job_class, snapshot, policy, admission.rule_d(job_class, snapshot, policy, running=running))
        source, slots_now, admit = 'd_rule', d_result['slots_now'], d_result['admit']
        if not floors:
            cached_jev = jev_client._cached_decision(governor_dir, job_class, time.time(), policy.decision_ttl_s)
        if policy.governor_mode != 'enforce':
            # Shadow: the slot loop admits only below the fixed `policy.slots` with no pressure
            # (the fast path above), so anything else really queues. Rule D and JEV are reported
            # for grading, never applied -- a preview that promised an admit the loop will not
            # honor would keep verify local behind a queue it never priced.
            decision, source, slots_now = 'deny', 'shadow_queue', policy.slots
        else:
            if cached_jev is not None and policy.jev_admission == 'enforce':
                admit = cached_jev.get('admit', admit)
                slots_now = cached_jev.get('slots_now', slots_now)
                source = cached_jev.get('source', 'jev_cache')
            decision = 'admit' if (admit and not floors) else 'deny'

    if decision == 'admit':
        eta_wait_p90_s = 0.0
    else:
        wait_candidates = []
        for lease in snapshot.get('leases') or []:
            lease_row = admission.class_row(class_stats, lease.get('class'))
            lease_p90 = lease_row.get('run_p90_s')
            if lease_p90 is not None:
                wait_candidates.append(max(0.0, lease_p90 - lease.get('age_s', 0)))
        if wait_candidates:
            min_wait = min(wait_candidates)
        elif running > 0:
            # A deny with running jobs but no per-class run-time data (a brand-new class, or a
            # cold class_stats before any job of this kind has ever completed) must not silently
            # report ETA 0 -- verify-route's R6 (ETA>600s -> CI) can never fire on a false 0
            # (live bug, 2026-09-29). `policy.wait_seconds` (with-heavy-lock's own queue timeout)
            # is the conservative, always-available floor for "unknown, but definitely not zero".
            min_wait = float(policy.wait_seconds)
        else:
            min_wait = 0.0
        # Price the queue by what is actually waiting: each ticket's own class p90, shared across
        # the slots that really drain it. A ticket with no recorded class (written before tickets
        # carried one) or an unmodeled class is priced as the caller's class, the old estimate.
        ahead = []
        for path in live_tickets(directory / 'queue'):
            ticket_class = (read_record(path) or {}).get('class')
            ahead.append(admission.class_row(class_stats, ticket_class).get('run_p90_s') if ticket_class else None)
        ahead += [None] * max(0, queued - len(ahead))
        queue_term = sum(p90 if p90 is not None else (run_p90 or 0) for p90 in ahead) / max(slots_now, 1)
        eta_wait_p90_s = min_wait + queue_term
    eta_run_p50_s = run_p50 if run_p50 is not None else 0.0
    eta_total_s = eta_wait_p90_s + eta_run_p50_s

    return {'decision': decision, 'source': source, 'slots_now': slots_now, 'running': running,
            'queued': queued, 'eta_wait_p90_s': round(eta_wait_p90_s, 1),
            'eta_run_p50_s': round(eta_run_p50_s, 1), 'eta_total_s': round(eta_total_s, 1),
            'jev': cached_jev}


def main():
    try:
        policy = load_policy()
        directory = state_directory()
        command = sys.argv[1:]
        if command == ['--status']:
            leases = []
            for slot in range(1, policy.slots + 1):
                lease = read_record(lease_path(directory, slot))
                live = not lock_available(directory, slot) or lease_group_alive(lease)
                leases.append({'slot': slot, 'live': live, 'lease': lease})
            print(json.dumps({**asdict(policy), 'live': any(entry['live'] for entry in leases),
                              'lease': next((entry['lease'] for entry in leases if entry['lease']), None),
                              'leases': leases, 'state_dir': str(directory)}))
            return 0
        if command == ['--check-lease']:
            return 0 if valid_lease(directory) else 75
        if command[:1] == ['--admit-preview']:
            try:
                job_class = command[command.index('--class') + 1]
            except (ValueError, IndexError):
                print('with-heavy-lock: --admit-preview requires --class <name>', file=sys.stderr)
                return 64
            try:
                result = admit_preview(directory, policy, job_class)
            except Exception as error:  # noqa: BLE001 - any failure here must fail closed (verify-route R4)
                print(f'with-heavy-lock: admit-preview unavailable: {type(error).__name__}: {error}',
                      file=sys.stderr)
                return 70
            print(json.dumps(result, sort_keys=True))
            return 0
        if command[:1] == ['--']:
            command = command[1:]
        if not command:
            print('usage: with-heavy-lock [--status|--check-lease] | COMMAND [ARGS...]', file=sys.stderr)
            return 64
        if valid_lease(directory):
            os.execvpe(command[0], command, child_environment(policy, os.environ['KEEL_HEAVY_JOB_ID']))
        if policy.governor_mode == 'enforce':
            broker_result = run_broker_if_wrapper(directory, policy, command)
            if broker_result is not None:
                return broker_result
        job_id = uuid.uuid4().hex
        try:
            claimed = acquire(directory, policy, job_id, command)
        except Interrupted as error:
            event(directory, 'interrupted', job_id=job_id, reason='signal', signal=error.args[0])
            return 128 + int(error.args[0])
        return run_job(command, directory, policy, job_id, *claimed) if claimed else 75
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print('with-heavy-lock: resource control unavailable; command refused: ' + str(error), file=sys.stderr)
        return 69


if __name__ == '__main__':
    raise SystemExit(main())
