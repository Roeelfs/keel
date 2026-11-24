#!/usr/bin/env python3
"""mine_all.py on fixture stores: chain resolution, checkpoint derivation, hole widening, receipt."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import contextlib  # noqa: E402
import io  # noqa: E402
from unittest import mock  # noqa: E402

import coverage_audit as ca  # noqa: E402
import mine_all  # noqa: E402
import mine_report  # noqa: E402
import program_family as pf  # noqa: E402
import transcript_chain as tc  # noqa: E402

NOW = time.time()
H = 3600
ACCT_HERE, ACCT_OTHER, ORG = "aaaa1111-0000", "bbbb2222-0000", "org00000-0000"


def iso_z(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(ts))


def u(n):
    return f"{n:08x}-0000-4000-8000-000000000000"


class Fixture:
    """A temp ~/.claude plus a temp session store with two accounts."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.store = os.path.join(root, "store")
        self.home = os.path.join(root, "home")
        self.projects = os.path.join(self.home, "projects")
        for d in (self.projects, os.path.join(self.home, "orchestrator", "programs"),
                  os.path.join(self.home, "sessions-to-chips", "handoff")):
            os.makedirs(d, exist_ok=True)

    def transcript(self, proj, cli, rows, mtime=None):
        d = os.path.join(self.projects, proj)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"{cli}.jsonl")
        with open(path, "w") as fh:
            for r in rows:
                fh.write(json.dumps(dict({"sessionId": cli}, **r)) + "\n")
        if mtime:
            os.utime(path, (mtime, mtime))
        return path

    def session(self, acct, sid, title, cli=None, last=NOW, parent=None, archived=False, **extra):
        d = os.path.join(self.store, acct, ORG)
        os.makedirs(d, exist_ok=True)
        row = {"sessionId": sid, "title": title, "cliSessionId": cli, "lastActivityAt": int(last * 1000),
               "createdAt": int((last - 48 * H) * 1000), "isArchived": archived, "cwd": "/nonexistent/wt"}
        if parent:
            row["spawnedFrom"] = {"sessionId": parent}
        row.update(extra)
        with open(os.path.join(d, f"{sid}.json"), "w") as fh:
            json.dump(row, fh)
        return row

    def run(self, *extra, cli_env=None):
        env = dict(os.environ, S2C_STORE=self.store, S2C_CLAUDE_HOME=self.home)
        env.pop("CLAUDE_SESSION_ID", None)
        if cli_env:
            env["CLAUDE_SESSION_ID"] = cli_env
        work = os.path.join(self.tmp.name, "work")
        r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "mine_all.py"), "--store", self.store,
                            "--claude-home", self.home, "--work-dir", work, "--now", iso_z(NOW), *extra],
                           capture_output=True, text=True, env=env)
        return r, work


def turn(n, ts, typ="assistant", parent=None):
    return {"type": typ, "uuid": u(n), "parentUuid": parent, "timestamp": iso_z(ts), "entrypoint": "claude-desktop"}


