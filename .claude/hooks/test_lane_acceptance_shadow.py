#!/usr/bin/env python3
"""Shadow acceptance, actual git evidence, and disabled-rule mutation controls."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

HOOK = Path(__file__).with_name("lane-acceptance-shadow.py")
spec = importlib.util.spec_from_file_location("acceptance", HOOK)
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.repo = self.base / "repo"
        self.git("init", "-q", str(self.repo), cwd=self.base)
        self.git("config", "user.name", "Mock")
        self.git("config", "user.email", "mock@example.invalid")
        self.commit()
        self.before = acceptance.snapshot(self.repo)
        self.event = {"session_id": "test-parent", "agent_id": "test-agent", "cwd": str(self.repo),
                      "agent_type": "general-purpose", "hook_event_name": "SubagentStop"}
        self.records = [{"type": "user", "message": {"content": "Role: implementation. Commit."}}]

    def git(self, *args, cwd=None):
        return subprocess.run(["git", "-c", "core.hooksPath=/dev/null", *args], cwd=cwd or self.repo,
                              capture_output=True, text=True, check=True).stdout.strip()

    def commit(self, cwd=None):
        self.git("commit", "-qm", "artifact", "--allow-empty", cwd=cwd)

    def evaluate(self, records=None, before=None, module=acceptance):
        return module.evaluate(self.event, before or self.before, records or self.records)

    def test_implementation_without_commit_would_block(self):
        self.assertEqual(self.evaluate()["would_block"], ["zero_commit"])

    def test_implementation_with_commit_passes(self):
        self.commit()
        self.assertEqual(self.evaluate()["would_block"], [])

    def test_research_without_commit_passes(self):
        records = [{"type": "user", "message": {"content": "Role: research. Report."}}]
        self.assertEqual(self.evaluate(records)["would_block"], [])

    def test_final_error_would_block(self):
        self.commit()
        result = self.evaluate(self.records + [{"type": "result", "is_error": True}])
        self.assertEqual(result["would_block"], ["is_error"])

    def test_own_worktree_commit_passes(self):
        own = self.base / "own"
        self.git("worktree", "add", "-qb", "own", str(own))
        self.commit(own)
        self.assertEqual(self.evaluate()["would_block"], [])

    def test_existing_worktree_identified_by_transcript(self):
        own = self.base / "existing"
        self.git("worktree", "add", "-qb", "existing", str(own))
        before = acceptance.snapshot(self.repo)
        self.commit(own)
        result = self.evaluate(self.records + [{"type": "assistant", "cwd": str(own)}], before)
        self.assertEqual(result["would_block"], [])
        self.assertEqual(self.evaluate(before=before)["would_block"], ["zero_commit"],
                         "a sibling commit cannot count without attribution")

    def test_new_worktree_on_different_base_is_not_a_commit(self):
        old = self.git("rev-parse", "HEAD")
        self.commit()
        before = acceptance.snapshot(self.repo)
        self.git("worktree", "add", "-qb", "older", str(self.base / "older"), old)
        self.assertEqual(self.evaluate(before=before)["would_block"], ["zero_commit"])

    def test_missing_start_is_unproven(self):
        result = acceptance.evaluate(self.event, None, self.records)
        self.assertEqual(result["unproven"], "missing_start")

    def invoke(self, event):
        result = subprocess.run(["python3", str(HOOK)], input=json.dumps(event), capture_output=True,
                                text=True, env={**os.environ, "LANE_ACCEPTANCE_HOME": str(self.base)}, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "", "shadow must never emit a blocking decision")

    def test_registered_start_stop_lifecycle_logs_would_block_but_never_blocks(self):
        # Registration is the machine's settings, not this repo's: checked when that file exists.
        path = Path(os.environ.get("LANE_ACCEPTANCE_SETTINGS", Path.home() / ".claude" / "settings.json"))
        if path.is_file():
            settings = json.loads(path.read_text())
            for event in ("SubagentStart", "SubagentStop"):
                self.assertIn("lane-acceptance-shadow.py", str(settings["hooks"][event]))
        self.invoke({**self.event, "hook_event_name": "SubagentStart"})
        transcript = self.base / "agent.jsonl"
        transcript.write_text("\n".join(json.dumps(r) for r in self.records))
        self.invoke({**self.event, "agent_transcript_path": str(transcript)})
        row = json.loads((self.base / "analytics/lane-acceptance.jsonl").read_text())
        self.assertEqual(row["mode"], "shadow")
        self.assertEqual(row["would_block"], ["zero_commit"])
        self.assertFalse(list((self.base / "state/lane-acceptance").glob("*.json")))

    def mutant(self, old, new):
        import types
        source = HOOK.read_text()
        self.assertIn(old, source)
        module = types.ModuleType("mutant")
        module.__file__ = str(HOOK)
        exec(compile(source.replace(old, new), str(HOOK), "exec"), module.__dict__)
        return module

    def test_mutation_control_disabled_zero_commit_rule(self):
        mutant = self.mutant('if not result["committed"]:', 'if False:')
        self.assertEqual(self.evaluate(module=mutant)["would_block"], [])

    def test_mutation_control_disabled_error_rule(self):
        mutant = self.mutant('final.get("is_error") is True', 'False')
        self.commit()
        self.assertEqual(self.evaluate(self.records + [{"type": "result", "is_error": True}],
                                       module=mutant)["would_block"], [])


if __name__ == "__main__":
    unittest.main()
