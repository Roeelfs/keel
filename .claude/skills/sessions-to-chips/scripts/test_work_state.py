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
import work_state_waiters as waiters  # noqa: E402

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

    def test_waiters_follow_relations_and_named_owners(self):
        tracker = tracker_of([
            child("T-1", 0, "Foundation", "completed", "task"),
            child("T-2", 1, "Consumer", "started", "task", [("T-1", "completed")]),
        ])
        tracker["children"][0]["blocks"].append({"ticket": "X-1", "state": tstate("started")})
        args = dict(tracker=tracker, bindings=[binding("T-2", [carrier("session", "consumer")])],
                    sessions={"consumer": {"title": "Consumer owner"}, "upstream": {"title": "Foundation owner"}},
                    programs=[{"program": "other", "map": {"issue": "X-1"}, "manager_session": "other-manager"}])
        before = copy.deepcopy(args)
        rows = snap(**args)["waiters"]
        self.assertEqual({(r["waiter"], r["blocker"]) for r in rows}, {("T-2", "T-1"), ("X-1", "T-1")})
        own = next(r for r in rows if r["waiter"] == "T-2")
        self.assertEqual(own["tell"], "Consumer owner (consumer)")
        self.assertIn("T-1 is completed", own["message"])
        self.assertEqual(next(r for r in rows if r["waiter"] == "X-1")["tell"], "other-manager")
        self.assertEqual(args, before)  # deriving must not write back to its owners

        # Mutation controls: reopen, name its owner, close the consumer, remove the edge.
        opened = copy.deepcopy(tracker)
        opened["children"][0]["state"] = tstate("started")
        opened["children"][1]["blocked_by"][0]["state"] = tstate("started")
        self.assertEqual(snap(**dict(args, tracker=opened, manager_session="manager"))["waiters"], [])
        named = args["bindings"] + [binding("T-1", [carrier("session", "upstream")])]
        row = snap(**dict(args, tracker=opened, bindings=named))["waiters"][0]
        self.assertEqual(row["tell"], "Foundation owner (upstream)")
        self.assertIn("T-2 waits on T-1", row["message"])
        unknown = copy.deepcopy(opened)
        unknown["children"][0]["state"] = None
        unknown["children"][1]["blocked_by"][0]["state"] = None
        self.assertEqual(snap(**dict(args, tracker=unknown))["waiters"], [])
        for ending in ("canceled", "duplicate"):
            ended = copy.deepcopy(tracker)
            ended["children"][0]["state"] = tstate(ending)
            row = snap(**dict(args, tracker=ended))["waiters"][0]
            self.assertIn(f"is {ending}", row["message"])
            self.assertNotIn("ready", row["message"])
        closed = copy.deepcopy(tracker)
        closed["children"][1]["state"] = tstate("completed")
        self.assertEqual([r["waiter"] for r in snap(**dict(args, tracker=closed))["waiters"]], ["X-1"])
        self.assertEqual(snap(tracker=tracker_of([child("T-2", 0, "Consumer", "started", "task")]))["waiters"], [])

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
        self.assertTrue(s["map_line"].endswith("; exit unset"))

    def test_exit_criteria_count_and_gate_done(self):
        exits = [{"outcome": "p95 under 2s", "proof": "trace.sh", "expected": "<2000", "green": True},
                 {"outcome": "zero refusals", "proof": "count.sql", "expected": "0", "green": None}]
        self.assertTrue(snap(exit_criteria=exits)["map_line"].endswith("; exit 1/2"))
        closed = copy.deepcopy(TRACKER)
        for c in closed["children"]:
            c["state"] = tstate("completed")
        done = snap(tracker=closed, state={"status": "DONE"}, exit_criteria=exits)
        self.assertIn("status_done_exit_not_green_1_of_2:no_exemption", done["notes"])
        self.assertNotIn("exempt:status_done_zero_open", done["notes"])
        exits[1]["green"] = True
        self.assertIn("exempt:status_done_zero_open", snap(tracker=closed, state={"status": "DONE"}, exit_criteria=exits)["notes"])
        unset = snap(tracker=closed, state={"status": "DONE"})
        self.assertIn("exit_criteria_unset", unset["notes"])

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

    def test_stale_open_when_the_bound_artifact_landed(self):  # TKT-3366 Ship 2
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

    def test_future_bake_hold_suppresses_ready_until_due(self):
        for due in ("2026-11-04", "2026-11-03T13:00:00Z"):
            s = self.hold("T-2", "awaiting-bake:" + due)
            self.assertNotIn("T-2", [x["item"] for x in s["blocking"]])
            self.assertTrue(s["holds"][0]["valid"])
            self.assertIn("T-6", [x["item"] for x in s["blocking"]])

    def test_bake_hold_accepts_date_argument(self):
        s = self.hold("T-2", "bake", "2026-11-04")
        self.assertTrue(s["holds"][0]["valid"])
        self.assertNotIn("T-2", [x["item"] for x in s["blocking"]])

    def test_bake_hold_does_not_hide_due_invalid_or_non_bake_work(self):
        for ticket, due in (("T-2", "2026-11-03"), ("T-2", "2026-11-03T12:00:00Z"),
                            ("T-2", ""), ("T-2", "later"), ("T-2", "2026-02-30"), ("T-6", "2026-11-04")):
            s = self.hold(ticket, "awaiting-bake:" + due)
            self.assertFalse(s["holds"][0]["valid"])
            self.assertIn(ticket, [x["item"] for x in s["blocking"]])

    def test_lane_whose_worktree_was_never_probed_does_not_crash(self):  # a folded lane
        c = carrier("lane", "L-fold")
        lanes = {"L-fold": {"pid": 1, "pid_start": "x", "outfile": "", "worktree": "/wt/folded"}}
        for git in ({}, {"/wt/folded": None}):  # a folded binding's worktree is absent from the probed map
            live, fp, _ = ws.carrier_state(c, ctx(lanes=lanes, git=git))
            self.assertFalse(live)
            self.assertIsNotNone(fp)

    def test_bake_carrier_has_a_valid_due_date_and_expires(self):
        c = carrier("bake", "2026-11-04T00:00:00Z")
        st.validate_carrier(c)
        self.assertTrue(ws.carrier_state(c, ctx())[0])
        self.assertFalse(ws.carrier_state(c, ctx(now=st.parse_iso(c["id"])))[0])
        before = snap(bindings=[binding("T-2", [c])])
        self.assertNotIn("T-2", [x["item"] for x in before["blocking"]])
        self.assertIn("T-6", [x["item"] for x in before["blocking"]])
        after = snap(bindings=[binding("T-2", [c])], now=st.parse_iso(c["id"]))
        self.assertIn("T-2", [x["item"] for x in after["flags"]["STALLED"]])
        with self.assertRaises(st.SchemaError):
            st.validate_carrier(carrier("bake", "later"))

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

    def test_guard_cli_skips_future_bake_hold_and_keeps_ready_work(self):
        ws.run_snapshot(self.slug, runner=FakeRunner())
        facts = {"state_facts": {"status": "WORKING", "holds": [
            {"ticket": "T-2", "reason": "bake", "args": ["2999-11-14"]}]}, "live_bg": []}
        result = subprocess.run([sys.executable, "-I", os.path.join(HERE, "work_state.py"),
                                 "guard", "--program", self.slug], input=json.dumps(facts),
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 4, result.stderr)
        snapshot = json.loads(result.stdout)
        self.assertNotIn("T-2", flagged(snapshot, "READY_NOT_DISPATCHED"))
        self.assertIn("T-6", flagged(snapshot, "READY_NOT_DISPATCHED"))
        self.assertTrue(snapshot["holds"][0]["valid"])

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


