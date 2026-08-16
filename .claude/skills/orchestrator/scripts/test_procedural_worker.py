#!/usr/bin/env python3
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
CORE = (SKILL_DIR / "SKILL.md").read_text()
RUNTIME = (SKILL_DIR / "references" / "codex-runtime.md").read_text()
ROUTING = (SKILL_DIR / "prompts" / "model-routing.md").read_text()
PROMPT = (SKILL_DIR / "prompts" / "procedural-worker.md").read_text()
def load_validator():
    path = Path(__file__).with_name("validate_procedural_result.py")
    spec = importlib.util.spec_from_file_location("validate_procedural_result", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ProceduralWorkerContractTests(unittest.TestCase):
    def test_root_worker_boundary_is_explicit(self):
        for text in (
            "control plane",
            "execution plane",
            "small bounded read-only probes",
            "production mutations",
        ):
            self.assertIn(text, CORE)

    def test_excerpt_carries_every_sub_check_not_only_the_failure(self):
        # A gate whose output enumerates N/M sub-checks was reported to the root
        # as one failing line, so the root fixed one check per gate run (five
        # cyn1489-verify-<sha> evidence dirs for one ticket, 2026-08-15).
        for text in (
            "enumerates named sub-checks",
            "every** sub-check",
            "one-bit report",
        ):
            self.assertIn(text, PROMPT)

    def test_pass_budget_is_documented_where_the_worker_contract_lives(self):
        for text in (
            "pass budget",
            "third *failing* pass",
            "all four lane-dispatch substrates",
        ):
            self.assertIn(text, PROMPT)

    def test_artifact_dir_basename_is_a_ticket_keyed_contract(self):
        # Left as free text, the evidence root could not answer "how many passes
        # has this ticket spent" — so a per-phase budget was reset by renaming
        # the lane (verify_release -> _correction -> _final -> _final_lint).
        for text in (
            "<ticket>-<pass-kind>-<short-sha>",
            "is a contract, not a convention",
            "a rename cannot reset",
        ):
            self.assertIn(text, PROMPT)

    def test_native_worker_is_fresh_low_effort_and_owns_process(self):
        for text in ('fork_turns: "none"', 'reasoning_effort: "low"', "Terra-low"):
            self.assertIn(text, RUNTIME + PROMPT + ROUTING)
        self.assertIn("root never calls `write_stdin`", RUNTIME)
        self.assertIn("latency-sized event wait", RUNTIME)
        self.assertIn("explicit child lease", RUNTIME + PROMPT)
        self.assertIn("interrupt the child", RUNTIME)
        self.assertIn("durable handoff", RUNTIME + PROMPT)
        self.assertNotIn("distinct unrelated mailbox update", RUNTIME)

    def test_worker_does_not_take_judgment_or_write_scope(self):
        self.assertIn(
            "You are a leaf agent: do NOT spawn sub-agents or Workflows",
            PROMPT,
        )
        for text in (
            "never edits source",
            "diagnoses a failure",
            "mutates production",
            "allowed_write_paths",
            "unexpected tracked-path",
        ):
            self.assertIn(text, PROMPT + RUNTIME)
        self.assertIn("literal string `procedural-summary/v1`", PROMPT)
        self.assertIn("nonempty string, never an object", PROMPT)

    def test_result_schema_accepts_only_a_valid_pointer(self):
        validator = load_validator()
        with tempfile.TemporaryDirectory() as temp:
            artifact_dir = Path(temp)
            log = artifact_dir / "verify.log"
            log.write_text("OK\n")
            artifact = artifact_dir / "summary.json"
            summary = {
                "schema": "procedural-summary/v1",
                "pass_id": "verify-1",
                "status": "pass",
                "head_sha": "a" * 40,
                "tracked_diff_sha256_before": "c" * 64,
                "tracked_diff_sha256_after": "c" * 64,
                "command_results": [{
                    "id": "verify",
                    "status": "pass",
                    "exit_code": 0,
                    "log": str(log),
                    "decisive_excerpt": "OK",
                }],
                "environment": "isolated test fixture",
                "blocker": None,
            }
            artifact.write_text(json.dumps(summary))
            value = {
                "schema": "procedural-worker/v1",
                "pass_id": "verify-1",
                "status": "pass",
                "head_sha": "a" * 40,
                "artifact": str(artifact),
                "unexpected_writes": [],
            }
            text = json.dumps(value, separators=(",", ":"))
            self.assertEqual([], validator.validate_text(text, "a" * 40))
            invalid = {
                "missing artifact": value | {"artifact": str(Path(temp) / "missing.json")},
                "wrong sha": value | {"head_sha": "b" * 40},
                "unexpected write": value | {"unexpected_writes": ["src/x.ts"]},
                "extra key": value | {"evidence": "inline"},
            }
            for name, candidate in invalid.items():
                with self.subTest(name=name):
                    self.assertTrue(
                        validator.validate_text(
                            json.dumps(candidate, separators=(",", ":")), "a" * 40
                        )
                    )
            self.assertTrue(validator.validate_text(text + "\nprose", "a" * 40))
            self.assertTrue(validator.validate_text(json.dumps(value | {"pass_id": "x" * 1100})))
            artifact.write_text("{}")
            self.assertTrue(validator.validate_text(text, "a" * 40))

    def test_pass_budget_refuses_the_third_failing_pass_on_one_stem(self):
        # cyn1489 spent five gate passes moving one check at a time, because each
        # new lane name (verify_release -> _correction -> _final -> _final_lint)
        # minted a fresh per-phase budget. The stem is what a rename cannot change.
        validator = load_validator()

        def make_dir(root, name, status):
            directory = Path(root) / name
            directory.mkdir()
            if status is not None:
                (directory / "procedural-summary.json").write_text(json.dumps({"status": status}))
            return directory

        def pointer_for(directory, status):
            return {
                "schema": "procedural-worker/v1",
                "pass_id": directory.name,
                "status": status,
                "head_sha": "c" * 40,
                "artifact": str(directory / "procedural-summary.json"),
                "unexpected_writes": [],
            }

        with tempfile.TemporaryDirectory() as temp:
            make_dir(temp, "cyn1489-verify-0f770780d", "fail")
            second = make_dir(temp, "cyn1489-verify-68db987e5", "fail")
            # Second failing pass is a correction cycle, not the treadmill.
            self.assertEqual([], validator.validate_pass_budget(pointer_for(second, "fail"), Path(temp)))
            third = make_dir(temp, "cyn1489-verify-02d19e055", "fail")
            errors = validator.validate_pass_budget(pointer_for(third, "fail"), Path(temp))
            self.assertEqual(1, len(errors))
            self.assertIn("failing pass #3", errors[0])
            self.assertIn("cyn1489-verify", errors[0])
            self.assertIn("Batch EVERY open failure", errors[0])
            # Convergence is not the treadmill: a PASSING gate never trips it,
            # which is also what keeps the sequential runtime carve-out legal.
            self.assertEqual([], validator.validate_pass_budget(pointer_for(third, "pass"), Path(temp)))
            # A different stem has its own budget.
            other = make_dir(temp, "cyn1490-verify-aaaaaaaaa", "fail")
            self.assertEqual([], validator.validate_pass_budget(pointer_for(other, "fail"), Path(temp)))

    def test_pass_budget_tolerates_evidence_predating_the_naming_contract(self):
        # The naming contract is prospective. A legacy or half-written sibling is
        # unreadable, not a failure — counting it would invent a treadmill.
        validator = load_validator()
        with tempfile.TemporaryDirectory() as temp:
            # Enough unreadable siblings that counting ANY of them as a failure
            # would trip the budget — otherwise this test cannot detect the bug.
            for name in ("cyn1489-cyn1490-v30-verify", "cyn1489-verify-0af10d423"):
                (Path(temp) / name).mkdir()
            for name in ("cyn1489-verify-0f770780d", "cyn1489-verify-1111111"):
                (Path(temp) / name).mkdir()
                (Path(temp) / name / "procedural-summary.json").write_text("{ broken")
            current = Path(temp) / "cyn1489-verify-68db987e5"
            current.mkdir()
            pointer = {
                "schema": "procedural-worker/v1",
                "pass_id": "p",
                "status": "fail",
                "head_sha": "c" * 40,
                "artifact": str(current / "procedural-summary.json"),
                "unexpected_writes": [],
            }
            self.assertEqual([], validator.validate_pass_budget(pointer, Path(temp)))
            # A non-conforming CURRENT dir has no budget key, so nothing is counted.
            stray = Path(temp) / "adhoc-scratch"
            stray.mkdir()
            self.assertEqual(
                [],
                validator.validate_pass_budget(pointer | {"artifact": str(stray / "s.json")}, Path(temp)),
            )

    def test_summary_rejects_forged_success_and_unbounded_output(self):
        validator = load_validator()
        with tempfile.TemporaryDirectory() as temp:
            artifact_dir = Path(temp)
            log = artifact_dir / "verify.log"
            log.write_text("failed\n")
            artifact = artifact_dir / "summary.json"
            pointer = {
                "schema": "procedural-worker/v1",
                "pass_id": "verify-1",
                "status": "pass",
                "head_sha": "a" * 40,
                "artifact": str(artifact),
                "unexpected_writes": [],
            }
            command = {
                "id": "verify",
                "status": "pass",
                "exit_code": 0,
                "log": str(log),
                "decisive_excerpt": "OK",
            }
            base = {
                "schema": "procedural-summary/v1",
                "pass_id": "verify-1",
                "status": "pass",
                "head_sha": "a" * 40,
                "tracked_diff_sha256_before": "c" * 64,
                "tracked_diff_sha256_after": "c" * 64,
                "command_results": [command],
                "environment": "fixture",
                "blocker": None,
            }
            forged = {
                "pass with failing command": base | {
                    "command_results": [command | {"exit_code": 1}],
                },
                "malformed command": base | {"command_results": [{}]},
                "missing log": base | {
                    "command_results": [command | {"log": str(artifact_dir / "missing.log")}],
                },
                "mismatched diff hashes": base | {"tracked_diff_sha256_after": "d" * 64},
                "embedded full output": base | {
                    "command_results": [command | {"full_output": "raw"}],
                },
                "oversized excerpt": base | {
                    "command_results": [command | {"decisive_excerpt": "x" * 2049}],
                },
            }
            for name, summary in forged.items():
                with self.subTest(name=name):
                    artifact.write_text(json.dumps(summary))
                    self.assertTrue(validator.validate_text(json.dumps(pointer), "a" * 40))

    def test_status_and_blocker_consistency(self):
        validator = load_validator()
        with tempfile.TemporaryDirectory() as temp:
            artifact_dir = Path(temp)
            log = artifact_dir / "verify.log"
            log.write_text("failed\n")
            artifact = artifact_dir / "summary.json"
            pointer = {
                "schema": "procedural-worker/v1",
                "pass_id": "verify-1",
                "status": "fail",
                "head_sha": "a" * 40,
                "artifact": str(artifact),
                "unexpected_writes": [],
            }
            summary = {
                "schema": "procedural-summary/v1",
                "pass_id": "verify-1",
                "status": "fail",
                "head_sha": "a" * 40,
                "tracked_diff_sha256_before": "c" * 64,
                "tracked_diff_sha256_after": "c" * 64,
                "command_results": [{
                    "id": "verify",
                    "status": "fail",
                    "exit_code": 1,
                    "log": str(log),
                    "decisive_excerpt": "failed",
                }],
                "environment": "fixture",
                "blocker": None,
            }
            artifact.write_text(json.dumps(summary))
            self.assertEqual([], validator.validate_text(json.dumps(pointer), "a" * 40))
            artifact.write_text(json.dumps(summary | {"status": "pass"}))
            self.assertTrue(validator.validate_text(json.dumps(pointer | {"status": "pass"}), "a" * 40))
            blocked = summary | {
                "status": "blocked",
                "command_results": [],
                "blocker": {"reason": "auth expired", "resume_key": "reauth"},
            }
            artifact.write_text(json.dumps(blocked))
            self.assertEqual([], validator.validate_text(json.dumps(pointer | {"status": "blocked"}), "a" * 40))
            artifact.write_text(json.dumps(blocked | {"blocker": {}}))
            self.assertTrue(validator.validate_text(json.dumps(pointer | {"status": "blocked"}), "a" * 40))

    def test_correction_requires_new_pass_sha_and_artifact(self):
        validator = load_validator()
        previous = json.dumps({
            "schema": "procedural-worker/v1",
            "pass_id": "verify-1",
            "status": "fail",
            "head_sha": "a" * 40,
            "artifact": "/tmp/verify-1/summary.json",
            "unexpected_writes": [],
        })
        correction = json.dumps({
            "schema": "procedural-worker/v1",
            "pass_id": "verify-2",
            "status": "pass",
            "head_sha": "b" * 40,
            "artifact": "/tmp/verify-2/summary.json",
            "unexpected_writes": [],
        })
        self.assertEqual([], validator.validate_correction(correction, previous))
        for field in ("pass_id", "head_sha", "artifact"):
            current = json.loads(correction)
            current[field] = json.loads(previous)[field]
            with self.subTest(field=field):
                self.assertTrue(validator.validate_correction(json.dumps(current), previous))


if __name__ == "__main__":
    unittest.main()
