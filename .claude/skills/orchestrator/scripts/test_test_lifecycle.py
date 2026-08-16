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

    def test_substrate_is_confirmed_before_dispatch_and_stated_once(self):
        # A verify lane dispatched at a SHA no environment carries returns
        # BLOCKED with zero information, and costs a second lane to locate the
        # environment (verify_e2_fix -> verify_current_staging_head).
        core = FILES["SKILL.md"]
        self.assertIn("Verify the substrate BEFORE dispatch", core)
        self.assertIn("git branch --contains", core)
        # One canonical statement: merge-and-retire's resume path points at the
        # SKILL.md bullet rather than restating the rule a third time.
        retire = FILES["references/merge-and-retire.md"]
        self.assertIn("Verify the substrate BEFORE dispatch", retire)
        self.assertIn("this line is its resume-path pointer", retire)

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

    def test_completion_mode_finishes_declared_scope_without_more_review(self):
        core = FILES["SKILL.md"]
        for text in (
            "Completion mode override",
            "freeze accepted scope",
            "current declared build task group",
            "UNVERIFIED",
        ):
            self.assertIn(text, core)

    def test_explicit_terminal_stop_ends_all_descendants(self):
        core = FILES["SKILL.md"]
        for text in (
            "Terminal stop override",
            "interrupt every active descendant",
            "zero further tools or waits",
            "return a concise handoff",
        ):
            self.assertIn(text, core)

    def test_active_owned_child_cannot_become_a_user_reactivation_handoff(self):
        core = FILES["SKILL.md"]
        runtime = FILES["references/codex-runtime.md"]
        for text in (
            "internal work, not an external wait",
            "must not emit a final answer",
            "expired explicit child lease",
        ):
            self.assertIn(text, core)
        for text in (
            "A timeout is not completion",
            "latency-sized event wait",
            "interrupt the child",
            "durable handoff",
        ):
            self.assertIn(text, runtime)
        self.assertNotIn("distinct unrelated mailbox update", runtime)

    def test_build_activation_and_status_taxonomy_are_bounded(self):
        lifecycle = FILES["references/lifecycle.md"]
        for text in (
            "exact accepted task group",
            "must not absorb adjacent discovered work",
            "FAIL` means an owned",
            "BLOCKED` means a prerequisite outside",
            "DEFERRED` means incomplete or nonblocking backlog",
        ):
            self.assertIn(text, lifecycle)


if __name__ == "__main__":
    unittest.main()