def notice_events(slug):
    try:
        with open(st.events_path(slug)) as fh:
            rows = [json.loads(x) for x in fh]
    except OSError:
        return []
    return [(r["waiter"], r["blocker"]) for r in rows if r.get("event") == "waiter-notice"]


class WaiterNotices(unittest.TestCase):  # a landed blocker tells each waiting item once per closure
    def setUp(self):
        self.slug = "n" + str(time.time_ns())
        write_manifest(self.slug)

    @staticmethod
    def tracker(stype):
        return tracker_of([child("T-1", 0, "Blocker", stype, "task"),
                           child("T-2", 1, "Waiter A", "started", "task", [("T-1", stype)]),
                           child("T-3", 2, "Waiter B", "started", "task", [("T-1", stype)])])

    def run_with(self, stype, mode="snapshot"):
        facts = {"state_facts": {}, "live_bg": []} if mode == "guard" else None
        s, _ = ws.run_snapshot(self.slug, mode=mode, refresh=True, stdin_facts=facts,
                               runner=FakeRunner(tracker=self.tracker(stype)))
        return sorted(w["waiter"] for w in s["waiters"] if w["notify"]), s

    def test_one_notice_per_waiter_per_closure(self):
        kids = {"T-1", "T-2", "T-3"}
        st.bind(self.slug, "T-1", children=kids, map_id="M-1")
        st.carrier(self.slug, "T-1", "session", "upstream")
        told, s = self.run_with("started")  # blocker still open: rows to its owner, no notice
        self.assertEqual((told, notice_events(self.slug)), ([], []))
        self.assertEqual(len(s["waiters"]), 2)
        self.assertEqual(self.run_with("completed")[0], ["T-2", "T-3"])
        self.assertEqual(sorted(notice_events(self.slug)), [("T-2", "T-1"), ("T-3", "T-1")])
        self.assertEqual(self.run_with("completed")[0], [])  # second run: already told
        self.assertEqual(len(notice_events(self.slug)), 2)
        self.assertEqual(self.run_with("started")[0], [])  # reopened: nothing to tell
        self.assertEqual(self.run_with("completed")[0], ["T-2", "T-3"])  # a new closure is a new transition
        self.assertEqual(len(notice_events(self.slug)), 4)

    def test_guard_mode_never_claims(self):
        cache = src.read_cache(self.slug)
        cache["tracker"] = {"data": self.tracker("completed"), "fetched_at": time.time()}
        src.write_cache(self.slug, cache)  # guard reads cached tiers only
        told, s = self.run_with("completed", mode="guard")
        self.assertEqual(sorted(w["waiter"] for w in s["waiters"] if w["closed"]), ["T-2", "T-3"])
        self.assertEqual((told, notice_events(self.slug)), ([], []))
        self.assertEqual(self.run_with("completed")[0], ["T-2", "T-3"])

    def test_a_merged_blocker_pr_tells_before_its_ticket_closes(self):
        t = self.tracker("started")
        bound = [binding("T-1", [carrier("session", "upstream")], publication={"repo": "o/r", "pr": 7})]
        merged = {"o/r#7": {"state": "MERGED", "mergedAt": iso(-30)}}
        rows = snap(tracker=t, bindings=bound, prs=merged)["waiters"]
        self.assertTrue(all(r["closed"] and "o/r#7 merged" in r["message"] for r in rows))
        self.assertEqual(sorted(r["waiter"] for r in rows), ["T-2", "T-3"])
        opened = snap(tracker=t, bindings=bound, prs={"o/r#7": {"state": "OPEN"}})["waiters"]
        self.assertFalse(any(r["closed"] for r in opened))

        def claim(prs, tracker=t):
            c = ctx(tracker=tracker, bindings=bound, prs=prs)
            return st.claim_notices(self.slug, waiters.notice_keys(ws.derive(c)[0]["waiters"]),
                                    waiters.still_told(c, ws.CLOSED))
        self.assertEqual(claim(merged), ["T-2|T-1", "T-3|T-1"])
        self.assertEqual(claim({}), [])  # gh missed the row this tick: the notice is not re-armed
        self.assertEqual(claim(merged), [])
        self.assertEqual(claim(merged, self.tracker("completed")), [])  # the ticket closing later is the same news


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


# ---------- row 11: a folded program's mission survives ----------

def fold_dir():
    return tempfile.mkdtemp(prefix="folds-", dir=TMP)


def put(P, slug, **kw):
    m = {"program": slug, "goal": f"goal of {slug}", "manager_session": f"local_{slug}mgr", "updated_at": iso(-60),
         "map": {"issue": f"M-{slug}", "snapshot_cmd": ["fake-tracker", "{map}"]}, "bindings": []}
    m.update(kw)
    m = {k: v for k, v in m.items() if v is not None}
    with open(os.path.join(P, slug + ".json"), "w") as fh:
        json.dump(m, fh)
    return m


