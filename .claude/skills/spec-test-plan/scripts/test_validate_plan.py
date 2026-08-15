#!/usr/bin/env python3
import importlib.util
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = Path(__file__).with_name("validate_plan.py")
SKILL = (SKILL_DIR / "SKILL.md").read_text()


def load_validator():
    if not VALIDATOR_PATH.exists():
        raise AssertionError("validate_plan.py is missing")
    spec = importlib.util.spec_from_file_location("validate_plan", VALIDATOR_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def plan(mode="moderate", obligations=(), reason=""):
    obligations = list(obligations)
    if mode in {"moderate", "critical"} and not any(
        item["kind"] == "project-gate" for item in obligations
    ):
        obligations.append(obligation(99, kind="project-gate", source="project-test-contract"))
    rows = "\n".join(
        f"| {item['id']} | {item['kind']} | {item['source']} | {item['proof']} | PENDING | |"
        for item in obligations
    )
    return f"""---
mode: {mode}
budget_override_reason: {reason}
---
# Test Plan

| ID | Kind | Source | Proof | Status | Evidence / deferred owner |
|---|---|---|---|---|---|
{rows}
"""


def obligation(number, kind="targeted", source=None, proof=None):
    return {
        "id": f"PO-{number:02d}",
        "kind": kind,
        "source": source if source is not None else f"AC-{number:02d}",
        "proof": proof if proof is not None else f"proof-{number}",
    }


class PlannerContractTests(unittest.TestCase):
    def test_skill_declares_moderate_modes_and_index_then_select(self):
        for text in ("checklist", "moderate", "critical", "budget_override_reason"):
            self.assertIn(text, SKILL)
        self.assertIn("index, then select", SKILL.lower())
        self.assertNotIn("Dispatch **one** agent", SKILL)

    def test_valid_moderate_plan_passes(self):
        validator = load_validator()
        errors = validator.validate_text(plan(obligations=[obligation(i) for i in range(1, 12)]))
        self.assertEqual([], errors)

    def test_missing_source_duplicate_key_and_duplicate_proof_fail(self):
        validator = load_validator()
        cases = {
            "missing source": [obligation(1, source="")],
            "duplicate key": [obligation(1), obligation(2) | {"id": "PO-01"}],
            "duplicate proof": [obligation(1), obligation(2, source="AC-01", proof="proof-1")],
        }
        for name, obligations in cases.items():
            with self.subTest(name=name):
                self.assertTrue(validator.validate_text(plan(obligations=obligations)))

    def test_budget_overflow_requires_reason_naming_overflow_source(self):
        validator = load_validator()
        obligations = [obligation(i) for i in range(1, 13)]
        self.assertTrue(validator.validate_text(plan(mode="critical", obligations=obligations)))
        self.assertEqual(
            [],
            validator.validate_text(
                plan(
                    mode="critical",
                    obligations=obligations,
                    reason="RISK-12 is represented by AC-12 and needs deployed proof",
                )
            ),
        )

    def test_more_than_two_journeys_requires_named_reason(self):
        validator = load_validator()
        obligations = [obligation(i, kind="journey") for i in range(1, 4)]
        self.assertTrue(validator.validate_text(plan(obligations=obligations)))
        self.assertEqual(
            [],
            validator.validate_text(
                plan(obligations=obligations, reason="AC-03 needs a distinct customer journey")
            ),
        )

    def test_only_one_project_gate(self):
        validator = load_validator()
        obligations = [obligation(1, kind="project-gate"), obligation(2, kind="project-gate")]
        self.assertTrue(validator.validate_text(plan(obligations=obligations)))

    def test_moderate_requires_project_gate_and_escaped_pipe_is_parsed(self):
        validator = load_validator()
        missing_gate = plan(mode="checklist", obligations=[obligation(1)]).replace(
            "mode: checklist", "mode: moderate"
        )
        self.assertTrue(validator.validate_text(missing_gate))
        escaped = plan(obligations=[obligation(1, proof=r"command \| tee output")])
        self.assertEqual([], validator.validate_text(escaped))
        malformed = escaped.replace(r"command \| tee", "command | tee")
        self.assertTrue(validator.validate_text(malformed))
        custom_id_bypass = malformed.replace("PO-01", "custom")
        self.assertTrue(validator.validate_text(custom_id_bypass))

    def test_deferred_status_requires_owner(self):
        validator = load_validator()
        text = plan(obligations=[obligation(1)]).replace("| PENDING | |", "| DEFERRED | |")
        self.assertTrue(validator.validate_text(text))
        self.assertEqual([], validator.validate_text(text.replace("| DEFERRED | |", "| DEFERRED | owner: CYN-1 |")))


if __name__ == "__main__":
    unittest.main()
