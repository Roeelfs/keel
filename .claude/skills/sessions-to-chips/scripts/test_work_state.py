#!/usr/bin/env python3
"""Hermetic tests for work_state.py (R37). No network, no real store: every path is a temp dir.

Run: python3 -m pytest -q test_work_state.py   (or python3 -I test_work_state.py)
"""
import copy
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

TMP = tempfile.mkdtemp(prefix="work-state-test-")
os.environ.update({"S2C_CLAUDE_HOME": TMP, "S2C_STORE": os.path.join(TMP, "store"),
                   "S2C_SESSION_INDEX": os.path.join(TMP, "index.json"),
                   "WORK_STATE_PROGRAMS": os.path.join(TMP, "programs"),
                   "WORK_STATE_DIR": os.path.join(TMP, "ws"), "WORK_STATE_LANE_ROWS": os.path.join(TMP, "lanes.jsonl"),
                   "WORK_STATE_ANALYTICS": os.path.join(TMP, "analytics.jsonl"),
                   "WORK_STATE_GUARD_SCRIPT": os.path.join(TMP, "no-guard.py")})
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import program_family as pf  # noqa: E402
import work_state as ws  # noqa: E402
import work_state_migrate as wm  # noqa: E402
import work_state_sources as src  # noqa: E402
import work_state_store as st  # noqa: E402

FIX = os.path.join(HERE, "fixtures", "work_state")
# The producer's own de-identified `linear-map.mjs snapshot --fixture` output (contract work-state-tracker/1),
# copied verbatim, never hand-edited (R19). Scenario rows below are cloned from its child row shape.
REAL = json.load(open(os.path.join(FIX, "linear-map-snapshot.fixture.json")))
STATE_NAMES = {"backlog": "Backlog", "unstarted": "Todo", "started": "In Progress", "completed": "Done",
               "canceled": "Canceled", "duplicate": "Duplicate"}


def tstate(stype):
    return {"type": stype, "name": STATE_NAMES[stype]}


def child(ticket, order, title, stype, kind, blocked_by=(), errors=(), inferred=False):
    """One child in the real producer row shape: blocked_by = [(ticket, state type|None)]."""
    c = copy.deepcopy(REAL["children"][0])
    c.update(ticket=ticket, order=order, title=title, state=tstate(stype), kind=kind, kind_inferred=inferred,
             blocked_by=[{"ticket": t, "state": None if s is None else tstate(s)} for t, s in blocked_by],
             blocks=[], errors=list(errors))
    return c


def tracker_of(children):
    kids = {c["ticket"]: c for c in children}
    for c in children:  # the inverse relation, as the producer emits it
        for b in c["blocked_by"]:
            if b["ticket"] in kids:
                kids[b["ticket"]]["blocks"].append({"ticket": c["ticket"], "state": copy.deepcopy(c["state"])})
    return dict(copy.deepcopy(REAL), map=dict(REAL["map"], ticket="M-1"), children=children,
                children_count=len(children))


TRACKER = tracker_of([
    child("T-1", 0, "Ship A", "completed", "ship"),
    child("T-2", 1, "Bake: Ship A", "unstarted", "bake", [("T-1", "completed")]),
    child("T-3", 2, "Ship B (stacked on C)", "backlog", "ship", [("T-4", "started")]),
    child("T-4", 3, "Ship C", "started", "ship"),
    child("T-5", 4, "Research", "unstarted", "task", [("X-99", None)], inferred=True),
    child("T-6", 5, "Grill: a founder ruling", "unstarted", "grill"),
    child("T-7", 6, "Two work labels", "unstarted", None, errors=["kind_conflict"]),
    child("T-8", 7, "Duplicate", "duplicate", "task"),
    child("T-9", 8, "Task after research", "backlog", "task", [("T-5", "unstarted")]),
])
GH_ROWS = json.load(open(os.path.join(FIX, "gh_pr_list.provisional.json")))["rows"]
SESSION_ROWS = json.load(open(os.path.join(FIX, "session_index_rows.json")))["rows"]
NOW = st.parse_iso("2026-11-03T12:00:00Z")


def iso(delta):
    return st.now_iso(NOW + delta)


def binding(ticket, carriers=(), **kw):
    b = {"ticket": ticket, "carriers": list(carriers), "bound_at": kw.pop("bound_at", iso(-60)), "bake": "required"}
    b.update(kw)
    return b


def carrier(t, cid, **kw):
    return dict({"type": t, "id": cid, "bound_at": iso(-60)}, **kw)


def ctx(**kw):
    base = {"now": NOW, "slug": "p", "map_id": "M-1", "absorbed": False, "bindings": [],
            "tracker": copy.deepcopy(TRACKER), "tracker_age_s": 10, "has_tracker_cmd": True, "prs": {},
            "gh_age_s": None, "sessions": {}, "cli": {}, "family_sessions": set(), "manager_ids": {"cli-M"},
            "lanes": {}, "pids": {}, "outfiles": {}, "git": {}, "state": {}, "live_bg": set(), "fp_cache": {},
            "ready_since": {}, "floor": 0, "pending_events": [], "notes": []}
    base.update(kw)
    return base


def snap(**kw):
    return ws.derive(ctx(**kw))[0]


def items(s):
    return {i["ticket"]: i for i in s["items"]}


def flagged(s, flag):
    return [x["item"] for x in s["flags"][flag]]


def session_row(i=1, **kw):
    r = dict(SESSION_ROWS[i], isArchived=False, lastActivityAt=str(int((NOW - 60) * 1000)))
    r.update(kw)
    return r


