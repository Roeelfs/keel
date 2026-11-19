#!/usr/bin/env python3
"""Unit tests for lane_pool.pick: the closest-to-limit headless pool, claude on any doubt."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lane_pool  # noqa: E402

SCRIPT = Path(__file__).resolve().parent / "lane_pool.py"


def codex(used, **extra):
    return dict({"used_percent": used, "verdict": "ok", "stale": False}, **extra)


def accounts(*pairs):
    return [{"account": a, "used_percent": u} for a, u in pairs]


class PickTests(unittest.TestCase):
    def pick(self, c, cl):
        return lane_pool.pick({"codex": c, "claude": cl})

    def test_highest_used_with_room_wins(self):
        self.assertEqual(self.pick(codex(80), accounts(("a", 40), ("b", 10)))[:2], ("codex", "codex"))
        self.assertEqual(self.pick(codex(30), accounts(("a", 70), ("b", 90)))[:2], ("claude", "claude:b"))

    def test_a_pool_at_or_over_its_limit_is_skipped(self):
        runtime, pool, reason = self.pick(codex(100), accounts(("a", 20)))
        self.assertEqual((runtime, pool), ("claude", "claude:a"))
        self.assertIn("skipped at limit: codex 100%", reason)
        self.assertEqual(self.pick(codex(50), accounts(("a", 100), ("b", 130)))[:2], ("codex", "codex"))

    def test_every_pool_at_limit_falls_back_to_claude(self):
        runtime, pool, reason = self.pick(codex(100), accounts(("a", 100)))
        self.assertEqual((runtime, pool), ("claude", "claude"))
        self.assertTrue(reason.startswith("fallback: every pool at or over its limit"))

    def test_a_tie_goes_to_claude_then_input_order(self):
        self.assertEqual(self.pick(codex(60), accounts(("a", 60)))[:2], ("claude", "claude:a"))
        self.assertEqual(self.pick(codex(10), accounts(("a", 60), ("b", 60)))[:2], ("claude", "claude:a"))

    def test_unmeasured_pools_fall_back_to_claude(self):
        cases = {
            "codex and claude": (None, None),
            "claude": (codex(40), None),
            "codex": (None, accounts(("a", 40))),
        }
        for missing, (c, cl) in cases.items():
            with self.subTest(missing=missing):
                runtime, pool, reason = self.pick(c, cl)
                self.assertEqual((runtime, pool), ("claude", "claude"))
                self.assertEqual(reason, "fallback: %s unmeasured, pools cannot be compared" % missing)

    def test_unknown_stale_or_malformed_codex_reading_is_unmeasured(self):
        for c in (codex(-1, verdict="unknown"), codex(90, stale=True), codex("90"), codex(True),
                  {"verdict": "ok"}, "90", []):
            with self.subTest(codex=c):
                self.assertTrue(self.pick(c, accounts(("a", 10)))[2].startswith("fallback: codex unmeasured"))

    def test_a_bad_claude_account_entry_is_ignored(self):
        bad = [{"account": "someone@example.invalid", "used_percent": 99},  # never an email
               {"account": "", "used_percent": 99}, {"account": "a", "used_percent": None},
               {"used_percent": 99}, "a", None]
        self.assertTrue(self.pick(codex(10), bad)[2].startswith("fallback: claude unmeasured"))
        runtime, pool, reason = self.pick(codex(10), bad + accounts(("ok", 50)))
        self.assertEqual((runtime, pool), ("claude", "claude:ok"))
        self.assertNotIn("@", reason)

    def test_non_object_input_falls_back(self):
        for m in (None, [], "x", 3):
            with self.subTest(m=m):
                self.assertEqual(lane_pool.pick(m)[:2], ("claude", "claude"))


class CliTests(unittest.TestCase):
    def run_cli(self, stdin):
        r = subprocess.run([sys.executable, "-I", str(SCRIPT)], input=stdin, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.splitlines()

    def test_two_line_output(self):
        out = self.run_cli(json.dumps({"codex": codex(80), "claude": accounts(("a", 20))}))
        self.assertEqual(out[0], "codex codex")
        self.assertEqual(len(out), 2)
        self.assertTrue(out[1].startswith("closest to its limit with room"))

    def test_unparseable_stdin_falls_back(self):
        self.assertEqual(self.run_cli("not json")[0], "claude claude")
        self.assertEqual(self.run_cli("")[0], "claude claude")


if __name__ == "__main__":
    unittest.main()
