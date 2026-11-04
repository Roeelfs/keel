#!/usr/bin/env python3
"""consolidation_check.py against real temporary git repos (a bare origin + clones). No network."""
import io
import json
import os
from contextlib import redirect_stdout
from pathlib import Path
import subprocess
import tempfile
import unittest

import consolidation_check as cc


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t"})


def head(cwd):
    return subprocess.run(["git", "-C", str(cwd), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


class ConsolidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.origin, self.repo = t / "origin.git", t / "repo"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True)
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.repo)], check=True, capture_output=True)
        git(self.repo, "checkout", "-q", "-b", "main")
        (self.repo / "a.txt").write_text("a\n")
        git(self.repo, "add", "a.txt")
        git(self.repo, "commit", "-q", "-m", "init")
        git(self.repo, "push", "-q", "-u", "origin", "main")
        git(self.repo, "remote", "set-head", "origin", "main")
        self.programs = t / "programs"
        self.programs.mkdir()
        cc.PROGRAMS = str(self.programs)
        self.state = t / "p.state.md"
        self.state.write_text("# state\n")

    def tearDown(self):
        self.tmp.cleanup()

    def run_cc(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cc.main(["--no-memory", *args])
        return rc, json.loads(buf.getvalue())

    def add_worktree(self, name, branch):
        wt = Path(self.tmp.name) / name
        git(self.repo, "worktree", "add", "-q", str(wt), "-b", branch)
        return wt

    def test_clean_pushed_worktree_is_ok(self):
        rc, out = self.run_cc("--worktree", str(self.repo), "--strict")
        self.assertEqual((rc, out["worktrees"][0]["state"], out["owed"]), (0, "OK", 0))

    def test_dirty_and_unpushed_are_owed_until_a_reason_is_named(self):
        dirty = self.add_worktree("wt-dirty", "feat/cyn-1-x")
        (dirty / "b.txt").write_text("wip\n")
        ahead = self.add_worktree("wt-ahead", "feat/cyn-2-y")
        (ahead / "c.txt").write_text("c\n")
        git(ahead, "add", "c.txt")
        git(ahead, "commit", "-q", "-m", "local only")
        rc, out = self.run_cc("--worktree", str(dirty), "--worktree", str(ahead), "--strict")
        states = {Path(w["path"]).name: w["state"] for w in out["worktrees"]}
        self.assertEqual(states, {"wt-dirty": "DIRTY", "wt-ahead": "UNPUSHED"})
        self.assertEqual((rc, out["owed"]), (1, 2))
        rc, out = self.run_cc("--worktree", str(dirty), "--worktree", str(ahead), "--strict",
                              "--reason", f"{dirty}=lane still writing", "--reason", f"{ahead}=pushed at next tick")
        self.assertEqual((rc, out["owed"]), (0, 0))

    def test_program_family_comes_from_bindings_and_ticket_branches(self):
        fam = self.add_worktree("wt-fam", "feat/cyn-7-thing")
        self.add_worktree("wt-other", "feat/cyn-9-unrelated")
        self.add_worktree("wt-prefix", "feat/cyn-71-shares-a-prefix")
        (self.programs / "p.json").write_text(json.dumps({
            "program": "p", "bindings": [{"ticket": "CYN-7"}],
            "repos": [{"repo": "o/r", "path": str(self.repo)}]}))
        rc, out = self.run_cc("--program", "p")
        self.assertEqual([Path(w["path"]).name for w in out["worktrees"]], ["wt-fam"])
        self.assertEqual(os.path.realpath(out["worktrees"][0]["path"]), os.path.realpath(fam))

    def test_missing_worktree_is_reported_not_owed(self):
        rc, out = self.run_cc("--worktree", str(Path(self.tmp.name) / "gone"), "--strict")
        self.assertEqual((rc, out["worktrees"][0]["state"]), (0, "MISSING"))

    def test_commit_claims_are_checked_by_git(self):
        pushed = head(self.repo)
        wt = self.add_worktree("wt-claim", "feat/cyn-3-z")
        (wt / "d.txt").write_text("d\n")
        git(wt, "add", "d.txt")
        git(wt, "commit", "-q", "-m", "unpushed")
        local = head(wt)
        rc, out = self.run_cc("--claim", f"{self.repo}:{pushed}", "--claim", f"{self.repo}:{local}",
                              "--claim", f"{self.repo}:{'0' * 40}", "--strict")
        v = [(c["verdict"], c.get("on_default")) for c in out["claims"]]
        self.assertEqual(v, [("CONFIRMED", True), ("UNCONFIRMED", False), ("UNCONFIRMED", False)])
        self.assertEqual(rc, 1)

    def test_record_appends_a_consolidation_block(self):
        dirty = self.add_worktree("wt-rec", "feat/cyn-4-r")
        (dirty / "e.txt").write_text("e\n")
        self.run_cc("--worktree", str(dirty), "--record", str(self.state))
        text = self.state.read_text()
        self.assertIn("## Consolidation ", text)
        self.assertIn("- worktree DIRTY", text)
        self.assertIn("- memory NOT-RUN", text)
        self.assertTrue(text.rstrip().endswith("Consolidation: OWED (1 owed)"))


if __name__ == "__main__":
    unittest.main()