class DerivedStates(unittest.TestCase):
    def test_each_state_from_the_fixture(self):
        it = items(snap())
        self.assertEqual(it["T-1"]["state"], "closed")
        self.assertEqual(it["T-8"]["state"], "closed")  # duplicate is closed
        self.assertEqual(it["T-2"]["state"], "ready")  # its only blocker is the closed ship
        self.assertEqual(it["T-3"]["state"], "ready")  # R6: ship -> ship does not block dispatch
        self.assertEqual(it["T-5"]["state"], "blocked")  # R6: an unknown outside-map blocker counts open
        self.assertEqual(it["T-9"]["state"], "blocked")
        it = items(snap(bindings=[binding("T-6", [carrier("founder", iso(-30))])]))
        self.assertEqual(it["T-6"]["state"], "active")

    def test_backlog_never_parks_a_ticket(self):  # R8a
        s = snap()
        self.assertIn("T-3", flagged(s, "READY_NOT_DISPATCHED"))

    def test_started_unbound_is_unbound_never_ready(self):  # R8b
        s = snap()
        self.assertIn("T-4", flagged(s, "UNBOUND"))
        self.assertNotIn("T-4", flagged(s, "READY_NOT_DISPATCHED"))

    def test_kind_conflict_is_listed_never_dispatched(self):  # K2
        s = snap()
        self.assertNotIn("T-7", flagged(s, "READY_NOT_DISPATCHED"))
        self.assertIn("kind_conflict:T-7", s["notes"])

    def test_kind_missing_without_conflict_is_still_dispatched(self):  # K2: only kind_conflict waits
        t = copy.deepcopy(TRACKER)
        t["children"].append(child("T-10", 9, "Unlabelled work", "unstarted", None))
        s = snap(tracker=t)
        self.assertIn("T-10", flagged(s, "READY_NOT_DISPATCHED"))
        self.assertIn("kind_missing:T-10", s["notes"])
        self.assertNotIn("T-7", flagged(s, "READY_NOT_DISPATCHED"))

    def test_frontier_and_map_line(self):
        s = snap()
        self.assertEqual(s["frontier"], ["T-2", "T-3", "T-4", "T-6", "T-7"])
        self.assertTrue(s["map_line"].startswith("Map M-1: done 2 / open 7 / blocked 2; frontier now: T-2"))

    def test_relations_truncated_is_never_ready(self):  # R20: never truncate silently
        t = copy.deepcopy(TRACKER)
        next(c for c in t["children"] if c["ticket"] == "T-6")["errors"] = ["relations_truncated"]
        s = snap(tracker=t)
        self.assertEqual(items(s)["T-6"]["state"], "blocked")
        self.assertNotIn("T-6", flagged(s, "READY_NOT_DISPATCHED"))
        self.assertIn("relations_truncated:T-6", s["notes"])


class RealProducerFixture(unittest.TestCase):  # R19: the producer's own output, not a hand-written shape
    def test_scenario_rows_have_exactly_the_producer_keys(self):
        for c in TRACKER["children"]:
            self.assertEqual(set(c), set(REAL["children"][0]))
        self.assertEqual(set(TRACKER), set(REAL))

    def test_the_real_snapshot_derives(self):
        ws.check_tracker_schema(REAL)
        s = snap(tracker=copy.deepcopy(REAL), map_id=REAL["map"]["ticket"])
        self.assertEqual(s["children_count"], 21)
        self.assertTrue(s["map_line"].startswith("Map TKT-1: done 9 / open 12 / blocked 0"))
        self.assertEqual(flagged(s, "UNBOUND"), ["TKT-22"])  # started, unbound
        self.assertEqual(len(flagged(s, "READY_NOT_DISPATCHED")), 11)
        self.assertTrue(all(i["kind_inferred"] for i in s["items"]))
        self.assertEqual([n for n in s["notes"] if n.startswith(("kind_", "relations_", "labels_"))], [])


