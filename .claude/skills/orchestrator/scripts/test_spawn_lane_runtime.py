#!/usr/bin/env python3
"""Behavioral tests for `spawn-lane.sh --runtime codex`.

Not phrase-matching: a stub `codex` earlier on PATH records the real argv, so these
assert the command the script actually builds."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "spawn-lane.sh"
STUB = '#!/bin/bash\nprintf "%s\\n" "$@" > "$STUB_OUT"\n'


def git(*args, cwd=None):
    subprocess.run(["git", *args], cwd=cwd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin"; self.bin.mkdir()
        for name in ("codex", "claude"):
            p = self.bin / name
            p.write_text(STUB); p.chmod(0o755)
        self.out = self.root / "argv.txt"
        self.base = self.root / "base"; self.base.mkdir()
        git("init", "-q", ".", cwd=self.base)
        (self.base / "s.txt").write_text("seed")
        git("add", "-A", cwd=self.base)
        git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "seed", cwd=self.base)
        self.mission = self.root / "m.md"; self.mission.write_text("do the thing")

    def tearDown(self):
        self.tmp.cleanup()

    def spawn(self, cwd, *extra):
        env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", STUB_OUT=str(self.out))
        r = subprocess.run([str(SCRIPT), "--mission", str(self.mission), "--cwd", str(cwd), *extra],
                           capture_output=True, text=True, env=env)
        argv = self.out.read_text().splitlines() if self.out.exists() else []
        return r, argv

    def roots(self, argv):
        for a in argv:
            if a.startswith("sandbox_workspace_write.writable_roots="):
                return a.split("=", 1)[1]
        return ""

    def test_default_runtime_is_still_claude(self):
        # Every existing call site must be unchanged by this feature.
        _, argv = self.spawn(self.base)
        self.assertIn("-p", argv)
        self.assertIn("--output-format", argv)

    def test_codex_runtime_grants_the_git_dir(self):
        _, argv = self.spawn(self.base, "--runtime", "codex")
        self.assertIn("workspace-write", argv)
        self.assertIn(str((self.base / ".git").resolve()), self.roots(argv))

    def test_linked_worktree_grants_BOTH_git_dirs(self):
        # The bug this pins: in a linked worktree, objects and refs/heads live in the
        # COMMON dir, outside the workspace. Granting only --absolute-git-dir writes the
        # file and then dies on `Operation not permitted`. Verified against a real lane.
        lane = self.root / "lane"
        git("worktree", "add", "-q", str(lane), "-b", "lane-b", cwd=self.base)
        _, argv = self.spawn(lane, "--runtime", "codex")
        roots = self.roots(argv)
        self.assertIn("worktrees/lane", roots, "per-worktree git dir must be granted")
        self.assertIn(f'"{(self.base / ".git").resolve()}"', roots,
                      "the COMMON git dir must be granted or the lane cannot commit")
        # CLOSED SET, not a floor. The two assertIn calls above name WHICH paths must be
        # granted; on their own they are blind to a THIRD root being added later — a
        # silent widening of the sandbox. Measured 2026-08-25: adding an unconditional
        # third root is caught by test_writable_roots_are_json_encoded_not_interpolated's
        # existing assertEqual(len(parsed), 1), but adding one inside the linked-worktree
        # branch left all 13 tests green. Cardinality closes that hole; keep both
        # assertIn calls, because cardinality alone would not say which two.
        parsed = json.loads(roots)
        self.assertEqual(len(parsed), 2,
                         "a linked worktree must grant exactly the per-worktree dir and "
                         "the common dir, nothing else")

    def test_network_is_DENIED_by_default(self):
        # The lane must not hold push authority. With HOME preserved, shared git config
        # granted and network open, it could `git push origin HEAD:main` as easily as its
        # own branch, gated only by prompt text. Denying egress removes the question.
        _, argv = self.spawn(self.base, "--runtime", "codex")
        self.assertNotIn("sandbox_workspace_write.network_access=true", argv)

    def test_network_is_opt_in_and_explicit(self):
        _, argv = self.spawn(self.base, "--runtime", "codex", "--allow-network")
        self.assertIn("sandbox_workspace_write.network_access=true", argv)

    def test_writable_roots_are_json_encoded_not_interpolated(self):
        # A `"` in a path previously injected ADDITIONAL writable roots (demonstrated
        # granting ~/.ssh, exit 0, no shell metacharacter needed).
        evil = self.root / 'ev"il'
        evil.mkdir()
        git("init", "-q", ".", cwd=evil)
        (evil / "s.txt").write_text("s")
        git("add", "-A", cwd=evil)
        git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "s", cwd=evil)
        _, argv = self.spawn(evil, "--runtime", "codex")
        roots = self.roots(argv)
        self.assertTrue(roots.startswith("["), roots)
        parsed = json.loads(roots)
        self.assertTrue(all(isinstance(r, str) for r in parsed))
        self.assertTrue(any('ev"il' in r for r in parsed), "the real path must survive encoding")
        self.assertEqual(len(parsed), 1, "a quote in the path must not inject extra roots")

    def test_a_lane_output_file_is_requested(self):
        # Claude gets --output-format json so empty output + exit 0 proves it never ran.
        # docs/codex-lane-contract.md requires -o <outfile> for the same classification.
        _, argv = self.spawn(self.base, "--runtime", "codex")
        self.assertIn("-o", argv)

    def test_the_mission_carries_the_session_id_and_no_push_rule(self):
        _, argv = self.spawn(self.base, "--runtime", "codex")
        # The stub records one argv element per LINE, so a multi-line mission spans lines;
        # search the joined text rather than the last line.
        mission = "\n".join(argv)
        self.assertIn("Session-Id: codex-lane-", mission)
        self.assertIn("Do NOT push", mission)

    def test_mcp_config_is_refused_rather_than_silently_dropped(self):
        cfg = self.root / "m.json"; cfg.write_text("{}")
        r, _ = self.spawn(self.base, "--runtime", "codex", "--mcp-config", str(cfg))
        self.assertEqual(r.returncode, 2)
        self.assertIn("claude-only", r.stderr)

    def test_mode_is_refused_rather_than_silently_dropped(self):
        r, _ = self.spawn(self.base, "--runtime", "codex", "--mode", "acceptEdits")
        self.assertEqual(r.returncode, 2)
        self.assertIn("claude-only", r.stderr)

    def test_codex_runtime_never_uses_the_home_isolating_wrapper(self):
        # That wrapper strips git identity; a shipping lane must keep it.
        _, argv = self.spawn(self.base, "--runtime", "codex")
        self.assertNotIn("codex-dispatch.sh", " ".join(argv))

    def test_an_unknown_runtime_is_rejected(self):
        r, _ = self.spawn(self.base, "--runtime", "bogus")
        self.assertEqual(r.returncode, 2)
        self.assertIn("claude|codex", r.stderr)

    def test_worktree_flag_is_refused_on_codex(self):
        # Codex has no --worktree equivalent; failing loudly beats spawning in the wrong dir.
        r, _ = self.spawn(self.base, "--runtime", "codex", "--worktree", "x")
        self.assertEqual(r.returncode, 2)
        self.assertIn("claude-only", r.stderr)


if __name__ == "__main__":
    unittest.main()
