#!/usr/bin/env python3
"""Mode 4 coverage audit: prove the sweeps saw every session, instead of assuming it.

Two tests, both read-only:
  A. Every session on --account active since --since must sit in some child-ledger file
     (child_ledger.py output) or be a [Manager] row. Anything else is a hole in the sweep.
  B. Every older, unarchived-or-unmerged descendant of a [Manager] that no handoff, wrap-up,
     or state file names (by session id or title prefix) is listed as UNNAMED. Merged-PR
     sessions are skipped: the PR is the durable record.

Usage:
  coverage_audit.py --account <id> --since 2026-10-24T00:46 --ledger-dir <dir>
Exit 0 always; the report is the artifact. A hole in A is a defect to fix before sending.
"""
import argparse
import glob
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.expanduser("~/.claude")


def load_sessions():
    out = subprocess.run([sys.executable, "-I", os.path.join(HERE, "list_sessions.py"), "--json"],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def named_text():
    paths = (glob.glob(os.path.join(ROOT, "sessions-to-chips/handoff/*.md"))
             + glob.glob(os.path.join(ROOT, "sessions-to-chips/wrapup/*.md"))
             + glob.glob(os.path.join(ROOT, "orchestrator/programs/*.state.md")))
    return "".join(open(p, errors="ignore").read() for p in paths)


def descendants(kids, sid):
    for k in kids.get(sid, []):
        yield k
        yield from descendants(kids, k["sessionId"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", required=True)
    ap.add_argument("--since", required=True)
    ap.add_argument("--ledger-dir", required=True)
    a = ap.parse_args()

    rows = load_sessions()
    ledgered = set()
    for f in glob.glob(os.path.join(a.ledger_dir, "children-*.json")):
        for c in json.load(open(f)).get("children", []):
            ledgered.add(c.get("sessionId"))

    holes = [r for r in rows
             if r["account"].startswith(a.account) and r["lastActivityAt"] >= a.since
             and r["sessionId"] not in ledgered and not r["title"].startswith("[Manager]")]
    print(f"A. post-checkpoint sessions on {a.account[:8]} outside every ledger: {len(holes)} "
          f"(ledger rows {len(ledgered)})")
    for r in sorted(holes, key=lambda r: r["lastActivityAt"]):
        print(f"   HOLE {r['lastActivityAt'][5:16]} {r['sessionId'][6:14]} {r['title'][:70]}")

    kids = {}
    for r in rows:
        kids.setdefault(r.get("parentSessionId") or "", []).append(r)
    text = named_text()
    unnamed = []
    for m in rows:
        if not m["title"].startswith("[Manager]"):
            continue
        for k in descendants(kids, m["sessionId"]):
            if k["lastActivityAt"] >= a.since or k.get("prState") == "MERGED":
                continue
            if not (k["sessionId"][6:14] in text or k["sessionId"] in text or k["title"][:28] in text):
                unnamed.append((m["title"], k))
    print(f"B. older unmerged descendants named in no handoff/wrap-up/state: {len(unnamed)}")
    for mt, k in sorted(unnamed, key=lambda x: x[1]["lastActivityAt"]):
        print(f"   UNNAMED {k['lastActivityAt'][5:16]} {k['sessionId'][6:14]} <{mt[:24]} {k['title'][:60]}")


if __name__ == "__main__":
    main()
