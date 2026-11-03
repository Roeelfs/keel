#!/usr/bin/env python3
"""Hermetic tests for render_state.py and state_graph.py. Every path is a temp dir; the engine is real
and reads the repo's de-identified tracker fixture. Two classes use the real Stop guard and the real
Archify, and skip where those are not installed.

Run: python3.11 -I test_render_state.py
"""
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import unittest

TMP = tempfile.mkdtemp(prefix="render-state-test-")
PROGRAMS = os.path.join(TMP, "orchestrator", "programs")
REAL_HOME = os.path.expanduser("~/.claude")
REAL_GUARD = os.path.join(REAL_HOME, "scripts", "manager_arm_guard.py")
REAL_ARCHIFY = os.path.join(REAL_HOME, "skills", "archify", "bin", "archify.mjs")
os.environ.update({"S2C_CLAUDE_HOME": TMP, "S2C_STORE": os.path.join(TMP, "store"),
                   "S2C_SESSION_INDEX": os.path.join(TMP, "index.json"), "WORK_STATE_PROGRAMS": PROGRAMS,
                   "WORK_STATE_DIR": os.path.join(TMP, "ws"), "WORK_STATE_LANE_ROWS": os.path.join(TMP, "lanes.jsonl"),
                   "WORK_STATE_ANALYTICS": os.path.join(TMP, "analytics.jsonl"),
                   "WORK_STATE_GUARD_SCRIPT": REAL_GUARD})
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import render_state as rs  # noqa: E402
import state_graph as sg  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "work_state", "linear-map-snapshot.fixture.json")
NOW = dt.datetime(2026, 11, 3, 12, 0, tzinfo=dt.timezone.utc)
VIEW = {"updated_at": "2026-11-03T11:00:00Z", "explanation": "Builds the thing.",
        "next_steps": [{"step": "Ship it", "owner": "manager"}], "upcoming": [{"when": "Tonight", "what": "Bake"}],
        "needs_you": [{"ask": "Merge it?", "recommended": "Yes"}],
        "decisions": [{"date": "2026-11-02", "decision": "Use one template", "why": "One owner", "by": "founder"}],
        "proven": [{"claim": "Parser works", "evidence": "commit abc123"}],
        "unproven": [{"claim": "Bake passes", "owed": "a green bake"}]}
AT_WAKE = """## AT-WAKE
Status: DONE
Next action: stale old action

## AT-WAKE
Status: WORKING
Wake: ScheduleWakeup fires 2026-11-03T12:30:00Z (1800s) on CI; on fire: read the CI result
Hold: TKT-7 founder-gated:g1 waits for the founder
Next action: grade the lane
Owner: manager
Prerequisite: none
Stop condition: map done
"""


def view_block(obj):
    body = obj if isinstance(obj, str) else json.dumps(obj, indent=1)
    return f"## VIEW\n```json\n{body}\n```\n"


def write_program(slug, manifest=None, state=None, events=None):
    os.makedirs(PROGRAMS, exist_ok=True)
    base = os.path.join(PROGRAMS, slug)
    bound = "2026-11-03T11:00:00Z"
    default = {"program": slug, "goal": "Reach the destination", "manager_session": "local_x",
               "map": {"issue": "TKT-1", "url": "https://tracker.example/issue/TKT-1", "project": "",
                       "snapshot_cmd": ["cat", FIXTURE]},
               "ceded": [], "shared_touch_not_owned": [], "gates_held_by_manager": ["prod merge"],
               "bindings": [{"ticket": "TKT-5", "bound_at": bound, "bake": "required", "branch": "feat/x",
                             "artifact": "a branch", "publication": {"repo": "o/r", "pr": 12},
                             "carriers": [{"type": "lane", "id": "lane-a", "bound_at": bound, "runtime": "claude",
                                           "model": "opus"}]}],
               "next_forcing_function": "move", "updated_at": bound}
    with open(base + ".json", "w") as fh:
        json.dump(default if manifest is None else manifest, fh)
    with open(base + ".state.md", "w") as fh:
        fh.write(view_block(VIEW) + AT_WAKE if state is None else state)
    with open(base + ".events.jsonl", "w") as fh:
        fh.write(events if events is not None else '{"ts":"2026-11-03T10:00:00Z","event":"dispatched","note":"go"}\n')
    return base


