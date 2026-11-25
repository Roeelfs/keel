#!/usr/bin/env python3
"""Tests for coordinate.py: peers, overlaps, the coordination ledger, ownership and takeover.
Rules: ../specs/2026-11-25-managers-coordinate.md (Tests 1-10)."""
import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
# Before any store import: work_state_store reads WORK_STATE_PROGRAMS once, at import. Never the real dir.
os.environ.setdefault("WORK_STATE_PROGRAMS", tempfile.mkdtemp(prefix="coordinate-test-"))
import coordinate as co  # noqa: E402
import work_state_store as st  # noqa: E402

NOW = dt.datetime(2026, 11, 25, 12, 0, tzinfo=dt.timezone.utc)
REPO = "acme/app"


def iso(delta_s=0):
    return st.now_iso(NOW.timestamp() + delta_s)


def carrier(type_="session", id_="local_c1", **kw):
    return dict({"type": type_, "id": id_, "bound_at": iso(-3600)}, **kw)


def binding(ticket, carriers=None, since=-3600, **kw):
    return dict({"ticket": ticket, "carriers": carriers if carriers is not None else [carrier()],
                 "bound_at": iso(since), "bake": "none:test"}, **kw)


def mrow(sid, title="[Manager] X", seen=-60):
    return {"sessionId": sid, "title": title, "lastActivityAt": iso(seen)}


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.rows = {}

    def manifest(self, slug, session=None, updated=-60, **kw):
        session = session or f"local_{slug}aaaa"
        m = dict({"program": slug, "goal": "g", "manager_session": session, "updated_at": iso(updated)}, **kw)
        with open(os.path.join(self.dir, f"{slug}.json"), "w") as fh:
            json.dump(m, fh)
        return session

    def live(self, slug, session=None):
        sid = self.manifest_session(slug) if session is None else session
        self.rows[sid] = mrow(sid)

    def manifest_session(self, slug):
        with open(os.path.join(self.dir, f"{slug}.json")) as fh:
            return json.load(fh)["manager_session"]

    def world(self):
        return co.World(NOW, self.dir, self.rows)

    def sidecar(self, slug, holdings, **extra):
        with open(os.path.join(self.dir, f"{slug}.state.json"), "w") as fh:
            json.dump(dict({"schema": "state-sidecar/1", "program": slug, "generated_at": iso(-60),
                            "holdings": holdings}, **extra), fh)


class Overlaps(Base):
    def test_1_same_ticket_one_line_each_naming_first_claim(self):
        self.manifest("aa", bindings=[binding("T-123", since=-7200)])
        self.manifest("bb", bindings=[binding("T-123", [carrier(id_="local_c2")], since=-600)])
        self.live("aa"), self.live("bb")
        w = self.world()
        a, b = co.view("aa", w)["overlaps"], co.view("bb", w)["overlaps"]
        self.assertEqual(len(a), 1)
        self.assertEqual(len(b), 1)
        self.assertIn("ticket:T-123", a[0])
        self.assertIn("first claim: yours", a[0])
        self.assertIn("first claim: theirs", b[0])
        self.assertIn("coordinate.py ask --program aa --to bb", a[0])

    def test_2_branch_worktree_pr_lines_and_fold_family_silent(self):
        wt = os.path.join(self.dir, "wt")
        os.makedirs(wt)
        shared = dict(branch="feat/x", worktree=wt, publication={"repo": REPO, "pr": 7})
        self.manifest("aa", bindings=[binding("T-1", **shared)])
        self.manifest("bb", bindings=[binding("T-2", [carrier(id_="local_c2")], **shared)])
        self.live("aa"), self.live("bb")
        kinds = sorted(l.split(":", 1)[0][2:] for l in co.view("aa", self.world())["overlaps"])
        self.assertEqual(kinds, ["branch", "pr", "worktree"])
        self.manifest("bb", absorbed_by="aa", bindings=[binding("T-2", [carrier(id_="local_c2")], **shared)])
        self.assertEqual(co.view("aa", self.world())["overlaps"], [])

    def test_3_seam_against_peer_pr_files_and_same_pr_silent(self):
        self.manifest("aa", owns=[{"seam": "auth", "repo": REPO, "paths": ["src/auth/*"], "since": iso(-100)}])
        self.manifest("bb", bindings=[binding("T-2", publication={"repo": REPO, "pr": 9})])
        self.sidecar("bb", {REPO: {"prs": {"9": ["src/auth/login.ts"]}, "paths": []}})
        self.live("aa"), self.live("bb")
        lines = co.view("aa", self.world())["path_overlaps"]
        self.assertEqual(len(lines), 1)
        self.assertIn("path:acme/app:src/auth/login.ts", lines[0])
        self.assertIn("(advisory)", lines[0])
        self.sidecar("aa", {REPO: {"prs": {"9": ["src/auth/login.ts"]}, "paths": []}})
        self.manifest("aa", bindings=[binding("T-1", publication={"repo": REPO, "pr": 9})])
        self.assertEqual(co.view("aa", self.world())["path_overlaps"], [])