class ChainResolutionTests(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture()
        p = "-wt-a"
        # old segment: no store row, rows u1..u3
        self.old = self.fx.transcript(p, "old-seg", [turn(1, NOW - 10 * H, "user"), turn(2, NOW - 9 * H, parent=u(1)),
                                                      turn(3, NOW - 8 * H, "user", parent=u(2))])
        # newest segment (the store's cli): continues from u2 via its head link
        self.new = self.fx.transcript("-wt-b", "new-seg", [{"type": "custom-title", "customTitle": "[Manager] Apps"},
                                                           turn(10, NOW - 7 * H, "user", parent=u(2)),
                                                           turn(11, NOW - 6 * H, parent=u(10))])
        # a sibling orphan that also continues from u2 (two files from one parent row)
        self.sib = self.fx.transcript(p, "sib-seg", [turn(20, NOW - 7 * H, "user", parent=u(2)),
                                                     turn(21, NOW - 6.5 * H, parent=u(20))])
        # a fork copy: carries its parent's sessionId on copied rows
        self.parent = self.fx.transcript(p, "fork-parent", [turn(30, NOW - 5 * H, "user")])
        self.fork = self.fx.transcript(p, "fork-child", [dict(turn(30, NOW - 5 * H, "user"), sessionId="fork-parent"),
                                                         turn(31, NOW - 4 * H, parent=u(30))])
        self.lost = self.fx.transcript(p, "lost-link", [turn(40, NOW - 3 * H, "user", parent=u(999))])

    def tearDown(self):
        self.fx.tmp.cleanup()

    def test_store_cli_resolves_ancestor_and_orphan_sibling(self):
        chains, _ = tc.resolve({"m": [self.new]}, NOW - 24 * H, self.fx.projects, owned={"new-seg"})
        self.assertEqual(set(chains["m"]["members"]), {self.new, self.old, self.sib})
        self.assertEqual(chains["m"]["pre_window"], [])

    def test_owned_sibling_is_not_absorbed(self):
        chains, _ = tc.resolve({"m": [self.new]}, NOW - 24 * H, self.fx.projects, owned={"new-seg", "sib-seg"})
        self.assertEqual(set(chains["m"]["members"]), {self.new, self.old})

    def test_fork_copy_links_to_parent_by_foreign_session_id(self):
        chains, _ = tc.resolve({"f": [self.fork]}, NOW - 24 * H, self.fx.projects)
        self.assertIn(self.parent, chains["f"]["members"])

    def test_link_missing_from_window_is_pre_window_not_a_member(self):
        chains, _ = tc.resolve({"l": [self.lost]}, NOW - 24 * H, self.fx.projects)
        self.assertEqual(chains["l"]["members"], [self.lost])
        self.assertEqual(chains["l"]["pre_window"], [u(999)])

    def test_turn_verdict_uses_last_assistant_uuid_not_last_activity(self):
        row = {"lastActivityAt": int((NOW - 1 * H) * 1000), "lastAssistantUuid": u(11)}
        self.assertEqual(pf.turn_verdict(row, [self.new])[0], "NON-TURN-ACTIVITY")
        row["lastAssistantUuid"] = u(77)
        self.assertEqual(pf.turn_verdict(row, [self.new])[0], "MISSING-TURNS")
        self.assertEqual(pf.turn_verdict(row, [])[0], "NO-TRANSCRIPT")


class IdentityTests(unittest.TestCase):
    def test_program_key_strips_fork_and_subtitle(self):
        self.assertEqual(pf.program_key("[Manager] CRM (fork)"), "crm")
        self.assertEqual(pf.program_key("[Manager] User Journey: map every path"), "user journey")
        self.assertEqual(pf.program_key("[Manager] - Random"), "random")

    def test_manifest_matches_an_old_chain_segment(self):
        rows = {"local_abc12345-x": {"sessionId": "local_abc12345-x", "title": "[Manager] Applications hub",
                                     "cliSessionId": "ffff0000"}}
        man = [{"slug": "apps", "ids": {"edae2f58"}, "mtime": 1, "absorbed_by": None}]
        self.assertEqual(list(pf.families(rows, man)), ["applications-hub"])  # title key alone
        self.assertEqual(list(pf.families(rows, man, {"local_abc12345-x": ["edae2f58-d761"]})), ["apps"])


class CheckpointTests(unittest.TestCase):
    def m(self, acct, last, archived=False):
        return {"acct": acct, "sid": "local_12345678", "cli": "c" * 8, "last_turn": last, "turn_edge": last,
                "store_last": last + 3 * 86400, "verdict": "NON-TURN-ACTIVITY", "archived": archived}

    def test_checkpoint_is_the_newest_last_turn_on_this_account(self):
        cp, src, _ = mine_all.checkpoint_for([self.m(ACCT_HERE, NOW - 5 * H), self.m(ACCT_HERE, NOW - 9 * H),
                                           self.m(ACCT_OTHER, NOW - 1 * H)], ACCT_HERE, NOW - 99 * H)
        self.assertEqual(cp, NOW - 5 * H)
        self.assertIn("last turn", src)
        self.assertIn("lastActivityAt", src)  # store activity is printed, never used as the checkpoint

    def test_no_manager_here_falls_back_to_window_floor(self):
        cp, src, sid = mine_all.checkpoint_for([self.m(ACCT_OTHER, NOW - 1 * H)], ACCT_HERE, NOW - 99 * H)
        self.assertIsNone(sid)
        self.assertEqual(cp, NOW - 99 * H)
        self.assertIn("no manager on this account", src)

    def test_here_detection_prefers_explicit_then_session_id(self):
        rows = {"s": {"_acct": ACCT_HERE, "cliSessionId": "cli-1", "sessionId": "local_00000000"}}
        self.assertEqual(mine_all.detect_here(rows, "aaaa", None)[0], ACCT_HERE)
        self.assertEqual(mine_all.detect_here(rows, None, "cli-1")[0], ACCT_HERE)
        self.assertIsNone(mine_all.detect_here(rows, None, "nope")[0])


class HoleWideningTests(unittest.TestCase):
    def test_test_a_hole_is_ledgered_then_closes(self):
        with tempfile.TemporaryDirectory() as d:
            ls_rows = [{"account": ACCT_HERE, "title": "Child", "sessionId": "local_c1", "parentSessionId": "",
                        "lastActivityAt": "2099-01-01T00:00:00", "prState": None}]
            rows = {"local_c1": {"sessionId": "local_c1", "title": "Child", "lastActivityAt": int(NOW * 1000)}}
            graph = {"heads": {}, "parents": {}, "held": {}}
            hist, res = mine_all.widen(rows, ls_rows, "2026-01-01T00:00:00", d, "", {}, graph, set(), d, 4)
            self.assertEqual([h["test_a"] for h in hist], [1, 0])
            self.assertEqual(res["holes"], [])
            self.assertTrue(os.path.exists(os.path.join(d, "children-widened-r1.json")))


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        fx = self.fx = Fixture()
        cli_here, cli_other = "cli-here-mgr", "cli-other-mgr"
        fx.transcript("-wt-h", cli_here, [turn(1, NOW - 30 * H, "user"), turn(2, NOW - 30 * H, parent=u(1))])
        fx.transcript("-wt-o", cli_other, [turn(3, NOW - 20 * H, "user"), turn(4, NOW - 2 * H, parent=u(3))])
        # orphan desktop transcript: no store row, no link, no title match -> ledgered
        fx.transcript("-wt-x", "orphan-one", [{"type": "custom-title", "customTitle": "Lost work"},
                                              turn(5, NOW - 3 * H, "user")])
        fx.session(ACCT_HERE, "local_h0000001", "[Manager] Release", cli_here, last=NOW - 30 * H,
                   lastAssistantUuid=u(2))
        fx.session(ACCT_OTHER, "local_o0000001", "[Manager] Release", cli_other, last=NOW - 1 * H,
                   lastAssistantUuid=u(4))
        fx.session(ACCT_OTHER, "local_k0000001", "Child after checkpoint", None, last=NOW - 4 * H, parent="local_o0000001")
        # old unmerged descendant named nowhere -> Test B, widened into the old-descendants ledger
        fx.session(ACCT_OTHER, "local_k0000002", "Old parked child", None, last=NOW - 200 * H, parent="local_o0000001")

    def tearDown(self):
        self.fx.tmp.cleanup()

    def test_dry_run_widens_to_zero_holes_and_owes_agent_gates(self):
        r, work = self.fx.run("--dry-run", "--here", "aaaa")
        self.assertEqual(r.returncode, 3, r.stdout[-2000:] + r.stderr[-2000:])
        receipt = open(os.path.join(work, time.strftime("%Y-%m-%d", time.gmtime(NOW)) + "-completeness-receipt.md")).read()
        self.assertIn("| aaaa1111 (here) |", receipt)
        self.assertIn("| bbbb2222 |", receipt)
        self.assertIn("**holes = 0**", receipt)
        self.assertRegex(receipt, r"\| 1 \| 0 \| 1 \| 1 \| 0 \|")  # round 1: Test B 1, orphan 1
        self.assertIn("| coverage-test-a | **PASS**", receipt)
        self.assertIn("| old-descendants-test-b | **PASS**", receipt)
        self.assertIn("OWED `handoff:release`", receipt)
        self.assertIn("dry run: not written", receipt)
        ledgers = sorted(os.listdir(os.path.join(work, "ledger")))
        self.assertTrue(any(f.startswith("children-old-descendants") for f in ledgers), ledgers)
        self.assertTrue(any(f.startswith("children-orphan-transcripts") for f in ledgers), ledgers)
        self.assertFalse(os.listdir(os.path.join(self.fx.home, "sessions-to-chips", "handoff")))  # dry run wrote nothing there

    def test_checkpoint_is_this_accounts_last_turn_and_program_moved(self):
        r, work = self.fx.run("--dry-run", "--here", "aaaa")
        plan = json.load(open([os.path.join(work, f) for f in os.listdir(work) if f.endswith("mine-plan.json")][0]))
        self.assertEqual([s["id"] for s in plan["phases"][0]["steps"]], ["handoff:release"])
        self.assertEqual(plan["since"], time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(NOW - 30 * H)))
        relay = plan["phases"][2]["messages"]
        self.assertEqual((relay[0]["kind"], relay[0]["target"]), ("catchup", "local_h0000001"))
        self.assertTrue(plan["phases"][2]["founder_kits"])

    def test_unknown_account_is_a_failed_gate(self):
        r, _ = self.fx.run("--dry-run")
        self.assertEqual(r.returncode, 2)
        self.assertIn("| this-account | **FAIL**", r.stdout)

    def test_gate_mode_passes_once_every_artifact_exists(self):
        r, work = self.fx.run("--dry-run", "--here", "aaaa")
        plan_path = [os.path.join(work, f) for f in os.listdir(work) if f.endswith("mine-plan.json")][0]
        plan = json.load(open(plan_path))
        self.assertEqual(mine_report.check_gate(plan_path, echo=False), 3)
        for ph in plan["phases"][:2]:
            for s in ph["steps"]:
                os.makedirs(os.path.dirname(s["out"]), exist_ok=True)
                with open(s["out"], "w") as fh:
                    fh.write("SAFE 1 / AT-RISK 0 / NOISE 0\n")
        # Switch window: the other account's recent sessions are ledgered but named in no handoff.
        import switch_coverage as sc
        sw = json.load(open(plan_path))["switch"]
        rep = sc.check(sw["here"], sw["hours"], plan["created"], store=sw["store"], home=sw["home"],
                       now_ms=NOW * 1000)
        self.assertTrue(rep["unrouted"], "fixture's other account should have unrouted recent sessions")
        if rep["unrouted"]:
            self.assertEqual(mine_report.check_gate(plan_path, echo=False), 2)
            self.assertIn("| switch-window | **FAIL**", open(plan["receipt"]).read())
            hd = os.path.join(sw["home"], "sessions-to-chips", "handoff")
            os.makedirs(hd, exist_ok=True)
            with open(os.path.join(hd, "uncovered-sessions.md"), "w") as fh:
                fh.write("\n".join(f"| {r['sessionId']} | release | DONE |" for r in rep["unrouted"]))
        self.assertEqual(mine_report.check_gate(plan_path, echo=False), 0)
        self.assertIn("ALL GATES PASS", open(plan["receipt"]).read())