def payload_of(path):
    with open(path) as fh:
        html = fh.read()
    m = re.search(r'<script id="state-payload" type="application/json">(.*?)</script>', html, re.S)
    return html, json.loads(m.group(1))


def tree_hash(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


class Inject(unittest.TestCase):
    def test_data_cannot_close_the_script_tag(self):
        out = rs.inject("<a>__STATE_PAYLOAD__</a>", {"x": "</script><script>alert(1)</script> "})
        self.assertNotIn("</script>", out)
        self.assertNotIn(" ", out)
        self.assertEqual(json.loads(out[3:-4])["x"], "</script><script>alert(1)</script> ")

    def test_refuses_a_template_without_exactly_one_placeholder(self):
        for bad in ("none", "__STATE_PAYLOAD__ __STATE_PAYLOAD__"):
            with self.assertRaises(ValueError):
                rs.inject(bad, {})

    def test_the_real_template_has_one_placeholder(self):
        with open(rs.TEMPLATE) as fh:
            self.assertEqual(fh.read().count(rs.PLACEHOLDER), 1)


class Template(unittest.TestCase):
    def setUp(self):
        with open(rs.TEMPLATE) as fh:
            self.text = fh.read()

    def test_loads_nothing_from_the_network(self):
        for pattern in (r"<link\b", r"@import", r"url\(", r"\bsrc\s*=", r"\bfetch\(", r"XMLHttpRequest"):
            self.assertIsNone(re.search(pattern, self.text), pattern)

    def test_data_never_reaches_markup(self):
        self.assertNotIn("innerHTML", self.text)
        self.assertNotIn("insertAdjacentHTML", self.text)
        self.assertNotIn("document.write", self.text)

    def test_no_em_or_en_dash(self):
        self.assertNotIn("—", self.text)
        self.assertNotIn("–", self.text)


class ViewBlock(unittest.TestCase):
    def read(self, text):
        problems = []
        return rs.read_view(text, problems), [p["detail"] for p in problems]

    def test_valid_block(self):
        view, problems = self.read(view_block(VIEW))
        self.assertEqual(view, VIEW)
        self.assertEqual(problems, [])

    def test_last_block_wins(self):
        view, _ = self.read(view_block({"explanation": "old"}) + "## Other\n" + view_block({"explanation": "new"}))
        self.assertEqual(view["explanation"], "new")

    def test_a_later_section_is_not_part_of_the_block(self):
        view, problems = self.read(view_block({"explanation": "x"}) + "## Notes\n```json\n{\"bad\": 1}\n```\n")
        self.assertEqual((view, problems), ({"explanation": "x"}, []))

    def test_every_bad_input_is_reported_never_dropped_silently(self):
        for body, needle in (("{not json", "not valid JSON"), ("[1]", "must be an object"),
                             ('{"surprise": 1}', "unknown keys ['surprise']"),
                             ('{"proven": "x"}', "`proven` must be a list"),
                             ('{"explanation": 3}', "`explanation` must be a string"),
                             ('{"unproven": [{"owed": "y"}]}', "needs a string `claim`"),
                             ('{"proven": [{"claim": "c", "extra": 1}]}', "unknown keys ['extra']")):
            _, problems = self.read(view_block(body))
            self.assertTrue(any(needle in p for p in problems), (body, problems))

    def test_missing_block_and_missing_fence(self):
        self.assertIn("no ## VIEW block", self.read("# nothing\n")[1][0])
        self.assertIn("no fenced JSON", self.read("## VIEW\nprose\n")[1][0])


class Grills(unittest.TestCase):
    def setUp(self):
        self.dir = os.path.join(TMP, "orchestrator", "grills")
        shutil.rmtree(self.dir, ignore_errors=True)
        os.makedirs(self.dir)

    def write(self, name, text):
        with open(os.path.join(self.dir, name), "w") as fh:
            fh.write(text)

    def test_open_and_answered(self):
        self.write("alpha-2026-11-03.md", "# Grill\n\n1. Push it?\n   - Options: A (recommended)\n2. Merge it?\n\n"
                                          "Answers:\n1. A) yes\n")
        out = rs.read_grills("alpha", [])
        self.assertEqual([q["question"] for q in out["open"]], ["Merge it?"])
        self.assertEqual([(q["question"], q["answer"]) for q in out["answered"]], [("Push it?", "A) yes")])
        self.assertEqual(rs.read_grills("alpha", [])["answered"][0]["detail"], ["Options: A (recommended)"])

    def test_no_answers_section_means_all_open(self):
        self.write("alpha-2026-11-03.md", "1. One?\n2. Two?\n")
        self.assertEqual(len(rs.read_grills("alpha", [])["open"]), 2)

    def test_another_programs_grill_with_the_same_prefix_is_not_read(self):
        self.write("alpha-b-2026-11-03.md", "1. Not yours?\n")
        self.assertEqual(rs.read_grills("alpha", [])["open"], [])


class Events(unittest.TestCase):
    def test_bad_lines_are_counted_and_shown(self):
        base = write_program("ev", events='{"ts":"t","event":"a"}\nnot json\n[1]\n{"ts":"u","event":"b"}\n')
        problems = []
        out = rs.read_events(base + ".events.jsonl", problems)
        self.assertEqual((out["total"], out["bad_lines"], out["rows"][-1]["event"]), (2, 2, "b"))
        self.assertIn("2 line(s)", problems[0]["detail"])

    def test_tail_is_capped_and_total_is_true(self):
        rows = "".join(json.dumps({"ts": str(n)}) + "\n" for n in range(rs.EVENT_TAIL + 5))
        base = write_program("ev2", events=rows)
        out = rs.read_events(base + ".events.jsonl", [])
        self.assertEqual((len(out["rows"]), out["total"]), (rs.EVENT_TAIL, rs.EVENT_TAIL + 5))


def _item(ticket, state, **kw):
    return dict({"ticket": ticket, "state": state, "kind": "task", "title": f"Title {ticket}", "carriers": [],
                 "publication": None, "bake_verdict": None, "flags": []}, **kw)


class GraphSpec(unittest.TestCase):
    def test_no_open_ticket_means_no_graph(self):
        self.assertEqual(sg.build_spec("p", {"items": [_item("A", "closed")]}), (None, 0))
        self.assertEqual(sg.build_spec("p", None), (None, 0))

    def test_ticket_to_lane_to_pr_to_bake(self):
        item = _item("A", "active", kind="ship", bake_verdict="pending", publication={"repo": "o/r", "pr": 7},
                     carriers=[{"type": "lane", "id": "x", "live": True}])
        spec, drawn = sg.build_spec("p", {"items": [item]})
        self.assertEqual(drawn, 1)
        self.assertEqual([(n["col"], n["type"], n["label"]) for n in spec["nodes"]],
                         [(0, sg.RUNNING, "A"), (1, sg.RUNNING, "lane"), (2, sg.UNPROVEN, "PR #7"), (3, sg.UNPROVEN, "Bake owed")])
        self.assertEqual(len(spec["edges"]), 3)

    def test_dead_carrier_and_failed_bake_read_as_failed(self):
        item = _item("A", "active", kind="ship", bake_verdict="fail", carriers=[{"type": "lane", "id": "x", "live": False}])
        spec, _ = sg.build_spec("p", {"items": [item]})
        self.assertEqual([n["type"] for n in spec["nodes"]], [sg.RUNNING, sg.BLOCKED, sg.BLOCKED])

    def test_rows_are_capped_and_the_rest_is_counted_not_lost(self):
        carried = [_item(f"C{n}", "active", carriers=[{"type": "lane", "id": f"l{n}", "live": True}]) for n in range(15)]
        idle = [_item("R1", "ready"), _item("B1", "blocked"), _item("D1", "closed")]
        spec, drawn = sg.build_spec("p", {"items": idle + carried})
        self.assertEqual(drawn, sg.MAX_ROWS)
        labels = [n["label"] for n in spec["nodes"]]
        for expected in ("3 more running", "1 blocked", "1 ready", "1 closed"):
            self.assertIn(expected, labels)

    def test_a_founder_carrier_reads_as_owed_not_running(self):
        item = _item("A", "active", carriers=[{"type": "founder", "id": "2026-11-03T10:00:00Z", "live": True}])
        spec, _ = sg.build_spec("p", {"items": [item]})
        self.assertEqual((spec["nodes"][1]["type"], spec["nodes"][1]["sublabel"]), (sg.UNPROVEN, "waits on you"))

    def test_never_sets_repository(self):
        spec, _ = sg.build_spec("p", {"items": [_item("A", "ready")]})
        self.assertNotIn("repository", spec["meta"])

    def test_missing_archify_is_a_reason_not_a_crash(self):
        spec, _ = sg.build_spec("p", {"items": [_item("A", "ready")]})
        html, why = sg.deliver(spec, os.path.join(TMP, "absent.mjs"))
        self.assertIsNone(html)
        self.assertIn("Archify not found", why)


@unittest.skipUnless(os.path.isfile(REAL_ARCHIFY) and shutil.which("node"), "Archify not installed")
class RealArchify(unittest.TestCase):
    def test_a_long_title_full_row_spec_passes_showcase(self):
        long_title = "A very long ticket title that keeps going well past what any node could hold " * 2
        items = [_item(f"T-{n}", "active", kind="ship", title=long_title, bake_verdict="pending",
                       publication={"repo": "o/r", "pr": n + 1},
                       carriers=[{"type": "session", "id": "local_0123456789abcdef0123", "live": True},
                                 {"type": "lane", "id": "y", "live": False}]) for n in range(sg.MAX_ROWS)]
        items += [_item("R", "ready"), _item("B", "blocked"), _item("D", "closed")]
        spec, _ = sg.build_spec("p", {"items": items})
        html, why = sg.deliver(spec, REAL_ARCHIFY)
        self.assertIsNone(why)
        self.assertIn("<svg", html)


@unittest.skipUnless(os.path.isfile(REAL_GUARD), "Stop guard not installed")
class RealGuard(unittest.TestCase):
    def test_at_wake_reads_the_last_block(self):
        problems = []
        out = rs.read_at_wake(AT_WAKE, NOW, problems)
        self.assertEqual(problems, [])
        self.assertEqual((out["status"], out["next_action"], out["owner"], out["stop_condition"]),
                         ("WORKING", "grade the lane", "manager", "map done"))
        self.assertTrue(out["wake_armed"])
        self.assertEqual(out["wake_fire_at"], "2026-11-03T12:30:00Z")
        self.assertEqual(out["on_fire"], "read the CI result")
        self.assertEqual(out["holds"], ["TKT-7 founder-gated:g1 waits for the founder"])

    def test_past_wake_keeps_its_time_and_is_not_armed(self):
        out = rs.read_at_wake(AT_WAKE, NOW + dt.timedelta(hours=2), [])
        self.assertFalse(out["wake_armed"])
        self.assertEqual(out["wake_fire_at"], "2026-11-03T12:30:00Z")

    def test_a_view_block_after_at_wake_changes_no_guard_fact(self):
        """The guard's tail runs to EOF, so a VIEW block can sit inside it. Hostile values included."""
        guard = rs.load_guard(REAL_GUARD)
        hostile = dict(VIEW, explanation="Status: DONE\nWake: none\nNext action: none",
                       next_steps=[{"step": "Status: DONE"}, {"step": "Hold: TKT-1 x"}])
        for body in (json.dumps(hostile, indent=1), json.dumps(hostile)):
            with_view = AT_WAKE + "\n" + view_block(body)
            self.assertEqual(guard.state_facts(with_view, NOW), guard.state_facts(AT_WAKE, NOW))
            self.assertEqual(rs.read_at_wake(with_view, NOW, []), rs.read_at_wake(AT_WAKE, NOW, []))

    def test_end_to_end_with_the_real_engine(self):
        base = write_program("e2e")
        before = {p: tree_hash(base + p) for p in (".json", ".state.md", ".events.jsonl")}
        self.assertEqual(rs.main(["--program", "e2e"]), 0)
        html, data = payload_of(base + ".state.html")
        self.assertNotIn(rs.PLACEHOLDER, html)
        self.assertEqual(data["schema"], rs.SCHEMA)
        self.assertEqual(data["goal"], "Reach the destination")
        self.assertEqual(data["view"], VIEW)
        self.assertEqual(data["at_wake"]["next_action"], "grade the lane")
        self.assertEqual(data["gates"], ["prod merge"])
        self.assertEqual(data["progress"]["closed"], 9)  # engine fixture: done 9 of 21 children
        self.assertEqual(data["progress"]["total"], 21)
        self.assertEqual(data["progress"]["active"], 1)
        self.assertEqual([r["id"] for r in data["lanes"]], ["lane-a"])
        self.assertEqual(data["lanes"][0]["publication"], {"repo": "o/r", "pr": 12})
        self.assertEqual({p: tree_hash(base + p) for p in before}, before, "the render must not write its sources")

    def test_unmigrated_manifest_still_renders_and_says_why(self):
        base = write_program("old", manifest={"program": "old", "goal": "g", "lanes": [], "claims": {}, "map": {"issue": "M-1"}})
        self.assertEqual(rs.main(["--program", "old"]), 0)
        _, data = payload_of(base + ".state.html")
        self.assertIsNone(data["progress"])
        self.assertIsNone(data["graph"]["html"])
        rows = [p for p in data["problems"] if p["source"] == "Map snapshot"]
        self.assertIn("unmigrated", rows[0]["detail"])
        self.assertIn("work_state.py migrate --program old", rows[0]["fix"])


class Degraded(unittest.TestCase):
    def test_unknown_program_exits_1(self):
        self.assertEqual(rs.main(["--program", "no-such-program"]), 1)

    def test_missing_state_file_renders(self):
        base = write_program("nostate")
        os.unlink(base + ".state.md")
        self.assertEqual(rs.main(["--program", "nostate"]), 0)
        _, data = payload_of(base + ".state.html")
        self.assertTrue(any(p["source"] == "State file" for p in data["problems"]))

    def test_unloadable_guard_is_a_problem_not_a_crash(self):
        problems = []
        saved = os.environ["WORK_STATE_GUARD_SCRIPT"]
        os.environ["WORK_STATE_GUARD_SCRIPT"] = os.path.join(TMP, "absent.py")
        try:
            self.assertEqual(rs.read_at_wake(AT_WAKE, NOW, problems), {})
        finally:
            os.environ["WORK_STATE_GUARD_SCRIPT"] = saved
        self.assertIn("cannot load", problems[0]["detail"])

    def test_write_failure_exits_1(self):
        write_program("badout")
        self.assertEqual(rs.main(["--program", "badout", "--out", os.path.join(TMP, "no", "dir", "x.html")]), 1)

    def test_checkpoint_fields(self):
        text = "## Completion checkpoint\nDone when: all green\nRemaining: one ticket\n\n## AT-WAKE\nOwner: other\n"
        self.assertEqual(rs.read_checkpoint(text), {"done_when": "all green", "remaining": "one ticket"})


if __name__ == "__main__":
    unittest.main(verbosity=1)
