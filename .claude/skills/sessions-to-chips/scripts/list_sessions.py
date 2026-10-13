#!/usr/bin/env python3
"""List Claude Code DESKTOP-app sessions across ALL local accounts.

Source of truth (NOT ~/.claude/sessions, which is only live interactive sessions):
  ~/Library/Application Support/Claude/claude-code-sessions/<account-uuid>/<org-uuid>/local_*.json

Each JSON carries: title, cliSessionId, cwd, worktreePath, worktreeName, branch,
prNumber, prState, isArchived, lastActivityAt. "Another account" == a different
<account-uuid> directory. Pinned-session titles from a screenshot are matched here.

Usage:
  list_sessions.py                       # all accounts, grouped, most-recent first
  list_sessions.py --account <account-id>  # filter by account-uuid substring
  list_sessions.py --grep "ABC-3"        # filter by title substring (case-insensitive)
  list_sessions.py --json                # machine-readable (pipe to jq / a workflow)
  list_sessions.py --tree [--grep T]     # lineage forest: parent session -> the chips it spawned

Lineage: a chip's JSON carries spawnedFrom.sessionId = the session that spawned it. That is
the sidebar's top-level / sub-level structure (a parent row with its chips nested under it).
`group_sessions.py` turns this lineage into one group per category (origin session + members).
"""
import json, glob, os, sys, argparse, datetime

BASE = os.path.expanduser("~/Library/Application Support/Claude/claude-code-sessions")

def norm_ts(v):
    """Return ISO-ish string for either epoch-ms ints or ISO strings; '' if absent."""
    if v in (None, ""):
        return ""
    s = str(v)
    if s.isdigit():
        try:
            return datetime.datetime.utcfromtimestamp(int(s) / 1000).strftime("%Y-%m-%dT%H:%M:%S")
        except Exception:
            return s
    return s[:19]

def load_all():
    rows = []
    for f in glob.glob(os.path.join(BASE, "*", "*", "local_*.json")):
        try:
            d = json.load(open(f))
        except Exception:
            continue
        acct = f[len(BASE) + 1:].split(os.sep)[0]
        rows.append({
            "account": acct,
            "title": d.get("title") or "",
            "cli": d.get("cliSessionId") or "",
            "sessionId": d.get("sessionId") or os.path.basename(f)[:-5],
            "parentSessionId": (d.get("spawnedFrom") or {}).get("sessionId") or "",
            "branch": d.get("branch") or "",
            "worktree": d.get("cwd") or d.get("worktreePath") or "",
            "worktreeName": d.get("worktreeName") or "",
            "pr": d.get("prNumber"),
            "prState": d.get("prState"),
            "archived": bool(d.get("isArchived")),
            "lastActivityAt": norm_ts(d.get("lastActivityAt")),
        })
    return rows

def print_tree(rows):
    """Forest of the listed rows. A row whose parent is not in `rows` is printed as a root."""
    by_id = {r["sessionId"]: r for r in rows}
    kids = {}
    for r in rows:
        p = r["parentSessionId"]
        kids.setdefault(p if p in by_id else "", []).append(r)
    def walk(r, depth):
        pr = f" PR#{r['pr']}/{r['prState']}" if r["pr"] else ""
        print(f"{'    ' * depth}{'└─ ' if depth else ''}{r['title']}  [{r['cli'][:8]}]{pr}")
        for c in sorted(kids.get(r["sessionId"], []), key=lambda x: x["lastActivityAt"]):
            walk(c, depth + 1)
    for r in kids.get("", []):
        walk(r, 0)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--account")
    ap.add_argument("--grep")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--tree", action="store_true", help="print the spawnedFrom lineage forest")
    a = ap.parse_args()
    rows = load_all()
    if a.account:
        rows = [r for r in rows if a.account in r["account"]]
    if a.grep:
        rows = [r for r in rows if a.grep.lower() in r["title"].lower()]
    rows.sort(key=lambda r: r["lastActivityAt"], reverse=True)
    if a.tree:
        print_tree(rows)
        return
    if a.json:
        print(json.dumps(rows, indent=2))
        return
    accts = {}
    for r in rows:
        accts.setdefault(r["account"], []).append(r)
    if not accts:
        print("(no sessions found — check the BASE path / account filter)")
    for acct, rs in accts.items():
        print(f"\n=== ACCOUNT {acct}  ({len(rs)} sessions) ===")
        for r in rs:
            pr = f"PR#{r['pr']}/{r['prState']}" if r["pr"] else "no-PR"
            arch = " [archived]" if r["archived"] else ""
            print(f"  [{r['lastActivityAt']:19}] {pr:16}{arch}")
            print(f"     {r['title']}")
            print(f"     cli={r['cli']}  branch={r['branch']}")
            print(f"     wt={r['worktreeName'] or r['worktree']}")

if __name__ == "__main__":
    main()
