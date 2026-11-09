#!/usr/bin/env python3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "validate_review_report.py"
sys.path.insert(0, str(SCRIPT.parent))
import validate_review_report as vrr  # noqa: E402


PASSING_REPORT = """\
## Spec Review — Final Report

### Falsifier wave: 3 dispatched over 3 CRITICAL/MAJOR — 1 REFUTED, 2 SURVIVES.

### Consensus Issues (2+ reviewers)
1. [F-1] [CRITICAL] Some issue — flagged by: completeness, codebase
   Codex confidence: 0.8 | File: foo.py:10
   Recommendation: fix it

### Edge Cases (from Edge-Case Miner — semantic boundary enumeration)
| EC-ID | Entity / Operation | Boundary | Spec Coverage | Recommended Resolution | Severity |
|---|---|---|---|---|---|
| EC-1 | Widget | max+1 | MISSING | add a cap | CRITICAL |

### Observability & Traceability Findings (from Observability Auditor)
| Obs-ID | Category | Spec Section | Gap | Severity | Recommended Resolution |
|---|---|---|---|---|---|
| Obs-1 | 3 | §4 | no correlation id | CRITICAL | add a request-threading id |

Obs-1 SURVIVES the falsifier wave — no correlation id exists yet.

### Resolved (non-issues after cross-checking)
- EC-1 — REFUTED: the spec's §3 already covers max+1 via a hard cap.
- F-1 — SURVIVES: kept as a real defect; fixed in spec prose.

## Carried obligations
| ID | Obligation | Proof | Owner | Close-by |
|---|---|---|---|---|
| Obs-1 | thread a correlation id end to end | test: `request_id_threads_through_worker` | - | - |
| F-1 | the spec-prose fix holds in the build | test: `rejects_max_plus_one` | - | - |
"""

CARRIED_OBS_ROW = "| Obs-1 | thread a correlation id end to end | test: `request_id_threads_through_worker` | - | - |\n"


def strip_falsifier_line(text):
    return "\n".join(
        line for line in text.splitlines() if "Falsifier wave" not in line
    )


