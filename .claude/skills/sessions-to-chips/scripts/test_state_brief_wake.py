#!/usr/bin/env python3
"""The wake block of state_brief: rulings ledger lines since the last AT-WAKE stamp, instruction-file commits, and
a visible line when the ledger cannot be read."""
import datetime as dt
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import state_brief as sb  # noqa: E402

LEDGER = """# Rulings ledger
- not a ruling
## Rulings
- 2026-11-01 | old rule | founder 2026-11-01
- 2026-11-04 | same-day rule | founder 2026-11-04
- 2026-11-04T18:00Z | evening rule | founder 2026-11-04
"""


def _git(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True,
                   env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
                            GIT_COMMITTER_EMAIL="t@t", GIT_AUTHOR_DATE="2026-11-04T12:00:00Z",
                            GIT_COMMITTER_DATE="2026-11-04T12:00:00Z"))


class WakeLines(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="brief-wake-")
        self.ledger = os.path.join(self.tmp, "rulings-ledger.md")
        with open(self.ledger, "w") as fh:
            fh.write(LEDGER)

    def test_rulings_newer_than_the_stamp_appear(self):
        out = "\n".join(sb.ruling_lines(sb.parse_when("2026-11-04T16:12Z"), self.ledger))
        self.assertIn("same-day rule", out)
        self.assertIn("evening rule", out)
        self.assertNotIn("old rule", out)
        self.assertIn("(2 of 3)", out)
        # Mutation control: a stamp after the timed ruling drops it; the date-only one still shows that day.
        later = "\n".join(sb.ruling_lines(sb.parse_when("2026-11-04T19:00Z"), self.ledger))
        self.assertNotIn("evening rule", later)
        self.assertIn("same-day rule", later)

    def test_no_stamp_prints_every_ruling(self):
        out = sb.ruling_lines(None, self.ledger)
        self.assertEqual(len(out), 4)
        self.assertIn("no AT-WAKE stamp", out[0])

    def test_nothing_new_is_one_line(self):
        out = sb.ruling_lines(sb.parse_when("2026-11-05T00:00Z"), self.ledger)
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].startswith("Rulings: none new since 2026-11-05T00:00Z"))

    def test_unreadable_ledger_prints_a_visible_line(self):
        missing = os.path.join(self.tmp, "gone.md")
        self.assertTrue(sb.ruling_lines(None, missing)[0].startswith("Rulings ledger unreadable: " + missing))
        empty = os.path.join(self.tmp, "empty.md")
        open(empty, "w").close()
        self.assertTrue(sb.ruling_lines(None, empty)[0].startswith("Rulings ledger unreadable: "))

    def test_git_log_section_lists_commits_since_the_stamp(self):
        _git(self.tmp, "init", "-q")
        _git(self.tmp, "add", "rulings-ledger.md")
        _git(self.tmp, "commit", "-q", "-m", "feat(rules): seed the ledger")
        files = (("ledger", self.ledger), ("again", self.ledger))
        out = sb.instruction_changes(sb.parse_when("2026-11-04T11:00Z"), files)
        self.assertEqual(out[0], "Instruction changes (since 2026-11-04T11:00Z): 1; Read the changed files")
        self.assertRegex(out[1], r"^- ledger: [0-9a-f]+ feat\(rules\): seed the ledger$")
        self.assertEqual(len(out), 2)  # the same commit through a second label is not repeated
        self.assertEqual(sb.instruction_changes(sb.parse_when("2026-11-04T13:00Z"), files)[0],
                         "Instruction changes (since 2026-11-04T13:00Z): none")

    def test_git_failure_is_visible(self):
        outside = tempfile.mkdtemp(prefix="brief-nogit-")
        path = os.path.join(outside, "x.md")
        open(path, "w").close()
        out = sb.instruction_changes(None, (("global", path),))
        self.assertTrue(out[-1].startswith("Instruction log unreadable: global ("))

    def test_brief_puts_the_wake_block_under_the_head_outside_the_bound(self):
        text = sb.brief({"program": "p"}, wake=["Rulings: none new since x", "Config freshness: unknown (test)"])
        lines = text.splitlines()
        self.assertTrue(lines[0].startswith("p (map none)"))
        self.assertEqual(lines[2:5], ["", "Rulings: none new since x", "Config freshness: unknown (test)"])
        self.assertEqual(len(lines), len(sb.brief({"program": "p"}).splitlines()) + 3)
        self.assertNotIn("Rulings", sb.brief({"program": "p"}))

    def test_parse_when(self):
        self.assertEqual(sb.parse_when("2026-11-04T16:22Z"), dt.datetime(2026, 11, 4, 16, 22, tzinfo=dt.timezone.utc))
        self.assertIsNone(sb.parse_when("soon"))
        self.assertIsNone(sb.parse_when(None))


if __name__ == "__main__":
    unittest.main()
