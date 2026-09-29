"""Rule D, the hard floors and the cheap-class +1 (spec §5.2, §5.3).

D is both the fallback and the shadow comparator for JEV (§5.4). Every input is read from
`Policy()` and a `class_stats` mapping — there are no literals here (§5.2, tested by the caller
reading defaults from `Policy()` directly).
"""
import math

OTHER_CLASS = 'other-heavy'

# Single source of truth for "synthetic" job classes that never appear in a recorded lease/event
# (they only exist as a `--class` argument to a read-only preview call). cynap's verify-route.mjs
# calls `--admit-preview --class cynap-verify-<mode>` (quick/full/...), but every real job it
# previews actually runs as the `cynap-sandbox` executable -- that is the name every `queued`/
# `started`/`completed` event and every lease is recorded under (spec §7). Without this map, a
# `cynap-verify-*` lookup always misses class_stats and silently falls through to `other-heavy`,
# which can itself be empty -- reported live 2026-09-29 as `eta_*_s: 0.0` on a real deny.
CLASS_ALIASES_PREFIXES = (('cynap-verify-', 'cynap-sandbox'),)


def canonical_class(job_class):
    """Map a synthetic preview-only class name to the executable it is actually recorded under."""
    for prefix, target in CLASS_ALIASES_PREFIXES:
        if job_class and job_class.startswith(prefix):
            return target
    return job_class


def class_row(class_stats, job_class):
    row = class_stats.get(job_class) or class_stats.get(canonical_class(job_class))
    if not row or row.get('n', 0) < 10:
        row = class_stats.get(OTHER_CLASS)
    return row or {}


def reserve_mb(leases, class_stats):
    """Sum, over live leases, of each job's not-yet-reached peak (§5.2)."""
    total = 0.0
    for lease in leases:
        row = class_row(class_stats, lease.get('class'))
        p90 = row.get('rss_p90_mb')
        if p90 is None:
            continue
        total += max(0.0, p90 - lease.get('rss_mb', 0.0))
    return total


def rule_d(job_class, snapshot, policy, running=None):
    """Returns {slots_now, admit, fit, reserve_mb} — the deterministic contended-path arbiter."""
    class_stats = snapshot.get('class_stats') or {}
    row = class_row(class_stats, job_class)
    p90_rss = row.get('rss_p90_mb')
    leases = snapshot.get('leases') or []
    running = len(leases) if running is None else running
    free_pct = snapshot.get('mem_free_percent')
    mem_total = snapshot.get('mem_total_mb')
    if free_pct is None or mem_total is None or not p90_rss:
        # An unknown/unmodeled input never admits past today's fixed policy on the contended path.
        return {'slots_now': running, 'admit': False, 'fit': 0, 'reserve_mb': None}
    reserve = reserve_mb(leases, class_stats)
    headroom_mb = (free_pct - policy.min_free_percent) / 100 * mem_total - reserve
    fit = math.floor(headroom_mb / p90_rss)
    slots_now = min(max(running + fit, 1), policy.max_slots)
    admit = running < slots_now
    return {'slots_now': slots_now, 'admit': admit, 'fit': fit, 'reserve_mb': reserve}


def cheap_class_bonus(job_class, snapshot, policy, d_result):
    """A cheap-RSS-seconds class may take one extra slot when no floor fired (§5.2)."""
    class_stats = snapshot.get('class_stats') or {}
    row = class_row(class_stats, job_class)
    rss_s_p90 = row.get('rss_s_p90')
    if rss_s_p90 is None or rss_s_p90 > policy.cheap_rss_seconds:
        return d_result
    if snapshot.get('mem_pressure_level') == 4:
        return d_result
    bumped = dict(d_result)
    bumped['slots_now'] = min(d_result['slots_now'] + 1, policy.max_slots)
    running = len(snapshot.get('leases') or [])
    bumped['admit'] = running < bumped['slots_now']
    return bumped


FLOOR_NAMES = ('disk', 'swap_growth', 'mem_critical', 'app_hang')


def floors_fired(snapshot, policy):
    """Hard floors (§5.3). A floor whose signal is unknown never fires. Deny, never kill."""
    fired = []
    disk_free = snapshot.get('disk_free_gib')
    if disk_free is not None and disk_free < policy.disk_floor_gib:
        fired.append('disk')
    growth = snapshot.get('swap_growth_mb_per_min')
    if growth is not None and growth > policy.swap_growth_floor_mb_per_min:
        fired.append('swap_growth')
    level = snapshot.get('mem_pressure_level')
    if level is not None and level == 4:
        fired.append('mem_critical')
    hangs = snapshot.get('hang_reports_recent')
    if hangs is not None and hangs >= 1:
        fired.append('app_hang')  # shadow-only per §5.3/§18 Q2; caller decides whether to enforce it
    return fired


def needs_reclaim(snapshot, policy):
    """Soft disk threshold: never denies, but always asks for reclaim (§5.3)."""
    disk_free = snapshot.get('disk_free_gib')
    return disk_free is not None and disk_free < policy.disk_reclaim_gib


def any_unknown(snapshot):
    return bool(snapshot.get('unknown'))
