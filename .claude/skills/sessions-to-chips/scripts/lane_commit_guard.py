#!/usr/bin/env python3
"""Shared zero-commit evidence for headless lanes and the shadow Agent hook.

Never count a changed sibling checkout. A named lane selects its worktree by path;
unnamed lanes infer only when exactly one new worktree exists. Compare its HEAD
to its own creation reflog.
Ambiguous or removed worktrees stay unproven, rather than borrowing another lane's work.
"""
import json
import subprocess
import sys
from pathlib import Path


def git(cwd, *args):
    result = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True,
                            text=True, timeout=5)
    return result.stdout.strip() if result.returncode == 0 else ""


def worktrees(cwd):
    raw = git(cwd, "worktree", "list", "--porcelain", "-z")
    return [part[len("worktree "):] for part in raw.split("\0")
            if part.startswith("worktree ")]


def snapshot(cwd):
    return {"cwd": str(Path(cwd).resolve()),
            "heads": {path: git(path, "rev-parse", "HEAD") for path in worktrees(cwd)}}


def evidence(before, cwd, actual_cwd=None, worktree_name=""):
    heads = before["heads"]
    launch = before["cwd"]
    paths = worktrees(cwd)
    # A transcript's cwd can identify an existing worktree used by the lane.
    actual = git(actual_cwd, "rev-parse", "--show-toplevel") if actual_cwd else ""
    new = [path for path in paths if path not in heads]
    error = None
    if worktree_name:
        matches = [path for path in paths
                   if path.endswith("/.claude/worktrees/" + worktree_name)]
        target = matches[0] if len(matches) == 1 else None
        if target is None:
            error = "named proof worktree is ambiguous or unavailable: " + worktree_name
    elif actual and actual != launch:
        target = actual
    elif len(new) > 1:
        target, error = None, "proof worktree is ambiguous"
    else:
        target = new[0] if new else launch
    if target is None or not git(target, "rev-parse", "HEAD"):
        return {"worktree": None, "head_before": None, "head_after": None,
                "committed": False, "dirty": False,
                "error": error or "proof worktree is unavailable"}
    initial = heads.get(target)
    if initial is None:
        # The oldest per-worktree HEAD reflog entry is the creation HEAD. Comparing
        # against launch HEAD falsely accepts an untouched worktree on another base.
        entries = git(target, "reflog", "show", "--format=%H", "HEAD").splitlines()
        initial = entries[-1] if entries else ""
    final = git(target, "rev-parse", "HEAD")
    return {"worktree": target, "head_before": initial, "head_after": final,
            "committed": bool(initial and final and initial != final),
            "dirty": bool(git(target, "status", "--porcelain"))}


def main():
    if sys.argv[1] == "snapshot":
        print(json.dumps(snapshot(sys.argv[2])))
        return 0
    before = json.loads(Path(sys.argv[2]).read_text())
    result = evidence(before, sys.argv[3], worktree_name=sys.argv[5] if len(sys.argv) > 5 else "")
    if result.get("error"):
        print("spawn-lane.sh: commit check deferred: " + result["error"], file=sys.stderr)
        return 75
    if result["committed"]:
        return 0
    detail = ("; uncommitted work is left in %s, salvage before re-dispatch" % result["worktree"]
              if result["dirty"] else " and left a clean tree")
    print("spawn-lane.sh: DEAD LANE: %s exited 0 but committed nothing%s" %
          (sys.argv[4], detail), file=sys.stderr)
    return 3


if __name__ == "__main__":
    sys.exit(main())
