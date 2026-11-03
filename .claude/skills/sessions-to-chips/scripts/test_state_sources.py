#!/usr/bin/env python3
"""Hermetic tests for state_sources.py and state_arch.py. gh, git, Archify and the red-main command are a
recorded-fixture runner; every path is a temp dir. The deploy fixtures are real gh responses, de-identified.

Run: python3 -m unittest test_state_sources
"""
import glob
import json
import os
import shutil
import sys
import tempfile
import types
import unittest

# One temp root shared with test_render_state, because the store reads its paths once at import.
TMP = os.environ.setdefault("STATE_PAGE_TEST_TMP", tempfile.mkdtemp(prefix="state-page-test-"))
os.environ.update({"S2C_CLAUDE_HOME": TMP, "WORK_STATE_PROGRAMS": os.path.join(TMP, "orchestrator", "programs"),
                   "WORK_STATE_DIR": os.path.join(TMP, "ws")})
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import state_arch as sa  # noqa: E402
import state_sources as ss  # noqa: E402

with open(os.path.join(HERE, "fixtures", "state_sources", "gh-deploys.recorded.json")) as fh:
    REC = json.load(fh)
REPO = "acme/shop"
M = "a" * 40   # the merge under test
D1 = "d" * 40  # a deploy that holds M
SURFACE = {"name": "backend", "kind": "deployment", "environment": "prod", "proof_step": "Deploy stack",
           "paths": ["apps/backend/**", "packages/sdk/**"]}
CUSTOMERS = {"name": "customers", "kind": "job", "workflow": "deploy.yml", "job": "deploy-customers / sync",
             "proof_step": "Sync non-org content to S3 (templates, catalog)", "paths": ["apps/customers/**"]}


class Fake:
    """A recorded-fixture runner: the first route whose every needle is in the joined argv answers."""

    def __init__(self, *routes):
        self.routes, self.calls = list(routes), []

    def __call__(self, argv, capture_output=True, text=True, timeout=None, cwd=None, env=None, **_):
        self.calls.append(" ".join(argv))
        joined = " ".join(argv)
        for needles, res in self.routes:
            if all(n in joined for n in needles):
                rc, out, err = res(argv) if callable(res) else res
                return types.SimpleNamespace(returncode=rc, stdout=out if isinstance(out, str) else json.dumps(out),
                                             stderr=err)
        return types.SimpleNamespace(returncode=1, stdout="", stderr="no route: " + joined)


def gh(fake):
    return ss.Runner(ss.Deadline(60), fake)


def status(state, job):
    return {"state": state, "log_url": f"https://github.com/{REPO}/actions/runs/1/job/{job}", "created_at": "2026-11-03T10:00:00Z"}


