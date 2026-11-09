#!/usr/bin/env python3
"""Hermetic tests for build_overview.py and its hook in render_state.py. Every path is a temp dir; the Stop guard is
a two-function stand-in so a program's AT-WAKE Status is read the way render_state reads it.

Run: python3 -m unittest test_build_overview
"""
import datetime as dt
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr
from unittest import mock

TMP = os.environ.setdefault("STATE_PAGE_TEST_TMP", tempfile.mkdtemp(prefix="state-page-test-"))
# The same temp layout as test_render_state, so either module may be imported first without reaching real state.
for key, value in {"S2C_CLAUDE_HOME": TMP, "S2C_STORE": os.path.join(TMP, "store"),
                   "S2C_SESSION_INDEX": os.path.join(TMP, "index.json"),
                   "WORK_STATE_PROGRAMS": os.path.join(TMP, "orchestrator", "programs"),
                   "WORK_STATE_DIR": os.path.join(TMP, "ws"), "WORK_STATE_LANE_ROWS": os.path.join(TMP, "lanes.jsonl"),
                   "WORK_STATE_ANALYTICS": os.path.join(TMP, "analytics.jsonl"), "RENDER_STATE_NO_OPEN": "1"}.items():
    os.environ.setdefault(key, value)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_overview as bo  # noqa: E402
import render_state as rs  # noqa: E402
import state_index as si  # noqa: E402

NOW = dt.datetime(2026, 11, 3, 12, 0, tzinfo=dt.timezone.utc)
FAKE_GUARD = '''import re
def at_wake_tail(text):
    return text[[m.start() for m in re.finditer(r"^## AT-WAKE", text, re.M)][-1]:]
def state_facts(text, now):
    if "## AT-WAKE" not in text:
        return {"has_at_wake": False}
    m = re.search(r"^Status:\\s*(\\S+)", at_wake_tail(text), re.M)
    return {"has_at_wake": True, "status": m.group(1) if m else None}
'''


def state_md(status, destination, claim, ticket=None):
    proof = {"claim": claim, "verdict": "owed"}
    if ticket:
        proof["ticket"] = ticket
    view = {"updated_at": "2026-11-03T11:00:00Z", "destination": destination,
            "proof_owed": [{"claim": "Already proven", "verdict": "pass"}, proof]}
    return f"## AT-WAKE\nStatus: {status}\n\n## VIEW\n```json\n{json.dumps(view)}\n```\n"


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="overview-test-")
        self.programs = os.path.join(self.root, "programs")
        self.odir = os.path.join(self.root, "overview")
        os.makedirs(self.programs)
        guard = os.path.join(self.root, "guard.py")
        with open(guard, "w") as fh:
            fh.write(FAKE_GUARD)
        env = mock.patch.dict(os.environ, {"WORK_STATE_GUARD_SCRIPT": guard})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(shutil.rmtree, self.root, True)
        self.program("alpha", "WORKING", "Orders ship.", "Orders are accepted", "TKT-2")
        self.program("beta", "GRILLING", "Invoices go out.", "An invoice is sent")
        self.program("gone", "DONE", "Old goal.", "x", manifest_status="done")

    def program(self, slug, status, destination, claim, ticket=None, manifest_status=None):
        manifest = {"program": slug, "goal": "Reach " + slug}
        if manifest_status:
            manifest["status"] = manifest_status
        with open(os.path.join(self.programs, slug + ".json"), "w") as fh:
            json.dump(manifest, fh)
        with open(os.path.join(self.programs, slug + ".state.md"), "w") as fh:
            fh.write(state_md(status, destination, claim, ticket))
        with open(os.path.join(self.programs, slug + ".state.json"), "w") as fh:
            json.dump({"schema": si.SIDECAR_SCHEMA, "program": slug, "generated_at": "2026-11-03T11:59:00Z"}, fh)

    def build(self, **kw):
        kw.setdefault("force", True)
        return bo.build(now=NOW, odir=self.odir, programs_dir=self.programs, titles={"alpha": "[Manager] Alpha"}, **kw)

    def page(self):
        with open(os.path.join(self.odir, bo.PAGE)) as fh:
            return fh.read()

    def diagrams(self, mtime):
        os.makedirs(self.odir, exist_ok=True)
        for d in bo.DIAGRAMS:
            path = os.path.join(self.odir, d)
            with open(path, "w") as fh:
                fh.write("<html></html>")
            os.utime(path, (mtime, mtime))