class Flags(unittest.TestCase):
    def test_ready_not_dispatched_blocks_and_binding_clears_it(self):
        s = snap()
        self.assertIn({"item": "T-6", "flag": "READY_NOT_DISPATCHED"},
                      [{"item": b["item"], "flag": b["flag"]} for b in s["blocking"]])
        s = snap(bindings=[binding("T-6", [carrier("founder", iso(-30))])])
        self.assertNotIn("T-6", flagged(s, "READY_NOT_DISPATCHED"))

    def test_unbound_live_child_session_lane_and_pr(self):
        row = session_row(1)
        lane = {"lane": "L1", "parent": "cli-M", "pid": 4242, "pid_start": "Mon Nov  3 10:00:00 2026",
                "outfile": "", "ts": iso(-300)}
        prs = {"owner/repo#104": GH_ROWS[3]}
        s = snap(sessions={row["sessionId"]: row}, family_sessions={row["sessionId"]},
                 lanes={"L1": lane}, pids={4242: "Mon Nov 3 10:00:00 2026"}, prs=prs)
        u = flagged(s, "UNBOUND")
        self.assertIn(row["sessionId"], u)
        self.assertIn("L1", u)
        self.assertIn("owner/repo#104", u)  # an open PR on a carrier's written branch
        # bound: the session and the lane drop out
        b = binding("T-6", [carrier("session", row["sessionId"]), carrier("lane", "L1", pid=4242)])
        s = snap(sessions={row["sessionId"]: row}, family_sessions={row["sessionId"]}, lanes={"L1": lane},
                 pids={4242: "Mon Nov 3 10:00:00 2026"}, bindings=[b])
        self.assertEqual([x for x in flagged(s, "UNBOUND") if x in (row["sessionId"], "L1")], [])

    def test_unbound_respects_the_migration_floor_and_finished_children(self):
        row = session_row(1)
        s = snap(sessions={row["sessionId"]: row}, family_sessions={row["sessionId"]}, floor=NOW)
        self.assertNotIn(row["sessionId"], flagged(s, "UNBOUND"))
        done = session_row(5)  # a fresh `completed` category: the turn ended, not live
        s = snap(sessions={done["sessionId"]: done}, family_sessions={done["sessionId"]})
        self.assertNotIn(done["sessionId"], flagged(s, "UNBOUND"))

    def test_lane_pid_reuse_is_not_liveness(self):
        lane = {"lane": "L1", "parent": "cli-M", "pid": 4242, "pid_start": "Mon Nov  3 10:00:00 2026", "outfile": "",
                "ts": iso(-300)}
        s = snap(lanes={"L1": lane}, pids={4242: "Tue Nov 4 01:00:00 2026"})
        self.assertNotIn("L1", flagged(s, "UNBOUND"))

    def test_no_map_is_unbound_create_the_map(self):
        s = snap(map_id=None, tracker=None)
        self.assertEqual(s["blocking"][0]["fix"], "create the map")

    def test_stalled_a_b_c(self):
        dead = binding("T-6", [carrier("lane", "L9", pid=1)])
        self.assertIn("T-6", flagged(snap(bindings=[dead]), "STALLED"))  # (a)
        empty = binding("T-6", bound_at=iso(-700))
        self.assertTrue(snap(bindings=[empty])["flags"]["STALLED"][0]["why"].startswith("c:"))  # (c)
        fresh = binding("T-6", bound_at=iso(-100))
        self.assertEqual(flagged(snap(bindings=[fresh]), "STALLED"), [])
        live = binding("T-6", [carrier("lane", "L1", pid=7, pid_start="X")], worktree="/wt")
        c = dict(bindings=[live], pids={7: "X"}, lanes={"L1": {"lane": "L1", "worktree": "/wt", "pid": 7}},
                 git={"/wt": {"head": "abc", "paths": []}})
        s1, parts = ws.derive(ctx(**c))
        self.assertEqual(flagged(s1, "STALLED"), [])
        old = {"T-6": dict(parts["fp"]["T-6"], since=NOW - 6000)}
        self.assertTrue(snap(fp_cache=old, **c)["flags"]["STALLED"][0]["why"].startswith("b:"))  # (b)
        moved = dict(c, git={"/wt": {"head": "def", "paths": []}})
        self.assertEqual(flagged(snap(fp_cache=old, **moved), "STALLED"), [])

    def test_awaiting_manager_is_never_stalled(self):  # R10
        row = session_row(4)
        b = binding("T-6", [carrier("session", row["sessionId"])])
        s = snap(bindings=[b], sessions={row["sessionId"]: row})
        self.assertEqual(flagged(s, "STALLED"), [])
        self.assertEqual(s["awaiting_manager"][0]["category"], "review_ready")
        closed = binding("T-6", [carrier("lane", "L9", pid=1)], publication={"repo": "owner/repo", "pr": 103})
        s = snap(bindings=[closed], prs={"owner/repo#103": GH_ROWS[2]})
        self.assertEqual(s["awaiting_manager"][0]["category"], "pr_closed")
        self.assertEqual(flagged(s, "STALLED"), [])

    def test_card_and_founder_never_stall(self):
        for c in (carrier("card", "task_1"), carrier("founder", iso(-3600))):
            self.assertEqual(flagged(snap(bindings=[binding("T-6", [c])]), "STALLED"), [])

    def test_bake_owed_once_per_publication_then_cleared(self):  # R12
        t = copy.deepcopy(TRACKER)
        t["children"] = [c for c in t["children"] if c["ticket"] != "T-2"]
        ship = binding("T-1", publication={"repo": "owner/repo", "pr": 101})
        prs = {"owner/repo#101": GH_ROWS[0]}
        s = snap(tracker=t, bindings=[ship], prs=prs)
        self.assertEqual(flagged(s, "BAKE_OWED"), ["T-1"])
        self.assertEqual(s["flags"]["BAKE_OWED"][0]["publication"], "owner/repo#101")
        self.assertEqual(flagged(snap(bindings=[ship], prs=prs), "BAKE_OWED"), [])  # open bake child exists
        none = dict(ship, bake="none:docs-only")
        self.assertEqual(flagged(snap(tracker=t, bindings=[none], prs=prs), "BAKE_OWED"), [])
        push = binding("T-1", publication={"repo": "owner/keel", "sha": "a" * 40, "via": "push"})
        self.assertEqual(flagged(snap(tracker=t, bindings=[push]), "BAKE_OWED"), ["T-1"])

    def test_stale_open_when_the_bound_artifact_landed(self):  # CYN-3366 Ship 2
        merged = binding("T-4", publication={"repo": "owner/repo", "pr": 101})
        s = snap(bindings=[merged], prs={"owner/repo#101": GH_ROWS[0]})
        self.assertEqual(flagged(s, "STALE_OPEN"), ["T-4"])
        self.assertIn("owner/repo#101", s["flags"]["STALE_OPEN"][0]["fix"])
        self.assertIn("STALE_OPEN", items(s)["T-4"]["flags"])
        self.assertNotIn("STALE_OPEN", [b["flag"] for b in s["blocking"]])  # never blocks
        push = binding("T-4", publication={"repo": "owner/keel", "sha": "a" * 40, "via": "push"})
        self.assertEqual(flagged(snap(bindings=[push]), "STALE_OPEN"), ["T-4"])
        opened = binding("T-4", publication={"repo": "owner/repo", "pr": 102})
        self.assertEqual(flagged(snap(bindings=[opened], prs={"owner/repo#102": GH_ROWS[1]}), "STALE_OPEN"), [])
        done = binding("T-1", publication={"repo": "owner/repo", "pr": 101})  # Done ticket: not stale
        self.assertEqual(flagged(snap(bindings=[done], prs={"owner/repo#101": GH_ROWS[0]}), "STALE_OPEN"), [])

    def test_duplicate_title_under_one_map(self):
        t = copy.deepcopy(TRACKER)
        t["children"] += [child("T-10", 9, "ship  c", "unstarted", "ship"),
                          child("T-11", 10, "Research", "canceled", "task")]  # canceled never counts
        s = snap(tracker=t)
        self.assertEqual(flagged(s, "DUPLICATE_TITLE"), ["T-10"])
        self.assertEqual(s["flags"]["DUPLICATE_TITLE"][0]["duplicate_of"], "T-4")
        self.assertEqual(flagged(snap(), "DUPLICATE_TITLE"), [])
        t["children"] += [child("T-12", 11, "Ship A", "completed", "ship")]  # both copies Done: no flag
        self.assertEqual(flagged(snap(tracker=t), "DUPLICATE_TITLE"), ["T-10"])

    def test_bake_verdict_from_the_bake_ticket(self):  # R17, R18
        t = copy.deepcopy(TRACKER)
        bake = next(c for c in t["children"] if c["ticket"] == "T-2")
        bake["state"] = tstate("completed")
        self.assertEqual(items(snap(tracker=t))["T-1"]["bake_verdict"], "pass")
        bake["state"] = tstate("canceled")
        self.assertEqual(items(snap(tracker=t))["T-1"]["bake_verdict"], "fail")
        t["children"].append(child("T-10", 9, "Ship D", "unstarted", "ship", [("T-1", "completed")]))
        it = items(snap(tracker=t, bindings=[binding("T-10", [carrier("founder", iso(-1))], carve_out=True)]))
        self.assertEqual(it["T-10"]["predecessor_verdicts"][0], {"ticket": "T-1", "bake_verdict": "fail",
                                                                  "bake_ticket": "T-2"})


