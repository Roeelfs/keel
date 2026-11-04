#!/usr/bin/env python3
"""Tests for the one Chrome tab on the state pages (render_state.tab_plan and show_in_chrome).
Every osascript and `open` call goes to a recording fake; nothing here touches a real browser.

Run: python3 -m unittest test_state_tabs
"""
import os
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

os.environ.setdefault("RENDER_STATE_NO_OPEN", "1")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_state as rs  # noqa: E402

DIR = "/Users/x/.claude/orchestrator/programs"
INDEX = DIR + "/index.state.html"


def url(name, d=DIR, tail=""):
    return "file://" + d + "/" + name + tail


class TabPlan(unittest.TestCase):
    def test_no_state_tab_opens_the_index(self):
        plan = rs.tab_plan([(1, 10, "https://example.com"), (1, 11, url("apps.state.md"))], DIR, INDEX)
        self.assertEqual(plan, {"action": "open", "url": "file://" + INDEX, "close": []})

    def test_an_open_index_is_reloaded_and_every_other_state_tab_closed(self):
        tabs = [(1, 10, url("apps.state.html")), (1, 11, "https://github.com"), (2, 20, url("index.state.html", tail="#program=apps")),
                (2, 21, url("cayp.state.html", tail="?embed=1")), (3, 30, url("index.state.html"))]
        plan = rs.tab_plan(tabs, DIR, INDEX)
        self.assertEqual(plan["action"], "reload")
        self.assertEqual(plan["tab"], (2, 20))
        self.assertEqual(sorted(plan["close"]), [(1, 10), (2, 21), (3, 30)])

    def test_without_the_index_the_first_state_tab_becomes_it_and_keeps_the_program(self):
        tabs = [(1, 9, "https://mail.google.com"), (1, 10, url("apps.state.html", tail="#history")), (2, 20, url("cayp.state.html"))]
        plan = rs.tab_plan(tabs, DIR, INDEX)
        self.assertEqual(plan, {"action": "repoint", "tab": (1, 10), "url": "file://" + INDEX + "#program=apps", "close": [(2, 20)]})

    def test_only_state_pages_directly_in_the_programs_dir_match(self):
        others = ["http://localhost" + DIR + "/apps.state.html", url("apps.state.html", d=DIR + "/archive"),
                  url("apps.state.html", d="/tmp/programs"), url("apps.state.html.bak"), url("apps.state.json"),
                  url("apps.state.html", d=DIR + "-old"), "", "about:blank"]
        plan = rs.tab_plan([(1, i, u) for i, u in enumerate(others)], DIR, INDEX)
        self.assertEqual(plan["action"], "open")

    def test_percent_encoded_paths_match(self):
        d = "/Users/x/my programs"
        plan = rs.tab_plan([(1, 1, "file:///Users/x/my%20programs/index.state.html")], d, d + "/index.state.html")
        self.assertEqual(plan["action"], "reload")

    def test_tabs_parse_and_skip_junk(self):
        self.assertEqual(rs.parse_tabs("1\t2\tfile:///a\tb\nnoise\n3\tx\turl\n\n"), [(1, 2, "file:///a\tb")])


class PlanScript(unittest.TestCase):
    def test_scripts_act_on_named_tabs_and_never_focus(self):
        for plan in ({"action": "reload", "tab": (2, 20), "close": [(1, 10)]},
                     {"action": "repoint", "tab": (1, 10), "url": 'file:///p/index.state.html#program=a"b', "close": [(2, 20), (3, 30)]}):
            script = rs.plan_script(plan)
            for banned in ("activate", "active tab", "select", "index of"):
                self.assertNotIn(banned, script)
            for w, t in plan["close"]:
                self.assertIn(f"close tab id {t} of window id {w}", script)
        self.assertIn("tell tab id 20 of window id 2 to reload", rs.plan_script({"action": "reload", "tab": (2, 20), "close": []}))
        self.assertIn('set URL of tab id 10 of window id 1 to "file:///p/index.state.html#program=a\\"b"',
                      rs.plan_script({"action": "repoint", "tab": (1, 10), "url": 'file:///p/index.state.html#program=a"b', "close": []}))


