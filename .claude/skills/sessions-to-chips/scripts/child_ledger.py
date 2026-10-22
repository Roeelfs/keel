#!/usr/bin/env python3
"""Per-manager ledger of every child session on the account you are leaving. Read-only.

Progress is lost in two places: in git (handoff_sweep.py covers that) and in a child's
conversation, where a finding, a decision or a "needs the founder to ..." exists only in its last
report. This writes one JSON per manager listing each descendant active since the checkpoint,
with its stored last report, status, PRs, branches and transcript path, for a haiku agent to
reconcile against the handoff (prompts/child-ledger-reconciler.md).

Usage:
  python3 -I child_ledger.py --account <other-account-id> --since 2026-10-18T20:00 --out <dir>
"""
import argparse
import datetime
import glob
import json
import os
import re

STORE = os.path.expanduser("~/Library/Application Support/Claude/claude-code-sessions")
PROJECTS = os.path.expanduser("~/.claude/projects")


def slug(title):
    return re.sub(r"[^a-z0-9]+", "-", title.lower().replace("[manager]", "")).strip("-")[:60]


def transcript_for(cli):
    hits = glob.glob(f"{PROJECTS}/*/{cli}.jsonl") if cli else []
    return max(hits, key=os.path.getmtime) if hits else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", required=True)
    ap.add_argument("--since", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    since = datetime.datetime.fromisoformat(args.since).replace(tzinfo=datetime.timezone.utc)
    since_ms = int(since.timestamp() * 1000)

    rows = {}
    for f in glob.glob(f"{STORE}/{args.account}/*/local_*.json"):
        with open(f) as fh:
            d = json.load(fh)
        rows[d["sessionId"]] = d

    def manager_of(sid):
        cur = (rows[sid].get("spawnedFrom") or {}).get("sessionId")
        for _ in range(10):
            if not cur or cur not in rows:
                return None
            if rows[cur].get("title", "").startswith("[Manager]"):
                return cur
            cur = (rows[cur].get("spawnedFrom") or {}).get("sessionId")
        return None

    ledgers = {}
    for sid, d in rows.items():
        if d.get("lastActivityAt", 0) < since_ms or d.get("title", "").startswith("[Manager]"):
            continue
        mgr = manager_of(sid) or "(unmanaged)"
        summary = d.get("postTurnSummary") or {}
        ledgers.setdefault(mgr, []).append({
            "title": d.get("title", ""),
            "sessionId": sid,
            "archived": bool(d.get("isArchived")),
            "lastActivity": datetime.datetime.fromtimestamp(d["lastActivityAt"] / 1000, datetime.timezone.utc).isoformat(timespec="minutes"),
            "status": summary.get("status_category"),
            "needsAction": summary.get("needs_action"),
            "awaitingPerson": d.get("interruptedAwaitingPerson"),
            "lastReport": d.get("lastTurnReport"),
            "prs": [f"#{p.get('prNumber')} {p.get('state')}" for p in d.get("prs") or []],
            "branches": [b.split("\u0000")[-1] for b in d.get("writtenBranches") or []],
            "worktree": d.get("cwd"),
            "transcript": transcript_for(d.get("cliSessionId")),
        })

    os.makedirs(args.out, exist_ok=True)
    index = []
    for mgr, children in ledgers.items():
        title = rows[mgr]["title"] if mgr in rows else mgr
        path = os.path.join(args.out, f"children-{slug(title) or 'unmanaged'}-{mgr.replace('local_', '')[:8] if mgr.startswith('local_') else 'none'}.json")
        with open(path, "w") as fh:
            json.dump({"manager": title, "managerSessionId": mgr, "children": sorted(children, key=lambda c: c["lastActivity"])}, fh, indent=1)
        index.append({"manager": title, "children": len(children), "file": path})
    print(json.dumps(sorted(index, key=lambda r: r["manager"]), indent=1))


if __name__ == "__main__":
    main()
