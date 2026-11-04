#!/usr/bin/env python3
"""Mock runtimes, real temporary git worktrees; never dispatch a real lane."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import test_spawn_lane_runtime as runtime_tests
from test_spawn_lane_runtime import git
import lane_proof

HERE = Path(__file__).resolve().parent


class ProofTests(unittest.TestCase):
    setUp = runtime_tests.RuntimeTests.setUp
    tearDown = runtime_tests.RuntimeTests.tearDown

    def spawn(self, *args, runtime="claude", own=False, change=False, runtime_rc=0, no_commit=False):
        scripts = self.root / "scripts"
        scripts.mkdir(exist_ok=True)
        for name in ("spawn-lane.sh", "lane_commit_guard.py", "lane_proof.py"):
            shutil.copyfile(HERE / name, scripts / name)
        (scripts / "spawn-lane.sh").chmod(0o755)
        if getattr(self, "mutation", None):
            file, old, new = self.mutation
            p = scripts / file
            self.assertIn(old, p.read_text())
            p.write_text(p.read_text().replace(old, new))
        proof = self.base / "proof.py"
        if not proof.exists():
            proof.write_text('import pathlib, sys\npathlib.Path("proof-ran").write_text("yes")\nsys.exit(int(sys.argv[1]))\n')
            git("add", "proof.py", cwd=self.base)
            git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "proof seed", cwd=self.base)
        mock = '''#!/bin/bash
set -eu
printf '%s\\n' "$@" > "$STUB_OUT"
if [ "$OWN" = 1 ]; then
  git -c core.hooksPath=/dev/null worktree add -qb lane "$OWN_CWD" >&2
  cd "$OWN_CWD"
fi
if [ "$CHANGE" = 1 ]; then printf '\\n# lane edit\\n' >> proof.py; git add proof.py; fi
if [ "$NO_COMMIT" = 0 ]; then git -c core.hooksPath=/dev/null -c user.name=t -c user.email=t@t commit -qm delivery --allow-empty; fi
printf '{"type":"result","is_error":false}'
exit "$RUNTIME_RC"
'''
        for name in ("claude", "codex"):
            (self.bin / name).write_text(mock)
        env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}", "HOME": str(self.home),
               "S2C_CLAUDE_HOME": str(self.home / ".claude"), "CLAUDE_SESSION_ID": "",
               "STUB_OUT": str(self.out), "STUB_GATE_ARGS": str(self.root / "gate-args"),
               "WORK_STATE_LANE_ROWS": str(self.root / "lane-parents.jsonl"),
               "OWN": str(int(own)), "OWN_CWD": str((self.root / "own").resolve()),
               "CHANGE": str(int(change)), "NO_COMMIT": str(int(no_commit)), "RUNTIME_RC": str(runtime_rc)}
        return subprocess.run([str(scripts / "spawn-lane.sh"), "--mission", str(self.mission),
                               "--cwd", str(self.base), "--runtime", runtime, "--class", "implementation",
                               "--ticket", "T-1", *args], env=env, capture_output=True, text=True, timeout=15)

    def rows(self):
        p = self.root / "lane-proofs.jsonl"
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    def assert_proof(self, rc, outcome, runtime="claude", **kw):
        r = self.spawn("--proof", "python3", "proof.py", str(rc), runtime=runtime, **kw)
        self.assertEqual(r.returncode, 0 if rc == 0 else 75 if rc == 75 else 4, r.stderr)
        row = self.rows()[-1]
        self.assertEqual(row["outcome"], outcome)
        self.assertEqual(row["exit_code"], rc)
        self.assertEqual(row["ticket"], "T-1")
        self.assertNotEqual(row["head_before"], row["head_after"])
        self.assertTrue(row["lane"])
        self.assertTrue(row["ts"])
        self.assertEqual(row["command"], ["python3", "proof.py", str(rc)])
        self.assertTrue((Path(row["worktree"]) / "proof-ran").exists())
        return row

    def test_pass_fail_deferred_both_runtimes_append_once_each(self):
        for runtime in ("claude", "codex"):
            for rc, outcome in ((0, "pass"), (1, "fail"), (75, "deferred")):
                with self.subTest(runtime=runtime, outcome=outcome):
                    self.assert_proof(rc, outcome, runtime)
        self.assertEqual(len(self.rows()), 6)

    def test_absent_proof_preserves_behavior_and_writes_no_receipt(self):
        for runtime in ("claude", "codex"):
            self.assertEqual(self.spawn(runtime=runtime).returncode, 0)
        self.assertEqual(self.rows(), [])
        self.assertFalse((self.base / "proof-ran").exists())

    def test_proof_runs_in_created_worktree_and_failure_preserves_salvage(self):
        row = self.assert_proof(1, "fail", own=True)
        self.assertEqual(Path(row["worktree"]), (self.root / "own").resolve())
        self.assertFalse((self.base / "proof-ran").exists())
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=row["worktree"], text=True).strip()
        self.assertEqual(head, row["head_after"])

    def test_own_files_advisory_does_not_fail(self):
        self.assertFalse(self.assert_proof(0, "pass")["proof_files_changed"])
        row = self.assert_proof(0, "pass", change=True)
        self.assertTrue(row["proof_files_changed"])
        self.assertEqual(row["changed_proof_files"], ["proof.py"])

    def test_runtime_failure_still_has_proof_attempt(self):
        r = self.spawn("--proof", "python3", "proof.py", "0", runtime_rc=7)
        self.assertEqual(r.returncode, 7)
        self.assertEqual(self.rows()[-1]["outcome"], "pass")

    def test_proof_is_opt_in_for_nonimplementation_both_runtimes(self):
        for runtime in ("claude", "codex"):
            r = self.spawn("--class", "research", "--proof", "python3", "proof.py", "1",
                           runtime=runtime, no_commit=True)
            self.assertEqual(r.returncode, 4, r.stderr)
            self.assertEqual(self.rows()[-1]["outcome"], "fail")
            self.assertEqual(self.rows()[-1]["head_before"], self.rows()[-1]["head_after"])

    def test_caps_pass_through_claude_and_codex_refuses(self):
        r = self.spawn("--max-turns", "5", "--max-budget-usd", "1.25")
        self.assertEqual(r.returncode, 0, r.stderr)
        argv = self.out.read_text().splitlines()
        self.assertEqual(argv[argv.index("--max-turns") + 1], "5")
        self.assertEqual(argv[argv.index("--max-budget-usd") + 1], "1.25")
        self.assertEqual(self.spawn("--max-turns", "5", runtime="codex").returncode, 2)

    def test_mutation_controls_reject_false_pass_deferred_and_own_files(self):
        for old, new, rc, outcome in (
            ('return 0 if rc == 0 else 75 if rc == 75 else 4', 'return 0', 1, "fail"),
            ('"deferred" if rc == 75', '"pass" if rc == 75', 75, "deferred"),
            ('"proof_files_changed": bool(own)', '"proof_files_changed": False', 0, "pass"),
        ):
            with self.subTest(mutation=old):
                self.mutation = ("lane_proof.py", old, new)
                with self.assertRaises(AssertionError):
                    row = self.assert_proof(rc, outcome, change=True)
                    self.assertTrue(row["proof_files_changed"])

    def test_mutation_control_missing_proof_is_detected(self):
        self.mutation = ("spawn-lane.sh", 'run_proof "$LANE_SESSION"', ': # proof removed')
        r = self.spawn("--proof", "python3", "proof.py", "1")
        self.assertEqual(r.returncode, 0, "mutant must violate the failure expectation")
        self.assertEqual(self.rows(), [])


class CountTests(unittest.TestCase):
    def test_deferral_does_not_count_and_pass_clears(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "proofs.jsonl"
            for outcome in ("fail", "fail", "deferred"):
                lane_proof.append({"ticket": "T-1", "outcome": outcome}, p)
            self.assertEqual(lane_proof.failure_counts(p), {"T-1": 2})
            lane_proof.append({"ticket": "T-1", "outcome": "fail"}, p)
            self.assertEqual(lane_proof.failure_counts(p), {"T-1": 3})
            lane_proof.append({"ticket": "T-1", "outcome": "pass"}, p)
            self.assertEqual(lane_proof.failure_counts(p), {"T-1": 0})

    def test_mutation_control_pass_not_clearing_is_detected(self):
        source = Path(lane_proof.__file__).read_text()
        self.assertIn('counts[ticket] = 0', source)
        namespace = dict(vars(lane_proof), __name__="proof_mutant")
        exec(compile(source.replace('counts[ticket] = 0', 'counts[ticket] = counts.get(ticket, 0)'),
                     lane_proof.__file__, "exec"), namespace)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "rows.jsonl"
            for outcome in ("fail", "fail", "fail", "pass"):
                lane_proof.append({"ticket": "T-1", "outcome": outcome}, p)
            with self.assertRaises(AssertionError):
                self.assertEqual(namespace["failure_counts"](p)["T-1"], 0)


if __name__ == "__main__":
    unittest.main()