CAND = "local_c0ffee01-0000-4000-8000-000000000000"


def pr(n):
    return {"prNumber": n, "repo": "acme/shop", "branch": f"b{n}", "state": "MERGED"}


class CandidateTests(unittest.TestCase):
    """Row 1: a program without a [Manager] title is a candidate, routed by the founder."""

    def setUp(self):
        EndToEndTests.setUp(self)
        fx = self.fx
        fx.session(ACCT_HERE, CAND, "Release features: phase 2", "cli-cand", last=NOW - 2 * H,
                   prs=[pr(1), pr(2), pr(3)])
        fx.session(ACCT_HERE, "local_c0ffee02", "Cand child one", None, last=NOW - 3 * H, parent=CAND)
        fx.session(ACCT_HERE, "local_c0ffee03", "Cand child two", None, last=NOW - 3 * H, parent=CAND)

    def tearDown(self):
        self.fx.tmp.cleanup()

    def plan(self, work):
        path = [os.path.join(work, f) for f in os.listdir(work) if f.endswith("mine-plan.json")][0]
        return path, json.load(open(path))

    def ledger(self, work, name):
        f = os.path.join(work, "ledger", name)
        return [c["sessionId"] for c in json.load(open(f))["children"]] if os.path.exists(f) else []

    def step_ids(self, plan, phase):
        return [s["id"] for s in plan["phases"][phase]["steps"]]

    def test_unmanaged_root_with_children_is_a_candidate(self):
        r, work = self.fx.run("--dry-run", "--here", "aaaa")
        self.assertEqual(r.returncode, 3, r.stdout[-2000:] + r.stderr[-2000:])
        _, plan = self.plan(work)
        self.assertIn("handoff:release-features-c0ffee01", self.step_ids(plan, 0))
        self.assertIn("route:c0ffee01", self.step_ids(plan, 1))
        kids = self.ledger(work, "children-release-features-c0ffee01.json")
        self.assertEqual(sorted(kids), ["local_c0ffee02", "local_c0ffee03"])
        self.assertNotIn(CAND, kids)
        unmanaged = self.ledger(work, "children-unmanaged-none.json")
        self.assertFalse({"local_c0ffee02", "local_c0ffee03", CAND} & set(unmanaged))
        receipt = open(plan["receipt"]).read()
        self.assertIn("(candidate, UNROUTED)", receipt)
        self.assertIn("1 unrouted candidates", receipt)
        self.assertTrue(any(CAND in k and "absorb <slug>" in k for k in plan["phases"][2]["founder_kits"]))
        msg = [m for m in plan["phases"][2]["messages"] if m["kind"] == "candidate"]
        self.assertEqual((msg[0]["target"], msg[0]["session"]), (None, CAND))

    def test_single_pr_root_is_not_a_candidate(self):
        self.fx.session(ACCT_HERE, "local_501e0001", "Solo fix", None, last=NOW - 2 * H, prs=[pr(9)])
        r, work = self.fx.run("--dry-run", "--here", "aaaa")
        _, plan = self.plan(work)
        self.assertNotIn("route:501e0001", self.step_ids(plan, 1))
        self.assertIn("local_501e0001", self.ledger(work, "children-unmanaged-none.json"))

    def test_old_root_with_prs_is_not_a_candidate(self):
        self.fx.session(ACCT_HERE, "local_01d00001", "Old work", None, last=NOW - 20 * 24 * H, prs=[pr(7), pr(8)])
        r, work = self.fx.run("--dry-run", "--here", "aaaa")
        self.assertNotIn("local_01d00001", json.load(open(os.path.join(work, "candidates.json"))))

    def test_nested_session_is_not_a_candidate(self):
        self.fx.session(ACCT_HERE, "local_c0ffee04", "Nested lead", None, last=NOW - 2 * H, parent=CAND,
                        prs=[pr(4), pr(5)])
        self.fx.session(ACCT_HERE, "local_c0ffee05", "Nested child", None, last=NOW - 2 * H, parent="local_c0ffee04")
        r, work = self.fx.run("--dry-run", "--here", "aaaa")
        self.assertEqual(list(json.load(open(os.path.join(work, "candidates.json")))), [CAND])
        kids = self.ledger(work, "children-release-features-c0ffee01.json")
        self.assertIn("local_c0ffee04", kids)
        self.assertIn("local_c0ffee05", kids)

    def test_self_is_not_a_candidate(self):
        r, work = self.fx.run("--dry-run", "--here", "aaaa", cli_env="cli-cand")
        _, plan = self.plan(work)
        self.assertNotIn("route:c0ffee01", self.step_ids(plan, 1))
        self.assertEqual(json.load(open(os.path.join(work, "candidates.json"))), {})

    def test_routed_candidate_is_not_replanned(self):
        r, work = self.fx.run("--dry-run", "--here", "aaaa")
        path, plan = self.plan(work)
        ok, msg = mine_report.write_route(CAND, "promote", None, path)
        self.assertTrue(ok, msg)
        mine_report.check_gate(path, echo=False)
        gate = [g for g in json.load(open(path))["gates"] if g["id"] == "route:c0ffee01"]
        self.assertEqual(gate[0]["status"], "PASS")
        r, work = self.fx.run("--dry-run", "--here", "aaaa")
        _, plan = self.plan(work)
        self.assertFalse([i for i in self.step_ids(plan, 1) if i.startswith("route:")])
        self.assertEqual(sorted(self.ledger(work, "children-release-features-c0ffee01.json")),
                         ["local_c0ffee02", "local_c0ffee03"])

    def test_absorbed_candidate_child_reaches_absorber(self):
        r, work = self.fx.run("--dry-run", "--here", "aaaa")
        path, _ = self.plan(work)
        ok, msg = mine_report.write_route(CAND, "absorb", "release", path)
        self.assertTrue(ok, msg)
        self.fx.session(ACCT_HERE, "local_c0ffee06", "Late child", None, last=NOW - 1 * H, parent=CAND)
        r, work = self.fx.run("--dry-run", "--here", "aaaa")
        self.assertIn("local_c0ffee06", self.ledger(work, "children-release-h0000001.json"))
        self.assertNotIn("local_c0ffee06", self.ledger(work, "children-unmanaged-none.json"))
        _, plan = self.plan(work)
        self.assertNotIn("release-features-c0ffee01", plan["program_slugs"])

    def test_route_writer_rejects_unknown(self):
        r, work = self.fx.run("--dry-run", "--here", "aaaa")
        path, _ = self.plan(work)
        self.assertFalse(mine_report.write_route("local_k0000001", "promote", None, path)[0])
        self.assertFalse(mine_report.write_route(CAND, "absorb", "no-such-program", path)[0])
        self.assertTrue(mine_report.write_route(CAND, "leave", None, path)[0])
        self.assertFalse(mine_report.write_route(CAND, "promote", None, path)[0])  # a route is permanent
        cli = subprocess.run([sys.executable, "-I", os.path.join(HERE, "mine_report.py"), "--route", "local_nope",
                              "promote", "--plan", path], capture_output=True, text=True)
        self.assertEqual(cli.returncode, 2)
        self.assertIn("not a candidate", cli.stderr)

    def test_candidate_program_fields(self):
        captured = {}
        real = mine_report.build_plan

        def spy(ctx):
            captured["programs"] = ctx["programs"]
            return real(ctx)

        args = mine_all.argparse.Namespace(dry_run=True, here="aaaa", window_days=14, max_rounds=4, date=None,
                                           now=iso_z(NOW), store=self.fx.store, claude_home=self.fx.home,
                                           work_dir=os.path.join(self.fx.tmp.name, "inproc"), gate=None)
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_SESSION_ID"}
        env.update(S2C_STORE=self.fx.store, S2C_CLAUDE_HOME=self.fx.home)
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(mine_report, "build_plan", spy), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(mine_all.mine(args), 3)
        cand = [p for p in captured["programs"] if p["kind"] == "candidate"][0]
        for key in ("kind", "slug", "key", "managers", "lineage", "live", "checkpoint", "checkpoint_src",
                    "checkpoint_sid", "moved", "absorbed_by", "relay_to", "conflict", "fold"):
            self.assertIn(key, cand)
        self.assertEqual((cand["slug"], cand["key"]), ("release-features-c0ffee01", "release features"))
        self.assertEqual([m["sid"] for m in cand["managers"]], [CAND])
        self.assertEqual(cand["lineage"][0], CAND)
        self.assertEqual((cand["moved"], cand["absorbed_by"], cand["relay_to"], cand["conflict"]), (False, None, None, False))
        self.assertTrue(cand["live"])
        self.assertEqual([p["kind"] for p in captured["programs"] if p["slug"] == "release"], ["manager"])


