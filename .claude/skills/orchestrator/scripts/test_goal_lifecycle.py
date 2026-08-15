#!/usr/bin/env python3
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
CORE = (SKILL_DIR / "SKILL.md").read_text()
RUNTIME = (SKILL_DIR / "references" / "codex-runtime.md").read_text()
LANE = (SKILL_DIR / "prompts" / "codex-lane-template.md").read_text()
ALL = "\n".join((CORE, RUNTIME, LANE))


class GoalLifecycleContractTests(unittest.TestCase):
    def test_goal_requires_explicit_autonomy_and_never_invents_token_budget(self):
        for text in (
            "explicitly requests autonomous goal execution",
            "Do not infer goal activation from an ordinary task",
            "omit `token_budget` unless the user supplied an explicit token budget",
        ):
            self.assertIn(text, RUNTIME)

    def test_goal_is_scoped_to_the_reachable_authorized_frontier(self):
        for text in (
            "reachable authorized autonomy frontier",
            "current accepted task group",
            "does not broaden scope, production authority, or approval",
        ):
            self.assertIn(text, ALL)

    def test_each_continuation_advances_one_forcing_function(self):
        for text in (
            "Call `get_goal` once at the start of each automatic continuation",
            "one `next_forcing_function`",
            "do not replay completed phases, PASS evidence, review slots, or unchanged failures",
        ):
            self.assertIn(text, RUNTIME)

    def test_goal_has_terminal_success_and_blocker_transitions(self):
        for text in (
            '`update_goal({"status":"complete"})`',
            "objective is actually achieved and no required work remains",
            "same blocker fingerprint",
            "three consecutive goal turns",
            '`update_goal({"status":"blocked"})`',
            "zero repeated side-effectful calls",
        ):
            self.assertIn(text, RUNTIME)

    def test_goal_state_is_durable_but_not_the_program_manifest(self):
        for text in (
            "## AUTONOMY",
            "stop predicates",
            "blocker fingerprint",
            "runtime continuation lease",
            "program manifest remains the cross-session source of truth",
        ):
            self.assertIn(text, RUNTIME)

    def test_terminal_stop_and_children_cannot_leave_a_goal_dangling(self):
        self.assertIn("Goal command contract", CORE)
        self.assertIn("owned child continuation invariant", ALL.lower())
        self.assertIn("Terminal stop still wins", RUNTIME)


if __name__ == "__main__":
    unittest.main()