class TableTest(Base):
    def test_table_lists_live_programs_from_two_views(self):
        note = self.build()
        self.assertEqual(note["rows"], 2)
        page = self.page()
        self.assertIn("<b>alpha</b></td><td>[Manager] Alpha</td><td>WORKING</td><td>Orders are accepted (TKT-2)</td>", page)
        self.assertIn('<b>beta</b></td><td><span class="unv">unknown</span></td><td>GRILLING</td><td>An invoice is sent</td>', page)
        self.assertIn("beta.state.html", page)
        self.assertNotIn("<b>gone</b>", page)
        self.assertIn("Program table updated <b>2026-11-03T12:00:00Z</b> from 2 live program(s)", page)

    def test_hand_built_regions_survive_and_legacy_table_is_adopted(self):
        os.makedirs(self.odir)
        with open(os.path.join(self.odir, bo.PAGE), "w") as fh:
            fh.write('<html><body><main><h1>Whole picture</h1><div class="goal">The one goal</div>'
                     '<iframe src="overview.release.html"></iframe><h2>Every live program</h2>\n<table><tr><td>old row</td></tr>'
                     '</table>\n<p class="mut">old note</p></main></body></html>')
        self.build()
        self.build()
        page = self.page()
        self.assertIn('<div class="goal">The one goal</div>', page)
        self.assertIn('<iframe src="overview.release.html">', page)
        self.assertNotIn("old row", page)
        self.assertNotIn("old note", page)
        self.assertEqual(page.count("<!-- auto:table -->"), 1)
        self.assertEqual(page.count("<!-- auto:head -->"), 1)
        self.assertLess(page.index("<!-- auto:head -->"), page.index('<div class="goal">'))

    def test_programs_the_index_collapses_are_one_line_not_rows(self):
        with open(os.path.join(self.programs, "quiet.json"), "w") as fh:
            json.dump({"program": "quiet", "goal": "g"}, fh)
        self.assertEqual(self.build()["rows"], 2)
        page = self.page()
        self.assertNotIn("<b>quiet</b>", page)
        self.assertIn("1 more live program(s) not shown (never rendered), as on the index</summary>quiet</details>", page)

    def test_markup_in_a_view_is_escaped(self):
        self.program("beta", "WORKING", "d", "<script>alert(1)</script>")
        self.build()
        self.assertNotIn("<script>alert", self.page())


class ChangedStripTest(Base):
    def test_first_build_has_nothing_to_compare(self):
        self.build()
        self.assertIn("No change between builds recorded yet.", self.page())

    def test_changes_since_last_build_are_listed_and_carried_forward(self):
        self.build()
        self.program("alpha", "BAKING", "Orders ship.", "Orders are paid", "TKT-4")
        self.program("gamma", "WORKING", "New.", "First proof")
        os.remove(os.path.join(self.programs, "beta.json"))
        note = self.build()
        self.assertEqual(note["changes"], 4)
        page = self.page()
        for line in ("gamma added", "beta removed", "alpha: status WORKING -&gt; BAKING", "alpha: next proof owed changed"):
            self.assertIn(line, page)
        self.build()
        self.assertIn("gamma added", self.page(), "an unchanged build keeps showing the last change")
        with open(os.path.join(self.odir, bo.LAST)) as fh:
            last = json.load(fh)
        self.assertEqual([r["program"] for r in last["rows"]], ["alpha", "gamma"])


class DiagramBannerTest(Base):
    def test_no_banner_until_programs_drift_from_the_diagrams(self):
        self.diagrams(time.time() - 3600)
        self.assertFalse(self.build()["banner"])
        self.assertNotIn("rebuild on request", self.page())
        self.program("alpha", "WORKING", "Orders ship worldwide.", "Orders are accepted")
        self.program("gamma", "WORKING", "New.", "First proof")
        self.assertTrue(self.build()["banner"])
        page = self.page()
        self.assertIn("rebuild on request", page)
        self.assertIn("gamma added; alpha: destination changed", page)

    def test_rebuilt_diagrams_reset_the_baseline(self):
        self.diagrams(time.time() - 3600)
        self.build()
        self.program("gamma", "WORKING", "New.", "First proof")
        self.assertTrue(self.build()["banner"])
        self.diagrams(time.time())
        self.assertFalse(self.build()["banner"])

    def test_a_status_change_alone_is_not_diagram_drift(self):
        self.diagrams(time.time() - 3600)
        self.build()
        self.program("alpha", "BAKING", "Orders ship.", "Orders are accepted")
        self.assertFalse(self.build()["banner"])


class DebounceTest(Base):
    def test_a_build_inside_the_window_is_skipped(self):
        self.build()
        self.assertIn("skipped", self.build(force=False))

    def test_a_build_after_the_window_runs(self):
        self.build()
        old = time.time() - bo.DEBOUNCE_S - 1
        os.utime(os.path.join(self.odir, bo.PAGE), (old, old))
        self.assertIn("out", self.build(force=False))


class HookTest(Base):
    def test_a_failed_build_never_propagates(self):
        err = io.StringIO()
        with mock.patch.object(bo, "build", side_effect=RuntimeError("disk gone")), redirect_stderr(err):
            note = rs.refresh_overview()
        self.assertIn("overview not refreshed: RuntimeError: disk gone", note)
        self.assertEqual(len(err.getvalue().strip().splitlines()), 1)

    def test_the_hook_calls_build(self):
        with mock.patch.object(bo, "build", return_value={"skipped": "debounced"}) as build:
            self.assertEqual(rs.refresh_overview(), {"skipped": "debounced"})
        build.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