class Owns(Base):
    def test_4_own_refuses_overlap_with_live_peer_and_accepts_disjoint(self):
        self.manifest("aa")
        self.manifest("bb", owns=[{"seam": "auth", "repo": REPO, "paths": ["src/auth/*"], "since": iso(-100)}])
        self.live("aa"), self.live("bb")
        ok, msg = co.own(self.world(), "aa", "login", REPO, ["src/auth/login.ts"])
        self.assertFalse(ok)
        self.assertIn("ask --program aa --to bb", msg)
        ok, _ = co.own(self.world(), "aa", "billing", REPO, ["src/billing/*"])
        self.assertTrue(ok)
        self.assertEqual(st.read_all(self.dir)["aa"]["owns"][0]["seam"], "billing")

    def test_5_validate_owns_refuses_bad_entries(self):
        good = {"seam": "s", "repo": REPO, "paths": ["src/*"], "since": iso()}
        st.validate_owns([good])
        for bad in ([dict(good, extra=1)], [dict(good, paths=["**"])], [good, dict(good)]):
            with self.assertRaises(st.SchemaError):
                st.validate_owns(bad)


class Ledger(Base):
    def setUp(self):
        super().setUp()
        self.manifest("aa", owns=[{"seam": "auth", "repo": REPO, "paths": ["src/auth/*"], "since": iso(-100)}])
        self.manifest("bb")
        self.live("aa"), self.live("bb")

    def state(self, tid):
        w = self.world()
        return co.thread_state(co.threads(w.ledger)[tid], w)

    def thread_of(self, out):
        return json.loads(out.splitlines()[-1])["message"].split("]")[0].split()[-1]

    def test_6_thread_states(self):
        ok, out = co.ask(self.world(), "bb", "aa", "question:who owns deploys?", "?")
        tid = self.thread_of(out)
        self.assertEqual(self.state(tid), ("open", None))
        self.assertTrue(json.loads(out.splitlines()[-1])["notify_when_idle"])
        co.answer(self.world(), "aa", "reply", tid, "me")
        self.assertEqual(self.state(tid)[0], "answered")

        _, out = co.ask(self.world(), "bb", "aa", "seam:auth", "may I?")
        tid = self.thread_of(out)
        co.answer(self.world(), "aa", "settle", tid, "yours", owner="bb")
        self.assertEqual(self.state(tid), ("settled", "bb"))
        m = st.read_all(self.dir)["aa"]
        self.assertEqual(m["owns"], [])
        self.assertIn({"item": "seam:auth", "to": "bb"}, m["ceded"])

        _, out = co.ask(self.world(), "bb", "aa", "ticket:T-5", "mine?")
        tid = self.thread_of(out)
        co.answer(self.world(), "aa", "settle", tid, "mine", owner="aa")
        co.answer(self.world(), "bb", "contest", tid, "no")
        self.assertEqual(self.state(tid)[0], "escalate")  # both live
        del self.rows[self.manifest_session("bb")]
        self.assertEqual(self.state(tid)[0], "contested")
        self.live("bb")
        with self.assertRaises(st.SchemaError):  # only the asker records the ruling
            co.answer(self.world(), "aa", "ruling", tid, "founder: aa", owner="aa")
        co.answer(self.world(), "bb", "ruling", tid, "founder: aa", owner="aa")
        self.assertEqual(self.state(tid), ("ruled", "aa"))
        with self.assertRaises(st.SchemaError):  # a ruled thread takes no more rows
            co.answer(self.world(), "aa", "reply", tid, "late")

    def test_6b_old_open_ask_with_both_live_escalates(self):
        row = {"ts": iso(-25 * 3600), "thread": "c-20261124-abcdef", "verb": "ask", "from": "bb", "to": "aa",
               "item": "ticket:T-9", "text": "?", "session": "s"}
        co.append_row(row, self.dir)
        self.assertEqual(self.state("c-20261124-abcdef")[0], "escalate")

    def test_9b_corrupt_line_skipped_with_note(self):
        co.ask(self.world(), "bb", "aa", "question:x", "?")
        with open(co.ledger_path(self.dir), "a") as fh:
            fh.write("{not json\n")
        rows, bad = co.read_rows(self.dir)
        self.assertEqual((len(rows), bad), (1, 1))
        self.assertIn("1 unreadable coordination.jsonl line(s) skipped", co.peers_block("aa", "", NOW, self.dir, self.rows))

    def test_8_settled_item_loser_still_holds_gets_release_line(self):
        for slug in ("aa", "bb"):
            self.manifest(slug, bindings=[binding("T-7", [carrier(id_=f"local_{slug}c")])])
        _, out = co.ask(self.world(), "bb", "aa", "ticket:T-7", "mine?")
        co.answer(self.world(), "aa", "settle", self.thread_of(out), "yours", owner="bb")
        va, vb = co.view("aa", self.world()), co.view("bb", self.world())
        self.assertTrue(any("release --program aa --item 'ticket:T-7'" in l for l in va["release"]))
        self.assertFalse(any("ticket:T-7" in l for l in vb["overlaps"] + vb["release"]))
        ok, msg = co.release(self.world(), "aa", "ticket:T-7")
        self.assertTrue(ok, msg)
        self.assertEqual(st.read_all(self.dir)["aa"].get("bindings"), [])
        with open(os.path.join(self.dir, "aa.events.jsonl")) as fh:
            ev = [json.loads(l) for l in fh]
        self.assertTrue(any(e.get("note") == "ceded to bb" and e.get("verdict") == "ceded" for e in ev))
        import render_state
        self.assertEqual(render_state.publications(ev), [])  # a cede is not shipped history