def get(P, slug):
    with open(os.path.join(P, slug + ".json")) as fh:
        return json.load(fh)


def rows_of(P, slug, event=None):
    return [r for r in st._log_rows(slug, P) if event is None or r.get("event") == event]


def old_scope_slugs(P, slug):
    """The pre-ship program_scope's scope derivation, kept verbatim as a fixture: the owner plus the string
    entries of its own `absorbs` list. Code from before row 11 is correct only while the mirror covers it."""
    try:
        m = get(P, slug)
    except OSError:
        return {slug}
    return {slug} | {a for a in m.get("absorbs") or [] if isinstance(a, str)}


class Boom(RuntimeError):
    pass


class FailOn:
    """Patch `owner.name` to raise Boom on its nth call (1-based); every other call runs the real function."""

    def __init__(self, owner, name, nth):
        self.owner, self.name, self.nth, self.n = owner, name, nth, 0

    def __enter__(self):
        self.real = getattr(self.owner, self.name)
        real = self.real

        def wrapped(*a, **kw):
            self.n += 1
            if self.n == self.nth:
                raise Boom(f"{self.name} #{self.nth}")
            return real(*a, **kw)
        setattr(self.owner, self.name, wrapped)
        return self

    def __exit__(self, *exc):
        setattr(self.owner, self.name, self.real)


class FoldWriter(unittest.TestCase):
    def setUp(self):
        self.P = fold_dir()
        put(self.P, "a")
        put(self.P, "b")

    def absorb(self, into, frm, **kw):
        return st.absorb(into, frm, by="local_tester", now=NOW, programs=self.P, **kw)

    def test_absorb_writes_mirror_then_pointer_then_one_row_per_log(self):
        r = self.absorb("a", "b")
        a, b = get(self.P, "a"), get(self.P, "b")
        self.assertEqual(a["absorbs"], ["b"])
        self.assertEqual(b["absorbed_by"], "a")
        self.assertEqual(b["fold"], {"id": f"b@{st.now_iso(NOW)}", "since": st.now_iso(NOW), "by": "local_tester",
                                     "closed": None})
        self.assertEqual((r["wrote"], sorted(r["events"])), (True, ["a", "b"]))
        for s in ("a", "b"):
            self.assertEqual([x["fold_id"] for x in rows_of(self.P, s, "absorb")], [b["fold"]["id"]])
        before = {s: os.path.getmtime(os.path.join(self.P, s + ".json")) for s in ("a", "b")}
        r2 = self.absorb("a", "b")
        self.assertEqual((r2["wrote"], r2["events"]), (False, []))
        self.assertEqual(before, {s: os.path.getmtime(os.path.join(self.P, s + ".json")) for s in ("a", "b")})
        self.assertEqual(len(rows_of(self.P, "a", "absorb")), 1)

    def test_pointer_without_fold_is_repaired(self):
        put(self.P, "b", absorbed_by="a")
        r = self.absorb("a", "b")
        self.assertTrue(r["wrote"])
        self.assertIn("repair: fold record written", r["notes"])
        st.validate_fold(get(self.P, "b")["fold"])
        self.assertEqual(get(self.P, "a")["absorbs"], ["b"])

    def test_crash_before_mirror_leaves_both_manifests_unchanged(self):
        a0, b0 = get(self.P, "a"), get(self.P, "b")
        with FailOn(st._Locked, "write", 1), self.assertRaises(Boom):
            self.absorb("a", "b")
        self.assertEqual((get(self.P, "a"), get(self.P, "b")), (a0, b0))

    def test_crash_after_mirror_old_scope_already_covers_and_rerun_completes(self):
        with FailOn(st._Locked, "write", 2), self.assertRaises(Boom):
            self.absorb("a", "b")
        self.assertIn("b", old_scope_slugs(self.P, "a"))
        self.assertNotIn("absorbed_by", get(self.P, "b"))
        r = self.absorb("a", "b")
        self.assertTrue(r["wrote"])
        self.assertEqual(get(self.P, "a")["absorbs"], ["b"])  # the mirror is never written twice
        self.assertEqual(get(self.P, "b")["absorbed_by"], "a")

    def test_crash_between_appends_rerun_appends_only_the_missing_row(self):
        for nth in (1, 2):
            P = fold_dir()
            put(P, "a")
            put(P, "b")
            with FailOn(st, "append_event", nth), self.assertRaises(Boom):
                st.absorb("a", "b", by="t", now=NOW, programs=P)
            self.assertEqual(get(P, "b")["absorbed_by"], "a")  # committed at step 2
            r = st.absorb("a", "b", by="t", now=NOW, programs=P)
            self.assertFalse(r["wrote"])
            fid = get(P, "b")["fold"]["id"]
            for s in ("a", "b"):
                self.assertEqual([x["fold_id"] for x in rows_of(P, s, "absorb")], [fid], (nth, s))

    def test_manifest_less_source_folds_as_a_closed_stub(self):
        r = self.absorb("a", "ghost")
        g = get(self.P, "ghost")
        self.assertEqual((g["program"], g["absorbed_by"]), ("ghost", "a"))
        st.validate_fold(g["fold"])
        self.assertTrue(g["fold"]["closed"]["reason"].strip())
        self.assertNotIn("goal", g)
        self.assertIn("ghost", get(self.P, "a")["absorbs"])
        self.assertTrue(any(n.startswith("fold_no_manifest:ghost") for n in r["notes"]))
        ms = st.read_all(self.P)
        self.assertEqual(pf.terminal_owner("ghost", ms), "a")
        self.assertEqual(pf.open_missions("a", ms), [])  # no mission was transferred
        for s_ in ("a", "ghost"):
            self.assertEqual([x["fold_id"] for x in rows_of(self.P, s_, "absorb")], [g["fold"]["id"]])
        r2 = self.absorb("a", "ghost")
        self.assertEqual((r2["wrote"], r2["events"]), (False, []))

    def test_manifest_less_source_keeps_an_explicit_closed_reason(self):
        self.absorb("a", "ghost", closed_reason="done in PR #9")
        self.assertEqual(get(self.P, "ghost")["fold"]["closed"]["reason"], "done in PR #9")

    def test_manifest_less_absorber_still_refuses(self):
        with self.assertRaisesRegex(st.SchemaError, "no manifest for ghost"):
            self.absorb("ghost", "b")
        self.assertNotIn("absorbed_by", get(self.P, "b"))

    def test_old_scope_covers_a_chain_built_by_two_absorbs(self):
        put(self.P, "c")
        self.absorb("b", "c")
        self.absorb("a", "b")
        self.assertEqual(old_scope_slugs(self.P, "a"), {"a", "b", "c"})
        self.assertEqual(pf.fold_family("a", st.read_all(self.P)), ["b", "c"])

    def test_retry_after_a_chained_fold_succeeds_without_writing(self):
        put(self.P, "c")
        with FailOn(st, "append_event", 1), self.assertRaises(Boom):
            self.absorb("b", "a")  # a -> b committed, no events
        self.absorb("c", "b")       # b -> c: a now rides c
        r = self.absorb("b", "a")
        self.assertEqual((r["wrote"], sorted(r["events"])), (False, ["a", "b"]))
        self.assertEqual(pf.terminal_owner("a", st.read_all(self.P)), "c")

    def test_reciprocal_absorbs_in_two_processes_one_wins(self):
        script = os.path.join(self.P, "absorb_one.py")
        with open(script, "w") as fh:
            fh.write("import sys\nsys.path.insert(0, %r)\nimport work_state_store as st\n"
                     "try:\n    st.absorb(sys.argv[1], sys.argv[2], by='t', programs=sys.argv[3]); print('ok')\n"
                     "except st.SchemaError as e:\n    print('refused', e)\n" % HERE)
        with st._GraphLock(self.P):  # both children queue on the graph lock, then race for it
            procs = [subprocess.Popen([sys.executable, script, x, y, self.P], stdout=subprocess.PIPE, text=True)
                     for x, y in (("a", "b"), ("b", "a"))]
            time.sleep(0.5)
        outs = sorted(p.communicate(timeout=30)[0].strip() for p in procs)
        self.assertEqual(outs[0], "ok")
        self.assertTrue(outs[1].startswith("refused") and "cycle" in outs[1], outs)
        a, b = get(self.P, "a"), get(self.P, "b")
        self.assertFalse(a.get("absorbed_by") and b.get("absorbed_by"))

    def test_refusals(self):
        put(self.P, "c")
        put(self.P, "done", status="DONE")
        put(self.P, "nomgr", manager_session=None)
        put(self.P, "nogoal", goal="")
        cases = [(("a", "a"), "itself"), (("a", "nogoal"), "no goal"), (("done", "c"), "DONE"),
                 (("nomgr", "c"), "manager_session")]
        for (into, frm), why in cases:
            with self.assertRaises(st.SchemaError) as e:
                self.absorb(into, frm)
            self.assertIn(why, str(e.exception))
        self.absorb("a", "b")
        with self.assertRaises(st.SchemaError) as e:
            self.absorb("b", "c")  # b is absorbed: the message names the terminal owner
        self.assertIn("fold into a instead", str(e.exception))
        with self.assertRaises(st.SchemaError) as e:
            self.absorb("b", "a")
        self.assertIn("cycle", str(e.exception))
        with self.assertRaises(st.SchemaError) as e:
            self.absorb("c", "b")
        self.assertIn("already absorbed by a", str(e.exception))

    def test_closed_fold_into_done_owner_needs_no_open_family_mission(self):
        put(self.P, "done", status="DONE")
        put(self.P, "c")
        self.absorb("b", "c")  # c's mission is open, under b
        with self.assertRaises(st.SchemaError) as e:
            self.absorb("done", "b", closed_reason="shipped")
        self.assertIn("c", str(e.exception))
        st.close_mission("c", "shipped in PR 9", now=NOW, programs=self.P)
        r = self.absorb("done", "b", closed_reason="shipped")
        self.assertTrue(r["wrote"])
        self.assertEqual(get(self.P, "b")["fold"]["closed"]["reason"], "shipped")
        with self.assertRaises(st.SchemaError) as e:
            st.reopen_mission("b", "not done after all", now=NOW, programs=self.P)
        self.assertIn("DONE", str(e.exception))

    def test_no_snapshot_cmd_notes_fold_no_tracker(self):
        put(self.P, "b", map={"issue": "M-b"})
        self.assertIn("fold_no_tracker:b", self.absorb("a", "b")["notes"])


