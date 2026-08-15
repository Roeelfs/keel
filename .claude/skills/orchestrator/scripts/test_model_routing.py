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

    def test_routine_planning_and_refactors_stay_on_terra(self):
        for purpose in (
            "Spec authoring (step 2)",
            "Implementation plan (step 5)",
            "Soak ESCALATE investigation",
            "Refactor (API change)",
            "Migration risk review",
        ):
            row = next(line for line in ROUTING.splitlines() if line.startswith(f"| {purpose} |"))
            self.assertIn("gpt-5.6-terra", row, purpose)

    def test_rescue_defaults_to_terra_and_sol_effort_is_explicit(self):
        self.assertIn("| Codex rescue | n/a | gpt-5.6-terra (medium) |", ROUTING)
        self.assertIn(
            "| Boundary / security / adversarial | Fable 5 + Opus 5 | gpt-5.6-sol (xhigh) |",
            ROUTING,
        )

    def test_review_uses_sol_only_for_named_final_adversarial_gates(self):
        self.assertIn(
            "| /spec-review coverage review (step 3) | Sonnet + Codex | gpt-5.6-terra | think / Medium |",
            ROUTING,
        )
        self.assertIn(
            "| /spec-review final adversarial gate (step 6) | Opus + Codex | gpt-5.6-sol | think harder / Extra high |",
            ROUTING,
        )
        self.assertIn(
            "| Plan review final adversarial gate (step 6) | Opus + Codex | gpt-5.6-sol | think harder / Extra high |",
            ROUTING,
        )
        self.assertNotIn("| /spec-review (steps 3, 6) |", ROUTING)
        self.assertNotIn("| Plan review (step 6) |", ROUTING)


if __name__ == "__main__":
    unittest.main()
