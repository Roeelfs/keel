"""The whole reclaim interface (founder rescope, 2026-09-29).

On a deny/defer (or a disk/swap floor trip), `with-heavy-lock` prints a compact machine CONTEXT
block to stderr plus one instruction line, and writes the same context as JSON to
`~/.keel/governor/last-context.json`. No kill or delete happens here or as a result of it —
the always-on `machine-steward` desktop session is the only thing that acts on this context.
"""
from datetime import datetime, timezone
import json

from governor import admission
from governor import registry as registry_module

STEWARD_LINE = ('GOVERNOR: send this context to the "machine-steward" session via SendMessage '
                 '(to: "machine-steward") and continue; do not kill or delete anything yourself.')
# Codex has no SendMessage to reach the Claude desktop steward; it hands the context up instead.
CODEX_STEWARD_LINE = ('GOVERNOR: quote this context in your final report so it reaches the '
                      '"machine-steward" session, and continue; do not kill or delete anything yourself.')


def steward_line(runtime):
    return CODEX_STEWARD_LINE if runtime == 'codex' else STEWARD_LINE


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
        candidates.append({
            'pid': pid, 'identity': owner.get('identity'), 'cwd': owner.get('cwd'),
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
        'instruction': steward_line(runtime),
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