class DeployedPerSurface(unittest.TestCase):
    def test_a_success_record_whose_proof_step_skipped_is_walked_past(self):
        skipped = REC["deployment_skipped"]
        fake = Fake((["deployments?environment=prod"], (0, [skipped, {"id": 2, "sha": D1}], "")),
                    ([f"deployments/{skipped['id']}/statuses"], (0, REC["deployment_skipped_status"], "")),
                    (["deployments/2/statuses"], (0, status("success", 22), "")),
                    (["actions/jobs/126014779654"], (0, REC["job_deploy_step_skipped"], "")),
                    (["actions/jobs/22"], (0, REC["job_deploy_step_ran"], "")))
        walk = ss.deployment_walk(gh(fake), REPO, SURFACE)
        self.assertEqual(walk["proven"]["sha"], D1, "the green record with a skipped Deploy stack is not proof")
        self.assertEqual(len(walk["skipped"]), 1)
        self.assertIn("did not run", walk["skipped"][0]["why"])

    def test_a_skipped_customers_sync_is_walked_past(self):
        runs = [{"databaseId": 41683280394, "headSha": "b" * 40, "headBranch": "main", "conclusion": "success",
                 "status": "completed", "url": "u1"},
                {"databaseId": 41666653246, "headSha": D1, "headBranch": "main", "conclusion": "success",
                 "status": "completed", "url": "u2"},
                {"databaseId": 9, "headSha": "c" * 40, "headBranch": "feature", "conclusion": "success", "status": "completed"}]
        fake = Fake((["run list"], (0, runs, "")),
                    (["run view 41683280394"], (0, REC["run_customers_sync_skipped"], "")),
                    (["run view 41666653246"], (0, REC["run_customers_sync_ran"], "")))
        walk = ss.job_walk(gh(fake), REPO, CUSTOMERS, "main")
        self.assertEqual(walk["proven"]["sha"], D1)
        self.assertEqual(walk["walked"], 2, "a run off main is filtered out here, never trusted to the search")

    def test_an_exhausted_search_reads_not_established_never_not_deployed(self):
        skipped = REC["deployment_skipped"]
        fake = Fake((["deployments?environment=prod"], (0, [skipped], "")),
                    ([f"deployments/{skipped['id']}/statuses"], (0, REC["deployment_skipped_status"], "")),
                    (["actions/jobs/"], (0, REC["job_deploy_step_skipped"], "")))
        walk = ss.deployment_walk(gh(fake), REPO, SURFACE)
        self.assertTrue(walk["exhausted"])
        self.assertIsNone(walk["proven"])
        state = ss.surface_state(M, {"files": ["apps/backend/x.ts"], "complete": True}, SURFACE, walk, lambda m, d: False)
        self.assertEqual(state["state"], "not_established")

    def test_deploying_and_failed_need_the_merge_inside_that_sha(self):
        walk = {"proven": {"sha": "0" * 40}, "pending": [{"sha": D1, "url": "p"}], "failed": None}
        files = {"files": ["apps/backend/x.ts"], "complete": True}
        inside = lambda m, d: d == D1  # noqa: E731
        self.assertEqual(ss.surface_state(M, files, SURFACE, walk, inside)["state"], "deploying")
        self.assertEqual(ss.surface_state(M, files, SURFACE, walk, lambda m, d: False)["state"], "not_established")
        walk = {"proven": None, "pending": [], "failed": {"sha": D1, "url": "f"}}
        self.assertEqual(ss.surface_state(M, files, SURFACE, walk, inside)["state"], "failed")

    def test_not_affected_needs_a_complete_file_list_that_misses_every_glob(self):
        walk = {"proven": {"sha": D1}, "pending": [], "failed": None}
        yes = lambda m, d: True  # noqa: E731
        self.assertEqual(ss.surface_state(M, {"files": ["docs/x.md"], "complete": True}, SURFACE, walk, yes)["state"], "na")
        self.assertEqual(ss.surface_state(M, {"files": ["docs/x.md"], "complete": False}, SURFACE, walk, yes)["state"], "cannot_tell")
        self.assertEqual(ss.surface_state(M, None, SURFACE, walk, yes)["state"], "cannot_tell")
        self.assertEqual(ss.surface_state(M, {"files": ["apps/backend/a/b.ts"], "complete": True}, SURFACE, walk, yes)["state"], "deployed")

    def test_ancestry_falls_back_to_compare_when_git_lacks_the_objects(self):
        fake = Fake((["merge-base"], (128, "", "fatal: Not a valid commit name")),
                    (["compare/"], (0, "ahead\n", "")))
        anc = ss.Ancestry(gh(fake), REPO, TMP, {})
        self.assertTrue(anc(M, D1))
        self.assertTrue(anc(M, D1))
        self.assertEqual(sum("compare/" in c for c in fake.calls), 1, "an answer for an immutable pair is kept")


