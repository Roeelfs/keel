#!/usr/bin/env python3
"""Run an opt-in argv proof and keep one append-only receipt per attempt.

A receipt is targeted evidence, never a bake. Named argv files are compared to
changed paths; this advisory cannot discover files imported indirectly by a test.
"""
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime, timezone

import lane_commit_guard as guard


def rows_path():
    lanes = os.environ.get("WORK_STATE_LANE_ROWS")
    home = os.environ.get("S2C_CLAUDE_HOME") or str(Path.home() / ".claude")
    return Path(lanes).with_name("lane-proofs.jsonl") if lanes else Path(home) / "state/lane-proofs.jsonl"


def append(row, path=None):
    path = Path(path) if path else rows_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.write(json.dumps(row) + "\n")


def failure_counts(path=None):
    """Count failures since the latest pass; deferrals never increment or clear."""
    counts = {}
    try:
        fh = (Path(path) if path else rows_path()).open()
    except FileNotFoundError:
        return counts
    with fh:
        for line in fh:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict) or not row.get("ticket"):
                continue
            ticket = row["ticket"]
            if row.get("outcome") == "pass":
                counts[ticket] = 0
            elif row.get("outcome") == "fail":
                counts[ticket] = counts.get(ticket, 0) + 1
    return counts


def proof_files(argv, cwd):
    paths = set()
    for i, arg in enumerate(argv):
        candidate = Path(cwd) / arg
        if i == 0 and not candidate.is_file():
            candidate = Path(shutil.which(arg) or candidate)
        if candidate.is_file():
            try:
                paths.add(str(candidate.resolve().relative_to(Path(cwd).resolve())))
            except ValueError:
                continue
    return paths


def run(before, cwd, lane, ticket, argv, worktree_name=""):
    evidence = guard.evidence(before, cwd, worktree_name=worktree_name)
    target = evidence["worktree"]
    own = []
    error = evidence.get("error")
    if error:
        rc = 75
    else:
        changed = set(guard.git(target, "diff", "--name-only", evidence["head_before"], evidence["head_after"]).splitlines())
        own = sorted(proof_files(argv, target) & changed)
        try:
            rc = subprocess.run(argv, cwd=target, stdin=subprocess.DEVNULL,
                                env={**os.environ, "CYNAP_HEADLESS_LANE": "1"}).returncode
        except OSError as exc:
            rc, error = 127, str(exc)
    outcome = "pass" if rc == 0 else "deferred" if rc == 75 else "fail"
    row = {"ticket": ticket or None, "lane": lane, "worktree": target,
           "head_before": evidence["head_before"], "head_after": evidence["head_after"],
           "command": argv, "exit_code": rc, "outcome": outcome,
           "ts": datetime.now(timezone.utc).isoformat(),
           "proof_files_changed": bool(own), "changed_proof_files": own}
    if error:
        row = {**row, "error": error}
    append(row)  # A requested proof must never silently lose its receipt.
    print(f"spawn-lane.sh: proof {outcome} (rc={rc}, own files changed={bool(own)})", file=sys.stderr)
    return 0 if rc == 0 else 75 if rc == 75 else 4


if __name__ == "__main__":
    sys.exit(run(json.loads(Path(sys.argv[1]).read_text()), *sys.argv[2:5], sys.argv[6:], worktree_name=sys.argv[5]))