class ValidateReviewReportTests(unittest.TestCase):
    def test_passing_report_is_ok(self):
        ok, failures, summary = vrr.validate(PASSING_REPORT)
        self.assertTrue(ok, failures)
        self.assertEqual(failures, [])

    def test_missing_canonical_line_fails(self):
        report = strip_falsifier_line(PASSING_REPORT)
        ok, failures, _ = vrr.validate(report)
        self.assertFalse(ok)
        self.assertTrue(any("canonical falsifier-wave line" in f for f in failures))

    def test_zero_dispatched_while_majors_exist_fails(self):
        report = PASSING_REPORT.replace(
            "### Falsifier wave: 3 dispatched over 3 CRITICAL/MAJOR — 1 REFUTED, 2 SURVIVES.",
            "### Falsifier wave: 0 dispatched over 3 CRITICAL/MAJOR — 0 REFUTED, 0 SURVIVES.",
        )
        ok, failures, _ = vrr.validate(report)
        self.assertFalse(ok)
        self.assertTrue(any("dispatched N=0" in f for f in failures))

    def test_critical_finding_without_verdict_fails(self):
        report = PASSING_REPORT.replace(
            "- EC-1 — REFUTED: the spec's §3 already covers max+1 via a hard cap.\n", ""
        )
        ok, failures, _ = vrr.validate(report)
        self.assertFalse(ok)
        self.assertTrue(any("EC-1" in f for f in failures))

    def test_surviving_obs_critical_without_carried_block_is_rejected(self):
        report = PASSING_REPORT.split("## Carried obligations")[0]
        ok, failures, _ = vrr.validate(report)
        self.assertFalse(ok)
        self.assertTrue(any("Carried obligations" in f for f in failures))

    def test_surviving_obs_critical_with_bare_carried_heading_is_rejected(self):
        # A heading with no matching row must also fail (not just a missing section).
        report = PASSING_REPORT.replace(CARRIED_OBS_ROW, "")
        ok, failures, _ = vrr.validate(report)
        self.assertFalse(ok)
        self.assertTrue(any("Obs-1" in f and "Carried obligations" in f for f in failures))

    def test_surviving_finding_from_any_lane_is_carried(self):
        report = PASSING_REPORT.replace("| F-1 | the spec-prose fix holds in the build | test: `rejects_max_plus_one` | - | - |\n", "")
        ok, failures, _ = vrr.validate(report)
        self.assertFalse(ok)
        self.assertTrue(any("missing: F-1" in f for f in failures))

    def test_carried_row_without_a_proof_is_rejected(self):
        report = PASSING_REPORT.replace("test: `request_id_threads_through_worker`", "TBD")
        self.assertTrue(any("no named proof" in f for f in vrr.validate(report)[1]))
        bulleted = PASSING_REPORT.split("| ID |")[0] + "- Obs-1, F-1 — tracked as a follow-up\n"
        self.assertTrue(any("Proof column" in f for f in vrr.validate(bulleted)[1]))

    def test_critical_tier_needs_a_drive_and_a_bake_row_with_owner_and_date(self):
        report = PASSING_REPORT.replace("## Spec Review — Final Report", "## Spec Review — Final Report\n### Profile: full (tier critical)")
        failures = vrr.validate(report)[1]
        self.assertTrue(any("PRE-MERGE DRIVE" in f for f in failures) and any("POST-DEPLOY BAKE" in f for f in failures))
        rows = ("| PRE-MERGE DRIVE | staging probe of the changed seam | drive: `probe-seam.sh` against the test org | the author | 2026-11-12 |\n"
                "| POST-DEPLOY BAKE | 24h error-rate parity | bake: alarm on the changed handler | the author | 2026-11-14 |\n")
        self.assertTrue(vrr.validate(report + rows)[0], vrr.validate(report + rows)[1])
        undated = report + rows.replace("2026-11-14", "after deploy")
        self.assertTrue(any("close-by date" in f for f in vrr.validate(undated)[1]))

    def test_standard_tier_runtime_path_needs_a_drive_row(self):
        head = "## Spec Review — Final Report\n### Profile: standard (tier standard) — runtime path: services/api/handler"
        report = PASSING_REPORT.replace("## Spec Review — Final Report", head)
        self.assertTrue(any("PRE-MERGE DRIVE" in f for f in vrr.validate(report)[1]))
        row = "| PRE-MERGE DRIVE | staging probe of the changed seam | drive: `probe-seam.sh` against the test org | the author | 2026-11-12 |\n"
        self.assertTrue(vrr.validate(report + row)[0], vrr.validate(report + row)[1])
        none = PASSING_REPORT.replace("## Spec Review — Final Report", head.replace("services/api/handler", "none"))
        self.assertFalse(any("PRE-MERGE DRIVE" in f for f in vrr.validate(none)[1]))

    def test_prints_per_lane_verdict_counts(self):
        _, _, summary = vrr.validate(PASSING_REPORT)
        joined = "\n".join(summary)
        for family in ("EC-N", "Sec-N", "Obs-N", "LE-N", "F-N"):
            self.assertIn(family, joined)

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            good = Path(d) / "good.review.md"
            bad = Path(d) / "bad.review.md"
            good.write_text(PASSING_REPORT)
            bad.write_text(strip_falsifier_line(PASSING_REPORT))

            r_good = subprocess.run(
                [sys.executable, str(SCRIPT), str(good)], capture_output=True, text=True
            )
            self.assertEqual(r_good.returncode, 0, r_good.stdout + r_good.stderr)
            self.assertIn("PASS", r_good.stdout)

            r_bad = subprocess.run(
                [sys.executable, str(SCRIPT), str(bad)], capture_output=True, text=True
            )
            self.assertEqual(r_bad.returncode, 1)
            self.assertIn("FAIL", r_bad.stdout)


if __name__ == "__main__":
    unittest.main()