class ShowInChrome(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="state-tabs-")
        self.index = os.path.join(self.dir, "index.state.html")
        self.calls = []
        self.patches = [mock.patch.object(rs, "REAL_PROGRAMS", self.dir), mock.patch.object(rs.sys, "platform", "darwin"),
                        mock.patch.dict(os.environ, {}, clear=False)]
        for p in self.patches:
            p.start()
        os.environ.pop("RENDER_STATE_NO_OPEN", None)

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()

    def fake(self, listing, rc=0, processes=None, probe_rc=0):
        self.calls = []

        def run(cmd, **kw):
            self.calls.append(cmd)
            if cmd[0] == "ps":
                out = processes if processes is not None else "123 /Applications/Google Chrome.app/Contents/MacOS/Google Chrome\n"
                return types.SimpleNamespace(returncode=probe_rc, stdout=out, stderr="probe failed")
            out = listing if len(self.calls) == 2 else ""
            return types.SimpleNamespace(returncode=rc if len(self.calls) == 2 else 0, stdout=out, stderr="boom")
        return run

    def test_guards_skip_without_calling_anything(self):
        self.assertEqual(rs.show_in_chrome("/tmp/elsewhere/index.state.html", run=self.fake("")), {"action": "skipped"})
        os.environ["RENDER_STATE_NO_OPEN"] = "1"
        self.assertEqual(rs.show_in_chrome(self.index, run=self.fake("")), {"action": "skipped"})
        self.assertEqual(self.calls, [])

    def test_reload_closes_duplicates(self):
        listing = f"1\t10\tfile://{self.dir}/apps.state.html\n1\t11\tfile://{self.index}\n1\t12\thttps://x\n"
        self.assertEqual(rs.show_in_chrome(self.index, run=self.fake(listing)), {"action": "reloaded", "closed": 1})
        self.assertEqual(self.calls[2][:2], ["osascript", "-e"])
        self.assertIn("tell tab id 11 of window id 1 to reload", self.calls[2][2])
        self.assertIn("close tab id 10 of window id 1", self.calls[2][2])
        self.assertNotIn("id 12", self.calls[2][2])

    def test_no_state_tab_opens_one_in_the_background(self):
        self.assertEqual(rs.show_in_chrome(self.index, run=self.fake("1\t12\thttps://x\n")), {"action": "opened", "closed": 0})
        self.assertEqual(self.calls[2], ["open", "-g", "-a", "Google Chrome", "file://" + self.index])

    def test_automation_chrome_skips_all_browser_access(self):
        chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome "
        for args in ("--remote-debugging-pipe", "--remote-debugging-port=9222", "--user-data-dir=/tmp/playwright_profile"):
            for listing in ("1\t12\thttps://example.com\n", f"1\t11\tfile://{self.index}\n"):
                with self.subTest(args=args, listing=listing):
                    result = rs.show_in_chrome(self.index, run=self.fake(listing, processes=f"78315 {chrome}{args}\n"))
                    self.assertEqual(result["action"], "skipped: automation Chrome running")
                    self.assertEqual(self.calls, [["ps", "-axo", "pid=,command="]])

    def test_unrelated_automation_does_not_block_chrome(self):
        processes = "123 /Applications/Google Chrome.app/Contents/MacOS/Google Chrome\n456 /tmp/other-browser --remote-debugging-pipe\n"
        result = rs.show_in_chrome(self.index, run=self.fake("1\t12\thttps://example.com\n", processes=processes))
        self.assertEqual(result["action"], "opened")
        self.assertEqual(self.calls[-1], ["open", "-g", "-a", "Google Chrome", "file://" + self.index])

    def test_failed_or_ambiguous_probe_skips_all_browser_access(self):
        for processes, rc in (("", 0), ("not a process row", 0), ("123", 0), ("", 1)):
            with self.subTest(processes=processes, rc=rc):
                result = rs.show_in_chrome(self.index, run=self.fake("", processes=processes, probe_rc=rc))
                self.assertTrue(result["action"].startswith("skipped:"))
                self.assertEqual(self.calls, [["ps", "-axo", "pid=,command="]])
        for error in (OSError("ps unavailable"), subprocess.TimeoutExpired("ps", 15)):
            with self.subTest(error=error):
                run = mock.Mock(side_effect=error)
                self.assertTrue(rs.show_in_chrome(self.index, run=run)["action"].startswith("skipped:"))
                self.assertEqual(run.call_count, 1)

    def test_closed_chrome_and_failures_are_reported(self):
        self.assertEqual(rs.show_in_chrome(self.index, run=self.fake("closed\n")), {"action": "chrome closed"})
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(rs.show_in_chrome(self.index, run=self.fake("", rc=1))["action"], "error")

        probe = self.fake("")

        def boom(cmd, **kw):
            if cmd[0] == "ps":
                return probe(cmd, **kw)
            raise subprocess.TimeoutExpired(cmd, 15)
        self.assertEqual(rs.show_in_chrome(self.index, run=boom)["action"], "error")


if __name__ == "__main__":
    unittest.main(verbosity=1)
