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

    def run(self, *extra):
        env = dict(os.environ, S2C_STORE=self.store, S2C_CLAUDE_HOME=self.home)
        env.pop("CLAUDE_SESSION_ID", None)
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
        self.assertEqual(mine_report.check_gate(plan_path, echo=False), 0)
        self.assertIn("ALL GATES PASS", open(plan["receipt"]).read())


if __name__ == "__main__":
    unittest.main()