class RootManagerTests(unittest.TestCase):
    def test_root_manager_roots_argument(self):
        rows = {"local_a": {"title": "Lead"}, "local_b": {"title": "Kid", "spawnedFrom": {"sessionId": "local_a"}},
                "local_m": {"title": "[Manager] X"}}
        self.assertIsNone(pf.root_manager("local_b", rows))
        self.assertEqual(pf.root_manager("local_b", rows, {"local_a": "local_a"}), "local_a")
        self.assertEqual(pf.root_manager("local_b", rows, {"local_a": "local_m"}), "local_m")

    def test_program_slug_is_the_one_slug(self):
        self.assertEqual(pf.program_slug("Release features: phase 2"), "release-features")
        self.assertEqual(pf.program_slug("[Manager] Release"), "release")


class RulingRecipientsTests(unittest.TestCase):
    def setUp(self):
        EndToEndTests.setUp(self)
        fx = self.fx
        fx.session(ACCT_HERE, "local_b1110001", "[Manager] Billing", "cli-bill", last=NOW - 5 * H, archived=True)
        fx.session(ACCT_HERE, "local_b1110002", "Billing child", None, last=NOW - 1 * H, parent="local_b1110001")

    def tearDown(self):
        self.fx.tmp.cleanup()

    def test_orphan_child_of_archived_managers_receives_rulings(self):
        r, work = self.fx.run("--dry-run", "--here", "aaaa")
        plan = json.load(open([os.path.join(work, f) for f in os.listdir(work) if f.endswith("mine-plan.json")][0]))
        self.assertIn("local_b1110002", plan["ruling_recipients"])
        self.assertIn("local_h0000001", plan["ruling_recipients"])
        self.assertNotIn("local_b1110001", plan["ruling_recipients"])

    def test_absorbed_program_adds_its_absorber(self):
        progs = [{"slug": "a", "live": False, "relay_to": None, "present_here": [], "absorbed_by": "b"},
                 {"slug": "b", "live": False, "relay_to": "local_bbbb", "present_here": [], "absorbed_by": None}]
        self.assertEqual(mine_report.ruling_recipients({"programs": progs}), ["local_bbbb"])

    def test_trust_kit_names_the_cwd(self):
        r, work = self.fx.run("--dry-run", "--here", "aaaa")
        plan = json.load(open([os.path.join(work, f) for f in os.listdir(work) if f.endswith("mine-plan.json")][0]))
        self.assertTrue(any("trust" in k and "cwd" in k for k in plan["phases"][2]["founder_kits"]))


