#!/usr/bin/env python3
"""Find work the handoff files would miss after an account switch. Read-only; sends nothing.

Two checks:
  1. Worktrees of the OTHER account's sessions active since --since: unpushed commits, no
     upstream, uncommitted files, and gutted worktrees (mass tracked deletions).
  2. Story maps and wrap-up notes written since --since that no handoff file names.

Usage:
  python3 -I handoff_sweep.py --account <other-account-id> --since 2026-10-18T20:00 \
      [--handoff-dir ~/.claude/sessions-to-chips/handoff] [--all]
"""
import argparse
import datetime
import glob
import json
import os
import subprocess

STORE = os.path.expanduser("~/Library/Application Support/Claude/claude-code-sessions")
S2C = os.path.expanduser("~/.claude/sessions-to-chips")
GUTTED = 100  # tracked deletions above this mean the checkout itself is broken


def git(cwd, *args):
    r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True)
    return r.stdout.strip()


def load_sessions(account, since_ms):
    rows = {}
    for f in glob.glob(f"{STORE}/{account}/*/local_*.json"):
        with open(f) as fh:
            d = json.load(fh)
        if d.get("lastActivityAt", 0) >= since_ms:
            rows[d["sessionId"]] = d
    return rows


def owning_manager(sid, rows):
    cur = sid
    for _ in range(10):
        d = rows.get(cur, {})
        if d.get("title", "").startswith("[Manager]"):
            return d["title"]
        parent = (d.get("spawnedFrom") or {}).get("sessionId")
        if not parent:
            break
        cur = parent
    return "(unmanaged)"


def worktree_findings(rows):
    # Several sessions can share one worktree; attribute it to a manager when any of them has one.
    by_cwd = {}
    for sid, d in rows.items():
        cwd = d.get("cwd", "")
        if cwd and (cwd not in by_cwd or owning_manager(by_cwd[cwd], rows) == "(unmanaged)"):
            by_cwd[cwd] = sid
    out = []
    for cwd, sid in by_cwd.items():
        d = rows[sid]
        if not os.path.isdir(cwd):
            continue  # reaped: only its pushed branch/PR survives
        if git(cwd, "rev-parse", "--show-toplevel") == "":
            continue
        branch = git(cwd, "branch", "--show-current")
        if branch in ("main", "master"):
            continue  # the main checkout, not a lane
        status = [l for l in git(cwd, "status", "--porcelain").splitlines() if "node_modules" not in l]
        deleted = sum(1 for l in status if l[:2].strip() == "D")
        upstream = git(cwd, "rev-parse", "--abbrev-ref", "@{u}")
        ahead = git(cwd, "log", "--oneline", "@{u}.." if upstream else "origin/main..HEAD")
        commits = ahead.splitlines() if ahead else []
        issues = []
        if deleted >= GUTTED:
            issues.append(f"GUTTED ({deleted} tracked files deleted): continue from the remote branch in a fresh worktree")
        if commits:
            issues.append(f"{len(commits)} unpushed{'' if upstream else ' (no upstream)'}: " + "; ".join(commits[:4]))
        untracked = [l[3:] for l in status if l.startswith("??")]
        if untracked and deleted < GUTTED:
            issues.append("untracked: " + ", ".join(untracked[:5]))
        if issues:
            out.append({"manager": owning_manager(sid, rows), "session": d.get("title", ""),
                        "sessionId": sid, "worktree": cwd, "branch": branch, "issues": issues})
    return sorted(out, key=lambda r: r["manager"])


def unreferenced_maps(since_ts, handoff_dir):
    handoffs = ""
    for f in glob.glob(os.path.join(handoff_dir, "*.md")):
        with open(f) as fh:
            handoffs += fh.read()
    missing = []
    for sub in ("maps", "wrapup"):
        for f in glob.glob(f"{S2C}/{sub}/*.md"):
            if os.path.getmtime(f) >= since_ts and os.path.basename(f) not in handoffs:
                missing.append(f)
    return sorted(missing)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", required=True, help="the account you are switching AWAY from")
    ap.add_argument("--since", required=True, help="ISO time of the last checkpoint, e.g. 2026-10-18T20:00")
    ap.add_argument("--handoff-dir", default=f"{S2C}/handoff")
    args = ap.parse_args()
    since = datetime.datetime.fromisoformat(args.since).replace(tzinfo=datetime.timezone.utc)
    rows = load_sessions(args.account, int(since.timestamp() * 1000))
    print(json.dumps({
        "sessionsScanned": len(rows),
        "worktrees": worktree_findings(rows),
        "unreferencedMapsAndNotes": unreferenced_maps(since.timestamp(), os.path.expanduser(args.handoff_dir)),
    }, indent=1))


if __name__ == "__main__":
    main()