class MissionSetters(unittest.TestCase):
    def setUp(self):
        self.P = fold_dir()
        put(self.P, "a")
        put(self.P, "b")
        st.absorb("a", "b", by="t", now=NOW, programs=self.P)

    def events(self, slug):
        return [r["event"] for r in rows_of(self.P, slug) if r.get("event") in st.MISSION_EVENTS]

    def test_close_twice_writes_once_and_logs_once(self):
        r1 = st.close_mission("b", "evidence", now=NOW, programs=self.P)
        r2 = st.close_mission("b", "evidence", now=NOW, programs=self.P)
        self.assertEqual((r1["wrote"], r2["wrote"], r2["events"]), (True, False, []))
        self.assertEqual((self.events("b"), self.events("a")), (["mission-close"], ["mission-close"]))
        self.assertEqual(get(self.P, "b")["fold"]["closed"]["reason"], "evidence")

    def test_crash_before_events_rerun_completes_them_once(self):
        with FailOn(st, "append_event", 1), self.assertRaises(Boom):
            st.close_mission("b", "evidence", now=NOW, programs=self.P)
        self.assertIsNotNone(get(self.P, "b")["fold"]["closed"])
        r = st.close_mission("b", "evidence", now=NOW, programs=self.P)
        self.assertFalse(r["wrote"])
        self.assertEqual((self.events("b"), self.events("a")), (["mission-close"], ["mission-close"]))

    def test_close_reopen_close_logs_three_in_order(self):
        for fn in (st.close_mission, st.reopen_mission, st.close_mission):
            fn("b", "why", now=NOW, programs=self.P)
        self.assertEqual(self.events("b"), ["mission-close", "mission-reopen", "mission-close"])

    def test_reason_required_and_unfolded_refused(self):
        with self.assertRaises(st.SchemaError):
            st.close_mission("b", " ", programs=self.P)
        with self.assertRaises(st.SchemaError):
            st.close_mission("a", "x", programs=self.P)