def fold_prog(slug, live=True, relay_to=None, absorbed_by=None, owner=None, missions_open=(), fold_record=True,
              moved=True):
    return {"kind": "manager", "slug": slug, "key": slug, "managers": [{"sid": f"local_{slug}0000001"}],
            "lineage": [], "live": live, "present_here": [], "checkpoint": NOW - H, "checkpoint_src": "test",
            "checkpoint_sid": None, "moved": moved, "absorbed_by": absorbed_by, "conflict": False,
            "relay_to": relay_to, "fold": {"state": f"/nonexistent/{slug}.state.md"},
            "owner": owner or (None if absorbed_by else slug), "missions_open": list(missions_open),
            "fold_record": fold_record}


class FoldRoutingTests(unittest.TestCase):
    """Row 11: mining resolves every fold through program_family.terminal_owner."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.manifests = [{"slug": "a"}, {"slug": "b", "absorbed_by": "a"}, {"slug": "c", "absorbed_by": "b"}]

    def tearDown(self):
        self.tmp.cleanup()

    def plan(self, programs):
        root = self.tmp.name
        ledger = os.path.join(root, "ledger")
        os.makedirs(ledger, exist_ok=True)
        ctx = {"date": "2026-11-17", "s2c": root, "now": NOW, "work": root, "programs": programs, "digests": {},
               "ledger_dir": ledger, "routes_file": os.path.join(root, "routes.jsonl"), "since_iso": "x",
               "here": "aaaa", "dry_run": True}
        return mine_report.build_plan(ctx)

    def messages(self, plan):
        return {m["program"]: m for m in plan["phases"][2]["messages"]}

    def test_absorb_route_through_a_chain_resolves_to_the_terminal_owners_manager(self):
        rows = {"local_a0000001": {"sessionId": "local_a0000001", "_acct": "aaaa", "lastActivityAt": int(NOW * 1000)}}
        fams = {"a": {"managers": ["local_a0000001"]}}
        cand = {"route": "absorb", "program": "b", "slug": "x"}
        before = dict(cand)
        owner = mine_all.candidate_owner("local_x", cand, {"local_x": cand}, fams, rows, "aaaa", self.manifests)
        self.assertEqual(owner, "local_a0000001")
        self.assertEqual(cand, before)  # the route record is never rewritten

    def test_fold_notice_names_the_terminal_owner_and_still_reaches_a_live_old_manager(self):
        progs = [fold_prog("a", relay_to="local_a0000001"),
                 fold_prog("c", relay_to="local_c0000001", absorbed_by="b", owner="a")]
        m = self.messages(self.plan(progs))
        self.assertEqual((m["c"]["kind"], m["c"]["absorber"], m["c"]["target"]), ("fold-notice", "a", "local_c0000001"))
        self.assertNotIn("repairs", m["a"])

    def test_pointer_without_fold_record_adds_the_repair_line_to_the_owner(self):
        progs = [fold_prog("a", relay_to="local_a0000001"),
                 fold_prog("c", relay_to="local_c0000001", absorbed_by="b", owner="a", fold_record=False)]
        m = self.messages(self.plan(progs))
        self.assertEqual(m["c"]["kind"], "fold-notice")  # the handover notice is unchanged
        self.assertEqual(m["a"]["repairs"], ["`c` has no fold record: run `work_state.py absorb --program a --from c`"])

    def test_closed_program_rows_and_rulings_go_to_the_terminal_owner(self):
        progs = [fold_prog("a", relay_to="local_a0000001"),
                 fold_prog("c", live=False, absorbed_by="b", owner="a")]
        plan = self.plan(progs)
        m = self.messages(plan)
        self.assertEqual((m["c"]["kind"], m["c"]["target"]), ("closed-program-rows", "local_a0000001"))
        self.assertIn("local_a0000001", plan["ruling_recipients"])

    def test_quiet_owner_with_an_open_mission_gets_no_manager_here(self):
        plan = self.plan([fold_prog("a", live=False, moved=False, missions_open=["c"])])
        m = self.messages(plan)
        self.assertEqual((m["a"]["kind"], m["a"]["missions"]), ("no-manager-here", ["c"]))
        kit = [k for k in plan["phases"][2]["founder_kits"] if "`c`" in k]
        self.assertTrue(kit and "mission-close" in kit[0] and "bind --program" in kit[0], kit)


class FoldOwnerFloorTests(unittest.TestCase):
    """An owner whose whole lineage is past the window floor stays visible while it owes an open mission."""

    def setUp(self):
        fx = self.fx = Fixture()
        old = NOW - 30 * 24 * H
        fx.transcript("-wt-q", "cli-q", [turn(11, old, "user"), turn(12, old, parent=u(11))], mtime=old)
        fx.session(ACCT_HERE, "local_q0000001", "[Manager] Quiet owner", "cli-q", last=old, lastAssistantUuid=u(12))
        progs = os.path.join(fx.home, "orchestrator", "programs")
        fold = {"id": "lost@2026-10-01T00:00:00Z", "since": "2026-10-01T00:00:00Z", "by": "t", "closed": None}
        for m in ({"program": "quiet-owner", "goal": "g", "manager_session": "local_q0000001"},
                  {"program": "lost", "goal": "the lost goal", "manager_session": "local_l0000001",
                   "absorbed_by": "quiet-owner", "fold": fold}):
            with open(os.path.join(progs, m["program"] + ".json"), "w") as fh:
                json.dump(m, fh)

    def tearDown(self):
        self.fx.tmp.cleanup()

    def test_owner_past_the_floor_is_kept_and_routed_no_manager_here(self):
        r, work = self.fx.run("--dry-run", "--here", "aaaa")
        plan = json.load(open([os.path.join(work, f) for f in os.listdir(work) if f.endswith("mine-plan.json")][0]))
        self.assertIn("quiet-owner", plan["program_slugs"], r.stdout[-1500:] + r.stderr[-1500:])
        m = {x["program"]: x for x in plan["phases"][2]["messages"]}
        self.assertEqual((m["quiet-owner"]["kind"], m["quiet-owner"]["missions"]), ("no-manager-here", ["lost"]))


class AbsorbedManifestNeverCapturesASession(unittest.TestCase):
    """An absorbed manifest still naming a live session (the 2026-11-19 Harness case: repo-hygiene, absorbed by
    harness, held the resumed manager's ids) resolves to its absorber, never to itself."""

    def test_absorbed_hit_resolves_to_the_owner(self):
        with tempfile.TemporaryDirectory() as d:
            sid = "f7c96cac-0000-4000-8000-000000000001"
            for slug, extra in (("harness", {"manager_session": "local_2d34eeca (old account)"}),
                                ("repo-hygiene", {"manager_session": sid, "absorbed_by": "harness",
                                                  "fold": {}, "status": "done"})):
                with open(os.path.join(d, slug + ".json"), "w") as fh:
                    json.dump(dict({"program": slug}, **extra), fh)
            os.utime(os.path.join(d, "harness.json"), (1, 1))  # the absorbed one is newer on disk
            got = pf.manifest_for({sid}, pf.load_manifests(d))
            self.assertEqual(got["slug"], "harness")

    def test_a_broken_fold_is_dropped(self):
        with tempfile.TemporaryDirectory() as d:
            sid = "abcdef12-0000-4000-8000-000000000001"
            with open(os.path.join(d, "orphan.json"), "w") as fh:
                json.dump({"program": "orphan", "manager_session": sid, "absorbed_by": "gone"}, fh)
            self.assertIsNone(pf.manifest_for({sid}, pf.load_manifests(d)))


if __name__ == "__main__":
    unittest.main()
