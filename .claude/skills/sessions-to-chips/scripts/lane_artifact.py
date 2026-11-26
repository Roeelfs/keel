#!/usr/bin/env python3
"""What a finished lane produced: the `artifact=` field of spawn-lane.sh's LANE RESULT line.

Usage: lane_artifact.py <guard-state.json> <cwd> [<worktree-name>]   (mission text on stdin)

Prints one token: comma-joined items, or `none` when the lane produced nothing.
  commits:<base7>..<head7>(<n>)  commits on the lane's worktree beyond its launch HEAD
                                 (the proof worktree lane_commit_guard.evidence resolves)
  pr:<url>                       the PR whose head is the lane's branch (`gh pr list --head`),
                                 when it was opened during the run or the lane added commits
  path:<abs path>                a mission-declared artifact that exists and was written
                                 during the run
A mission declares an artifact on its own line: `Artifact: <path>` (also `- Artifact:` and
`Phase artifact:`); relative paths resolve against the lane worktree.
The outfile (Codex -o, LANE_RECORD_OUTFILE) is NOT an artifact: it exists for every launched
lane, so counting it made `artifact=` non-none for a lane that did nothing (2026-11-25).
Advisory: any failure degrades to fewer items, never an exception.
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import lane_commit_guard as guard

DECLARED = re.compile(r"^\s*(?:[-*]\s*)?(?:phase\s+)?artifact\s*:\s*(.+?)\s*$", re.I | re.M)


def commits(ev):
    before, after = ev.get("head_before"), ev.get("head_after")
    if not ev.get("committed"):
        return []
    n = guard.git(ev["worktree"], "rev-list", "--count", after, "^" + before) or "?"
    return ["commits:%s..%s(%s)" % (before[:7], after[:7], n)]


def _iso(ts):
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def prs(ev, since):
    wt = ev.get("worktree")
    branch = guard.git(wt, "symbolic-ref", "--short", "-q", "HEAD") if wt else ""
    if not branch or not guard.git(wt, "remote"):
        return []
    try:
        out = subprocess.run(["gh", "pr", "list", "--head", branch, "--state", "all",
                              "--json", "url,createdAt,state", "--limit", "5"],
                             cwd=wt, capture_output=True, text=True, timeout=20,
                             stdin=subprocess.DEVNULL)
        rows = json.loads(out.stdout) if out.returncode == 0 else []
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []
    keep = [r["url"] for r in rows if isinstance(r, dict) and r.get("url")
            and (_iso(r.get("createdAt")) >= since - 1
                 or (ev.get("committed") and r.get("state") == "OPEN"))]
    return ["pr:" + url for url in keep]


def declared(mission, root, since):
    found = []
    for line in DECLARED.findall(mission or ""):
        for token in re.split(r"[\s,]+", line):
            token = token.strip("`'\"()<>[];.")
            if not token or ("/" not in token and "." not in token):
                continue
            path = Path(os.path.expanduser(token))
            path = path if path.is_absolute() else Path(root) / path
            try:
                if path.exists() and path.stat().st_mtime >= since:
                    item = "path:" + str(path.resolve())
                    if item not in found:
                        found.append(item)
            except OSError:
                continue
    return found


def produced(before, cwd, worktree_name, mission):
    ev = guard.evidence(before, cwd, worktree_name=worktree_name)
    since = float(before.get("ts") or 0)
    root = ev.get("worktree") or before.get("cwd") or cwd
    return commits(ev) + prs(ev, since) + declared(mission, root, since)


def main(argv):
    try:
        before = json.loads(Path(argv[1]).read_text())
        items = produced(before, argv[2], argv[3] if len(argv) > 3 else "", sys.stdin.read())
    except Exception as exc:  # noqa: BLE001 - the LANE RESULT line must always print
        print("spawn-lane.sh: artifact check skipped: %s" % exc, file=sys.stderr)
        items = []
    print(",".join(items) or "none")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
