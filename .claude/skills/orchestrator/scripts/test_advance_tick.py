#!/usr/bin/env python3
"""Conformance tests for the advance tick.

SCOPE, stated honestly: SKILL.md is prose, so these pin the CONTRACT — the order of
the gates and the presence of guards whose absence has a measured cost. They cannot
prove runtime behavior. Where a rule is testable as an ordering (an override that must
precede any tool call), it is tested as an ordering, not as a phrase count."""

import re
import unittest
from pathlib import Path

SKILL = (Path(__file__).resolve().parents[1] / "SKILL.md").read_text()
TICK = SKILL.split("## The advance tick")[1].split("\n## Grading a lane")[0]


def pos(needle, hay=TICK):
    i = hay.find(needle)
    assert i != -1, f"missing from the tick: {needle!r}"
    return i


class AdvanceTickTests(unittest.TestCase):
    def test_the_tick_exists_and_is_ordered(self):
        for n in range(1, 9):
            self.assertTrue(re.search(rf"^{n}\. \*\*", TICK, re.M), f"step {n} missing")

    def test_overrides_gate_the_tick_before_any_tool_call(self):
        # An override checked AFTER a survey has already been violated by the survey.
        self.assertLess(pos("Terminal stop?"), pos("Survey once"))
        self.assertLess(pos("Completion-mode freeze?"), pos("Survey once"))
        self.assertLess(pos("Owned child active?"), pos("Survey once"))
        self.assertIn("before any tool call", TICK)

    def test_it_invokes_the_frontier_rather_than_reimplementing_it(self):
        self.assertIn("Do not reimplement that computation here", TICK)
        self.assertIn("§Autonomous stretches", TICK)

    def test_it_dispatches_one_forcing_function_under_the_caps(self):
        self.assertIn("Dispatch ONE forcing function", TICK)
        self.assertIn("heavy", TICK)

    def test_the_known_wrong_liveness_probe_is_named_as_wrong(self):
        # This probe returns 0 for HEALTHY lanes; believing it re-dispatches live work.
        self.assertIn('grep -c "[c]laude -p"', TICK)
        self.assertIn("0 for healthy lanes", TICK)
        self.assertIn('grep "[b]in/claude"', TICK)
        self.assertIn("sanity-control", TICK.lower())

    def test_a_zero_byte_output_is_not_treated_as_death(self):
        self.assertIn("0-byte output file is not death", TICK)

    def test_a_dead_lane_is_salvaged_before_replacement(self):
        self.assertLess(pos("status --porcelain"), pos("The replacement is a **continuation**"))
        self.assertIn("never a replay", TICK)

    def test_the_lane_never_waits_on_a_deploy(self):
        self.assertIn("commits and pushes synchronously", TICK)
        self.assertIn("hook-denied", TICK)
        self.assertIn("session that\nno longer exists", TICK)

    def test_an_early_wake_runs_no_verifier(self):
        # A sleeping root verifies nothing; a wake only triggers inspection.
        self.assertIn("exact deploy SHA", TICK)
        self.assertIn("no verifier\nruns", TICK)
        self.assertIn("retain the keyed wake artifact", TICK)

    def test_there_is_no_fixed_stall_threshold(self):
        # Wake count measures scheduler cadence, not progress. A universal N parks a
        # healthy long build; the bound must be per-lane.
        self.assertIn("no fixed number of idle wakes", TICK)
        self.assertIn("lease or checkpoint\ndeadline", TICK)
        self.assertNotRegex(
            TICK, r"(?i)on the (second|third|fourth|Nth) consecutive (no-delta|idle) wake",
            "a universal N was reintroduced")

    def test_semantic_delta_excludes_log_churn(self):
        self.assertIn("normalized semantic fingerprint", TICK)
        self.assertIn("mtimes do not qualify", TICK)

    def test_another_lanes_wake_does_not_penalize_a_live_lane(self):
        self.assertIn("never counts against a live lane still inside its lease", TICK)


if __name__ == "__main__":
    unittest.main()