class RedMain(unittest.TestCase):
    CFG = {"repo": REPO, "path": TMP, "red_main_cmd": ["main-health", "--json"]}

    def test_no_command_reads_unavailable_with_its_reason(self):
        out = ss.red_main(gh(Fake()), dict(self.CFG, red_main_cmd=None, red_main_unproven="T-9 owes a read verb"), {}, 0)
        self.assertEqual(out["state"], "unavailable")
        self.assertIn("T-9", out["why"])

    def test_red_under_a_green_health_run_reads_red_and_never_asks_the_workflow(self):
        fake = Fake((["main-health"], (0, {"schema": 1, "state": "red", "sha": D1, "owners": [], "claim": None}, "")),
                    (["run list"], (0, [{"conclusion": "success", "headBranch": "main"}], "")))
        out = ss.red_main(gh(fake), self.CFG, {}, 0)
        self.assertEqual((out["state"], out["owners"]), ("red", []))
        self.assertFalse(any("run list" in c or "main-health.yml" in c for c in fake.calls))

    def test_empty_or_off_contract_output_is_unavailable_and_a_problem(self):
        for out in ("", '{"state": "green"}', "not json"):
            res = ss.red_main(gh(Fake((["main-health"], (0, out, "")))), self.CFG, {}, 0)
            self.assertEqual(res["state"], "unavailable", out)
            self.assertTrue(res.get("problem"))


class TicketPrs(unittest.TestCase):
    def test_keeps_only_whole_token_matches_and_counts_a_pr_once(self):
        rows = [{"number": 1, "title": "feat(x): T-12 and T-13 together", "headRefName": "feat/t-12"},
                {"number": 12, "title": "unrelated", "headRefName": "x"},
                {"number": 3, "title": "T-120 is not T-12's", "headRefName": "y"}]
        kept = ss.keep_rows(rows, ["T-12", "T-13"])
        self.assertEqual(sorted(kept), [1, 3])
        self.assertEqual(kept[1]["tickets"], ["T-12", "T-13"])

    def test_a_full_page_is_split_and_rerun_never_read_as_complete(self):
        full = [{"number": n, "title": f"T-1 {n}", "headRefName": "b"} for n in range(100)]

        def answer(argv):
            q = argv[argv.index("--search") + 1]
            return (0, full if " OR " in q else [{"number": 1, "title": q, "headRefName": "b"}], "")
        rows, fail, short = ss.search_batch(gh(Fake((["pr list"], answer))), REPO, ["T-1", "T-2"])
        self.assertIsNone(fail)
        self.assertEqual(short, [])
        self.assertEqual(len(rows), 2)

    def test_gh_failures_are_classified_with_their_fix(self):
        self.assertEqual(ss.gh_failure(1, "HTTP 401: Bad credentials")["kind"], "auth")
        self.assertEqual(ss.gh_failure(1, "API rate limit exceeded")["kind"], "rate")
        self.assertEqual(ss.gh_failure(1, "GraphQL: Could not resolve to a Repository")["kind"], "missing")
        self.assertTrue(ss.gh_failure(1, "HTTP 403: Resource not accessible")["fix"])
        self.assertEqual(ss.gh_failure(None, "timed out")["kind"], "timeout")


class Overlap(unittest.TestCase):
    def test_globs_cross_directories_and_generated_and_same_pr_pairs_drop(self):
        mine = {REPO: {"prs": {"7": ["apps/a/b/c.ts", "pnpm-lock.yaml"]}, "paths": []}}
        others = [{"program": "p2", "holdings": {REPO: {"prs": {"9": ["pnpm-lock.yaml"]}, "paths": ["apps/a/**"]}}},
                  {"program": "p3", "holdings": {REPO: {"prs": {"7": ["apps/a/b/c.ts"]}, "paths": []}}},
                  {"program": "p4", "holdings": {"other/repo": {"prs": {"1": ["apps/a/b/c.ts"]}, "paths": []}}}]
        rows = ss.overlap(mine, others)
        self.assertEqual([r["program"] for r in rows], ["p2"])
        self.assertEqual(rows[0]["theirs"], ["bound paths"])

    def test_glob_matching(self):
        self.assertTrue(ss.glob_re("apps/**").match("apps/x/y/z.ts"))
        self.assertTrue(ss.glob_re("**/auth/**").match("apps/backend/auth/x.ts"))
        self.assertFalse(ss.glob_re("apps/*.ts").match("apps/x/y.ts"))
        self.assertTrue(ss.paths_overlap("apps/backend/**", "apps/**"))
        self.assertFalse(ss.paths_overlap("apps/portal/**", "apps/backend/**"))


