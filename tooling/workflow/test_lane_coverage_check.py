#!/usr/bin/env python3
"""Tests for lane_coverage_check. Run: python3 -m unittest tooling.workflow.test_lane_coverage_check -v
or simply: python3 tooling/workflow/test_lane_coverage_check.py
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "lane_coverage_check.py")


def run(journal_rows, program_text, extra=()):
    with tempfile.TemporaryDirectory() as d:
        jp = os.path.join(d, "journal.jsonl")
        pp = os.path.join(d, "program.md")
        with open(jp, "w", encoding="utf-8") as fh:
            for row in journal_rows:
                fh.write(json.dumps(row) + "\n")
        with open(pp, "w", encoding="utf-8") as fh:
            fh.write(program_text)
        proc = subprocess.run(
            [sys.executable, TOOL, "--journal", jp, "--program", pp, *extra],
            capture_output=True, text=True)
        return proc.returncode, proc.stdout + proc.stderr


def lane(label, **payload):
    return {"type": "result", "label": label, "value": payload}


class LaneCoverage(unittest.TestCase):
    def test_cited_lane_passes(self):
        rows = [lane("measure:a", headline="define->build gap median 36.55h p90 155.95h N=10")]
        rc, out = run(rows, "The gap is median 36.55h, p90 155.95h — that is the answer.")
        self.assertEqual(rc, 0, out)
        self.assertIn("PASS", out)

    def test_dropped_lane_fails_and_is_named(self):
        """The exact 2026-08-26 defect: a lane is read, then omitted from the program."""
        rows = [
            lane("measure:kept", headline="verify blocked 19.36h over 276 calls"),
            lane("measure:define-phase", headline="define->build median 36.55h p90 155.95h N=10"),
        ]
        program = "Only the verify finding: 19.36h across 276 calls."
        rc, out = run(rows, program)
        self.assertEqual(rc, 1, out)
        self.assertIn("measure:define-phase", out)
        self.assertIn("not cited", out)
        self.assertNotIn("'measure:kept' is not cited", out)

    def test_refuted_lane_counts_as_cited_when_mentioned_in_did_not_survive(self):
        rows = [lane("measure:schema", headline="3-PR chain costs 78.5 min, 8.8x slower, n=21")]
        program = "## DID_NOT_SURVIVE\n- Schema chain REJECTED: the 8.8x was inverted; 78.5 min stands."
        rc, out = run(rows, program)
        self.assertEqual(rc, 0, out)

    def test_undisclosed_lane_death_fails_and_is_named(self):
        """dispatched > completed must never read as clean."""
        rows = [
            {"type": "started", "label": "falsify:p1"},
            {"type": "started", "label": "falsify:p4p5"},
            lane("falsify:p1", verdict="REJECT",
                 reason="return 0 at line 693 is a false green; 262 runs, 21.62h"),
        ]
        rc, out = run(rows, "falsify:p1 REJECT — the call site at 693 makes it green; 262 runs.")
        self.assertEqual(rc, 1, out)
        self.assertIn("falsify:p4p5", out)
        self.assertIn("never returned", out)

    def test_disclosed_lane_death_passes(self):
        """A gate that cannot be satisfied gets ignored. Disclosure is the requirement."""
        rows = [
            {"type": "started", "label": "falsify:p1"},
            {"type": "started", "label": "falsify:p4p5"},
            lane("falsify:p1", verdict="REJECT",
                 reason="return 0 at line 693 is a false green; 262 runs, 21.62h"),
        ]
        program = ("falsify:p1 REJECT — the call site at 693 makes it green; 262 runs. "
                   "Lane falsify:p4p5 DIED (StructuredOutput retry cap); that axis is UNTESTED.")
        rc, out = run(rows, program)
        self.assertEqual(rc, 0, out)
        self.assertIn("is disclosed", out)

    def test_generic_numbers_do_not_count_as_citation(self):
        """A program that shares only stopwords/small ints with a lane is NOT citing it."""
        rows = [lane("measure:x", headline="found 8536 calls consuming 23.9 hours")]
        rc, out = run(rows, "We looked at 100 things in 2026 and found 3 issues.")
        self.assertEqual(rc, 1, out)

    def test_incidental_payload_match_is_not_citation(self):
        """REGRESSION (2026-08-26): v1 judged coverage over the WHOLE payload, so a lane's
        commands_run/probe fields — full of paths and dates that appear in any program —
        certified a lane whose actual finding had been dropped. v1 PASSED this input."""
        rows = [lane(
            "measure:define-phase",
            headline="define->build gap median 36.55h, p90 155.95h, N=10 tickets",
            commands_run=["gh pr list --limit 400", "python3 decompose3.py"],
            probe="/Users/x/.claude/analytics/harness-improvement/2026-08-26-program.md line 137",
            artifact_path="/scratch/define_gaps.json",
        )]
        # Program cites the lane's INCIDENTALS but not one number from its claim.
        program = ("See /Users/x/.claude/analytics/harness-improvement/2026-08-26-program.md "
                   "and run gh pr list --limit 400; artifact at /scratch/define_gaps.json.")
        rc, out = run(rows, program)
        self.assertEqual(rc, 1, out)
        self.assertIn("measure:define-phase", out)

    def test_two_claim_tokens_required(self):
        """One matching number from the claim is not enough."""
        rows = [lane("m", headline="gap median 36.55h p90 155.95h across N=10")]
        rc, out = run(rows, "the gap median was 36.55h")
        self.assertEqual(rc, 1, out)

    def test_unreadable_input_is_not_a_pass(self):
        proc = subprocess.run(
            [sys.executable, TOOL, "--journal", "/nonexistent/j.jsonl", "--program", "/nonexistent/p.md"],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("NOT a pass", proc.stdout + proc.stderr)

    def test_empty_journal_is_not_a_pass(self):
        rc, out = run([], "anything")
        self.assertEqual(rc, 2, out)
        self.assertIn("NOT a pass", out)

    def test_malformed_lines_are_counted_not_silently_dropped(self):
        with tempfile.TemporaryDirectory() as d:
            jp = os.path.join(d, "j.jsonl")
            pp = os.path.join(d, "p.md")
            with open(jp, "w", encoding="utf-8") as fh:
                fh.write("{not json\n")
                fh.write(json.dumps(lane("a", headline="value 36.55 and 155.95 here")) + "\n")
            with open(pp, "w", encoding="utf-8") as fh:
                fh.write("cites 36.55 and 155.95")
            proc = subprocess.run([sys.executable, TOOL, "--journal", jp, "--program", pp],
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0)
            self.assertIn("1 malformed", proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