class Takeover(Base):
    def setUp(self):
        super().setUp()
        self.manifest("aa")
        self.live("aa")

    def peer(self, carriers, updated=-30 * 3600):
        self.manifest("bb", updated=updated, bindings=[binding("T-4", carriers)])

    def test_7_takeover_abandoned_claim(self):
        self.peer([carrier("lane", "L1", pid=999999)])
        with self.assertRaises(st.SchemaError):  # outside my map: refused, nothing moves
            co.takeover(self.world(), "aa", "bb", "ticket:T-4", children=set())
        self.assertEqual(len(st.read_all(self.dir)["bb"]["bindings"]), 1)
        ok, msg = co.takeover(self.world(), "aa", "bb", "ticket:T-4", children={"T-4"})
        self.assertTrue(ok, msg)
        ms = st.read_all(self.dir)
        self.assertEqual(ms["bb"].get("bindings"), [])
        self.assertEqual([b["ticket"] for b in ms["aa"]["bindings"]], ["T-4"])
        with open(os.path.join(self.dir, "bb.events.jsonl")) as fh:
            ev = [json.loads(l) for l in fh]
        self.assertTrue(any(e["event"] == "binding-transferred" and e["note"] == "takeover by aa" for e in ev))
        self.assertFalse(any(e["event"] == "binding-retired" for e in ev))  # a hand-over is not a finish
        w = self.world()
        tid = next(iter(co.threads(w.ledger)))
        self.assertEqual(co.thread_state(co.threads(w.ledger)[tid], w), ("taken", "aa"))

    def test_7b_live_manager_or_live_carrier_refuses(self):
        self.peer([carrier("lane", "L1", pid=999999)])
        self.live("bb")
        with self.assertRaises(st.SchemaError):
            co.takeover(self.world(), "aa", "bb", "ticket:T-4", children={"T-4"})
        del self.rows[self.manifest_session("bb")]
        self.peer([carrier("lane", "L1", pid=os.getpid(), pid_start=st.pid_start(os.getpid()))])
        with self.assertRaises(st.SchemaError):
            co.takeover(self.world(), "aa", "bb", "ticket:T-4", children={"T-4"})

    def test_7c_fail_closed_liveness(self):
        # An unparseable updated_at is not stale; an unknown background carrier is live; ps failing is live.
        self.manifest("bb", updated=0, bindings=[binding("T-4", [carrier("lane", "L1", pid=999999)])])
        with open(os.path.join(self.dir, "bb.json")) as fh:
            m = json.load(fh)
        m["updated_at"] = "garbage"
        with open(os.path.join(self.dir, "bb.json"), "w") as fh:
            json.dump(m, fh)
        self.assertFalse(self.world().abandoned("bb"))
        self.peer([carrier("agent", "A1")])
        self.assertFalse(self.world().abandoned("bb"))
        import work_state_sources as wss
        real = wss.ps_pids
        wss.ps_pids = lambda pids, **kw: {}
        try:
            self.peer([carrier("lane", "L1", pid=os.getpid())])
            self.assertFalse(self.world().abandoned("bb"))
        finally:
            wss.ps_pids = real

    def test_7d_folded_peer_refused_naming_owner(self):
        self.peer([carrier("lane", "L1", pid=999999)])
        self.manifest("cc", absorbed_by="bb", updated=-30 * 3600)
        with self.assertRaises(st.SchemaError) as e:
            co.takeover(self.world(), "aa", "cc", "ticket:T-4", children={"T-4"})
        self.assertIn("folded into bb", str(e.exception))
        with self.assertRaises(st.SchemaError) as e:
            co.ask(self.world(), "aa", "cc", "question:x", "?")
        self.assertIn("ask bb instead", str(e.exception))


