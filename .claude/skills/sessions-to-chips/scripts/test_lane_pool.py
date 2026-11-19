#!/usr/bin/env python3
"""Unit tests for lane_pool.pick: the closest-to-limit headless pool, claude on any doubt."""

import json
import os
import subprocess
import sys
import tempfile
import time
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


NOW = 1_800_000_000.0


class SnapshotTests(unittest.TestCase):
    """The Claude reader: one usage snapshot per account, unmeasured on any doubt."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, email, used=40, resets=NOW + 3600, written=NOW - 60, mtime=NOW - 60, doc=None, raw=None):
        path = self.dir / (email + ".json")
        if raw is None:
            raw = json.dumps(doc if doc is not None else {
                "account": email, "seven_day": {"used_percentage": used, "resets_at": resets},
                "five_hour": {"used_percentage": 5, "resets_at": NOW + 600}, "written_at": written})
        path.write_text(raw)
        os.utime(path, (mtime, mtime))
        return path

    def read(self):
        return lane_pool.claude_snapshots(self.dir, NOW)

    def test_fresh_snapshot_is_measured_under_an_opaque_label(self):
        self.write("one@example.invalid", used=62.5)
        accounts, notes = self.read()
        self.assertEqual(notes, [])
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0]["used_percent"], 62.5)
        label = accounts[0]["account"]
        self.assertRegex(label, lane_pool.LABEL_RE)
        self.assertNotIn("@", label)
        self.assertTrue(label.startswith("one-"))

    def test_stale_snapshot_is_unmeasured(self):
        for written, mtime in ((NOW - 31 * 60, NOW - 60), (NOW - 60, NOW - 31 * 60)):
            with self.subTest(written=written, mtime=mtime):
                self.write("one@example.invalid", written=written, mtime=mtime)
                accounts, notes = self.read()
                self.assertEqual(accounts, [])
                self.assertIn("stale", notes[0])

    def test_expired_window_is_unmeasured(self):
        for resets in (NOW, NOW - 1):
            with self.subTest(resets=resets):
                self.write("one@example.invalid", resets=resets)
                accounts, notes = self.read()
                self.assertEqual(accounts, [])
                self.assertIn("expired", notes[0])

    def test_malformed_snapshot_is_unmeasured(self):
        email = "one@example.invalid"
        week = {"used_percentage": 40, "resets_at": NOW + 3600}
        cases = {
            "not json": dict(raw="{nope"),
            "not an object": dict(raw="[]"),
            "account mismatch": dict(doc={"account": "two@example.invalid", "seven_day": week, "written_at": NOW}),
            "no seven_day": dict(doc={"account": email, "written_at": NOW}),
            "string percent": dict(used="40"),
            "negative percent": dict(used=-1),
            "bool percent": dict(used=True),
            "no resets_at": dict(doc={"account": email, "seven_day": {"used_percentage": 40}, "written_at": NOW}),
            "no written_at": dict(doc={"account": email, "seven_day": week}),
        }
        for name, kwargs in cases.items():
            with self.subTest(case=name):
                self.write(email, **kwargs)
                accounts, notes = self.read()
                self.assertEqual(accounts, [])
                self.assertIn("malformed", notes[0])
                self.assertNotIn("@", notes[0])

    def test_two_accounts_are_both_measured_and_the_closer_one_wins(self):
        self.write("one@example.invalid", used=30)
        self.write("two@example.invalid", used=85)
        self.write("three@example.invalid", used=99, written=NOW - 3600)  # stale: skipped
        accounts, notes = self.read()
        self.assertEqual([a["used_percent"] for a in accounts], [30, 85])
        self.assertEqual(len(notes), 1)
        runtime, pool, _ = lane_pool.pick({"codex": codex(50), "claude": accounts})
        self.assertEqual((runtime, pool), ("claude", "claude:" + accounts[1]["account"]))

    def test_no_snapshots_means_claude_unmeasured(self):
        for directory in (self.dir, self.dir / "absent"):
            with self.subTest(directory=directory):
                doc, notes = lane_pool.measure(json.dumps(codex(50)), directory, NOW)
                self.assertEqual((doc["claude"], notes), ([], []))
                self.assertTrue(lane_pool.pick(doc)[2].startswith("fallback: claude unmeasured"))

    def test_measure_cli_reads_the_env_dir_and_names_skips_on_stderr(self):
        now = time.time()
        fresh = self.write("one@example.invalid", used=70, resets=now + 3600, written=now, mtime=now)
        self.write("two@example.invalid", resets=now - 1, written=now, mtime=now)
        env = dict(os.environ, LANE_POOL_CLAUDE_USAGE_DIR=str(self.dir))
        r = subprocess.run([sys.executable, "-I", str(SCRIPT), "--measure"], input="garbage",
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        doc = json.loads(r.stdout)
        self.assertIsNone(doc["codex"])
        self.assertEqual([a["used_percent"] for a in doc["claude"]], [70])
        self.assertIn("snapshot unmeasured: expired", r.stderr)
        self.assertNotIn("@", r.stdout + r.stderr)
        self.assertTrue(fresh.exists())


if __name__ == "__main__":
    unittest.main()
