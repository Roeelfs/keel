"""The whole reclaim interface (founder rescope, 2026-09-29).

On a deny/defer (or a disk/swap floor trip), `with-heavy-lock` prints a compact machine CONTEXT
block to stderr plus one instruction line, and writes the same context as JSON to
`~/.keel/governor/last-context.json`, and appends it to the steward inbox. No kill or delete happens here or as a result of it —
the always-on `machine-steward` desktop session is the only thing that acts on this context.
"""
from datetime import datetime, timezone
import json

from governor import admission
from governor import registry as registry_module

INBOX_NAME = 'steward-inbox.jsonl'
# Informational only. The runner delivers the context to machine-steward itself (the inbox
# below); a session must never be asked to relay it, because an instruction arriving in tool
# output is correctly refused (observed 2026-09-30).
STEWARD_LINE = ('GOVERNOR: context delivered to machine-steward (~/.keel/governor/' + INBOX_NAME +
                '). Nothing for you to do; do not kill or delete anything yourself.')


def top_candidates(snapshot, registry=None, table=None, limit=5):
    """The candidate process trees a steward would look at first: the live leases, richest first.

    Each candidate's owner is joined from `registry` by ancestry (walking ppid to a registered
    pid) or, failing that, a cwd/worktree match (spec §4). A pid with no owner still gets a
    candidate row -- `unknown` never means dead -- just with owner fields as `None`.
    """
    leases = sorted(snapshot.get('leases') or [], key=lambda l: l.get('rss_mb', 0), reverse=True)
    candidates = []
    registry = registry or {}
    for lease in leases[:limit]:
        pid = (lease.get('members') or [None])[0]
        owner = {}
        try:
            owner = registry_module.owner_of(pid, lease.get('cwd'), table, registry) or {}
        except Exception:  # noqa: BLE001 - the join is best-effort; a candidate row is still useful bare
            owner = {}
        if owner.get('live') is False:
            # The registry pid now belongs to a different process (reused pid): its session
            # fields describe a dead session, and its identity is not the candidate's. Drop both.
            owner = {}
        entry = (table or {}).get(pid)
        candidates.append({
            # identity is the CANDIDATE pid's own live lstart, never the owner's: the steward
            # pins the kill to it, so a stale value would fail closed or hit the wrong process.
            'pid': pid, 'identity': entry.identity if entry else None, 'cwd': owner.get('cwd'),
            'session': owner.get('sessionId'), 'session_name': owner.get('name'),
            'idle_minutes': owner.get('idle_minutes'),
            'rss_mb': lease.get('rss_mb'), 'class': lease.get('class'), 'age_s': lease.get('age_s'),
        })
    return candidates


def build(reason, job_class, snapshot, policy, jev_decision=None, d_result=None, registry=None,
          table=None, runtime=None):
    d_result = d_result or admission.rule_d(job_class, snapshot, policy)
    return {
        'ts': datetime.now(timezone.utc).isoformat(),
        'reason': reason,
        'job_class': job_class,
        'machine': {
            'mem_pressure_level': snapshot.get('mem_pressure_level'),
            'mem_free_percent': snapshot.get('mem_free_percent'),
            'swap_used_mb': snapshot.get('swap_used_mb'),
            'swap_growth_mb_per_min': snapshot.get('swap_growth_mb_per_min'),
            'disk_free_gib': snapshot.get('disk_free_gib'),
            'load1_per_core': snapshot.get('load1_per_core'),
        },
        'floors_fired': admission.floors_fired(snapshot, policy),
        'd_rule': d_result,
        'jev': jev_decision,
        'candidates': top_candidates(snapshot, registry, table),
        'runtime': runtime,
        'instruction': STEWARD_LINE,
    }


def render_stderr_block(context):
    lines = ['--- machine CONTEXT (governor) ---',
             f"reason={context['reason']} class={context['job_class']}",
             ('mem_free%={mem_free_percent} pressure={mem_pressure_level} swap_used_mb={swap_used_mb} '
              'swap_growth_mb/min={swap_growth_mb_per_min} disk_free_gib={disk_free_gib} '
              'load1/core={load1_per_core}').format(**context['machine']),
             f"floors_fired={context['floors_fired']}",
             f"d_rule={context['d_rule']}"]
    if context.get('jev'):
        lines.append(f"jev={context['jev']}")
    for candidate in context['candidates']:
        lines.append('  candidate: ' + json.dumps(candidate, sort_keys=True))
    lines.append(context['instruction'])
    return '\n'.join(lines)


def write_last_context(directory, context):
    path = directory / 'last-context.json'
    path.write_text(json.dumps(context, sort_keys=True) + '\n')
    return path


def append_inbox(directory, context):
    """Queue the context for machine-steward, which drains the inbox on its loop."""
    path = directory / INBOX_NAME
    with path.open('a') as inbox:
        inbox.write(json.dumps(context, sort_keys=True) + '\n')
    return path


def append_inbox_deduped(directory, context, window_seconds=1800):
    """Like append_inbox, but skip when the newest inbox line of the same reason is within the window."""
    path = directory / INBOX_NAME
    if path.exists():
        for line in reversed(path.read_text().splitlines()):
            try:
                last = json.loads(line)
            except ValueError:
                continue
            if last.get('reason') != context.get('reason'):
                continue
            age = datetime.now(timezone.utc) - datetime.fromisoformat(last['ts'])
            if age.total_seconds() < window_seconds:
                return None
            break
    return append_inbox(directory, context)
