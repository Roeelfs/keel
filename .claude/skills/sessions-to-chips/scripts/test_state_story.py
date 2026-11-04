#!/usr/bin/env python3
"""Tests for the page as the work: program names from the manager session, the `done` story joined to proof, the
not-yet-summarized list, and the --context brief (one payload, two renderings). Shares test_render_state's temp root
and fixtures, so the session store and programs dir are throwaway."""
import io
import json
import os
import unittest
from contextlib import redirect_stdout

import test_render_state as T  # sets the env before the engine modules import

import program_family as pf  # noqa: E402
import render_state as rs  # noqa: E402
import state_brief  # noqa: E402
import state_index as si  # noqa: E402
import state_story  # noqa: E402

STORE_DIR = os.path.join(T.TMP, "store", "acct", "org")
MANAGER_ID = "local_4242aaaa-0000-4000-8000-000000000001"


def write_manager_session(title, sid=MANAGER_ID, last="2026-11-03T11:00:00Z"):
    os.makedirs(STORE_DIR, exist_ok=True)
    with open(os.path.join(STORE_DIR, sid + ".json"), "w") as fh:
        json.dump({"sessionId": sid, "title": title, "lastActivityAt": last}, fh)


def ladder_row(pr, step, merged_at="2026-11-03T09:00:00Z", title="feat(x): a thing"):
    return {"pr": pr, "repo": T.REPO, "title": title, "merged_at": merged_at, "ladder": {"step": step}, "tickets": []}


class Names(unittest.TestCase):
    def test_display_title_strips_the_manager_prefix_and_fork_suffix(self):
        self.assertEqual(pf.display_title("[Manager] CAYP cutover (Access v2)"), "CAYP cutover (Access v2)")
        self.assertEqual(pf.display_title("[Manager] Cynap (fork)"), "Cynap")

    def test_the_page_and_index_carry_the_manager_session_title(self):
        manifest = None
        T.write_program("named")
        with open(os.path.join(T.PROGRAMS, "named.json")) as fh:
            manifest = json.load(fh)
        manifest["manager_session"] = MANAGER_ID
        with open(os.path.join(T.PROGRAMS, "named.json"), "w") as fh:
            json.dump(manifest, fh)
        write_manager_session("[Manager] CAYP cutover (Access v2)")
        rc, _ = T.render("named")
        self.assertEqual(rc, 0)
        _, data = T.payload_of(os.path.join(T.PROGRAMS, "named.state.html"))
        self.assertEqual(data["name"], "CAYP cutover (Access v2)")
        self.assertFalse([p for p in data["problems"] if p["source"] == "Name"])
        _, index = T.payload_of(os.path.join(T.PROGRAMS, "index.state.html"))
        row = next(r for r in index["rows"] if r["program"] == "named")
        self.assertEqual((row["name"], row["map"]["issue"]), ("CAYP cutover (Access v2)", "TKT-1"))

    def test_without_a_readable_session_the_manifest_title_is_used_and_one_problem_said(self):
        problems = []
        self.assertEqual(rs.program_name("p", {"title": "Apps"}, problems, titles={}), "Apps")
        self.assertEqual([p["source"] for p in problems], ["Name"])
        problems = []
        self.assertEqual(rs.program_name("p", {}, problems, titles={}), "p")
        self.assertEqual(len(problems), 1)
        self.assertIn("title", problems[0]["fix"])