def pr_row(**kw):
    return dict({"number": 9, "state": "OPEN", "isDraft": False, "headRefOid": "abc", "statusCheckRollup": [],
                 "reviewDecision": "APPROVED", "mergeStateStatus": "CLEAN", "_age_s": 5.0}, **kw)


class PrReadiness(unittest.TestCase):  # a draft never reads ready; a block reason is never carried forward
    PUB = {"repo": "o/r", "pr": 9}

    def view(self, **kw):
        return ws.pr_view(self.PUB, {"o/r#9": pr_row(**kw)})

    def test_clean_is_ready(self):
        self.assertEqual((self.view()["readiness"], self.view()["draft"]), ("ready", False))

    def test_draft_is_never_ready(self):
        v = self.view(isDraft=True, mergeStateStatus="CLEAN")
        self.assertEqual((v["readiness"], v["draft"]), ("draft", True))
        self.assertEqual(self.view(isDraft=None)["readiness"], "unknown")  # not read is not "not a draft"

    def test_block_reasons_are_derived_from_this_read(self):
        v = self.view(statusCheckRollup=[{"name": "e2e", "status": "COMPLETED", "conclusion": "FAILURE"}],
                      mergeStateStatus="BLOCKED")
        self.assertEqual((v["readiness"], v["why"]), ("blocked", "checks failing: e2e"))
        self.assertEqual(self.view(mergeStateStatus="DIRTY")["why"], "merge conflict")
        self.assertEqual(self.view(reviewDecision="CHANGES_REQUESTED")["why"], "changes requested")
        self.assertEqual(self.view(mergeStateStatus="UNKNOWN")["readiness"], "unknown")

    def test_a_stale_read_says_unknown_never_the_old_reason(self):
        v = self.view(_age_s=src.TTL["gh"] + 1, mergeStateStatus="BLOCKED",
                      statusCheckRollup=[{"name": "e2e", "conclusion": "FAILURE", "status": "COMPLETED"}])
        self.assertEqual(v["readiness"], "unknown")
        self.assertNotIn("e2e", v["why"])
        self.assertEqual(self.view(_age_s=None)["readiness"], "unknown")
        self.assertEqual(ws.pr_view(self.PUB, {})["readiness"], "unknown")
        self.assertIsNone(ws.pr_view({"repo": "o/r", "sha": "abc"}, {}))

    def test_snapshot_items_carry_it(self):
        b = binding("T-6", [carrier("session", "s1")], publication=dict(self.PUB))
        s = snap(bindings=[b], prs={"o/r#9": pr_row(isDraft=True)})
        self.assertEqual(items(s)["T-6"]["pr"]["readiness"], "draft")

    def test_load_gh_stamps_each_row_with_its_read_age(self):
        cache = {"gh": {"o/r": {"fetched_at": NOW - 900, "data": [pr_row()]}}}
        prs, _, _ = src.load_gh("p", [binding("T-6", publication=dict(self.PUB))], cache, NOW, offline=True)
        self.assertEqual(prs["o/r#9"]["_age_s"], 900)
        self.assertEqual(ws.pr_view(self.PUB, prs)["readiness"], "unknown")
        self.assertIn("isDraft", src.GH_FIELDS)