class Skills(unittest.TestCase):
    def test_rules_fire_once_per_ref_and_skills_done_silences(self):
        prs = [{"number": n, "repo": REPO, "title": f"fix(x): T-1 part {n}", "mergedAt": "2026-11-01T00:00:00Z",
                "tickets": ["T-1"], "additions": 300, "deletions": 0, "files": ["apps/auth/x.ts"], "state": "MERGED"}
               for n in range(3)]
        view = {"design": [{"what": "spec", "kind": "spec", "ref": "#9"}],
                "incidents": [{"what": "a", "cause": "Runner died"}, {"what": "b", "cause": "runner died", "rca": "r.md"}]}
        cfg = [{"repo": REPO, "security_paths": ["**/auth/**"]}]
        items = [{"ticket": "T-1", "state": "closed"}]
        got = {(s["skill"], s["ref"]) for s in ss.skills(prs, view, cfg, items, 0, set())}
        for want in (("/improve-codebase-architecture", "T-1"), ("/spec-review", "#9"), ("/root-cause-analysis", "a"),
                     ("/root-cause-analysis", "Runner died"), ("/security-review", "#0"), ("/standards-spec-review", "T-1")):
            self.assertIn(want, got)
        quiet = ss.skills(prs, view, cfg, items, 0, {("/spec-review", "#9")})
        self.assertNotIn(("/spec-review", "#9"), {(s["skill"], s["ref"]) for s in quiet})


class Ladder(unittest.TestCase):
    PR = {"state": "MERGED", "mergedAt": "2026-11-03T10:00:00Z", "mergeCommit": {"oid": M},
          "surfaces": [{"surface": "backend", "state": "deployed"}, {"surface": "portal", "state": "na"}]}

    def test_merged_never_reads_live(self):
        lad = ss.ladder(self.PR, None, {"verdict": None}, True)
        self.assertEqual((lad["step"], lad["final"], lad["steps"]["exposure"]["state"]), ("deployed", False, "unstated"))
        self.assertFalse(ss.ladder(self.PR, {"state": "dark"}, {"verdict": None}, True)["final"])
        self.assertTrue(ss.ladder(self.PR, {"state": "live"}, {"verdict": None}, True)["final"])

    def test_no_surfaces_means_merged_is_final(self):
        lad = ss.ladder(dict(self.PR, surfaces=[]), None, {"verdict": None}, False)
        self.assertEqual((lad["step"], lad["final"], lad.get("no_deploy_step")), ("merged", True, True))

    def test_a_canceled_bake_is_not_a_pass(self):
        items = [{"ticket": "T-2", "bake_verdict": "fail", "bake_ended": "canceled"}]
        bake = ss.bake_of(["T-2"], items, [])
        self.assertEqual((bake["verdict"], bake["canceled"], bake["owed"]), ("fail", True, True))
        self.assertFalse(ss.ladder(self.PR, {"state": "live"}, bake, True)["final"])


ARCH_VIEW = {"schema_version": 1, "diagram_type": "architecture", "meta": {"title": "t", "output": "x.html"},
             "components": [{"id": "a", "type": "backend", "label": "A"}], "connections": []}


def archify_fake(calls):
    def run(cmd, **kw):
        calls.append((cmd, kw.get("env") or {}))
        out = cmd[cmd.index("--receipt") - 1] if "--receipt" in cmd else cmd[-2]
        with open(out, "w") as fh:
            fh.write("<html>diagram</html>")
        if "--receipt" in cmd:
            with open(cmd[cmd.index("--receipt") + 1], "w") as fh:
                json.dump({"summary": {"components": {"added": 3, "changed": 1, "removed": 0}}}, fh)
        return types.SimpleNamespace(returncode=0, stdout="{}", stderr="")
    return run


