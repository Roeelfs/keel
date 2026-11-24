"""Read-only inventory of the heavy slots: held slots and live queue tickets.

The one counting rule shared by acquisition (`heavy_runner.acquire`), the callers around
`claim_slot`, `--admit-preview`, `--cpu-check` and the governor snapshot, so their views of
"running" and "queued" can never disagree.

Nothing here creates, rewrites or deletes a file. Dead-ticket cleanup belongs to acquisition
(`heavy_runner.prune_tickets`) only; a preview that pruned tickets would be a hidden writer.
"""
import fcntl
import os
import time

from heavy_resources import MAX_SLOTS, job_members, processes, read_record


def slot_path(directory, slot):
    return directory / f'slot.{slot}'


def lease_path(directory, slot):
    return directory / f'lease.{slot}.json'


def lock_available(directory, slot):
    """True when nobody holds slot `slot`'s flock. A missing slot file was never opened, so it is free.

    Opens read-only and never creates the file (flock does not need a writable descriptor).
    """
    try:
        descriptor = os.open(slot_path(directory, slot), os.O_RDONLY)
    except FileNotFoundError:
        return True
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False
    finally:
        os.close(descriptor)


def lease_group_alive(lease):
    # A job outlives a killed supervisor as the live processes of its session, whatever their group.
    # A lease from an older runner has no leader identity; its pgid is still the session it started.
    return bool(lease and job_members(lease.get('pgid'), lease.get('leader_identity'), processes()))


def held_slots(directory):
    """Every slot (not only the policy's) whose flock is held or whose job group is still alive.

    This is `claim_slot`'s held count: a lowered ceiling still accounts for jobs admitted under the
    previous policy, and a zero-member lease in an unlocked slot is not a running job.
    """
    return [slot for slot in range(1, MAX_SLOTS + 1)
            if not lock_available(directory, slot) or lease_group_alive(read_record(lease_path(directory, slot)))]


def running_job_count(directory):
    """Held heavy slots: the one `running_jobs` figure the lock, --cpu-check and the preview share."""
    return len(held_slots(directory))


def heartbeat(path):
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def ticket_liveness(queue):
    """(live, dead) queue tickets, each sorted. A dead ticket is a dead waiter, a reused pid or unreadable."""
    # List tickets before sampling processes: every listed writer existed before the sample.
    paths = sorted(queue.glob('*.json'))
    table = processes()
    live, dead = [], []
    for path in paths:
        try:
            ticket = read_record(path)
        except (OSError, ValueError):
            ticket = None
        pid = ticket.get('pid') if ticket else None
        owner = table.get(pid) if isinstance(pid, int) else None
        alive = owner and not owner.state.startswith('Z') and owner.identity == ticket.get('identity')
        (live if alive else dead).append(path)
    return live, dead


def live_tickets(queue):
    return ticket_liveness(queue)[0]


def fresh_after(policy, now=None):
    """A waiter whose heartbeat is older than this has stalled (6 polls, at least 3 s)."""
    return (time.time() if now is None else now) - max(3, 6 * policy.poll_seconds)


def contending(live, fresh):
    """Live tickets that compete for the next slot: fresh, and not yielding.

    A stalled waiter is skipped, never deleted; a yielding one (refused for memory) lets a smaller
    job behind it take the slot it cannot use.
    """
    return [path for path in live if heartbeat(path) >= fresh and not (read_record(path) or {}).get('yield')]

