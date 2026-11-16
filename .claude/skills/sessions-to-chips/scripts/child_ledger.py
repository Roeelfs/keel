#!/usr/bin/env python3
"""Per-manager ledger of every child session on the account you are leaving. Read-only.

Progress is lost in two places: in git (handoff_sweep.py covers that) and in a child's
conversation, where a finding, a decision or a "needs the founder to ..." exists only in its last
report. This writes one JSON per manager listing each descendant active since the checkpoint,
with its stored last report, status, PRs, branches and transcript path, for a haiku agent to
reconcile against the handoff (prompts/child-ledger-reconciler.md).

Usage:
  python3 -I child_ledger.py --account <other-account-id> --since 2026-10-18T20:00 --out <dir> [--roots <candidates.json>]
"""
import argparse
import datetime
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import program_family as pf  # noqa: E402

STORE = os.environ.get("S2C_STORE") or os.path.expanduser("~/Library/Application Support/Claude/claude-code-sessions")
PROJECTS = os.path.join((os.environ.get("S2C_CLAUDE_HOME") or os.path.expanduser("~/.claude")), "projects")


def transcript_for(cli, projects=None):
    hits = glob.glob(f"{projects or PROJECTS}/*/{cli}.jsonl") if cli else []
    return max(hits, key=os.path.getmtime) if hits else None


def ledger_row(sid, d, projects=None):
    """One child row: everything stored about the session that a reconciler judges."""
    summary = d.get("postTurnSummary") or {}
    return {
        "title": d.get("title", ""),
        "sessionId": sid,
        "archived": bool(d.get("isArchived")),
        "lastActivity": datetime.datetime.fromtimestamp(d.get("lastActivityAt", 0) / 1000, datetime.timezone.utc).isoformat(timespec="minutes"),
        "status": summary.get("status_category"),
        "needsAction": summary.get("needs_action"),
        "awaitingPerson": d.get("interruptedAwaitingPerson"),
        "lastReport": d.get("lastTurnReport"),
        "prs": [f"#{p.get('prNumber')} {p.get('state')}" for p in d.get("prs") or []],
        "branches": [b.split("\u0000")[-1] for b in d.get("writtenBranches") or []],
        "worktree": d.get("cwd"),
        "transcript": transcript_for(d.get("cliSessionId"), projects),
    }


def ledger_owner(sid, d, rows, roots):
    """-> owner session id, None (unmanaged), or False (the row is itself a program root: never its
    own child). Walks from the parent, so a self-owned candidate is never ledgered as its child."""
    if pf.is_manager(d) or roots.get(sid) == sid:
        return False
    if sid in roots:
        return roots[sid]  # an absorbed candidate rides its absorber's ledger
    return pf.root_manager((d.get("spawnedFrom") or {}).get("sessionId"), rows, roots)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", required=True, help="account dir prefix, comma list, or 'all'")
    ap.add_argument("--since", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--roots", help="<work>/candidates.json from mine_all.py (program roots without a [Manager] title)")
    args = ap.parse_args()
    since = datetime.datetime.fromisoformat(args.since).replace(tzinfo=datetime.timezone.utc)
    since_ms = int(since.timestamp() * 1000)
    # Ancestry walks the FULL store: a child of a quiet manager on the other account still has an owner.
    rows, _, _ = pf.load_store(STORE)
    roots = pf.load_roots(args.roots)
    accts = None if args.account in ("all", "*") else [a.strip() for a in args.account.split(",")]

    ledgers = {}
    for sid, d in rows.items():
        if d.get("lastActivityAt", 0) < since_ms or (accts and not any(d["_acct"].startswith(a) for a in accts)):
            continue
        owner = ledger_owner(sid, d, rows, roots)
        if owner is False:
            continue
        ledgers.setdefault(owner or "(unmanaged)", []).append(ledger_row(sid, d))

    os.makedirs(args.out, exist_ok=True)
    index = []
    for mgr, children in ledgers.items():
        title = rows[mgr]["title"] if mgr in rows else mgr
        name = "unmanaged-none" if mgr not in rows else f"{pf.program_slug(title) or 'session'}-{mgr.replace('local_', '')[:8]}"
        path = os.path.join(args.out, f"children-{name}.json")
        with open(path, "w") as fh:
            json.dump({"manager": title, "managerSessionId": mgr, "children": sorted(children, key=lambda c: c["lastActivity"])}, fh, indent=1)
        index.append({"manager": title, "children": len(children), "file": path})
    print(json.dumps(sorted(index, key=lambda r: r["manager"]), indent=1))


if __name__ == "__main__":
    main()
