#!/usr/bin/env python3
"""Behavioral tests for the native-dispatch gate (codex-first-gate.sh): run the real shim with a temp HOME and read its stdout."""
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
        reason = out["permissionDecisionReason"]
        self.assertIn("spawn-lane.sh --runtime claude --model opus", reason)
        self.assertIn("Native-why:", reason)
        # Codex is the exception, mentioned after the headless Claude command, never pushed.
        self.assertLess(reason.index("--runtime claude"), reason.index("--runtime codex"))
        self.assertNotIn("codex-dispatch.sh", reason)
        self.assertNotIn("Codex-no", reason)

    def test_opus_implementation_without_reason_is_denied(self):
        self.assertDenied(self.run_hook("Agent", {"prompt": "Role: implementation\nFix it.", "model": "opus"}))
        self.assertEqual(self.log_rows()[0]["verdict"], "deny")
        self.assertIn("--cwd <worktree> --class implementation",
                      self.run_hook("Agent", {"prompt": "Build it."})["permissionDecisionReason"])
        self.assertEqual(self.log_rows()[0]["eligibility"], "headless")

    def test_unset_model_inherits_opus_and_is_gated(self):
        self.assertDenied(self.run_hook("Agent", {"prompt": "Role: implementation. Fix it."}))

    def test_named_agent_pinned_opus_is_gated(self):
        self.assertDenied(self.run_hook("Agent", {"prompt": "Role: implementation", "subagent_type": "architect"}))

    def test_reason_line_allows_and_is_logged(self):
        out = self.run_hook("Agent", {"prompt": "Role: implementation\nNative-why: edits harness hooks under the home dir",
                                      "model": "opus"})
        self.assertIsNone(out)
        row = self.log_rows()[0]
        self.assertEqual(row["verdict"], "allow")
        self.assertIn("harness hooks", row["native_why"])

    def test_short_reason_does_not_count(self):
        self.assertDenied(self.run_hook("Agent", {"prompt": "Role: implementation\nNative-why: no", "model": "opus"}))

    def test_mechanical_and_spec_lanes_pass_and_are_logged(self):
        cases = [
            {"prompt": "Role: implementation", "model": "sonnet"},
            {"prompt": "Role: implementation", "model": "haiku"},
            {"prompt": "Role: implementation", "subagent_type": "executor"},
            {"prompt": "Role: spec\nWrite the spec.", "model": "opus"},
        ]
        for ti in cases:
            with self.subTest(ti=ti):
                self.assertIsNone(self.run_hook("Agent", ti))
        self.assertTrue(all(r["dispatch_runtime"] == "native" for r in self.log_rows()))

    def test_plain_native_lanes_require_a_reason(self):
        for tool in ("Agent", "Task"):
            with self.subTest(tool=tool):
                self.assertDenied(self.run_hook(tool, {"prompt": "Review the repository and return findings."}))
        self.assertEqual(self.log_rows()[0]["dispatch_runtime"], "native")

    def test_large_document_pass_overrides_cheap_and_spec_exemptions(self):
        for prompt in ("Role: spec\nResearch the entire repository and write a report.",
                       "Read-only review of all modules; return findings.md.",
                       "Research the architecture and produce a report."):
            for model in ("sonnet", "haiku", "opus"):
                with self.subTest(prompt=prompt, model=model):
                    self.assertDenied(self.run_hook("Agent", {"prompt": prompt, "model": model}))

    def test_reason_is_one_line_and_counts_trimmed_characters(self):
        for reason in ("Native-why:          x", "Native-why: short\nmore text here",
                       "Codex-no: needs harness state to finish", "Mention Native-why: needs harness state"):
            with self.subTest(reason=reason):
                self.assertDenied(self.run_hook("Agent", {"prompt": "Review everything.\n" + reason}))
        for name in ("critic", "verifier", "security-reviewer"):
            (self.home / ".claude/agents" / (name + ".md")).write_text("---\nmodel: sonnet\n---\n")
            self.assertDenied(self.run_hook("Agent", {"subagent_type": name, "prompt": "Review everything."}))
            self.assertIsNone(self.run_hook("Agent", {"subagent_type": name,
                "prompt": "Review everything.\nNative-why: needs MCP servers from this harness"}))
        self.assertIn("MCP servers", self.log_rows()[-1]["native_why"])

    def test_workflow_without_agents_is_not_gated(self):
        self.assertIsNone(self.run_hook("Workflow", {"script": "return 'Role: implementation'"}))
        self.assertEqual(self.log_rows(), [])

    def test_workflow_document_pass_and_mixed_models(self):
        self.assertDenied(self.run_hook("Workflow", {"script":
            "await agent('Research all modules and write a report', {model: 'sonnet'})"}))
        self.assertDenied(self.run_hook("Workflow", {"script":
            "await agent('Count files', {model: 'sonnet'}); await agent('Review everything')"}))
        self.assertIsNone(self.run_hook("Workflow", {"script":
            "await agent('Review everything\\nNative-why: needs MCP servers in this harness')"}))
        self.assertIsNone(self.run_hook("Workflow", {"script": "await agent(args.prompt)",
            "args": {"prompt": "Review everything.\nNative-why: needs MCP servers in this harness"}}))

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
        self.assertDenied(self.run_hook("Workflow", {"script": review}))
        reasoned = deep + "\n// Native-why: needs this conversation's accumulated context"
        self.assertIsNone(self.run_hook("Workflow", {"script": reasoned}))

    def test_kill_switch_allows_everything(self):
        (self.home / ".claude/run").mkdir(parents=True)
        (self.home / ".claude/run/codex-first-gate.off").write_text("")
        self.assertIsNone(self.run_hook("Agent", {"prompt": "Role: implementation", "model": "opus"}))

    def test_garbage_input_fails_open(self):
        r = subprocess.run(["bash", str(SHIM)], input="not json", capture_output=True, text=True,
                           env=dict(os.environ, HOME=str(self.home)))
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_logging_failure_does_not_fail_open_the_decision(self):
        (self.home / ".claude/analytics").write_text("not a directory")
        self.assertDenied(self.run_hook("Agent", {"prompt": "Review everything."}))

    def test_unexpected_payload_fails_open(self):
        r = subprocess.run(["bash", str(SHIM)], input="[]", capture_output=True, text=True,
                           env=dict(os.environ, HOME=str(self.home)))
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_synthetic_flag_without_transcript(self):
        self.run_hook("Agent", {"prompt": "Role: implementation", "model": "opus"}, transcript=False)
        self.assertTrue(self.log_rows()[0]["synthetic"])


if __name__ == "__main__":
    unittest.main()