class Arch(unittest.TestCase):
    def setUp(self):
        self.programs = os.path.join(TMP, "orchestrator", "programs")
        for p in glob.glob(os.path.join(self.programs, "p.arch*")):
            shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else os.unlink(p)
        os.makedirs(self.programs, exist_ok=True)
        fake_bin = os.path.join(TMP, "archify.mjs")
        open(fake_bin, "w").close()
        os.environ["STATE_ARCH_ARCHIFY"] = fake_bin
        os.environ["ARCHIFY_BRAND_ALLOW_PRIVATE"] = "1"

    def tearDown(self):
        os.environ.pop("ARCHIFY_BRAND_ALLOW_PRIVATE", None)
        os.environ.pop("STATE_ARCH_ARCHIFY", None)

    def write(self, doc):
        with open(os.path.join(self.programs, "p.arch.json"), "w") as fh:
            json.dump(doc, fh)

    def test_refuses_meta_repository_and_unknown_shapes(self):
        bad = dict(ARCH_VIEW, meta=dict(ARCH_VIEW["meta"], repository={"name": "x"}))
        errs = sa.validate({"views": [{"id": "s", "type": "architecture", "head": bad}]})
        self.assertTrue(any("meta.repository" in e for e in errs))
        self.assertTrue(sa.validate({"views": [{"id": "s", "type": "sequence", "base": ARCH_VIEW, "head": ARCH_VIEW}]}))
        self.assertTrue(sa.validate({"views": []}))

    def test_builds_once_per_hash_strips_the_private_flag_and_archives_versions(self):
        calls = []
        self.write({"updated_at": "2026-11-03T10:00:00Z", "views": [{"id": "system", "type": "architecture", "base": ARCH_VIEW, "head": ARCH_VIEW}]})
        index, problems = sa.build("p", run=archify_fake(calls))
        self.assertEqual(problems, [])
        self.assertEqual(len(calls), 1)
        self.assertNotIn("ARCHIFY_BRAND_ALLOW_PRIVATE", calls[0][1])
        self.assertNotIn("--repo-root", calls[0][0])
        self.assertEqual(index["versions"][0]["views"][0]["summary"], {"added": 3, "changed": 1, "removed": 0})
        sa.build("p", run=archify_fake(calls))
        self.assertEqual(len(calls), 1, "an unchanged hash does not rebuild")
        self.write({"updated_at": "2026-11-03T11:00:00Z", "views": [{"id": "system", "type": "sequence", "head": ARCH_VIEW}]})
        sa.build("p", run=archify_fake(calls))
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1][0][2], "deliver")

    def test_archived_diagrams_survive_cache_loss(self):
        calls = []
        self.write({"updated_at": "2026-11-03T10:00:00Z", "views": [{"id": "system", "type": "architecture", "head": ARCH_VIEW}]})
        sa.build("p", run=archify_fake(calls))
        self.write({"updated_at": "2026-11-03T11:00:00Z", "views": [{"id": "system", "type": "architecture", "base": ARCH_VIEW, "head": ARCH_VIEW}]})
        sa.build("p", run=archify_fake(calls))
        shutil.rmtree(os.path.join(TMP, "ws"), ignore_errors=True)  # every derived cache gone
        section = sa.page_section("p")
        self.assertTrue(section["current"]["built"])
        self.assertEqual(len(section["archived"]), 1)
        self.assertTrue(section["archived"][0]["views"][0]["file"].startswith("p.arch/"))
        with open(os.path.join(self.programs, "p.arch", f"{section['archived'][0]['sha']}.json")) as fh:
            self.assertEqual(json.load(fh)["updated_at"], "2026-11-03T10:00:00Z")

    def test_a_failed_build_is_not_marked_built_and_retries(self):
        self.write({"views": [{"id": "system", "type": "architecture", "head": ARCH_VIEW}]})
        fail = lambda cmd, **kw: types.SimpleNamespace(returncode=2, stdout="", stderr="layout error")  # noqa: E731
        index, problems = sa.build("p", run=fail)
        self.assertFalse(index["versions"][0]["built"])
        self.assertIn("layout error", problems[0])
        calls = []
        sa.build("p", run=archify_fake(calls))
        self.assertEqual(len(calls), 1)
        self.assertTrue(sa.page_section("p")["current"]["built"])

    def test_absent_file_reads_no_diagram_yet(self):
        section = sa.page_section("p")
        self.assertIsNone(section["current"])
        self.assertEqual(section["reason"], "No system diagram yet")


if __name__ == "__main__":
    unittest.main(verbosity=1)
