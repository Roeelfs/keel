#!/usr/bin/env python3
"""Behavioral tests for codex-first-gate: run the real shim with a temp HOME and read its stdout."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHIM = HERE / "codex-first-gate.sh"


class GateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        agents = self.home / ".claude/agents"
        agents.mkdir(parents=True)
        (agents / "executor.md").write_text("---\nname: executor\nmodel: sonnet\n---\n")
        (agents / "architect.md").write_text("---\nname: architect\nmodel: opus\n---\n")

    def run_hook(self, tool, ti, transcript=True):
        payload = {"tool_name": tool, "tool_input": ti, "session_id": "s1"}
        if transcript:
            payload["transcript_path"] = "/x.jsonl"
        r = subprocess.run(["bash", str(SHIM)], input=json.dumps(payload), capture_output=True,
                           text=True, env=dict(os.environ, HOME=str(self.home)))
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None

    def log_rows(self):
        p = self.home / ".claude/analytics/codex-first-gate.jsonl"
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    def assertDenied(self, out):
        self.assertIsNotNone(out)
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("codex-dispatch.sh standard <promptfile> <outfile> [workdir]",
                      out["permissionDecisionReason"])
        self.assertIn("Codex-no:", out["permissionDecisionReason"])

    def test_opus_implementation_without_reason_is_denied(self):
        self.assertDenied(self.run_hook("Agent", {"prompt": "Role: implementation\nFix it.", "model": "opus"}))
        self.assertEqual(self.log_rows()[0]["verdict"], "deny")

    def test_unset_model_inherits_opus_and_is_gated(self):
        self.assertDenied(self.run_hook("Agent", {"prompt": "Role: implementation. Fix it."}))

    def test_named_agent_pinned_opus_is_gated(self):
        self.assertDenied(self.run_hook("Agent", {"prompt": "Role: implementation", "subagent_type": "architect"}))

    def test_reason_line_allows_and_is_logged(self):
        out = self.run_hook("Agent", {"prompt": "Role: implementation\nCodex-no: edits harness hooks under the home dir",
                                      "model": "opus"})
        self.assertIsNone(out)
        row = self.log_rows()[0]
        self.assertEqual(row["verdict"], "allow")
        self.assertIn("harness hooks", row["reason"])

    def test_short_reason_does_not_count(self):
        self.assertDenied(self.run_hook("Agent", {"prompt": "Role: implementation\nCodex-no: no", "model": "opus"}))

    def test_mechanical_and_spec_lanes_pass_silently(self):
        cases = [
            {"prompt": "Role: implementation", "model": "sonnet"},
            {"prompt": "Role: implementation", "model": "haiku"},
            {"prompt": "Role: implementation", "subagent_type": "executor"},
            {"prompt": "Role: spec\nWrite the spec.", "model": "opus"},
            {"prompt": "Model-why: deep architecture judgment needed", "model": "opus"},
            {"prompt": "Count the files."},
        ]
        for ti in cases:
            with self.subTest(ti=ti):
                self.assertIsNone(self.run_hook("Agent", ti))
        self.assertEqual(self.log_rows(), [])

    def test_other_tools_pass(self):
        self.assertIsNone(self.run_hook("Bash", {"command": "echo Role: implementation"}))

    def test_workflow_inline_and_scriptpath(self):
        deep = "await agent('Role: implementation\\nbuild it', {model: 'opus'})"
        self.assertDenied(self.run_hook("Workflow", {"script": deep}))
        unset = "await agent('Role: implementation\\nbuild it')"
        self.assertDenied(self.run_hook("Workflow", {"script": unset}))
        f = self.home / "wf.js"
        f.write_text(deep)
        self.assertDenied(self.run_hook("Workflow", {"scriptPath": str(f), "args": {}}))
        mech = "await agent('Role: implementation\\nbuild it', {model: 'sonnet'})"
        self.assertIsNone(self.run_hook("Workflow", {"script": mech}))
        review = "await agent('review the spec', {model: 'opus'})"
        self.assertIsNone(self.run_hook("Workflow", {"script": review}))
        reasoned = deep + "\n// Codex-no: needs this conversation's accumulated context"
        self.assertIsNone(self.run_hook("Workflow", {"script": reasoned}))

    def test_kill_switch_allows_everything(self):
        (self.home / ".claude/run").mkdir(parents=True)
        (self.home / ".claude/run/codex-first-gate.off").write_text("")
        self.assertIsNone(self.run_hook("Agent", {"prompt": "Role: implementation", "model": "opus"}))

    def test_garbage_input_fails_open(self):
        r = subprocess.run(["bash", str(SHIM)], input="not json", capture_output=True, text=True,
                           env=dict(os.environ, HOME=str(self.home)))
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_synthetic_flag_without_transcript(self):
        self.run_hook("Agent", {"prompt": "Role: implementation", "model": "opus"}, transcript=False)
        self.assertTrue(self.log_rows()[0]["synthetic"])


if __name__ == "__main__":
    unittest.main()
