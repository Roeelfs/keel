#!/usr/bin/env python3
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SKILL = (SKILL_DIR / "SKILL.md").read_text()
ROUTING = (SKILL_DIR / "prompts" / "model-routing.md").read_text()
SOL_LANE = (SKILL_DIR / "prompts" / "sol-judgment-lane.md").read_text()

# The Codex model + effort ladder is single-sourced in codex-headroom.sh's case statement
# ("THIS CASE STATEMENT IS THE ONE ROUTE TABLE"). These three docs used to restate that
# table's rows; they must now only name the CLASS a reader passes to `--route <class>`.
RESTATED_GEN6_IDS = ("gpt-6-sol", "gpt-6-astra", "gpt-6-luna")


class ModelRoutingContractTests(unittest.TestCase):
    def test_long_lived_codex_root_points_at_the_gate(self):
        self.assertIn("Long-lived Codex root", SKILL)
        self.assertIn("codex-headroom.sh --route standard", SKILL)
        self.assertIn(
            "| Orchestrator (long-lived Codex root) | n/a | n/a | standard |",
            ROUTING,
        )

    def test_sol_is_a_bounded_judgment_escalation(self):
        self.assertIn("Sol-high escalation", SKILL)
        self.assertIn("fresh, bounded", SKILL)
        self.assertIn("Return the decision artifact to the Sol-medium root", SKILL)

    def test_representative_codex_lane_asks_the_gate_not_a_hardcoded_tier(self):
        self.assertIn(
            "read -r MODEL EFFORT < <(~/.claude/scripts/codex-headroom.sh --route standard)",
            SKILL,
        )
        self.assertNotIn("-m gpt-6-sol", SKILL)
        self.assertNotIn("model_reasoning_effort=medium", SKILL)
        self.assertNotIn("| Orchestrator | Opus | standard |", ROUTING)

    def test_bounded_children_keep_minimal_history(self):
        self.assertIn('`fork_turns: "none"`', ROUTING)

    def test_procedural_worker_is_mining_class_not_standard(self):
        row = next(
            line for line in ROUTING.splitlines()
            if line.startswith("| Procedural worker: deterministic command pass |")
        )
        self.assertIn("mining", row)
        self.assertNotIn("standard", row)

    def test_native_children_use_the_mining_class(self):
        for role in ("State miner", "Procedural worker", "Doc writer / file search"):
            row = next(line for line in ROUTING.splitlines() if line.startswith(f"| {role} |"))
            self.assertIn("mining", row, role)

    def test_routine_planning_and_refactors_stay_on_standard(self):
        for purpose in (
            "Define: spec + moderate proof ledger",
            "Build: implementation + targeted tests",
            "Verify-release: finite execution",
            "Soak ESCALATE investigation",
            "Refactor (API change)",
            "Migration risk review",
        ):
            row = next(line for line in ROUTING.splitlines() if line.startswith(f"| {purpose} |"))
            self.assertIn("standard", row, purpose)

    def test_diagnosis_defaults_to_standard_and_security_class_is_explicit(self):
        self.assertIn(
            "| Failure-cluster diagnostician | Sonnet | standard |",
            ROUTING,
        )
        self.assertIn(
            "| Boundary / security / adversarial | Fable 5.1 + Opus 5.5 | security |",
            ROUTING,
        )

    def test_review_uses_the_security_class_only_for_named_critical_dispute(self):
        self.assertIn(
            "| Define: one critical coverage review | Sonnet | think | standard |",
            ROUTING,
        )
        self.assertIn(
            "| Define: unresolved security/irreversible dispute | Opus + Codex | think harder | security |",
            ROUTING,
        )
        self.assertNotIn("| /spec-test-plan | Opus", ROUTING)

    def test_docs_point_at_the_gate_as_the_route_table_owner(self):
        for doc, name in ((SKILL, "SKILL.md"), (ROUTING, "model-routing.md"), (SOL_LANE, "sol-judgment-lane.md")):
            self.assertIn("codex-headroom.sh", doc, name)
        self.assertIn("--route", SKILL)
        self.assertIn("--route <class>", ROUTING)
        self.assertIn("--route falsifier", SOL_LANE)
        self.assertIn("the one route table", ROUTING)

    def test_no_restated_gen6_model_id_remains_outside_the_owner(self):
        # codex-runtime.md's fixed procedural-worker `model: "gpt-6-luna"` call is a single
        # concrete spawn_agent parameter, not a restated purpose->model/effort TABLE, and is
        # intentionally out of this lane's scope — these three docs held the actual tables.
        for doc, name in ((SKILL, "SKILL.md"), (ROUTING, "model-routing.md"), (SOL_LANE, "sol-judgment-lane.md")):
            for bad_id in RESTATED_GEN6_IDS:
                self.assertNotIn(bad_id, doc, f"{name} must not restate {bad_id} — ask the gate by class")

    def test_negative_control_the_restated_id_check_actually_fires(self):
        """Sanity-control: prove assertNotIn above is not vacuously true on this corpus."""
        poisoned = ROUTING + "\n| Regression check | Sonnet | gpt-6-sol |\n"
        with self.assertRaises(AssertionError):
            self.assertNotIn("gpt-6-sol", poisoned)


if __name__ == "__main__":
    unittest.main()


class SolJudgmentLaneTests(unittest.TestCase):
    """Sol is bounded by SHAPE, not by frequency — the distinction the burn data forced."""

    def test_sol_lane_contract_exists_and_is_referenced(self):
        skill_dir = Path(__file__).resolve().parents[1]
        lane = (skill_dir / "prompts" / "sol-judgment-lane.md").read_text()
        for text in (
            "One question · fresh context · one document · stop",
            "research-as-retrieval is Sol-medium",
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
