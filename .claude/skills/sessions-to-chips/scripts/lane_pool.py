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

`lane_pool.py --measure` builds that document: stdin is the raw `codex-headroom.sh --json`
output (empty or garbage = unmeasured), and the claude list is read from usage snapshots,
one per account, at $LANE_POOL_CLAUDE_USAGE_DIR (default ~/.claude/run/claude-usage)/<email>.json:
  {"account": "<email>", "seven_day": {"used_percentage": n, "resets_at": epoch},
   "five_hour": {...}, "written_at": epoch}
seven_day.used_percentage is the account's used_percent. A snapshot is UNMEASURED (skipped,
never guessed, one stderr line naming why) when it is malformed, its account does not match
its filename, its seven_day window has reset (resets_at <= now), or written_at or the file's
mtime is older than 30 minutes. The label is the email's local part plus a hash of the email.

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
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

LABEL_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
LIMIT = 100.0
SNAPSHOT_MAX_AGE_S = 30 * 60
SNAPSHOT_DIR_ENV = "LANE_POOL_CLAUDE_USAGE_DIR"


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


def _label(email):
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", email.split("@", 1)[0]).strip("-")[:20] or "acct"
    return "%s-%s" % (slug, hashlib.sha256(email.lower().encode()).hexdigest()[:8])


def _number(value):
    return None if isinstance(value, bool) or not isinstance(value, (int, float)) else value


def _snapshot(path, now):
    """Return (label, used_percent, None) for a fresh snapshot, else (label, None, why)."""
    email = path.name[: -len(".json")]
    label = _label(email)
    try:
        mtime = path.stat().st_mtime
        doc = json.loads(path.read_text())
    except (OSError, ValueError):
        return label, None, "malformed"
    week = doc.get("seven_day") if isinstance(doc, dict) else None
    if not isinstance(week, dict) or doc.get("account") != email:
        return label, None, "malformed"
    used, resets, written = _used(week.get("used_percentage")), _number(week.get("resets_at")), _number(doc.get("written_at"))
    if used is None or resets is None or written is None:
        return label, None, "malformed"
    if resets <= now:
        return label, None, "expired (seven_day window reset)"
    if now - min(written, mtime) > SNAPSHOT_MAX_AGE_S:
        return label, None, "stale (older than 30 minutes)"
    return label, used, None


def claude_snapshots(directory, now):
    """Return ([{"account", "used_percent"}], [skip notes]) from a snapshot directory."""
    accounts, notes = [], []
    try:
        paths = sorted(p for p in Path(directory).iterdir() if p.name.endswith(".json") and "@" in p.name)
    except OSError:
        return accounts, notes
    for path in paths:
        label, used, why = _snapshot(path, now)
        if why:
            notes.append("claude:%s snapshot unmeasured: %s" % (label, why))
        else:
            accounts.append({"account": label, "used_percent": used})
    return accounts, notes


def measure(codex_text, directory, now):
    """Return (measurement document, skip notes) for pick()."""
    try:
        codex = json.loads(codex_text)
    except ValueError:
        codex = None
    accounts, notes = claude_snapshots(directory, now)
    return {"codex": codex, "claude": accounts}, notes


def main():
    if sys.argv[1:] == ["--measure"]:
        directory = os.environ.get(SNAPSHOT_DIR_ENV) or str(Path.home() / ".claude/run/claude-usage")
        doc, notes = measure(sys.stdin.read(), directory, time.time())
        for note in notes:
            print("lane_pool.py: " + note, file=sys.stderr)
        print(json.dumps(doc))
        return 0
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
