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

    def test_native_worker_is_fresh_low_effort_and_owns_process(self):
        for text in ('fork_turns: "none"', 'reasoning_effort: "low"', "Luna-low"):
            self.assertIn(text, RUNTIME + PROMPT + ROUTING)
        self.assertIn("root never calls `write_stdin`", RUNTIME)
        self.assertIn("Start with one realistically sized `wait_agent`", RUNTIME)
        self.assertIn("distinct unrelated mailbox update", RUNTIME)

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