class FoldResolver(unittest.TestCase):
    def g(self, **edges):
        return {s: {"program": s, "absorbed_by": t} for s, t in edges.items()}

    def test_chain_resolves_to_its_live_end(self):
        g = self.g(a=None, b="a", c="b")
        self.assertEqual((pf.terminal_owner("c", g), pf.fold_family("a", g)), ("a", ["b", "c"]))
        self.assertEqual(pf.fold_chain("c", g), (["c", "b", "a"], None))

    def test_cycle_and_missing_target_have_notes_and_no_owner(self):
        g = self.g(a="b", b="a", c="gone")
        self.assertTrue(pf.fold_chain("a", g)[1].startswith("fold_cycle:"))
        self.assertEqual(pf.fold_chain("c", g)[1], "fold_target_missing:gone")
        self.assertIsNone(pf.terminal_owner("a", g))
        self.assertIsNone(pf.terminal_owner("c", g))
        self.assertEqual(pf.fold_family("a", g), [])

    def test_open_missions_count_missing_and_malformed_records_open(self):
        fold = {"id": "x@t", "since": iso(-60), "by": "t", "closed": None}
        g = {"a": {"program": "a"},
             "b": {"program": "b", "absorbed_by": "a", "fold": fold},
             "c": {"program": "c", "absorbed_by": "a", "fold": dict(fold, closed={"at": iso(-1), "reason": "r"})},
             "d": {"program": "d", "absorbed_by": "a"},
             "e": {"program": "e", "absorbed_by": "a", "fold": {"id": "e"}}}
        self.assertEqual(pf.open_missions("a", g), ["b", "d", "e"])
        self.assertEqual((pf.fold_note(g["d"]), pf.fold_note(g["e"])), ("fold_record_missing:d", "fold_malformed:e"))


FOLD = {"id": "b@2026-11-03T11:00:00Z", "since": "2026-11-03T11:00:00Z", "by": "t", "closed": None}


def member(slug="b", bindings=(), **kw):
    m = {"slug": slug, "goal": f"goal of {slug}", "fold": dict(FOLD), "map": f"M-{slug}", "open": True,
         "bindings": list(bindings), "sub": None, "fix": None, "self": False, "notes": []}
    m.update(kw)
    return m


def blocking_flags(s):
    return [(x["flag"], x["item"]) for x in s["blocking"]]


PAST_LEASE = str(int((NOW - ws.LEASE["session"] - 600) * 1000))


def incident_bindings():
    """The live incident's carrier mix on the absorbed manifest: 13 bg, 2 agent, 6 sessions past the lease,
    one card, one wake. None of it is positive evidence of life for the owner."""
    cs = [carrier("bg", f"bg{i}") for i in range(13)] + [carrier("agent", f"ag{i}") for i in range(2)]
    cs += [carrier("card", "card-1", bound_at=iso(-60)), carrier("wake", "wake-1")]
    sessions = [carrier("session", SESSION_ROWS[i]["sessionId"]) for i in range(min(6, len(SESSION_ROWS)))]
    return [binding(f"T-{i + 1}", [c]) for i, c in enumerate(cs + sessions)], sessions


class MissionDriver(unittest.TestCase):
    def test_open_mission_without_binding_blocks(self):
        s = snap(fold_members=[member()])
        self.assertIn(("MISSION_UNDRIVEN", "b"), blocking_flags(s))
        self.assertEqual(s["missions"][0]["program"], "b")
        self.assertTrue(s["missions"][0]["undriven"])
        self.assertIn("missions open 1, undriven 1", s["map_line"])

    def test_incident_shape_still_flags(self):
        bs, sessions = incident_bindings()
        rows = {c["id"]: session_row(i, lastActivityAt=PAST_LEASE) for i, c in enumerate(sessions)}
        s = snap(fold_members=[member(bindings=bs)], sessions=rows, live_bg={"other"})
        self.assertIn(("MISSION_UNDRIVEN", "b"), blocking_flags(s))
        self.assertEqual(s["missions"][0]["drivers"], [])

    def test_each_positive_evidence_clears_it(self):
        sid = SESSION_ROWS[1]["sessionId"]
        lane = {"lane": "L1", "pid": 4242, "pid_start": "Mon Nov 3 10:00:00 2026"}
        cases = [
            ({"sessions": {sid: session_row(1)}}, carrier("session", sid)),
            ({"lanes": {"L1": lane}, "pids": {4242: "Mon Nov 3 10:00:00 2026"}}, carrier("lane", "L1")),
            ({"live_bg": {"bg7"}}, carrier("bg", "bg7")),
        ]
        for extra, c in cases:
            s = snap(fold_members=[member(bindings=[binding("T-9", [c])])], **extra)
            self.assertNotIn("MISSION_UNDRIVEN", [f for f, _ in blocking_flags(s)], c)
            self.assertEqual(s["missions"][0]["drivers"], [f"{c['type']}:{c['id']}"])

    def test_owner_live_bg_none_is_unknown_not_a_driver(self):
        s = snap(fold_members=[member(bindings=[binding("T-9", [carrier("bg", "bg7")])])], live_bg=None)
        self.assertIn(("MISSION_UNDRIVEN", "b"), blocking_flags(s))

    def test_closed_mission_does_not_flag(self):
        closed = dict(FOLD, closed={"at": iso(-1), "reason": "r"})
        s = snap(fold_members=[member(fold=closed, open=False)])
        self.assertEqual(s["missions"], [])
        self.assertNotIn("MISSION_UNDRIVEN", [f for f, _ in blocking_flags(s)])

    def test_malformed_fold_is_a_note_and_the_flag(self):
        s = snap(fold_members=[member(fold={"id": "x"}, notes=["fold_malformed:b"])])
        self.assertIn("fold_malformed:b", s["notes"])
        self.assertIn(("MISSION_UNDRIVEN", "b"), blocking_flags(s))

    def test_done_and_hold_do_not_exempt(self):
        done = copy.deepcopy(TRACKER)
        for c in done["children"]:
            c["state"] = tstate("completed")
        s = snap(fold_members=[member()], tracker=done, state={"status": "DONE"})
        self.assertIn(("MISSION_UNDRIVEN", "b"), blocking_flags(s))
        self.assertIn("status_done_open_mission_b:no_exemption", s["notes"])
        self.assertNotIn("exempt:status_done_zero_open", s["notes"])

    def test_folded_child_session_is_bound_for_the_owner(self):
        row = session_row(1)
        sid = row["sessionId"]
        base = dict(sessions={sid: row}, family_sessions={sid})
        self.assertIn(sid, [x["item"] for x in snap(**base)["flags"]["UNBOUND"]])
        s = snap(fold_members=[member(bindings=[binding("T-9", [carrier("session", sid)])])], **base)
        self.assertNotIn(sid, [x["item"] for x in s["flags"]["UNBOUND"]])

    def test_ticket_in_two_family_manifests_is_a_duplicate_note(self):
        s = snap(bindings=[binding("T-6", [carrier("card", "c1", bound_at=iso(-60))])],
                 fold_members=[member(bindings=[binding("T-6", [carrier("card", "c2", bound_at=iso(-60))])])])
        self.assertIn("fold_duplicate:T-6:b,p", s["notes"])


