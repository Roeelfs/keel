#!/usr/bin/env python3
"""Tests for SR2 plan_falsifier_batches.py."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from plan_falsifier_batches import (  # noqa: E402
    assert_seam_cohesion,
    build_plan,
    parse_findings,
    plan_batches,
)

CONSENSUS_SAMPLE = """
### Consensus Issues (2+ reviewers)
1. [F-1] [CRITICAL] Missing tenant check — flagged by: completeness, codebase
   Codex confidence: 0.9 | File: apps/backend/src/foo.ts:42
   Recommendation: add org_id predicate

2. [F-2] [MAJOR] Race on dedup key — flagged by: architecture
   Codex confidence: 0.7 | File: apps/backend/src/foo.ts:88
   Recommendation: CAS the write

3. [F-3] [MINOR] Naming nit — flagged by: codebase
   Codex confidence: 0.5 | File: apps/backend/src/bar.ts:5
   Recommendation: rename variable

### Codex-Only Findings (investigate — possible Claude blind spot)
Category: Risk (from adversarial)
1. [F-4] [CRITICAL] Unbounded fan-out
   Body: no cap on concurrent sub-lanes
   File: apps/backend/src/baz.ts:120-140 | Confidence: 0.8
   Recommendation: cap concurrency

2. [F-5] [MAJOR] No File field on this one
   Body: a finding whose reviewer forgot to cite a location
   Recommendation: cite file:line next time
"""


class ParseFindingsTests(unittest.TestCase):
    def test_parses_id_severity_and_seam(self):
        findings = parse_findings(CONSENSUS_SAMPLE)
        by_id = {f["id"]: f for f in findings}
        self.assertEqual(by_id["F-1"]["severity"], "CRITICAL")
        self.assertEqual(by_id["F-1"]["seam"], "apps/backend/src/foo.ts")
        self.assertEqual(by_id["F-2"]["seam"], "apps/backend/src/foo.ts")
        self.assertEqual(by_id["F-3"]["severity"], "MINOR")

    def test_strips_line_range_suffix_from_seam(self):
        findings = parse_findings(CONSENSUS_SAMPLE)
        by_id = {f["id"]: f for f in findings}
        # "File: apps/backend/src/baz.ts:120-140" -> seam has no line info.
        self.assertEqual(by_id["F-4"]["seam"], "apps/backend/src/baz.ts")

    def test_finding_without_file_field_has_no_seam(self):
        findings = parse_findings(CONSENSUS_SAMPLE)
        by_id = {f["id"]: f for f in findings}
        self.assertIsNone(by_id["F-5"]["seam"])

    def test_parses_all_five_findings_in_order(self):
        findings = parse_findings(CONSENSUS_SAMPLE)
        self.assertEqual([f["id"] for f in findings], ["F-1", "F-2", "F-3", "F-4", "F-5"])


class PlanBatchesTests(unittest.TestCase):
    def test_filters_to_critical_major_only(self):
        plan = build_plan(CONSENSUS_SAMPLE, "fake.review.md", max_batches=4)
        # F-3 is MINOR and must not appear anywhere in the plan.
        self.assertEqual(plan["critical_major_count"], 4)
        all_ids = [fid for b in plan["batches"] for fid in b["finding_ids"]]
        self.assertNotIn("F-3", all_ids)
        self.assertEqual(sorted(all_ids), ["F-1", "F-2", "F-4", "F-5"])

    def test_missing_seam_finding_is_reported_and_still_batched(self):
        plan = build_plan(CONSENSUS_SAMPLE, "fake.review.md", max_batches=4)
        self.assertIn("F-5", plan["findings_missing_seam"])
        all_ids = [fid for b in plan["batches"] for fid in b["finding_ids"]]
        self.assertIn("F-5", all_ids)  # missing-seam findings are never dropped

    def test_same_seam_findings_land_in_one_batch(self):
        plan = build_plan(CONSENSUS_SAMPLE, "fake.review.md", max_batches=4)
        f1_batch = next(b["batch_id"] for b in plan["batches"] if "F-1" in b["finding_ids"])
        f2_batch = next(b["batch_id"] for b in plan["batches"] if "F-2" in b["finding_ids"])
        # F-1 and F-2 share the seam apps/backend/src/foo.ts.
        self.assertEqual(f1_batch, f2_batch)

    def test_batch_count_never_exceeds_max_batches(self):
        # 6 distinct seams, cap of 4 -> at most 4 batches, no seam split.
        findings = [
            {"id": f"F-{i}", "severity": "CRITICAL", "seam": f"pkg/mod{i}.ts", "file_field": None}
            for i in range(6)
        ]
        batches, missing = plan_batches(findings, max_batches=4)
        self.assertLessEqual(len(batches), 4)
        self.assertEqual(missing, [])
        all_ids = sorted(fid for b in batches for fid in b["finding_ids"])
        self.assertEqual(all_ids, [f["id"] for f in sorted(findings, key=lambda f: f["id"])])

    def test_batch_count_when_fewer_seams_than_cap(self):
        # Only 2 distinct seams -- must not manufacture 4 empty batches.
        findings = [
            {"id": "F-1", "severity": "CRITICAL", "seam": "a.ts", "file_field": None},
            {"id": "F-2", "severity": "CRITICAL", "seam": "b.ts", "file_field": None},
        ]
        batches, _ = plan_batches(findings, max_batches=4)
        self.assertEqual(len(batches), 2)

    def test_no_finding_lost_or_duplicated_across_batches(self):
        findings = [
            {"id": f"F-{i}", "severity": "CRITICAL", "seam": f"seam{i % 3}.ts", "file_field": None}
            for i in range(9)
        ]
        batches, _ = plan_batches(findings, max_batches=4)
        all_ids = [fid for b in batches for fid in b["finding_ids"]]
        self.assertEqual(sorted(all_ids), sorted(f["id"] for f in findings))
        self.assertEqual(len(all_ids), len(set(all_ids)), "a finding id appeared more than once")


class SeamCohesionAssertionTests(unittest.TestCase):
    """Real planner output must pass the cohesion check; a hand-corrupted
    plan must make it fail. The second half is the negative control that
    proves the assertion line actually catches broken grouping rather than
    passing vacuously."""

    def test_real_plan_passes_cohesion_check(self):
        plan = build_plan(CONSENSUS_SAMPLE, "fake.review.md", max_batches=4)
        assert_seam_cohesion(plan["batches"])  # must not raise

    def test_negative_control_broken_grouping_is_caught(self):
        # Hand-construct a plan where the SAME seam is claimed by two
        # different batches -- exactly the bug seam-cohesion exists to catch.
        broken_batches = [
            {"batch_id": 1, "seams": ["apps/backend/src/foo.ts"], "finding_ids": ["F-1"]},
            {"batch_id": 2, "seams": ["apps/backend/src/foo.ts"], "finding_ids": ["F-2"]},
        ]
        with self.assertRaises(AssertionError):
            assert_seam_cohesion(broken_batches)


if __name__ == "__main__":
    unittest.main()
