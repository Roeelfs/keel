#!/usr/bin/env python3
"""handoff_sweep.py: the content-based landed test on hermetic repos with a bare origin, the
--repo walk, full-store ownership, stranded scheduled tasks and stranded PR bindings."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import handoff_sweep as hs  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "handoff_sweep", "scheduled-tasks.json")
GIT_ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
LINES = [f"line {i}\n" for i in range(1, 11)]


def sh(cwd, *args):
    return subprocess.run(["git", "-C", cwd, *args], check=True, capture_output=True, text=True, env=GIT_ENV).stdout.strip()


def write(path, lines):
    with open(path, "w") as fh:
        fh.writelines(lines)


def edit(path, idx, text):
    with open(path) as fh:
        lines = fh.readlines()
    lines[idx] = text + "\n"
    write(path, lines)


class Repo:
    """origin.git (bare) plus a clone `work` with main pushed, and a `feat` branch in a worktree."""

    def __init__(self, default="main", remote=True):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.origin, self.work, self.wt = (os.path.join(root, n) for n in ("origin.git", "work", "wt"))
        os.makedirs(self.work)
        sh(root, "init", "-q", "-b", default, self.work)
        self.f = os.path.join(self.work, "f.txt")
        write(self.f, LINES)
        sh(self.work, "add", "f.txt")
        sh(self.work, "commit", "-q", "-m", "base")
        self.default = default
        if remote:
            sh(root, "init", "-q", "--bare", "-b", default, self.origin)
            sh(self.work, "remote", "add", "origin", self.origin)
            sh(self.work, "push", "-q", "-u", "origin", default)

    def feature(self, commits=((1, "feat one"), (2, "feat two"))):
        sh(self.work, "worktree", "add", "-q", "-b", "feat", self.wt, self.default)
        for idx, msg in commits:
            edit(os.path.join(self.wt, "f.txt"), idx, msg)
            sh(self.wt, "commit", "-q", "-am", msg)
        return sh(self.wt, "rev-parse", "HEAD")

    def squash_to_main(self):
        sh(self.work, "merge", "-q", "--squash", "feat")
        sh(self.work, "commit", "-q", "-m", "feat (#5)")
        sh(self.work, "push", "-q", "origin", self.default)

    def main_edit(self, idx, text):
        edit(self.f, idx, text)
        sh(self.work, "commit", "-q", "-am", f"main edits line {idx + 1}")
        sh(self.work, "push", "-q", "origin", self.default)


class Landed(unittest.TestCase):
    def setUp(self):
        self.r = Repo()

    def tearDown(self):
        self.r.tmp.cleanup()

    def test_squash_merged_branch_is_landed_and_not_in_findings(self):
        self.r.feature()
        self.r.squash_to_main()
        self.assertEqual(hs.landed(self.r.wt, "HEAD")["verdict"], "LANDED")
        window = {"local_s1": {"cwd": self.r.wt, "title": "lane", "_acct": "a"}}
        self.assertEqual(hs.worktree_findings(window, window, {}), [])

    def test_main_edit_in_another_hunk_still_landed(self):
        self.r.feature()
        self.r.squash_to_main()
        self.r.main_edit(8, "main changed line 9")
        self.assertEqual(hs.landed(self.r.wt, "HEAD")["verdict"], "LANDED")

    def test_main_edit_on_the_same_line_needs_the_merged_pr(self):
        head = self.r.feature()
        self.r.squash_to_main()
        self.r.main_edit(1, "main rewrote line 2")
        pr = [{"prNumber": 5, "repo": "acme/x", "branch": "feat"}]
        with mock.patch.object(hs, "gh_json", return_value={"state": "MERGED", "headRefOid": head}) as gh:
            self.assertEqual(hs.landed(self.r.wt, "HEAD", pr)["verdict"], "LANDED (PR #5 merged)")
            self.assertIn("5", gh.call_args[0][0])
        self.assertEqual(hs.landed(self.r.wt, "HEAD")["verdict"], "UNPUSHED 2 (conflicts with main)")

    def test_real_unmerged_commit_is_unpushed_and_named(self):
        self.r.feature(commits=((4, "real work"),))
        res = hs.landed(self.r.wt, "HEAD")
        self.assertEqual(res["verdict"], "UNPUSHED 1")
        self.assertTrue(any("real work" in e for e in res["evidence"]), res)

    def test_landed_worktree_keeps_untracked_and_modified_issues(self):
        self.r.feature()
        self.r.squash_to_main()
        write(os.path.join(self.r.wt, "scratch.txt"), ["x\n"])
        window = {"local_s1": {"cwd": self.r.wt, "title": "lane", "_acct": "a"}}
        rows = hs.worktree_findings(window, window, {})
        self.assertEqual(rows[0]["issues"], ["untracked: scratch.txt"])
        self.assertEqual(rows[0]["landed"]["verdict"], "LANDED")
        edit(os.path.join(self.r.wt, "f.txt"), 9, "dirty")
        rows = hs.worktree_findings(window, window, {})
        self.assertTrue(any(i.startswith("modified: ") for i in rows[0]["issues"]), rows[0]["issues"])


class MainRef(unittest.TestCase):
    def test_master_default_resolves_and_fetches_master(self):
        r = Repo(default="master")
        try:
            self.assertEqual(hs.main_ref(r.work), ("origin/master", "master"))
            r.feature()
            r.squash_to_main()
            res = hs.landed(r.wt, "HEAD")
            self.assertEqual(res["verdict"], "LANDED")
            self.assertFalse(any("fetch failed" in e for e in res["evidence"]))
        finally:
            r.tmp.cleanup()

    def test_origin_head_is_preferred_then_origin_main(self):
        r = Repo()
        try:
            self.assertEqual(hs.main_ref(r.work), ("origin/main", "main"))  # no origin/HEAD yet
            sh(r.work, "remote", "set-head", "origin", "main")
            self.assertEqual(hs.main_ref(r.work), ("origin/main", "main"))
        finally:
            r.tmp.cleanup()

    def test_no_remote_is_unknown_and_stays_in_findings(self):
        r = Repo(remote=False)
        try:
            r.feature()
            self.assertEqual(hs.landed(r.wt, "HEAD")["verdict"], "UNKNOWN (no main ref)")
            window = {"local_s1": {"cwd": r.wt, "title": "lane", "_acct": "a"}}
            rows = hs.worktree_findings(window, window, {})
            self.assertTrue(rows[0]["issues"][0].startswith("UNKNOWN (no main ref)"))
            self.assertTrue(rows[0]["atRisk"])
        finally:
            r.tmp.cleanup()


class RepoMode(unittest.TestCase):
    def test_branch_without_worktree_or_upstream_is_reported(self):
        r = Repo()
        try:
            sh(r.work, "branch", "loose", "main")
            sh(r.work, "checkout", "-q", "loose")
            edit(r.f, 6, "loose work")
            sh(r.work, "commit", "-q", "-am", "loose work")
            sh(r.work, "checkout", "-q", "main")
            rows = hs.repo_findings(r.work, 0, {}, {})
            loose = [x for x in rows if x["branch"] == "loose"]
            self.assertEqual(loose[0]["kind"], "branch")
            self.assertTrue(loose[0]["issues"][0].startswith("UNPUSHED 1"), loose[0]["issues"])
        finally:
            r.tmp.cleanup()


class Ownership(unittest.TestCase):
    def test_quiet_manager_still_owns_the_worktree(self):
        r = Repo()
        try:
            r.feature(commits=((4, "real work"),))
            store = os.path.join(r.tmp.name, "store")
            os.makedirs(os.path.join(store, "acct-1", "org-1"))
            now = time.time()
            for sid, title, last, parent, cwd in (
                    ("local_m0000001", "[Manager] Quiet", now - 30 * 86400, None, "/nowhere"),
                    ("local_k0000001", "Lane", now - 3600, "local_m0000001", r.wt)):
                row = {"sessionId": sid, "title": title, "lastActivityAt": int(last * 1000), "cwd": cwd}
                if parent:
                    row["spawnedFrom"] = {"sessionId": parent}
                with open(os.path.join(store, "acct-1", "org-1", f"{sid}.json"), "w") as fh:
                    json.dump(row, fh)
            since = time.strftime("%Y-%m-%dT%H:%M", time.gmtime(now - 86400))
            out = subprocess.run([sys.executable, "-I", os.path.join(HERE, "handoff_sweep.py"), "--account", "all",
                                  "--since", since, "--handoff-dir", r.tmp.name],
                                 capture_output=True, text=True, env=dict(GIT_ENV, S2C_STORE=store), check=True)
            rows = json.loads(out.stdout)["worktrees"]
            self.assertEqual(rows[0]["ownerSessionId"], "local_m0000001")
        finally:
            r.tmp.cleanup()


U = lambda n: f"{n}{n}{n}{n}{n}{n}{n}{n}-{n}{n}{n}{n}-4{n}{n}{n}-8{n}{n}{n}-{n * 12}"  # noqa: E731
HERE_MGR, OTHER_MGR, OTHER_KID, SHORT_KID = U("1"), U("2"), U("3"), U("4")
A, B = "acct-here", "acct-other"
NOW_MS = 1795000000000


class Schedules(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.store, self.tasks = os.path.join(root, "store"), os.path.join(root, "tasks")
        with open(FIXTURE) as fh:
            text = fh.read().replace("{TASKS}", self.tasks).replace("{HERE_MGR}", HERE_MGR).replace("{OTHER_MGR}", OTHER_MGR)
        reg = json.loads(text)
        here_tasks = [t for t in reg["scheduledTasks"] if t["id"] != "other-registry"]
        self.write_registry(A, dict(reg, scheduledTasks=here_tasks))
        self.write_registry(B, dict(reg, scheduledTasks=[t for t in reg["scheduledTasks"] if t["id"] == "other-registry"]))
        os.makedirs(os.path.join(self.store, A, "org-empty"))
        with open(os.path.join(self.store, A, "org-empty", "scheduled-tasks.json"), "w") as fh:
            json.dump({"recordedSkips": {}}, fh)  # seen live: a registry with no scheduledTasks key
        bodies = {"body-only-target": f"Wake {OTHER_KID} and local_{SHORT_KID[:8]}; also {U('9')}.",
                  "no-target": "Check the dashboard and report."}
        for t in reg["scheduledTasks"]:
            os.makedirs(os.path.join(self.tasks, t["id"]))
            with open(os.path.join(self.tasks, t["id"], "SKILL.md"), "w") as fh:
                fh.write(bodies.get(t["id"], "Run the check."))
        self.rows = {
            f"local_{HERE_MGR}": {"sessionId": f"local_{HERE_MGR}", "title": "[Manager] Here", "_acct": A},
            f"local_{OTHER_MGR}": {"sessionId": f"local_{OTHER_MGR}", "title": "[Manager] Other", "_acct": B},
            "local_aaaa0003": {"sessionId": "local_aaaa0003", "title": "Kid", "_acct": B, "cliSessionId": OTHER_KID,
                               "spawnedFrom": {"sessionId": f"local_{OTHER_MGR}"}},
            f"local_{SHORT_KID}": {"sessionId": f"local_{SHORT_KID}", "title": "Short kid", "_acct": B,
                                   "spawnedFrom": {"sessionId": f"local_{OTHER_MGR}"}},
        }

    def tearDown(self):
        self.tmp.cleanup()

    def write_registry(self, acct, reg):
        d = os.path.join(self.store, acct, "org-1")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "scheduled-tasks.json"), "w") as fh:
            json.dump(reg, fh)

    def sweep(self):
        return {r["taskId"]: r for r in hs.stranded_schedules(self.store, A, self.rows, now_ms=NOW_MS)}

    def test_reader_iterates_the_real_shape(self):
        regs = hs.registries(self.store)
        self.assertEqual(sorted(len(t) for _, _, t in regs), [0, 1, 7])
        with open(FIXTURE) as fh:
            raw = json.load(fh)
        self.assertEqual(sorted(raw), ["dayFieldsOrBoundaryStamped", "recordedSkips", "scheduledTasks",
                                       "sundayAliasBoundaryStamped"])

    def test_cron_task_aimed_at_the_other_account(self):
        row = self.sweep()["cron-other-target"]
        self.assertEqual(row["class"], ["target-elsewhere"])
        self.assertEqual(row["ownerSessionId"], f"local_{OTHER_MGR}")
        self.assertEqual(row["schedule"], "0 6 * * *")

    def test_body_ids_resolve_and_unknown_is_kept(self):
        row = self.sweep()["body-only-target"]
        self.assertIn("target-elsewhere", row["class"])
        self.assertEqual(sorted(t["sessionId"] for t in row["targets"]), sorted(["local_aaaa0003", f"local_{SHORT_KID}"]))
        self.assertEqual(row["unresolved"], [U("9")])
        self.assertEqual(row["ownerSessionId"], f"local_{OTHER_MGR}")

    def test_other_registry_missed_and_no_target(self):
        rows = self.sweep()
        self.assertEqual(rows["other-registry"]["class"], ["registry-elsewhere", "target-elsewhere"])
        self.assertEqual(rows["missed-one-shot"]["class"], ["missed"])
        self.assertIn("still owed", rows["missed-one-shot"]["fix"])
        self.assertEqual(rows["no-target"]["class"], ["no-target"])

    def test_disabled_ran_and_here_live_are_excluded(self):
        rows = self.sweep()
        for tid in ("disabled-cron", "ran-one-shot", "here-live-target"):
            self.assertNotIn(tid, rows)

    def test_stranded_here_task_does_not_suppress_a_sibling(self):
        rows = self.sweep()
        self.assertIn("cron-other-target", rows)
        self.assertIn("body-only-target", rows)  # same owner as cron-other-target, both stay

    def test_here_task_naming_the_here_owner_suppresses_the_other_registry_row(self):
        with open(os.path.join(self.store, B, "org-1", "scheduled-tasks.json")) as fh:
            reg = json.load(fh)
        reg["scheduledTasks"][0]["notifySessionId"] = f"local_{HERE_MGR}"
        self.write_registry(B, reg)
        self.assertNotIn("other-registry", self.sweep())  # here-live-target already wakes that owner

    def test_recreated_here_suppresses_the_row(self):
        with open(os.path.join(self.store, A, "org-1", "scheduled-tasks.json")) as fh:
            reg = json.load(fh)
        reg["scheduledTasks"].append({"id": "recreated", "cronExpression": "0 5 * * *", "enabled": True,
                                      "filePath": os.path.join(self.tasks, "other-registry", "SKILL.md"),
                                      "notifySessionId": f"local_{HERE_MGR}"})
        self.write_registry(A, reg)
        self.assertNotIn("other-registry", self.sweep())


def binding(n, repo="acme/shop", state="OPEN", **kw):
    return dict({"prNumber": n, "repo": repo, "state": state, "branch": f"b{n}", "autoFix": True}, **kw)


class Bindings(unittest.TestCase):
    SINCE = 1_000_000

    def rows(self, here_prs=(), other_prs=(), here_last=2_000_000, other_last=2_000_000):
        return {
            "local_om": {"sessionId": "local_om", "title": "[Manager] Other", "_acct": B, "lastActivityAt": other_last},
            "local_ob": {"sessionId": "local_ob", "title": "Bound", "_acct": B, "lastActivityAt": other_last,
                         "prs": list(other_prs), "spawnedFrom": {"sessionId": "local_om"}},
            "local_hb": {"sessionId": "local_hb", "title": "Here", "_acct": A, "lastActivityAt": here_last,
                         "prs": list(here_prs)},
        }

    def sweep(self, rows, live=None):
        with mock.patch.object(hs, "gh_json", side_effect=lambda args: {"state": live} if live else None):
            return hs.stranded_bindings(rows, A, self.SINCE)

    def test_open_pr_bound_only_elsewhere_is_stranded(self):
        out = self.sweep(self.rows(other_prs=[binding(7)]), live="OPEN")
        self.assertEqual((out[0]["pr"], out[0]["state"], out[0]["ownerSessionId"]), (7, "OPEN", "local_om"))
        self.assertEqual(out[0]["boundSession"]["sessionId"], "local_ob")

    def test_here_binding_clears_it_even_old_or_case_different(self):
        rows = self.rows(other_prs=[binding(7)], here_prs=[binding(7, repo="Acme/Shop")], here_last=10)
        self.assertEqual(self.sweep(rows, live="OPEN"), [])

    def test_here_entry_without_autofix_is_not_a_binding(self):
        here = binding(7)
        del here["autoFix"]
        self.assertEqual(len(self.sweep(self.rows(other_prs=[binding(7)], here_prs=[here]), live="OPEN")), 1)

    def test_dismissed_and_non_autofix_bindings_are_excluded(self):
        self.assertEqual(self.sweep(self.rows(other_prs=[binding(7, dismissed=True)]), live="OPEN"), [])
        self.assertEqual(self.sweep(self.rows(other_prs=[binding(7, autoFix=False)]), live="OPEN"), [])
        bare = binding(7)
        del bare["autoFix"]
        self.assertEqual(self.sweep(self.rows(other_prs=[bare]), live="OPEN"), [])

    def test_closed_and_old_merged_are_excluded(self):
        self.assertEqual(self.sweep(self.rows(other_prs=[binding(7)]), live="CLOSED"), [])
        old = self.rows(other_prs=[binding(7, state="MERGED")], other_last=10)
        self.assertEqual(self.sweep(old, live="MERGED"), [])
        fresh = self.sweep(self.rows(other_prs=[binding(7, state="MERGED")]), live="MERGED")
        self.assertEqual(fresh[0]["state"], "MERGED")

    def test_live_state_overrides_the_stored_one(self):
        self.assertEqual(self.sweep(self.rows(other_prs=[binding(7)]), live="CLOSED"), [])
        out = self.sweep(self.rows(other_prs=[binding(7)]), live="MERGED")
        self.assertEqual((out[0]["state"], out[0]["storedState"]), ("MERGED", "OPEN"))
        old = self.rows(other_prs=[binding(7)], other_last=10)
        self.assertEqual(self.sweep(old, live="MERGED"), [])

    def test_gh_failure_uses_the_stored_state(self):
        out = self.sweep(self.rows(other_prs=[binding(7)]), live=None)
        self.assertTrue(out[0]["stateUnverified"])


if __name__ == "__main__":
    unittest.main()
