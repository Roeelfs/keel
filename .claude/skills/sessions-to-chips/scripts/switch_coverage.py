#!/usr/bin/env python3
"""Switch-window coverage: no session that was working on the other account just before the switch
may be left without an owner here.

Why (measured 2026-11-24): the founder switches accounts on the spot, mid-work. The coverage audit
proved every active session was LEDGERED, yet 7 of 49 sessions active that day (old managers and
standalone children) were named in no handoff, so no manager here owned them and their in-progress
work would have stopped at the cap. Ledgered is not routed.

The rule: for every account other than this one, take its newest lastActivityAt; every
non-archived session active within --hours before that moment must have its 8-char short id in a
handoff file written in THIS round (mtime >= --since-epoch). Excluded only by a line
`<shortid> <reason>` in relay/switch-exclude.txt (personal sessions). An account idle longer than
--max-age-days is not a switch and is skipped. Exit 1 lists the unrouted.

Usage: python3 -I switch_coverage.py --here ACCT [--hours 36] [--since-epoch S] [--json]
"""
import argparse
import glob
import json
import os
import sys

STORE = os.environ.get("S2C_STORE") or os.path.expanduser("~/Library/Application Support/Claude/claude-code-sessions")
HOME = os.environ.get("S2C_CLAUDE_HOME") or os.path.expanduser("~/.claude")


def short(sid):
    return sid.removeprefix("local_")[:8]


def load_rows(store):
    out = []
    for f in glob.glob(os.path.join(store, "*", "**", "local_*.json"), recursive=True):
        try:
            r = json.load(open(f))
        except (OSError, ValueError):
            continue
        acct = os.path.relpath(f, store).split(os.sep)[0]
        out.append(dict(r, _acct=acct))
    return out


def handoff_text(home, since_epoch):
    files = [f for f in glob.glob(os.path.join(home, "sessions-to-chips", "handoff", "*.md"))
             if os.path.getmtime(f) >= since_epoch]
    return files, "\n".join(open(f, errors="replace").read() for f in files)


def excluded(home):
    p = os.path.join(home, "sessions-to-chips", "relay", "switch-exclude.txt")
    out = {}
    if os.path.exists(p):
        for line in open(p):
            parts = line.strip().split(None, 1)
            if parts and not parts[0].startswith("#"):
                out[parts[0][:8]] = parts[1] if len(parts) > 1 else "(no reason)"
    return out


def check(here, hours=36, since_epoch=0, store=STORE, home=HOME, max_age_days=7, now_ms=None):
    import time
    now_ms = now_ms or time.time() * 1000
    rows = load_rows(store)
    files, text = handoff_text(home, since_epoch)
    excl = excluded(home)
    report = {"handoff_files": len(files), "accounts": {}, "unrouted": [], "excluded": []}
    for acct in sorted(a for a in {r["_acct"] for r in rows} if not a.startswith(here)):
        mine = [r for r in rows if r["_acct"] == acct and r.get("lastActivityAt")]
        if not mine:
            continue
        last = max(r["lastActivityAt"] for r in mine)
        if now_ms - last > max_age_days * 86400 * 1000:
            report["accounts"][acct[:8]] = {"skipped": f"idle > {max_age_days:g}d (not a switch)"}
            continue
        start = last - hours * 3600 * 1000
        win = [r for r in mine if r["lastActivityAt"] >= start and not r.get("isArchived")]
        routed = 0
        for r in win:
            s = short(r.get("sessionId", ""))
            row = {"acct": acct[:8], "sessionId": r.get("sessionId"), "title": r.get("title"),
                   "lastActivityAt": r["lastActivityAt"], "cwd": r.get("cwd")}
            if s in excl:
                report["excluded"].append(dict(row, reason=excl[s]))
            elif s in text:
                routed += 1
            else:
                report["unrouted"].append(row)
        report["accounts"][acct[:8]] = {"window_start_ms": start, "last_ms": last, "live_in_window": len(win),
                                        "routed": routed}
    return report


def evidence(rep):
    acc = "; ".join(f"{a}: " + (v["skipped"] if "skipped" in v else f"{v['routed']}/{v['live_in_window']} routed")
                    for a, v in rep["accounts"].items()) or "no other account"
    return (f"{acc}; {len(rep['unrouted'])} unrouted, {len(rep['excluded'])} excluded; "
            f"{rep['handoff_files']} handoff files this round")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--here", required=True)
    ap.add_argument("--hours", type=float, default=36)
    ap.add_argument("--since-epoch", type=float, default=0)
    ap.add_argument("--max-age-days", type=float, default=7, help="skip an account idle longer than this")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    rep = check(a.here, a.hours, a.since_epoch, max_age_days=a.max_age_days)
    if a.json:
        print(json.dumps(rep, indent=1))
    else:
        print(evidence(rep))
        for r in rep["unrouted"]:
            print(f"UNROUTED {r['acct']} {r['sessionId']}\t{r['title']}\t{r['cwd']}")
    sys.exit(1 if rep["unrouted"] else 0)


if __name__ == "__main__":
    main()
