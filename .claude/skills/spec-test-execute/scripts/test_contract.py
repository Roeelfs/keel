#!/usr/bin/env python3
import re
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SKILL = (SKILL_DIR / "SKILL.md").read_text()


def executable_blocks(text):
    return "\n".join(re.findall(r"```(?:bash|sh)\n(.*?)```", text, re.S))


class ExecutorContractTests(unittest.TestCase):
    def test_finite_two_pass_cluster_contract(self):
        for text in (
            "one targeted pass",
            "one changed-seam correction pass",
            "failure signature",
            "Terra-medium",
            "readiness",
            "blocker artifact",
        ):
            self.assertIn(text, SKILL)

    def test_load_bearing_evidence_rules_survive(self):
        for text in (
            "Evidence before PASS",
            "strong assertion",
            "SKIP",
            "BLOCKED",
            "existing tests",
            "project test contract",
            "real-boundary",
        ):
            self.assertIn(text, SKILL)
        self.assertIn("git worktree list --porcelain", SKILL)
        self.assertIn("Relevant in-flight work", SKILL)

    def test_legacy_maximal_actions_are_gone(self):
        for legacy in (
            "Max 5 cycles",
            "one per failing test",
            "Staging Auto-Deploy Protocol",
            "full tier suite",
            "Step 5.5: Knowledge Sync",
        ):
            self.assertNotIn(legacy, SKILL)

        blocks = executable_blocks(SKILL)
        self.assertNotRegex(blocks, r"(?m)^\s*sleep\s+\d+")
        self.assertNotIn("git push origin HEAD:staging", blocks)
        self.assertNotIn("gpt-5.6-sol", blocks)

    def test_cluster_prompt_is_read_only_and_write_rescue_is_absent(self):
        prompt = (SKILL_DIR / "prompts" / "failure-cluster-diagnostician.md").read_text()
        self.assertIn("read-only", prompt.lower())
        self.assertIn("normalized failure signature", prompt.lower())
        self.assertFalse((SKILL_DIR / "prompts" / "codex-rescue-stuck.md").exists())

    def test_native_codex_groups_procedural_work_off_root(self):
        for text in (
            "one procedural worker per pass",
            "history-free",
            "Terra-low",
            "one realistic wait",
            "Do not spawn one worker per command",
            "promotes decisive evidence into the durable ledger",
            "final group in the targeted-pass worker",
            "one fresh procedural worker",
        ):
            self.assertIn(text, SKILL)


if __name__ == "__main__":
    unittest.main()