class Story(unittest.TestCase):
    NOW = T.NOW

    def test_a_summary_asserting_more_than_its_proof_reads_as_a_claim(self):
        view = {"done": [{"date": "2026-11-03T10:00:00Z", "what": "Orders are live in production", "refs": ["#7"]},
                         {"date": "2026-11-03T09:00:00Z", "what": "Orders are accepted by the API", "refs": ["#7"]}]}
        rows = state_story.done_rows(view, [ladder_row(7, "merged")])
        self.assertEqual([(r["claim"], r["reached"]) for r in rows], [(True, "merged"), (False, "merged")])

    def test_a_change_with_nothing_to_expose_never_reads_as_live(self):
        row = dict(ladder_row(7, "exposed"), ladder={"step": "exposed", "steps": {"exposure": {"state": "n/a"}}})
        rows = state_story.done_rows({"done": [{"what": "It is live now", "refs": ["#7"]}]}, [row])
        self.assertEqual((rows[0]["reached"], rows[0]["claim"]), ("deployed", True))

    def test_merged_work_no_line_names_is_listed_as_not_summarized(self):
        view = {"done": [{"date": "2026-11-03T10:00:00Z", "what": "x", "refs": ["#7"]}],
                "design": [{"what": "spec", "ref": "#9"}]}
        pending = state_story.unsummarized(view, [ladder_row(7, "merged"), ladder_row(8, "merged"), ladder_row(9, "merged"),
                                                  dict(ladder_row(10, "open"), merged_at=None)], [])
        self.assertEqual([p["pr"] for p in pending], [8])

    def test_adopted_prs_are_not_asked_for_and_never_count_as_delivered(self):
        view = {"done": [{"date": "2026-11-03T10:00:00Z", "what": "x", "refs": ["#7"]}],
                "adopted": [{"refs": ["#8", "#9"], "note": "delivered by another program, adopted with the ticket"}]}
        rows = [ladder_row(7, "merged"), ladder_row(8, "merged"), ladder_row(9, "deployed"), ladder_row(10, "merged")]
        told = state_story.story(view, rows, [], [], self.NOW)
        self.assertEqual([p["pr"] for p in told["history"]["unsummarized"]], [10])
        self.assertEqual([d["what"] for d in told["history"]["done"]], ["x"])
        self.assertEqual([[r["pr"] for r in a["refs"]] for a in told["history"]["adopted"]], [[8, 9]])
        self.assertNotIn("adopted", told["now"])
        author = rs.author_line(view, [], [], [], {}, [], told["history"])
        self.assertTrue(any("#10" in a and "#8" not in a for a in author if a.startswith("done:")), author)

    def test_story_orders_newest_first_and_caps_now(self):
        view = {"done": [{"date": f"2026-11-0{d}T10:00:00Z", "what": f"w{d}", "refs": []} for d in range(1, 4)]}
        told = state_story.story(view, [], [], [], self.NOW)
        self.assertEqual([d["what"] for d in told["now"]["done"]], ["w3", "w2", "w1"])


class Brief(unittest.TestCase):
    def payload(self):
        T.write_program("brief")
        payload, _ = rs.build_payload("brief", T.NOW, run=T.GhFake())
        return payload

    def test_brief_reads_in_the_founders_order_and_ends_with_the_keys(self):
        text = state_brief.brief(self.payload())
        lines = text.splitlines()
        self.assertLessEqual(len(lines), state_brief.MAX_LINES)
        heads = [ln for ln in lines if ln.endswith(":") and not ln.startswith("-")]
        order = [h for h in ("Done recently:", "Architecture changes:", "Decisions in force:", "Next outcomes on the map:",
                             "Held by:", "Update in ## VIEW before ending the turn:") if h in heads]
        self.assertEqual(order, [h for h in heads if h in order])
        self.assertIn("Destination: The shop takes orders in production.", lines)
        self.assertIn("- done: summarize #7 (what changed for the product, and why)", lines)
        self.assertTrue(lines[-1].startswith("Then re-render: render_state.py --program brief"))
        self.assertNotIn("{", text, "no JSON in the brief")

    def test_the_bound_keeps_the_footer(self):
        body = [f"line {i}" for i in range(200)]
        out = state_brief._bound(body, ["Update in ## VIEW before ending the turn:", "- x", "Then re-render"])
        self.assertEqual(len(out), state_brief.MAX_LINES)
        self.assertEqual(out[-1], "Then re-render")

    def test_context_prints_the_brief_and_writes_no_page(self):
        T.write_program("ctx")
        page = os.path.join(T.PROGRAMS, "ctx.state.html")
        if os.path.exists(page):
            os.unlink(page)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = rs.main(["--program", "ctx", "--context"], run=T.GhFake())
        self.assertEqual(rc, 0)
        self.assertTrue(buf.getvalue().startswith("ctx (map TKT-1)"))
        self.assertFalse(os.path.exists(page))


class WorkerFlags(unittest.TestCase):
    def test_a_flag_on_a_worker_goes_to_the_footer_not_held_by(self):
        snap = {"blocking": [{"flag": "UNBOUND", "item": "CYN-1"}, {"flag": "UNBOUND", "item": "codex-dispatch-lane-x"}]}
        on_ticket, other = rs.flag_rows(snap)
        self.assertEqual(([r["id"] for r in on_ticket], [r["id"] for r in other]), (["CYN-1"], ["codex-dispatch-lane-x"]))


class Index(unittest.TestCase):
    def test_overlap_and_held_blockers_name_programs_by_their_title(self):
        self.assertEqual(si._held_text({"kind": "overlap", "program": "apps", "name": "Apps"}), "overlap:Apps")


if __name__ == "__main__":
    unittest.main()