class Holds(unittest.TestCase):
    def hold(self, ticket, reason, *args, **kw):
        return snap(state=dict({"holds": [{"ticket": ticket, "reason": reason, "args": list(args)}]}, **kw.pop("state", {})),
                    **kw)

    def test_file_collision(self):
        other = binding("T-4", [carrier("founder", iso(-1))], paths=["src/a/**"])
        s = self.hold("T-6", "file-collision:T-4", "src/a/b.py", bindings=[other])
        self.assertNotIn("T-6", flagged(s, "READY_NOT_DISPATCHED"))
        s = self.hold("T-6", "file-collision:T-4", "docs/x.md", bindings=[other])
        self.assertIn("T-6", flagged(s, "READY_NOT_DISPATCHED"))
        s = self.hold("T-6", "file-collision:T-4", bindings=[other])  # no paths named
        self.assertIn("T-6", flagged(s, "READY_NOT_DISPATCHED"))

    def test_completion_mode(self):
        s = self.hold("T-6", "completion-mode", state={"mode": "completion"})
        self.assertNotIn("T-6", flagged(s, "READY_NOT_DISPATCHED"))
        s = self.hold("T-6", "completion-mode")
        self.assertIn("T-6", flagged(s, "READY_NOT_DISPATCHED"))

    def test_founder_gated(self):
        grill = binding("T-6", [carrier("founder", iso(-10))])
        s = self.hold("T-3", "founder-gated:T-6", bindings=[grill])
        self.assertNotIn("T-3", flagged(s, "READY_NOT_DISPATCHED"))
        s = self.hold("T-3", "founder-gated:T-6")  # the grill is not bound to a founder carrier
        self.assertIn("T-3", flagged(s, "READY_NOT_DISPATCHED"))

    def test_non_map_ticket_and_unknown_reason_are_invalid(self):
        s = self.hold("Z-1", "completion-mode")
        self.assertIn("hold_invalid:Z-1:not_a_map_ticket", s["notes"])
        s = self.hold("T-6", "heavy-lock")
        self.assertFalse(s["holds"][0]["valid"])


class Exemptions(unittest.TestCase):  # R29
    def test_done_exempts_only_with_zero_open_children(self):
        self.assertTrue(snap(state={"status": "DONE"})["blocking"])
        t = copy.deepcopy(TRACKER)
        for c in t["children"]:
            c["state"] = tstate("completed")
        self.assertEqual(snap(tracker=t, state={"status": "DONE"})["blocking"], [])

    def test_grilling_unheld_ready_still_blocks(self):
        s = snap(state={"status": "GRILLING"})
        self.assertIn("T-6", [b["item"] for b in s["blocking"]])

    def test_stale_tracker_drops_ready_keeps_unbound(self):
        s = snap(tracker_age_s=7300)
        flags = {b["flag"] for b in s["blocking"]}
        self.assertEqual(flags, {"UNBOUND"})
        self.assertTrue(any(n.startswith("ready_dropped:") for n in s["notes"]))

    def test_absorbed_program_gets_no_ready(self):
        self.assertEqual(flagged(snap(absorbed=True), "READY_NOT_DISPATCHED"), [])


class Predicates(unittest.TestCase):
    def test_docs_only_bake_exempt(self):  # R15
        self.assertTrue(ws.docs_only(["docs/specs/x.md", "docs/img/a.png", "README.md"]))
        self.assertFalse(ws.docs_only(["docs/x.md", "src/a.py"]))
        self.assertFalse(ws.docs_only([".claude/skills/foo/SKILL.md"]))  # behavior-changing markdown
        self.assertFalse(ws.docs_only(["docs/agents/rules.md"]))
        self.assertFalse(ws.docs_only(["notes.md"], deny_globs=["notes.md"]))
        self.assertFalse(ws.docs_only([]))

    def test_bake_key_set_equals_merge_and_retire(self):  # R16
        keys = ws.bake_keys()
        self.assertEqual(keys, ["obligation", "deploy SHA", "environment", "command/journey", "test identity",
                                "human-step kit", "terminal assertion"])

    def test_session_live_and_awaiting(self):  # R9, R10
        r = session_row(1)
        self.assertTrue(pf.session_live(r, NOW, 14400))
        self.assertFalse(pf.session_live(dict(r, isArchived=True), NOW, 14400))
        self.assertFalse(pf.session_live(dict(r, lastActivityAt=str(int((NOW - 20000) * 1000))), NOW, 14400))
        a = session_row(5)
        self.assertFalse(pf.session_live(a, NOW, 14400))
        self.assertTrue(pf.awaiting_manager(a))
        stale = dict(a, postTurnSummaryFor="other")  # the category describes an older turn
        self.assertFalse(pf.awaiting_manager(stale))
        self.assertTrue(pf.session_live(stale, NOW, 14400))

    def test_paths_intersect(self):
        self.assertTrue(ws.paths_intersect(["a/b/**"], ["a/b/c.py"]))
        self.assertFalse(ws.paths_intersect(["a/b/**"], ["a/c/**"]))


class Validator(unittest.TestCase):
    def test_strict(self):
        st.validate_binding(binding("T-1"))
        for bad in (dict(binding("T-1"), kind="ship"), dict(binding("T-1"), bake="none:"),
                    dict(binding("T-1"), paths=["**"]), dict(binding("T-1"), lease_s="9"),
                    binding("T-1", [carrier("founder", "yesterday")]),
                    binding("T-1", [dict(carrier("lane", "L"), extra=1)]),
                    dict(binding("T-1"), publication={"repo": "o/r", "sha": "abc", "via": "push"})):
            with self.assertRaises(st.SchemaError):
                st.validate_binding(bad)
        with self.assertRaises(st.SchemaError):
            st.validate_bindings([binding("T-1", [carrier("lane", "L")]), binding("T-2", [carrier("lane", "L")])])


def write_manifest(slug, **kw):
    os.makedirs(st.PROGRAMS, exist_ok=True)
    m = dict({"program": slug, "goal": "g", "manager_session": "local_m1aaaaaa", "updated_at": iso(-60),
              "map": {"issue": "M-1", "snapshot_cmd": ["fake-tracker", "{map}"]}}, **kw)
    with open(st.manifest_path(slug), "w") as fh:
        json.dump(m, fh)
    return m


