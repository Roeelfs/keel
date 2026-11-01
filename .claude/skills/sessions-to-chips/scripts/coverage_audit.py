#!/usr/bin/env python3
"""Coverage audit: prove the sweeps saw every session, instead of assuming it. Read-only.

Two tests:
  A. Every session on --account active since --since must sit in some child-ledger file
     (children-*.json in --ledger-dir) or be a [Manager] row. Anything else is a HOLE.
  B. Every older, unmerged descendant of a [Manager] that no handoff, wrap-up or state file names
     (by session id or title prefix), and that no ledger holds, is UNNAMED. Merged-PR sessions are
     skipped: the PR is the durable record. mine_all.py widens by ledgering these rows for the
     old-descendant classifier, so a ledgered row is no longer UNNAMED.

Usage:
  coverage_audit.py --account all --since 2026-10-24T00:46 --ledger-dir <dir> [--json]
Exit 0 always; mine_all.py turns the counts into gates.
"""
import argparse
import glob
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = (os.environ.get("S2C_CLAUDE_HOME") or os.path.expanduser("~/.claude"))


def load_sessions():
    out = subprocess.run([sys.executable, "-I", os.path.join(HERE, "list_sessions.py"), "--json"],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def named_text(root=None):
    root = root or ROOT
    paths = (glob.glob(os.path.join(root, "sessions-to-chips/handoff/*.md"))
             + glob.glob(os.path.join(root, "sessions-to-chips/wrapup/*.md"))
             + glob.glob(os.path.join(root, "orchestrator/programs/*.state.md")))
    return "".join(open(p, errors="ignore").read() for p in paths)


def ledgered_ids(ledger_dir):
    ids = set()
    for f in glob.glob(os.path.join(ledger_dir, "children-*.json")):
        try:
            for c in json.load(open(f)).get("children", []):
                ids.add(c.get("sessionId"))
        except (OSError, ValueError):
            continue
    return ids


def descendants(kids, sid, seen=None):
    seen = seen if seen is not None else set()
    for k in kids.get(sid, []):
        if k["sessionId"] in seen:
            continue
        seen.add(k["sessionId"])
        yield k
        yield from descendants(kids, k["sessionId"], seen)


def in_account(row, account):
    return account in ("all", "*") or any(row["account"].startswith(x) for x in account.split(","))


def audit(rows, account, since, ledger_dir, text):
    """-> {"holes": [rows], "unnamed": [(manager title, row)], "ledgered": n}. `since` is the ISO
    string list_sessions.py emits (YYYY-MM-DDTHH:MM:SS), compared as text."""
    ledgered = ledgered_ids(ledger_dir)
    holes = [r for r in rows if in_account(r, account) and r["lastActivityAt"] >= since
             and r["sessionId"] not in ledgered and not r["title"].startswith("[Manager]")]
    kids = {}
    for r in rows:
        kids.setdefault(r.get("parentSessionId") or "", []).append(r)
    unnamed, seen = [], set()
    for m in rows:
        if not m["title"].startswith("[Manager]"):
            continue
        for k in descendants(kids, m["sessionId"]):
            if k["sessionId"] in seen or k["lastActivityAt"] >= since or k.get("prState") == "MERGED":
                continue
            if k["title"].startswith("[Manager]") or k["sessionId"] in ledgered:
                continue
            if not (k["sessionId"][6:14] in text or k["sessionId"] in text or k["title"][:28] in text):
                seen.add(k["sessionId"])
                unnamed.append((m["title"], k))
    return {"holes": holes, "unnamed": unnamed, "ledgered": len(ledgered)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", required=True)
    ap.add_argument("--since", required=True)
    ap.add_argument("--ledger-dir", required=True)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    res = audit(load_sessions(), a.account, a.since, a.ledger_dir, named_text())
    if a.json:
        print(json.dumps({"holes": res["holes"], "ledgered": res["ledgered"],
                          "unnamed": [{"manager": t, **k} for t, k in res["unnamed"]]}, indent=1))
        return
    print(f"A. post-checkpoint sessions on {a.account[:8]} outside every ledger: {len(res['holes'])} "
          f"(ledger rows {res['ledgered']})")
    for r in sorted(res["holes"], key=lambda r: r["lastActivityAt"]):
        print(f"   HOLE {r['lastActivityAt'][5:16]} {r['sessionId'][6:14]} {r['title'][:70]}")
    print(f"B. older unmerged descendants named in no handoff/wrap-up/state/ledger: {len(res['unnamed'])}")
    for mt, k in sorted(res["unnamed"], key=lambda x: x[1]["lastActivityAt"]):
        print(f"   UNNAMED {k['lastActivityAt'][5:16]} {k['sessionId'][6:14]} <{mt[:24]} {k['title'][:60]}")


if __name__ == "__main__":
    main()
