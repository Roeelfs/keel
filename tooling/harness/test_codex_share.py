#!/usr/bin/env python3
"""codex_share.py over a synthetic ~/.claude in a temp dir: every source, every share."""
import json
import os
import tempfile
import unittest
from pathlib import Path

import codex_share as cs


def tool_use(ts, name, inp):
    return json.dumps({"timestamp": ts, "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]}})


class ShareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        h = Path(self.tmp.name)
        self.home = str(h)
        (h / "analytics").mkdir()
        (h / "analytics/codex-dispatch.jsonl").write_text("\n".join(json.dumps(r) for r in [
            {"ts": "2026-11-10T01:00:00Z", "model": "gpt-6.1-sol", "verdict": "ok"},
            {"ts": "2026-11-10T02:00:00Z", "model": "gpt-6-luna", "verdict": "ok"},
            {"ts": "2026-11-01T02:00:00Z", "model": "gpt-6-luna", "verdict": "ok"},  # outside
        ]) + "\n")
        proj = h / "projects/p1"
        sess = proj / "mgr-1"
        (sess / "subagents").mkdir(parents=True)
        (sess / "custom-title.json").write_text(json.dumps({"customTitle": "[Manager] demo"}))
        for i, model in enumerate(("claude-opus-5-5", "claude-sonnet-5-5")):
            meta = sess / "subagents" / ("a%d.meta.json" % i)
            meta.write_text(json.dumps({"model": model}))
            t = cs.parse_ts("2026-11-10T05:00:00Z").timestamp()
            os.utime(meta, (t, t))
        mission = h / "spec.md"
        mission.write_text("Role: spec\nwrite it")
        lines = [
            tool_use("2026-11-10T03:00:00Z", "Agent", {"prompt": "Role: implementation\nfix", "model": "opus"}),
            tool_use("2026-11-10T03:00:00Z", "Agent", {"prompt": "Role: implementation\nfix", "model": "opus"}),  # dup
            tool_use("2026-11-10T03:01:00Z", "Agent", {"prompt": "Role: implementation\nCodex-no: needs the MCP servers here",
                                                       "model": "opus"}),
            tool_use("2026-11-10T03:02:00Z", "Bash", {"command": "~/.claude/scripts/spawn-lane.sh --mission m.md --cwd w"}),
            tool_use("2026-11-10T03:03:00Z", "Bash", {"command": "spawn-lane.sh --mission m.md --model opus --runtime claude"}),
            tool_use("2026-11-10T03:04:00Z", "Bash", {"command": "spawn-lane.sh --mission %s --model opus" % mission}),
            tool_use("2026-11-10T03:05:00Z", "Bash", {"command": "echo spawn-lane.sh --mission m.md"}),
            tool_use("2026-11-10T03:06:00Z", "Bash", {"command": "~/.claude/scripts/codex-dispatch.sh standard p o"}),
            tool_use("2026-11-10T03:07:00Z", "Workflow", {"scriptPath": "x.js"}),
        ]
        (proj / "mgr-1.jsonl").write_text("\n".join(lines) + "\n")
        t = cs.parse_ts("2026-11-10T05:00:00Z").timestamp()
        os.utime(proj / "mgr-1.jsonl", (t, t))

    def test_measure(self):
        r = cs.measure(self.home, "2026-11-09T00:00:00Z", "2026-11-11T00:00:00Z", "2026-11-06T00:00:00Z")
        self.assertEqual(r["codex_lanes"]["gate_rows"], 2)
        self.assertEqual(r["claude_subagent_lanes"]["total"], 2)
        self.assertEqual(r["top_level_agent_dispatches"]["total"], 2)
        self.assertEqual(r["top_level_agent_dispatches"]["opus_implementation_with_codex_no"], 1)
        self.assertEqual((r["spawn_lane"]["codex"], r["spawn_lane"]["claude"]), (1, 2))
        self.assertEqual(r["codex_dispatch_calls"], 1)
        self.assertEqual(r["workflow_invocations"], 1)
        q = r["qualifying_inputs"]
        # codex: 1 spawn + 1 dispatch; claude unjustified: 1 Agent + 1 spawn (the spec mission is exempt)
        self.assertEqual((q["codex_hand"], q["claude_agent_opus_impl_no_reason"], q["claude_spawn_opus_no_reason"]),
                         (2, 1, 1))
        self.assertEqual(r["shares_pct"]["qualifying"], 50.0)
        self.assertEqual(r["managers"]["manager"]["spawn_codex"], 1)

    def test_runtime_before_the_flip_defaults_to_claude(self):
        r = cs.measure(self.home, "2026-11-09T00:00:00Z", "2026-11-11T00:00:00Z", "2026-11-20T00:00:00Z")
        self.assertEqual((r["spawn_lane"]["codex"], r["spawn_lane"]["claude"]), (0, 3))


if __name__ == "__main__":
    unittest.main()
