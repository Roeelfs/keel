#!/usr/bin/env python3
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SKILL = (SKILL_DIR / "SKILL.md").read_text()
ROUTING = (SKILL_DIR / "prompts" / "model-routing.md").read_text()


class ModelRoutingContractTests(unittest.TestCase):
    def test_long_lived_codex_root_is_terra_medium(self):
        self.assertIn("Long-lived Codex root", SKILL)
        self.assertIn("`gpt-5.6-terra` at Medium", SKILL)
        self.assertIn(
            "| Orchestrator (long-lived Codex root) | n/a | gpt-5.6-terra | Medium |",
            ROUTING,
        )

    def test_sol_is_a_bounded_judgment_escalation(self):
        self.assertIn("Sol escalation", SKILL)
        self.assertIn("fresh, bounded", SKILL)
        self.assertIn("Return the decision artifact to the Terra root", SKILL)

    def test_representative_codex_lane_is_not_sol_high(self):
        self.assertIn("-m gpt-5.6-terra", SKILL)
        self.assertIn("model_reasoning_effort=medium", SKILL)
        self.assertNotIn("| Orchestrator | Opus | gpt-5.6-sol | think / Medium |", ROUTING)

    def test_bounded_children_keep_minimal_history(self):
        self.assertIn('`fork_turns: "none"`', ROUTING)

    def test_procedural_worker_is_terra_low_not_sol(self):
        row = next(
            line for line in ROUTING.splitlines()
            if line.startswith("| Procedural worker: deterministic command pass |")
        )
        self.assertIn("gpt-5.6-terra", row)
        self.assertIn("standard / Low", row)
        self.assertNotIn("gpt-5.6-sol", row)

    def test_native_children_use_supported_terra_low(self):
        for role in ("State miner", "Procedural worker", "Doc writer / file search"):
            row = next(line for line in ROUTING.splitlines() if line.startswith(f"| {role} |"))
            self.assertIn("gpt-5.6-terra (low)", row, role)

    def test_routine_planning_and_refactors_stay_on_terra(self):
        for purpose in (
            "Define: spec + moderate proof ledger",
            "Build: implementation + targeted tests",
            "Verify-release: finite execution",
            "Soak ESCALATE investigation",
            "Refactor (API change)",
            "Migration risk review",
        ):
            row = next(line for line in ROUTING.splitlines() if line.startswith(f"| {purpose} |"))
            self.assertIn("gpt-5.6-terra", row, purpose)

    def test_diagnosis_defaults_to_terra_and_sol_effort_is_explicit(self):
        self.assertIn(
            "| Failure-cluster diagnostician | Sonnet | gpt-5.6-terra (medium) |",
            ROUTING,
        )
        self.assertIn(
            "| Boundary / security / adversarial | Fable 5 + Opus 5 | gpt-5.6-sol (xhigh) |",
            ROUTING,
        )

    def test_review_uses_sol_only_for_named_critical_dispute(self):
        self.assertIn(
            "| Define: one critical coverage review | Sonnet | gpt-5.6-terra | think / Medium |",
            ROUTING,
        )
        self.assertIn(
            "| Define: unresolved security/irreversible dispute | Opus + Codex | gpt-5.6-sol | think harder / Extra high |",
            ROUTING,
        )
        self.assertNotIn("| /spec-test-plan | Opus", ROUTING)


if __name__ == "__main__":
    unittest.main()


class SolJudgmentLaneTests(unittest.TestCase):
    """Sol is bounded by SHAPE, not by frequency — the distinction the burn data forced."""

    def test_sol_lane_contract_exists_and_is_referenced(self):
        skill_dir = Path(__file__).resolve().parents[1]
        lane = (skill_dir / "prompts" / "sol-judgment-lane.md").read_text()
        for text in (
            "One question · fresh context · one document · stop",
            "research-as-retrieval is Terra",
            "codex-headroom.sh --model falsifier",
            "You are a leaf agent",
        ):
            self.assertIn(text, lane)
        routing = (skill_dir / "prompts" / "model-routing.md").read_text()
        self.assertIn("prompts/sol-judgment-lane.md", routing,
                      "rule 10 must point at the mission contract")
        self.assertIn("The bound is the SHAPE, not the frequency", routing)


if __name__ == "__main__":
    unittest.main()
