#!/usr/bin/env python3
"""Pick a headless lane's runtime: the measured pool CLOSEST to its limit that still has room.

Founder ruling 2026-11-19: "always use the closest limit possible, with native as last".
Spend the pool nearest its cap first, because unused headroom in a window that resets is lost.
Native Agent/Workflow is never a candidate here: it runs the actual sessions, and the
codex-first-gate hook keeps it last (Native-why).

Input (stdin, one JSON object) is the measurement, injected so the choice is unit-testable:
  {"codex":  <the object `codex-headroom.sh --json` prints> | null,
   "claude": [{"account": "<label>", "used_percent": <0..100+>}, ...] | null}
A Claude account label is a short opaque name ([A-Za-z0-9_-]{1,32}), never an email.

Output (stdout, two lines): "<runtime> <pool>", then a one-line reason.
  runtime  claude | codex
  pool     codex | claude | claude:<label>

Rules, in order:
  1. A pool is MEASURED when its used_percent is a number >= 0. A Codex reading with verdict
     "unknown" or stale:true is unmeasured (a stale snapshot can straddle a reset).
  2. Codex unmeasured, or no Claude account measured → claude, reason "fallback": the pools
     cannot be compared, and claude is the runtime with no extra gate.
  3. A pool at or over 100% is skipped. Every pool skipped → claude fallback.
  4. Otherwise the highest used_percent wins. A tie goes to claude, then to input order.
"""
import json
import re
import sys

LABEL_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
LIMIT = 100.0


def _used(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if value >= 0 else None


def _codex(reading):
    if not isinstance(reading, dict) or reading.get("verdict") == "unknown" or reading.get("stale") is True:
        return None
    return _used(reading.get("used_percent"))


def _claude(accounts):
    pools = []
    for acct in accounts if isinstance(accounts, list) else []:
        if not isinstance(acct, dict):
            continue
        label, used = acct.get("account"), _used(acct.get("used_percent"))
        if isinstance(label, str) and LABEL_RE.match(label) and used is not None:
            pools.append(("claude", "claude:" + label, used))
    return pools


def _fmt(pools):
    return ", ".join("%s %g%%" % (pool, used) for _, pool, used in pools)


def pick(measurements):
    """Return (runtime, pool, reason). Pure: same measurements, same answer."""
    m = measurements if isinstance(measurements, dict) else {}
    codex_used = _codex(m.get("codex"))
    claude_pools = _claude(m.get("claude"))
    missing = ([] if codex_used is not None else ["codex"]) + ([] if claude_pools else ["claude"])
    if missing:
        return "claude", "claude", "fallback: %s unmeasured, pools cannot be compared" % " and ".join(missing)
    pools = claude_pools + [("codex", "codex", codex_used)]
    open_pools = [p for p in pools if p[2] < LIMIT]
    if not open_pools:
        return "claude", "claude", "fallback: every pool at or over its limit (%s)" % _fmt(pools)
    order = {p[1]: i for i, p in enumerate(pools)}
    best = max(open_pools, key=lambda p: (p[2], p[0] == "claude", -order[p[1]]))
    skipped = [p for p in pools if p[2] >= LIMIT]
    reason = "closest to its limit with room: %s" % _fmt(open_pools)
    if skipped:
        reason += "; skipped at limit: %s" % _fmt(skipped)
    return best[0], best[1], reason


def main():
    try:
        measurements = json.load(sys.stdin)
    except ValueError:
        measurements = None
    runtime, pool, reason = pick(measurements)
    print("%s %s" % (runtime, pool))
    print(reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