class FoldedEndToEnd(unittest.TestCase):
    """build_ctx + derive on manifests in a scratch store: the owner's snapshot over its folded manifests."""

    def setUp(self):
        self.P = fold_dir()
        self.a, self.b = "fa" + str(time.time_ns()), "fb" + str(time.time_ns())
        put(self.P, self.a)
        put(self.P, self.b)
        st.absorb(self.a, self.b, by="t", programs=self.P)

    def run_a(self, **kw):
        return ws.run_snapshot(self.a, programs=self.P, runner=FakeRunner(), **kw)

    def test_incident_shape_flags_exit_4_no_stall_and_caches_missions(self):
        bs, _ = incident_bindings()
        m = get(self.P, self.b)
        put(self.P, self.b, **dict(m, bindings=bs))
        s, rc = self.run_a()
        self.assertEqual(rc, 4)
        self.assertIn(("MISSION_UNDRIVEN", self.b), blocking_flags(s))
        stalled = (s["folded"].get(self.b) or {}).get("flags", {}).get("STALLED") or []
        self.assertFalse([x for x in stalled if str(x["item"]).startswith("T-")
                          and any(c["type"] in ("bg", "agent") for b in bs if b["ticket"] == x["item"]
                                  for c in b["carriers"])])
        cache = src.read_cache(self.a)
        self.assertEqual([r["program"] for r in cache["missions"]["rows"]], [self.b])
        self.assertTrue(cache["missions"]["rows"][0]["undriven"])

    def test_close_clears_reopen_restores_and_retire_flags_again(self):
        st.close_mission(self.b, "evidence", programs=self.P)
        s, _ = self.run_a()
        self.assertNotIn("MISSION_UNDRIVEN", [f for f, _ in blocking_flags(s)])
        st.reopen_mission(self.b, "back", programs=self.P)
        s, _ = self.run_a()
        self.assertIn(("MISSION_UNDRIVEN", self.b), blocking_flags(s))
        children = {c["ticket"] for c in TRACKER["children"]}
        st.bind(self.b, "T-6", children=children, map_id=f"M-{self.b}", programs=self.P)
        st.carrier(self.b, "T-6", "bg", "bg-live", programs=self.P)
        s, _ = self.run_a(mode="guard", stdin_facts={"state_facts": {}, "live_bg": ["bg-live"]})
        self.assertNotIn("MISSION_UNDRIVEN", [f for f, _ in blocking_flags(s)])
        st.retire(self.b, "T-6", carrier_ids=["bg-live"], reason="done", programs=self.P)
        s, _ = self.run_a(mode="guard", stdin_facts={"state_facts": {}, "live_bg": ["bg-live"]})
        self.assertIn(("MISSION_UNDRIVEN", self.b), blocking_flags(s))

    def test_missing_fold_record_is_a_note_never_a_schema_error(self):
        m = get(self.P, self.b)
        m.pop("fold")
        put(self.P, self.b, **m)
        s, rc = self.run_a()
        self.assertEqual(rc, 4)
        self.assertIn(f"fold_record_missing:{self.b}", s["notes"])
        self.assertIn(("MISSION_UNDRIVEN", self.b), blocking_flags(s))

    def test_unmigrated_folded_manifest_gets_note_and_migrate_fix(self):
        m = get(self.P, self.b)
        put(self.P, self.b, **dict(m, lanes=[]))
        s, _ = self.run_a()
        self.assertIn(f"folded_unmigrated:{self.b}", s["notes"])
        fix = [x["fix"] for x in s["blocking"] if x["flag"] == "MISSION_UNDRIVEN"]
        self.assertEqual(fix, [f"work_state.py migrate --program {self.b}"])

    def test_lifecycle_on_the_absorbed_manifest(self):
        open_t1 = tracker_of([child("T-50", 0, "Owner work", "completed", "task")])

        class MapRunner(FakeRunner):  # the owner's map lacks T-1; only the absorbed map knows it closed
            def __call__(inner, argv, **kw):
                inner.tracker = open_t1 if argv[0] == "fake-tracker" and argv[1] == f"M-{self.a}" else TRACKER
                res = FakeRunner.__call__(inner, argv, **kw)
                if argv[:3] == ["gh", "pr", "view"]:
                    res.stdout = json.dumps(dict(GH_ROWS[0], number=7, state="MERGED", mergedAt=iso(-3600)))
                return res
        children = {c["ticket"] for c in TRACKER["children"]}
        st.bind(self.b, "T-1", children=children, map_id=f"M-{self.b}", publication={"repo": "o/r", "pr": 7},
                programs=self.P)
        s, _ = ws.run_snapshot(self.a, programs=self.P, runner=MapRunner())
        self.assertIn(self.b, s["folded"])
        self.assertNotIn("T-1", [x["item"] for x in s["blocking"]])
        for fl, xs in s["folded"][self.b]["flags"].items():
            self.assertIn(fl, ws.LIFTED)
        allow = ws._retire_allow(self.b, self.P)  # closure is proven from b's own tracker tier
        ok, why = allow(get(self.P, self.b)["bindings"][0])
        self.assertFalse(ok)
        self.assertIn("bake ticket's binding exists", why)
        st.bind(self.b, "T-2", children=children, map_id=f"M-{self.b}", programs=self.P)
        out = st.retire(self.b, "T-1", reason="shipped", allow=ws._retire_allow(self.b, self.P), programs=self.P)
        self.assertEqual(out["ticket"], "T-1")

    def test_bind_refuses_a_ticket_open_elsewhere_in_the_family(self):
        children = {c["ticket"] for c in TRACKER["children"]}
        st.bind(self.a, "T-6", children=children, map_id=f"M-{self.a}", programs=self.P)
        with self.assertRaises(st.SchemaError):
            st.bind(self.b, "T-6", children=children, map_id=f"M-{self.b}", programs=self.P)


