#!/usr/bin/env python3
"""Shared zero-commit evidence for headless lanes and the shadow Agent hook.

Never count a changed sibling checkout. The proof worktree resolves deterministically:
  1. a named lane (--worktree <name>) selects its worktree by path, preferring the one
     created during the run when the name matches more than one;
  2. a transcript cwd (the shadow Agent hook) selects that checkout;
  3. the launch checkout, when its HEAD moved: the lane committed where it was launched,
     so worktrees other sessions created meanwhile are irrelevant (2026-11-25: in a busy repo
     every --cwd lane in a linked worktree came back "ambiguous", rc=75, despite commits);
  4. otherwise the one worktree created during the run, else the launch checkout.
Compare its HEAD to its own creation reflog. Only a lane whose launch HEAD did not move while
several worktrees appeared stays unproven, and the error names the candidates.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def git(cwd, *args):
    result = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True,
                            text=True, timeout=5)
    return result.stdout.strip() if result.returncode == 0 else ""


def real(path):
    return os.path.realpath(path) if path else path


def worktrees(cwd):
    raw = git(cwd, "worktree", "list", "--porcelain", "-z")
    return [real(part[len("worktree "):]) for part in raw.split("\0")
            if part.startswith("worktree ")]


def snapshot(cwd):
    return {"cwd": real(str(Path(cwd).resolve())), "ts": time.time(),
            "heads": {path: git(path, "rev-parse", "HEAD") for path in worktrees(cwd)}}


def _named(paths, heads, worktree_name):
    matches = [path for path in paths if path.endswith("/.claude/worktrees/" + worktree_name)]
    fresh = [path for path in matches if path not in heads]
    for pool in (fresh, matches):
        if len(pool) == 1:
            return pool[0], None
    if not matches:
        return None, ("named proof worktree is unavailable: no worktree ends in .claude/worktrees/"
                      + worktree_name)
    return None, "named proof worktree is ambiguous: %s matches %s" % (worktree_name, ", ".join(matches))


def evidence(before, cwd, actual_cwd=None, worktree_name=""):
    heads = {real(k): v for k, v in before["heads"].items()}
    launch = real(before["cwd"])
    launch_top = real(git(launch, "rev-parse", "--show-toplevel")) or launch
    paths = worktrees(cwd)
    # A transcript's cwd can identify an existing worktree used by the lane.
    actual = real(git(actual_cwd, "rev-parse", "--show-toplevel")) if actual_cwd else ""
    new = [path for path in paths if path not in heads]
    launch_before = heads.get(launch_top)
    launch_moved = bool(launch_before) and git(launch_top, "rev-parse", "HEAD") not in ("", launch_before)
    error = None
    if worktree_name:
        target, error = _named(paths, heads, worktree_name)
    elif actual and actual not in (launch, launch_top):
        target = actual
    elif launch_moved or not new:
        target = launch_top
    elif len(new) == 1:
        target = new[0]
    else:
        target, error = None, ("proof worktree is ambiguous: the launch checkout %s did not move and %d "
                               "worktrees appeared during the run (%s)" % (launch_top, len(new), ", ".join(new)))
    if target is None or not git(target, "rev-parse", "HEAD"):
        return {"worktree": None, "head_before": None, "head_after": None,
                "committed": False, "dirty": False,
                "error": error or "proof worktree is unavailable: %s has no HEAD" % target}
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


def foreign_links(worktree):
    """node_modules symlinks (root, apps/*, packages/*) resolving outside the worktree."""
    root = Path(worktree).resolve()
    candidates = [root / "node_modules", *root.glob("apps/*/node_modules"),
                  *root.glob("packages/*/node_modules")]
    hits = []
    for link in candidates:
        if not link.is_symlink():
            continue
        target = link.resolve()
        if target != root and root not in target.parents:
            hits.append((link, target))
    return hits


def warn_foreign_links(worktree):
    """Best-effort: one line per foreign link plus its removal command; never deletes or fails."""
    try:
        for link, target in foreign_links(worktree) if worktree else []:
            print("spawn-lane.sh: FOREIGN LINK %s -> %s (lanes never link another checkout; "
                  "remove: rm %s)" % (link, target, link), file=sys.stderr)
    except Exception as exc:  # noqa: BLE001 - advisory must never fail the lane
        print("spawn-lane.sh: foreign-link check skipped: %s" % exc, file=sys.stderr)


def main():
    if sys.argv[1] == "snapshot":
        print(json.dumps(snapshot(sys.argv[2])))
        return 0
    before = json.loads(Path(sys.argv[2]).read_text())
    result = evidence(before, sys.argv[3], worktree_name=sys.argv[5] if len(sys.argv) > 5 else "")
    warn_foreign_links(result.get("worktree"))
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