class Threads(Base):
    def setUp(self):
        super().setUp()
        self.manifest("aa"), self.manifest("bb")
        self.live("aa"), self.live("bb")

    def state(self, tid):
        w = self.world()
        return co.thread_state(co.threads(w.ledger)[tid], w)

    def tid(self, out):
        return out.split("[coordination ")[1].split("]")[0]

    def test_11_self_award_is_proposed_until_counterparty_agrees(self):
        _, out = co.ask(self.world(), "bb", "aa", "ticket:T-1", "mine?")
        t = self.tid(out)
        co.answer(self.world(), "aa", "settle", t, "mine", owner="aa")
        self.assertEqual(self.state(t), ("proposed", "aa"))
        co.answer(self.world(), "bb", "settle", t, "ok", owner="aa")
        self.assertEqual(self.state(t), ("settled", "aa"))

    def test_12_contest_after_settle_reopens(self):
        _, out = co.ask(self.world(), "bb", "aa", "ticket:T-2", "?")
        t = self.tid(out)
        co.answer(self.world(), "aa", "settle", t, "yours", owner="bb")
        self.assertEqual(self.state(t)[0], "settled")
        co.answer(self.world(), "aa", "contest", t, "changed my mind")
        self.assertEqual(self.state(t)[0], "escalate")

    def test_13_ask_is_idempotent_and_non_party_refused(self):
        _, o1 = co.ask(self.world(), "bb", "aa", "ticket:T-3", "?")
        _, o2 = co.ask(self.world(), "bb", "aa", "ticket:T-3", "again?")
        self.assertEqual(self.tid(o1), self.tid(o2))
        self.assertIn("already open", o2)
        self.assertEqual(len(self.world().ledger), 1)
        self.manifest("cc"), self.live("cc")
        with self.assertRaises(st.SchemaError):
            co.answer(self.world(), "cc", "reply", self.tid(o1), "butting in")

    def test_14_ledger_only_when_contact_unresolved(self):
        self.manifest("aa", session="codex-rollout-123", bindings=[binding("T-8")])
        ok, out = co.ask(self.world(), "bb", "aa", "question:y", "?")
        self.assertTrue(ok)
        self.assertIn("ledger-only", out)
        self.assertNotIn('"to":', out)
        self.assertIn("ledger-only", "\n".join(co.view("bb", self.world())["peers"]))

    def test_15_coverage_line_never_claims_no_overlap(self):
        self.manifest("bb", bindings=[binding("T-9", publication={"repo": REPO, "pr": 3})])
        self.sidecar("bb", {REPO: {"prs": {"3": ["src/**"]}, "paths": [], "collapsed": True}})
        text = co.peers_block("aa", "", NOW, self.dir, self.rows)
        self.assertIn("path coverage incomplete for bb (files collapsed to dirs)", text)
        self.assertIn("not a no-overlap verdict", text)

    def test_16_branch_without_repo_is_uncertain(self):
        self.manifest("aa", bindings=[binding("T-1", branch="feat/x")])
        self.manifest("bb", bindings=[binding("T-2", [carrier(id_="local_c2")], branch="feat/x",
                                              publication={"repo": REPO})])
        lines = co.view("aa", self.world())["overlaps"]
        self.assertTrue(any("repo unknown" in l for l in lines), lines)
        self.manifest("aa", bindings=[binding("T-1", branch="feat/x", publication={"repo": "other/repo"})])
        self.assertFalse(any("branch:" in l for l in co.view("aa", self.world())["overlaps"]))

    def test_17_own_retry_keeps_since(self):
        co.own(self.world(), "aa", "billing", REPO, ["src/billing/*"])
        first = st.read_all(self.dir)["aa"]["owns"][0]["since"]
        later = co.World(NOW + dt.timedelta(hours=1), self.dir, self.rows)
        co.own(later, "aa", "billing", REPO, ["src/billing/*"])
        self.assertEqual(st.read_all(self.dir)["aa"]["owns"][0]["since"], first)