class FoldWaiters(unittest.TestCase):
    def test_absorbed_manifest_session_carrier_owns_the_ticket(self):
        sid = SESSION_ROWS[1]["sessionId"]
        progs = [{"program": "a", "manager_session": "local_amgr", "bindings": []},
                 {"program": "b", "absorbed_by": "a", "manager_session": "local_bmgr",
                  "bindings": [binding("T-9", [carrier("session", sid)])]}]
        c = ctx(programs=progs, sessions={}, cli={})
        self.assertIn(sid, waiters._owners("T-9", c))
        progs[1]["bindings"] = []
        progs[1]["map"] = {"issue": "T-9"}
        self.assertEqual(waiters._owners("T-9", c), "local_amgr")  # the owner's manager answers, not b's


def snapshot_files(P):
    out = {}
    for f in sorted(os.listdir(P)):
        if f.endswith(".json"):
            with open(os.path.join(P, f)) as fh:
                out[f] = fh.read()
    return out


class MigrateFolds(unittest.TestCase):
    def setUp(self):
        self.P = P = fold_dir()
        self.sid = SESSION_ROWS[1]["sessionId"]
        put(P, "own", supersedes=["x4"], absorbs=["x5", {"program": "x6", "note": "legacy dict"}])
        with open(os.path.join(P, "own.state.md"), "w") as fh:
            fh.write("# own\n\n## Taken over from `x7`\n\nhandover\n")
        put(P, "x1", absorbed_by="own", bindings=[binding("T-1", [carrier("session", self.sid)])])
        put(P, "x2", status="merged-into-own")
        put(P, "x3", superseded_by="own")
        for s in ("x4", "x5", "x6"):
            put(P, s)
        put(P, "x7", bindings=[binding("T-7", [carrier("card", "c7", bound_at=iso(-60))])])
        put(P, "y", status="superseded-by-x2")  # a chain: y -> x2 -> own

    def census(self):
        return wm.fold_census(programs=self.P, now=NOW)

    def edge(self, plan, a):
        return next(e for e in plan["edges"] if e["absorbed"] == a)

    def apply(self, plan):
        return wm.fold_apply(plan, by="t", programs=self.P, now=NOW)

    def test_census_lists_six_shapes_resolves_chain_and_records_exact_values(self):
        before = snapshot_files(self.P)
        plan = self.census()
        shapes = {c["shape"] for e in plan["edges"] for c in e["claims"]}
        self.assertEqual(shapes, {"absorbed_by", "status", "superseded_by", "supersedes", "absorbs", "absorbs_dict",
                                  "prose"})
        self.assertEqual(sorted(e["absorbed"] for e in plan["edges"]), ["x1", "x2", "x3", "x4", "x5", "x6", "x7", "y"])
        self.assertEqual(self.edge(plan, "y")["recorded_targets"], ["x2"])
        self.assertEqual(self.edge(plan, "y")["proposed_target"], "own")  # resolved to the live end
        self.assertEqual(self.edge(plan, "x1")["disposition"], "open")  # a session carrier
        self.assertTrue(self.edge(plan, "x3")["disposition"].startswith("closed: "))
        self.assertEqual(plan["legacy"]["own"], {"supersedes": ["x4"], "absorbs": [{"program": "x6", "note": "legacy dict"}]})
        self.assertEqual(plan["legacy"]["x2"], {"status": "merged-into-own"})
        self.assertEqual(plan["legacy"]["x3"], {"superseded_by": "own"})
        self.assertEqual(plan["binding_keys"]["x1"], [["T-1", "session", self.sid]])
        self.assertEqual(plan["binding_keys"]["x7"], [["T-7", "card", "c7"]])
        self.assertEqual(snapshot_files(self.P), before)  # read-only

    def test_apply_then_old_scope_covers_every_absorbed_slug(self):
        res = self.apply(self.census())
        self.assertEqual(res["refused"], [])
        ms = st.read_all(self.P)
        for s in ("x1", "x2", "x3", "x4", "x5", "x6", "x7", "y"):
            self.assertIsNone(pf.fold_note(ms[s]), s)
            self.assertEqual(pf.terminal_owner(s, ms), "own")
        self.assertTrue({"x1", "x2", "x3", "x4", "x5", "x6", "x7", "y"} <= old_scope_slugs(self.P, "own"))
        self.assertIsNone(ms["x1"]["fold"]["closed"])
        self.assertIsNotNone(ms["x3"]["fold"]["closed"])
        self.assertEqual(ms["x2"]["status"], "merged-into-own")  # apply removes nothing

    def test_apply_refusals_leave_every_manifest_untouched(self):
        P = self.P
        base = self.census()
        bad = copy.deepcopy(base)
        self.edge(bad, "x3")["disposition"] = None
        put(P, "c1", status="merged-into-c2")
        put(P, "c2", status="merged-into-c1")
        put(P, "z", absorbed_by="own", status="merged-into-x5")
        put(P, "done", status="DONE")
        put(P, "w", status="merged-into-done", bindings=[binding("T-2", [carrier("session", "local_w1")])])
        before = snapshot_files(P)
        plan = self.census()
        refused = "\n".join(self.apply(plan)["refused"]) + "\n" + "\n".join(self.apply(bad)["refused"])
        for want in ("x3: disposition", "c1: cycle", "z: conflict", "w: open mission cannot move under done"):
            self.assertIn(want, refused)
        self.assertEqual(snapshot_files(P), before)

    def test_apply_rerun_after_crash_applies_each_edge_once(self):
        plan = self.census()
        with FailOn(st, "append_event", 5), self.assertRaises(Boom):
            self.apply(plan)
        self.assertEqual(self.apply(plan)["refused"], [])
        for e in plan["edges"]:
            fid = get(self.P, e["absorbed"])["fold"]["id"]
            self.assertEqual(len([r for r in rows_of(self.P, e["absorbed"], "absorb") if r["fold_id"] == fid]), 1)
            self.assertEqual(len([r for r in rows_of(self.P, "own", "absorb") if r["fold_id"] == fid]), 1)

    def test_finish_removes_exact_values_keeps_strings_and_refuses_changed(self):
        plan = self.census()
        self.apply(plan)
        m = get(self.P, "x3")
        put(self.P, "x3", **dict(m, superseded_by="someone-else"))
        res = wm.fold_finish(plan, programs=self.P)
        self.assertIn("x3", res["refused"])
        own = get(self.P, "own")
        self.assertNotIn("supersedes", own)
        self.assertEqual([e for e in own["absorbs"] if isinstance(e, dict)], [])
        self.assertTrue({"x5", "x1"} <= set(own["absorbs"]))
        self.assertNotIn("status", get(self.P, "x2"))
        self.assertEqual(get(self.P, "x3")["superseded_by"], "someone-else")

    def test_finish_refuses_an_added_absorbs_dict(self):
        plan = self.census()
        self.apply(plan)
        own = get(self.P, "own")
        put(self.P, "own", **dict(own, absorbs=own["absorbs"] + [{"program": "late"}]))
        res = wm.fold_finish(plan, programs=self.P)
        self.assertIn("own", res["refused"])
        self.assertIn({"program": "late"}, get(self.P, "own")["absorbs"])

    def test_finish_logs_before_removing_and_rerun_logs_no_second_event(self):
        plan = self.census()
        self.apply(plan)
        with FailOn(st._Locked, "write", 1), self.assertRaises(Boom):
            wm.fold_finish(plan, programs=self.P)
        first = sorted(plan["legacy"])[0]
        self.assertEqual(len(rows_of(self.P, first, "fold-migrated")), 1)  # the audit row landed first
        wm.fold_finish(plan, programs=self.P)
        for slug in plan["legacy"]:
            self.assertEqual(len(rows_of(self.P, slug, "fold-migrated")), 1, slug)
        self.assertEqual(wm.fold_finish(plan, programs=self.P)["removed"], {})

    def test_verify_fails_each_class_and_passes_after_new_bind_and_retire(self):
        plan = self.census()
        v = wm.fold_verify(plan, programs=self.P)
        self.assertTrue(any(x.startswith("fold_unrecorded:") for x in v))
        self.assertTrue(any(x.startswith("legacy_present:") for x in v))
        self.apply(plan)
        wm.fold_finish(plan, programs=self.P)
        self.assertEqual(wm.fold_verify(plan, programs=self.P), [])
        st.bind("x1", "M-x1", children=None, map_id="M-x1", programs=self.P)
        st.retire("x1", "T-1", reason="done", programs=self.P)
        self.assertEqual(wm.fold_verify(plan, programs=self.P), [])
        own = get(self.P, "own")
        put(self.P, "own", **dict(own, absorbs=[a for a in own["absorbs"] if a != "x4"]))
        x5 = get(self.P, "x5")
        put(self.P, "x5", **dict(x5, absorbed_by="gone"))
        x7 = get(self.P, "x7")
        put(self.P, "x7", **dict(x7, bindings=[]))
        x3 = get(self.P, "x3")
        put(self.P, "x3", **dict(x3, superseded_by="own"))
        v = wm.fold_verify(plan, programs=self.P)
        for want in ("mirror_missing:x4:own", "fold_unrecorded:x5", "binding_lost:x7:T-7:card:c7", "legacy_present:x3:superseded_by"):
            self.assertIn(want, "\n".join(v))

    def test_chain_with_missing_fold_keeps_its_edge_and_is_repaired(self):  # G-astra3-1
        P = fold_dir()
        put(P, "a")
        put(P, "b", absorbed_by="a")
        put(P, "c", absorbed_by="b")
        plan = wm.fold_census(programs=P, now=NOW)
        self.assertEqual(self.edge(plan, "c")["proposed_target"], "b")
        self.assertEqual(self.edge(plan, "c")["terminal_owner"], "a")
        self.assertEqual(wm.fold_apply(plan, by="t", programs=P, now=NOW)["refused"], [])
        ms = st.read_all(P)
        self.assertEqual((ms["c"]["absorbed_by"], pf.fold_note(ms["c"]), pf.fold_note(ms["b"])), ("b", None, None))
        self.assertEqual(old_scope_slugs(P, "a"), {"a", "b", "c"})
        self.assertEqual(wm.fold_verify(plan, programs=P), [])

    def test_cli_census_writes_a_plan_and_verify_exits_1(self):
        out = os.path.join(self.P, "plan.json")
        env = dict(os.environ, WORK_STATE_PROGRAMS=self.P)
        r = subprocess.run([sys.executable, os.path.join(HERE, "work_state.py"), "migrate", "--folds", "--census",
                            "--out", out], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out) as fh:
            self.assertEqual(json.load(fh)["schema"], wm.CENSUS_SCHEMA)
        r = subprocess.run([sys.executable, os.path.join(HERE, "work_state.py"), "migrate", "--folds", "--verify", out],
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 1)


class MigrateProgramRace(unittest.TestCase):
    def test_refuses_when_a_bind_lands_between_plan_and_write(self):
        P = fold_dir()
        put(P, "r", bindings=None, lanes=[{"name": "old", "status": "completed", "kind": "agent"}])
        real = st.validate_bindings
        state = {"n": 0}

        def racing(bs):
            state["n"] += 1
            if state["n"] == 1:  # a concurrent writer lands a binding after planning, before the lock
                m = get(P, "r")
                put(P, "r", **dict(m, bindings=[binding("T-6")]))
            return real(bs)
        st.validate_bindings = racing
        try:
            res = wm.migrate_program("r", programs=P, rows={}, now=NOW)
        finally:
            st.validate_bindings = real
        self.assertEqual(res.get("error"), "manifest changed since planning; re-run")
        self.assertEqual([b["ticket"] for b in get(P, "r")["bindings"]], ["T-6"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
