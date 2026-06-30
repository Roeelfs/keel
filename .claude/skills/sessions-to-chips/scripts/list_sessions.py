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
            "branch": d.get("branch") or "",
            "worktree": d.get("cwd") or d.get("worktreePath") or "",
            "worktreeName": d.get("worktreeName") or "",
            "pr": d.get("prNumber"),
            "prState": d.get("prState"),
            "archived": bool(d.get("isArchived")),
            "lastActivityAt": norm_ts(d.get("lastActivityAt")),
        })
    return rows

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--account")
    ap.add_argument("--grep")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    rows = load_all()
    if a.account:
        rows = [r for r in rows if a.account in r["account"]]
    if a.grep:
        rows = [r for r in rows if a.grep.lower() in r["title"].lower()]
    rows.sort(key=lambda r: r["lastActivityAt"], reverse=True)
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