class FakeRunner:
    def __init__(self, tracker=None, rc=0, out=None, err=""):
        self.calls, self.tracker, self.rc, self.out, self.err = [], tracker, rc, out, err

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        res = type("R", (), {})()
        res.returncode, res.stdout, res.stderr = 0, "", ""
        if argv[0] == "fake-tracker":
            res.returncode, res.stderr = self.rc, self.err
            res.stdout = self.out if self.out is not None else json.dumps(self.tracker or TRACKER)
        elif argv[0] == "gh":
            res.stdout = json.dumps(GH_ROWS)
        return res

    def tracker_calls(self):
        return sum(1 for c in self.calls if c[0] == "fake-tracker")


class CacheAndCommands(unittest.TestCase):
    def setUp(self):
        self.slug = "p" + str(time.time_ns())
        write_manifest(self.slug)

    def test_ttl_hit_makes_zero_adapter_calls_and_bind_clears_ready_without_fetch(self):
        r = FakeRunner()
        s1, rc = ws.run_snapshot(self.slug, runner=r)
        self.assertEqual((r.tracker_calls(), rc), (1, 4))
        self.assertIn("T-6", flagged(s1, "READY_NOT_DISPATCHED"))
        st.bind(self.slug, "T-6", children={c["ticket"] for c in TRACKER["children"]}, map_id="M-1")
        s2, _ = ws.run_snapshot(self.slug, runner=r)
        self.assertEqual(r.tracker_calls(), 1)  # TTL hit: no adapter call
        self.assertNotIn("T-6", flagged(s2, "READY_NOT_DISPATCHED"))
        with open(src.ANALYTICS) as fh:
            rows = [json.loads(x) for x in fh]
        self.assertTrue(any(x.get("source") == "tracker" and x.get("x_complexity") == [238] for x in rows))

    def test_rate_limit_keeps_stale_and_emits_linear_reset(self):  # R25
        ws.run_snapshot(self.slug, runner=FakeRunner())
        cache = src.read_cache(self.slug)
        cache["tracker"]["fetched_at"] -= 1000
        src.write_cache(self.slug, cache)
        until = st.now_iso(time.time() + 120)
        r = FakeRunner(rc=4, out="", err=json.dumps({"error": "Linear rate limited (HTTP 429)", "code": 4,
                                                     "type": "rate_limited", "status": 429,
                                                     "rate_limited_until": until}) + "\n")
        s, _ = ws.run_snapshot(self.slug, runner=r)
        self.assertEqual(s["pending_events"][0], {"event": "linear-reset", "at": until})
        self.assertIn("T-6", flagged(s, "READY_NOT_DISPATCHED"))  # stale data kept
        s, _ = ws.run_snapshot(self.slug, runner=r)  # inside the window: no retry
        self.assertEqual(r.tracker_calls(), 1)

    def test_rate_limit_without_a_reset_header_waits_the_default(self):  # R25: else now + 600 s
        err = json.dumps({"error": "429", "code": 4, "type": "rate_limited", "status": 429, "rate_limited_until": None})
        before = time.time()
        s, _ = ws.run_snapshot(self.slug, runner=FakeRunner(rc=4, out="", err=err))
        at = st.parse_iso(s["pending_events"][0]["at"])
        self.assertGreaterEqual(at, before + src.DEFAULT_RESET_S - 2)
        self.assertIn("tracker_rate_limited", s["notes"])

    def test_other_adapter_errors_name_their_type_and_emit_no_reset(self):
        err = json.dumps({"error": "org urlKey is not cynap", "code": 3, "type": "refused"})
        s, _ = ws.run_snapshot(self.slug, runner=FakeRunner(rc=3, out="", err=err))
        self.assertIn("tracker_error:rc=3:refused", s["notes"])
        self.assertEqual(s["pending_events"], [])

    def test_schema_mismatch_fails_closed(self):  # R19
        bad = dict(TRACKER, schema="work-state-tracker/2")
        with self.assertRaises(ws.SchemaMismatch):
            ws.run_snapshot(self.slug, runner=FakeRunner(tracker=bad))

    def test_guard_mode_is_offline_and_exits_4(self):
        ws.run_snapshot(self.slug, runner=FakeRunner())
        r = FakeRunner()
        s, rc = ws.run_snapshot(self.slug, mode="guard", runner=r,
                                stdin_facts={"state_facts": {"status": "WORKING"}, "live_bg": []})
        self.assertEqual((rc, r.tracker_calls()), (4, 0))
        self.assertFalse(any(c[0] in ("gh", "git") for c in r.calls))

    def test_one_wake_carries_many_bindings(self):
        kids = {c["ticket"] for c in TRACKER["children"]}
        for t in ("T-3", "T-6"):
            st.bind(self.slug, t, children=kids, map_id="M-1")
            st.carrier(self.slug, t, "wake", "w-1")
        m = st.read_manifest(self.slug)
        self.assertEqual(sorted(b["ticket"] for b in m["bindings"] if any(c["id"] == "w-1" for c in b["carriers"])),
                         ["T-3", "T-6"])
        st.carrier(self.slug, "T-3", "lane", "L9")
        with self.assertRaises(st.SchemaError):
            st.carrier(self.slug, "T-6", "lane", "L9")  # a writer still sits in one binding
        st.retire(self.slug, "T-3", carrier_ids=["w-1"])
        self.assertTrue(any(c["id"] == "w-1" for b in st.read_manifest(self.slug)["bindings"]
                            if b["ticket"] == "T-6" for c in b["carriers"]))

    def test_bind_refusals_and_carrier_idempotence(self):  # R2
        kids = {c["ticket"] for c in TRACKER["children"]}
        with self.assertRaises(st.SchemaError):
            st.bind(self.slug, "Z-1", children=kids, map_id="M-1")
        with self.assertRaises(st.SchemaError):
            st.bind(self.slug, "T-6", children=kids, map_id="M-1", paths=["*"])
        st.bind(self.slug, "M-1", children=None, map_id="M-1")  # the map itself (R4)
        st.bind(self.slug, "T-6", children=kids, map_id="M-1")
        with self.assertRaises(st.SchemaError):
            st.bind(self.slug, "T-6", children=kids, map_id="M-1")
        st.bind(self.slug, "T-6", children=kids, map_id="M-1", cont=True, branch="feat/x")
        st.carrier(self.slug, "T-6", "lane", "L1", pid=1)
        _, notes = st.carrier(self.slug, "T-6", "lane", "L1", pid=1)
        self.assertIn("idempotent", notes[0])
        with self.assertRaises(st.SchemaError):
            st.carrier(self.slug, "M-1", "lane", "L1")  # one carrier, one open binding

    def test_retire_appends_the_whole_binding(self):  # R5
        st.bind(self.slug, "T-6", children={"T-6"}, map_id="M-1")
        st.retire(self.slug, "T-6", merge_sha="b" * 40, reason="done", allow=lambda b: (True, ""))
        with open(st.events_path(self.slug)) as fh:
            ev = json.loads(fh.readlines()[-1])
        self.assertEqual((ev["event"], ev["binding"]["ticket"], ev["merge_sha"]), ("binding-retired", "T-6", "b" * 40))
        st.bind(self.slug, "T-6", children={"T-6"}, map_id="M-1")
        with self.assertRaises(st.SchemaError):
            st.retire(self.slug, "T-6", allow=lambda b: (False, "not closed"))

    def test_retire_allow_keys_the_bake_child_by_ticket(self):  # R5: tracker children carry `ticket`, never `id`
        ws.run_snapshot(self.slug, runner=FakeRunner())  # warm the tracker cache: _retire_allow reads it (TTL hit)
        ship = {"ticket": "T-1", "publication": {"sha": "a" * 40}, "bake": "required", "carriers": []}
        ok, why = ws._retire_allow(self.slug)(ship)  # bake T-2 open and unbound
        self.assertFalse(ok)
        self.assertIn("bake ticket's binding", why)
        st.bind(self.slug, "T-2", children={c["ticket"] for c in TRACKER["children"]}, map_id="M-1")
        self.assertEqual(ws._retire_allow(self.slug)(ship), (True, ""))

    def test_unmigrated_manifest_fails(self):
        write_manifest(self.slug, lanes=[])
        with self.assertRaises(st.SchemaError):
            ws.run_snapshot(self.slug, runner=FakeRunner())

    def test_bake_body_emits_exactly_the_key_set(self):
        ws.run_snapshot(self.slug, runner=FakeRunner())
        body, keys = ws.bake_body(self.slug, "T-1")
        emitted = [ln.split("**")[1] for ln in body.splitlines() if ln.startswith("- **")]
        self.assertEqual(emitted, keys)

    def test_cli_exit_codes(self):
        env = dict(os.environ)
        p = subprocess.run([sys.executable, "-I", os.path.join(HERE, "work_state.py"), "guard", "--program", "nope"],
                           input="{}", capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(p.returncode, 1)


class LaneRows(unittest.TestCase):
    def test_offset_reader_ignores_legacy_rows(self):
        path = os.path.join(TMP, "lr.jsonl")
        cache = os.path.join(TMP, "lr-cache.json")
        with open(path, "w") as fh:
            fh.write(json.dumps({"lane": "old", "parent": "p", "ts": iso(-10)}) + "\n")
        st.append_lane_row("L1", "cli-M", "codex", "m", os.getpid(), "/o", "/wt", path=path, now=NOW)
        rows = st.read_lane_rows(path, cache, now=NOW)
        self.assertEqual(sorted(rows), ["L1"])
        self.assertTrue(rows["L1"]["pid_start"])
        st.append_lane_row("L2", "cli-M", "claude", "m", os.getpid(), "", "", path=path, now=NOW)
        self.assertEqual(sorted(st.read_lane_rows(path, cache, now=NOW)), ["L1", "L2"])


class Migration(unittest.TestCase):  # R36
    def test_plan(self):
        m = {"program": "p", "updated_at": iso(-60), "map": {"issue": "M-1"}, "claims": {"issues": ["T-6"]},
             "lanes": [{"name": "build T-6", "status": "running", "kind": "headless", "where": "feat/t6",
                        "artifact": "the PR", "model": "opus"},
                       {"name": "done thing", "status": "completed", "kind": "agent"},
                       {"name": "mystery", "status": "running", "kind": "codex"},
                       {"name": "x T-3", "status": "running", "stacked_on": "#5", "where": "local_abc12345-1"}]}
        p = wm.plan("p", m, state_text="## Owed\n- bake T-1 after deploy\n", children={"T-1", "T-3", "T-6"},
                    live_manager=True, now=NOW)
        self.assertEqual([b["ticket"] for b in p["manifest"]["bindings"]], ["T-6", "T-3"])
        self.assertNotIn("lanes", p["manifest"])
        self.assertNotIn("claims", p["manifest"])
        self.assertEqual(p["manifest"]["bindings"][1]["carriers"][0]["type"], "session")
        self.assertEqual(sorted(t["key"].split(":")[0] for t in p["todo"]), ["bake", "blocks", "ticket"])
        self.assertEqual(p["census"]["events_only"], 1)
        stale = wm.plan("p", dict(m, status="done"), children={"T-6"}, now=NOW)
        self.assertEqual((stale["census"]["bindings"], stale["census"]["events_only"]), (0, 4))

    def test_bake_todo_only_for_an_open_merged_ship_without_a_bake(self):
        t = tracker_of([child("T-1", 0, "Ship A", "completed", "ship"),
                        child("T-3", 1, "Ship B", "started", "ship"),
                        child("T-4", 2, "Ship C", "started", "ship"),
                        child("T-5", 3, "Ship D", "started", "ship"),
                        child("T-6", 4, "Research", "started", "task"),
                        child("T-8", 6, "Unlabelled ship", "started", "task", inferred=True),
                        child("T-7", 5, "Bake: Ship C", "unstarted", "bake", [("T-4", "started")])])
        m = {"program": "p", "updated_at": iso(-60), "map": {"issue": "M-1"},
             "bindings": [binding("T-5", publication={"repo": "o/r", "pr": 102})]}
        text = "## Owed\n- bake T-1, T-3, T-4, T-5, T-6, T-8\n"
        p = wm.plan("p", m, state_text=text, children={c["ticket"] for c in t["children"]}, tracker=t,
                    live_manager=True, now=NOW, gh_rows={"o/r#102": GH_ROWS[1]})
        self.assertEqual([x["key"] for x in p["todo"] if x["key"].startswith("bake:")], ["bake:T-3", "bake:T-8"])
        why = {x["ticket"]: x["why"] for x in p["bake_not_owed"]}
        self.assertEqual(sorted(why), ["T-1", "T-4", "T-5", "T-6"])
        self.assertIn("Done", why["T-1"])
        self.assertIn("T-7", why["T-4"])
        self.assertIn("not merged", why["T-5"])
        self.assertIn("not a ship", why["T-6"])
        self.assertEqual(p["census"]["bake_not_owed"], 4)
        self.assertEqual(p["census"]["bake_merge_unverified"], 2)  # open, but nothing shows the merge
        self.assertIn("UNVERIFIED", p["todo"][[x["key"] for x in p["todo"]].index("bake:T-8")]["do"])
        blind = wm.plan("p", m, state_text=text, children=None, live_manager=True, now=NOW)  # no tracker tier
        self.assertEqual(blind["census"]["bake_tickets_to_file"], 6)

    def test_a_relative_snapshot_cmd_needs_a_cwd(self):
        base = {"program": "p", "updated_at": iso(-60), "lanes": []}
        for map_, owed in (({"issue": "M-1", "snapshot_cmd": ["node", "tooling/linear-map.mjs", "snapshot", "--map", "{map}"]}, True),
                           ({"issue": "M-1", "snapshot_cmd": "node tooling/linear-map.mjs --map {map}", "snapshot_cwd": "/r"}, False),
                           ({"issue": "M-1", "snapshot_cmd": ["/abs/linear-map", "--map", "{map}"]}, False),
                           ({"issue": "M-1", "snapshot_cmd": ["fake-tracker", "{map}"]}, False)):
            p = wm.plan("p", dict(base, map=map_), now=NOW)
            self.assertEqual(("cwd:map" in [t["key"] for t in p["todo"]], p["census"]["snapshot_cwd_missing"]),
                             (owed, int(owed)), map_)
        p = wm.plan("p", dict(base, map={"issue": "M-1", "snapshot_cmd": ["node", "x/y.mjs"]}), now=NOW, resolved={"cwd:map"})
        self.assertNotIn("cwd:map", [t["key"] for t in p["todo"]])

    def test_real_migrate_writes_floor_event_first_and_refuses_open_todos(self):
        slug = "mig" + str(time.time_ns())
        write_manifest(slug, lanes=[{"name": "a", "status": "done"}], claims={"issues": []})
        res = wm.migrate_program(slug, rows={}, now=NOW)
        self.assertTrue(res["written"])
        with open(st.events_path(slug)) as fh:
            first = json.loads(fh.readline())
        self.assertEqual(first["event"], "migrated")
        self.assertIsNotNone(st.migration_floor(slug))
        slug2 = "mig2" + str(time.time_ns())
        write_manifest(slug2, lanes=[{"name": "no ticket", "status": "running"}])
        res = wm.migrate_program(slug2, rows={}, now=NOW)
        self.assertFalse(res["written"])
        self.assertIn("lanes", st.read_manifest(slug2))


class ProofFlagTests(unittest.TestCase):
    def test_three_failures_flag_context_and_pass_clears(self):
        import lane_proof
        import render_state
        import state_brief
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "proofs.jsonl")
            for _ in range(2):
                lane_proof.append({"ticket": "T-4", "outcome": "fail"}, path)
            def snapshot():
                return ws.derive(ctx(proof_failures=lane_proof.failure_counts(path)))[0]
            self.assertEqual(snapshot()["flags"]["PROOF_FAILED"], [])
            lane_proof.append({"ticket": "T-4", "outcome": "fail"}, path)
            snap = snapshot()
            self.assertEqual([x["item"] for x in snap["flags"]["PROOF_FAILED"]], ["T-4"])
            self.assertIn("PROOF_FAILED", next(i for i in snap["items"] if i["ticket"] == "T-4")["flags"])
            held = [r for r in render_state.flag_rows(snap)[0] if r["flag"] == "PROOF_FAILED"]
            self.assertIn("three or more failed proofs", state_brief.held_text(held[0]))
            lane_proof.append({"ticket": "T-4", "outcome": "deferred"}, path)
            self.assertTrue(snapshot()["flags"]["PROOF_FAILED"])
            lane_proof.append({"ticket": "T-4", "outcome": "pass"}, path)
            self.assertEqual(snapshot()["flags"]["PROOF_FAILED"], [])

    def test_mutation_control_wrong_threshold_is_detected(self):
        with open(ws.__file__) as fh:
            source = fh.read()
        self.assertIn("count >= 3", source)
        namespace = dict(vars(ws))
        exec(compile(source.replace("count >= 3", "count >= 4"), ws.__file__, "exec"), namespace)
        snap = namespace["derive"](ctx(proof_failures={"T-4": 3}))[0]
        with self.assertRaises(AssertionError):
            self.assertTrue(snap["flags"]["PROOF_FAILED"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
