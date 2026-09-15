#!/usr/bin/env python3
"""Per-command wall budgets and recorded arguments: matching, validation and events."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

from heavy_resources import Policy, command_seconds
from heavy_runner import event_args
from resource_test_support import isolated_wrapper


class EventArgsTests(unittest.TestCase):
    def test_records_up_to_three_arguments_after_the_executable(self):
        self.assertEqual(event_args(["/repo/project-verify", "verify", "--quick", "--grep", "more"]),
                         ["verify", "--quick", "--grep"])
        self.assertEqual(event_args(["project-verify"]), [])

    def test_redacts_assignments_and_long_arguments(self):
        self.assertEqual(event_args(["tool", "--token=abc", "x" * 121, "x" * 120]),
                         ["<redacted>", "<redacted>", "x" * 120])


class CommandSecondsTests(unittest.TestCase):
    def test_longest_word_prefix_wins_and_never_exceeds_max_seconds(self):
        policy = Policy(max_seconds=100, command_max_seconds={
            "project-verify": 50, "project-verify verify": 30, "project-verify verify --full": 90})
        self.assertEqual(command_seconds(policy, ["/repo/tooling/project-verify", "verify", "--full"]), 90)
        self.assertEqual(command_seconds(policy, ["project-verify", "verify", "--quick"]), 30)
        self.assertEqual(command_seconds(policy, ["project-verify", "e2e"]), 50)
        self.assertEqual(command_seconds(policy, ["project-verify-other", "verify"]), 100)
        tightened = Policy(max_seconds=20, command_max_seconds={"project-verify": 60})
        self.assertEqual(command_seconds(tightened, ["project-verify"]), 20)

    def test_prefix_matches_whole_words_only(self):
        policy = Policy(max_seconds=100, command_max_seconds={"pnpm te": 10, "pnpm test run": 5})
        self.assertEqual(command_seconds(policy, ["pnpm", "test"]), 100)
        self.assertEqual(command_seconds(policy, ["pnpm", "test", "runner"]), 100)


class CommandPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.keel = os.path.join(self.tmp.name, ".keel")
        os.makedirs(self.keel)
        self.wrapper = isolated_wrapper(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write_policy(self, **values):
        with open(os.path.join(self.keel, "resource-policy.json"), "w", encoding="utf-8") as handle:
            json.dump({"min_free_percent": 0, **values}, handle)

    def run_wrapper(self, args, **extra):
        env = {**os.environ, "HOME": self.tmp.name, "KEEL_HEAVY_POLL_SECONDS": "0.05",
               "KEEL_HEAVY_MIN_FREE_PERCENT": "0", **extra}
        return subprocess.run([self.wrapper, *args], env=env, capture_output=True, text=True, timeout=15)

    def events(self):
        with open(os.path.join(self.keel, "heavy.slots", "events.jsonl"), encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def test_valid_budgets_load_and_are_checked_against_the_policy_file(self):
        self.write_policy(command_max_seconds={"project-verify verify": 3600})
        result = self.run_wrapper(["--status"], KEEL_HEAVY_MAX_SECONDS="10")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["command_max_seconds"], {"project-verify verify": 3600})

    def test_a_non_object_refuses_with_a_clear_error(self):
        self.write_policy(command_max_seconds=[])
        result = self.run_wrapper(["--status"])
        self.assertEqual(result.returncode, 69, result.stderr)
        self.assertIn("command_max_seconds", result.stderr)

    def test_a_bad_entry_is_skipped_or_clamped_and_never_refuses_every_command(self):
        self.write_policy(command_max_seconds={
            "whole-float": 600.0, "above-max": 9999, "null": None, "text": "5", "flag": True,
            "zero": 0, "negative": -3, "fraction": 1.5, "/usr/bin/tool": 5, "  ": 5})
        result = self.run_wrapper(["--status"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["command_max_seconds"],
                         {"whole-float": 600, "above-max": 7200})
        for skipped in ("null", "text", "flag", "zero", "negative", "fraction", "/usr/bin/tool"):
            self.assertIn(repr(skipped), result.stderr)
        self.write_policy(max_seconds=100, command_max_seconds={"project-verify": 3600})
        lowered = self.run_wrapper(["--status"])
        self.assertEqual(lowered.returncode, 0, lowered.stderr)
        self.assertEqual(json.loads(lowered.stdout)["command_max_seconds"], {"project-verify": 100})

    def test_matching_command_stops_at_its_budget_and_records_it(self):
        self.write_policy(command_max_seconds={os.path.basename(sys.executable) + " -c": 1})
        result = self.run_wrapper([sys.executable, "-c", "import time; time.sleep(10)"])
        self.assertEqual(result.returncode, 137, result.stderr)
        stops = [row for row in self.events() if row.get("reason") == "wall_time_budget"]
        self.assertEqual(len(stops), 1, self.events())
        self.assertEqual(stops[0]["budget_seconds"], 1)
        other = self.run_wrapper([sys.executable, "-B", "-c", "import time; time.sleep(1.3)"])
        self.assertEqual(other.returncode, 0, "a non-matching command keeps max_seconds: " + other.stderr)

    def test_started_event_records_redacted_arguments(self):
        self.write_policy()
        result = self.run_wrapper(["true", "verify", "--secret=value", "x" * 121, "--full"])
        self.assertEqual(result.returncode, 0, result.stderr)
        started = [row for row in self.events() if row["event"] == "started"]
        self.assertEqual(len(started), 1, self.events())
        self.assertEqual(started[0]["args"], ["verify", "<redacted>", "<redacted>"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