def _own_in_child(programs, seam, path, q):
    import coordinate as c
    q.put(c.own(c.World(NOW, programs, {}), seam, seam, REPO, [path])[0])


class Concurrency(Base):
    def test_18_concurrent_overlapping_own_admits_exactly_one(self):
        import multiprocessing as mp
        for slug in ("aa", "bb"):
            self.manifest(slug, bindings=[binding("T-" + slug)])
        ctx = mp.get_context("fork")
        q = ctx.Queue()
        ps = [ctx.Process(target=_own_in_child, args=(self.dir, s, "src/x/*", q)) for s in ("aa", "bb")]
        [p.start() for p in ps]
        [p.join(10) for p in ps]
        self.assertEqual(sorted([q.get(timeout=5), q.get(timeout=5)]), [False, True])


class Bounds(Base):
    def test_10_peer_cap(self):
        self.manifest("me")
        for i in range(20):
            self.manifest(f"p{i:02d}", bindings=[binding(f"T-{i}", [carrier(id_=f"local_p{i}c")])])
        lines = co.view("me", self.world())["peers"]
        self.assertEqual(len(lines), 13)
        self.assertIn("+8 more", lines[-1])
        self.assertEqual(len(co.view("me", self.world(), all_=True)["peers"]), 20)

    def test_10b_escalations_and_threads_never_cut(self):
        self.manifest("me", session="local_ffff0000"), self.live("me")  # holder ids are hex
        for i in range(15):
            self.manifest(f"p{i:02d}", session=f"local_{i:08x}"), self.live(f"p{i:02d}")
            co.append_row({"ts": iso(-25 * 3600), "thread": f"c-20261124-{i:06x}", "verb": "ask", "from": "me",
                           "to": f"p{i:02d}", "item": f"ticket:T-{i}", "text": "?", "session": "s"}, self.dir)
        v = co.view("me", self.world())
        self.assertEqual(len(v["escalate"]), 15)


if __name__ == "__main__":
    unittest.main()
