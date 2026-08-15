#!/usr/bin/env python3
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
FILES = {
    relative: (SKILL_DIR / relative).read_text()
    for relative in (
        "SKILL.md",
        "references/lifecycle.md",
        "references/merge-and-retire.md",
        "references/codex-runtime.md",
        "prompts/codex-lane-template.md",
        "prompts/loop-directive.md",
        "prompts/session-template.md",
        "prompts/state-miner.md",
        "prompts/model-routing.md",
    )
}
ALL = "\n".join(FILES.values())


class TestLifecycleContractTests(unittest.TestCase):
    def test_three_fresh_bounded_phases_are_canonical(self):
        lifecycle = FILES["references/lifecycle.md"]
        for text in ("define", "build", "verify-release", "fresh bounded"):
            self.assertIn(text, lifecycle)
        for path in (
            "SKILL.md",
            "prompts/codex-lane-template.md",
            "prompts/loop-directive.md",
            "prompts/session-template.md",
        ):
            self.assertIn("define → build → verify-release", FILES[path], path)

    def test_shared_modes_and_obligation_ledger_reach_consumers(self):
        for path in (
            "references/lifecycle.md",
            "prompts/codex-lane-template.md",
            "prompts/loop-directive.md",
            "prompts/state-miner.md",
        ):
            for text in ("checklist", "moderate", "critical", "proof-obligation ledger"):
                self.assertIn(text, FILES[path], f"{path}: {text}")

    def test_empty_4b_and_legacy_tiers_are_removed(self):
        for text in ("no spec patches required", "[ADV]", "[EC-MISSING]", "Tier 3a"):
            self.assertNotIn(text, ALL)

    def test_postmerge_proof_is_keyed_and_changed_seam_only(self):
        retire = FILES["references/merge-and-retire.md"]
        for text in ("obligation", "deploy SHA", "environment", "command/journey", "changed runtime seam"):
            self.assertIn(text, retire)
        self.assertIn("never rerun local suites", retire)

    def test_project_gate_once_and_terminal_or_owned_deferred(self):
        lifecycle = FILES["references/lifecycle.md"]
        self.assertIn("project gate exactly once", lifecycle)
        self.assertIn("deferred owner", lifecycle)

    def test_review_wait_and_headless_contracts_are_bounded(self):
        core = FILES["SKILL.md"]
        for text in (
            "moderate` permits at most **two total activations**",
            "critical` permits at most **five total activations**",
            "External waits end the bounded task",
            "Only the `verify-release` phase runs the project gate, exactly once",
        ):
            self.assertIn(text, core)
        self.assertNotIn("Monitor` with an until-loop", core)
        self.assertNotIn("Lanes never run the machine's full verify gate", core)

    def test_existing_implementation_resumes_without_lifecycle_replay(self):
        lifecycle = FILES["references/lifecycle.md"]
        for text in (
            "Existing implementation fast path",
            "same SHA",
            "one changed-seam review",
            "one grouped verification pass",
            "never replay define or build",
        ):
            self.assertIn(text.lower(), lifecycle.lower())

    def test_user_stop_is_terminal_for_review_and_testing(self):
        core = FILES["SKILL.md"]
        for text in (
            "Terminal stop override",
            "interrupt active review/test lanes",
            "zero further verification",
            "return a concise handoff",
        ):
            self.assertIn(text, core)


if __name__ == "__main__":
    unittest.main()
