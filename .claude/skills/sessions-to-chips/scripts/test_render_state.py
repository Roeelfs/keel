#!/usr/bin/env python3
"""Hermetic tests for render_state.py, state_view.py and state_index.py. Every path is a temp dir; the engine
is real and reads a tracker fixture; gh and git are a recorded-fixture runner. One class uses the real Stop
guard and skips where it is not installed. A budget class checks real rendered pages when
STATE_VIEW_BUDGET_DIR names their programs dir
and STATE_VIEW_BUDGET_PROGRAMS lists the slugs.

Run: python3 -m unittest test_render_state
"""
import datetime as dt
import glob
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout

# One temp root shared with test_state_sources, because the store reads its paths once at import.
TMP = os.environ.setdefault("STATE_PAGE_TEST_TMP", tempfile.mkdtemp(prefix="state-page-test-"))
PROGRAMS = os.path.join(TMP, "orchestrator", "programs")
WS = os.path.join(TMP, "ws")
REAL_GUARD = os.path.join(os.path.expanduser("~/.claude"), "scripts", "manager_arm_guard.py")
os.environ.update({"S2C_CLAUDE_HOME": TMP, "S2C_STORE": os.path.join(TMP, "store"),
                   "S2C_SESSION_INDEX": os.path.join(TMP, "index.json"), "WORK_STATE_PROGRAMS": PROGRAMS,
                   "WORK_STATE_DIR": WS, "WORK_STATE_LANE_ROWS": os.path.join(TMP, "lanes.jsonl"),
                   "WORK_STATE_ANALYTICS": os.path.join(TMP, "analytics.jsonl"),
                   "WORK_STATE_GUARD_SCRIPT": REAL_GUARD, "RENDER_STATE_NO_OPEN": "1"})
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import render_state as rs  # noqa: E402
import state_index as si  # noqa: E402
import state_view as sv  # noqa: E402

NOW = dt.datetime(2026, 11, 3, 12, 0, tzinfo=dt.timezone.utc)
REPO = "acme/shop"
SHA_M, SHA_D = "a" * 40, "d" * 40
VIEW = {"updated_at": "2026-11-03T11:00:00Z", "destination": "The shop takes orders in production.",
        "outcomes": [{"outcome": "Orders are accepted", "tickets": ["TKT-2"]},
                     {"outcome": "Orders are paid", "tickets": ["TKT-4"]}],
        "needs_you": [{"ask": "Merge it?", "recommended": "Yes"}],
        "decisions": [{"date": "2026-11-02T10:00:00Z", "decision": "Use one template", "why": "One owner", "by": "founder"}],
        "dead_ends": [{"date": "2026-11-01T10:00:00Z", "what": "A second page", "why": "two owners"}]}
AT_WAKE = """## AT-WAKE
Status: DONE
Next action: stale old action

## AT-WAKE
Status: WORKING
Wake: ScheduleWakeup fires 2026-11-03T12:30:00Z (1800s) on CI; on fire: read the CI result
Next action: grade the lane
Owner: manager
"""


def child(ticket, stype, kind="task", blocked_by=(), order=0):
    return {"ticket": ticket, "title": f"Title {ticket}", "order": order, "created_at": "2026-11-01T00:00:00Z",
            "updated_at": "2026-11-01T00:00:00Z", "state": {"type": stype, "name": stype}, "kind": kind,
            "kind_inferred": False, "blocked_by": [{"ticket": b, "state": {"type": "completed"}} for b in blocked_by],
            "blocks": [], "errors": []}


def tracker_fixture(bake_state="canceled"):
    kids = [child("TKT-2", "completed", "ship", order=1), child("TKT-3", bake_state, "bake", ["TKT-2"], 2),
            child("TKT-4", "backlog", "task", order=3), child("TKT-5", "completed", "task", order=4)]
    data = {"schema": "work-state-tracker/1", "map": {"ticket": "TKT-1", "title": "Map", "state": {"type": "started", "name": "x"}},
            "taken_at": "2026-11-03T11:59:00Z", "children_count": len(kids), "page_size": 50, "truncated": False,
            "requests": [], "children": kids}
    path = os.path.join(TMP, f"tracker-{bake_state}.json")
    with open(path, "w") as fh:
        json.dump(data, fh)
    return path


REPOS = [{"repo": REPO, "path": TMP, "ticket_pattern": "TKT-\\d+", "main": "main", "red_main_cmd": None,
          "red_main_unproven": "no read-only main-health verb yet",
          "surfaces": [{"name": "backend", "kind": "deployment", "environment": "prod", "proof_step": "Deploy stack",
                        "paths": ["apps/backend/**"]}], "security_paths": ["**/auth/**"]}]


def view_block(obj):
    body = obj if isinstance(obj, str) else json.dumps(obj, indent=1)
    return f"## VIEW\n```json\n{body}\n```\n"


def write_program(slug, manifest=None, state=None, events=None, bake_state="canceled", repos=REPOS):
    os.makedirs(PROGRAMS, exist_ok=True)
    base = os.path.join(PROGRAMS, slug)
    default = {"program": slug, "goal": "Reach the destination", "manager_session": "local_x",
               "map": {"issue": "TKT-1", "url": "https://tracker.example/issue/TKT-1", "project": "",
                       "snapshot_cmd": ["cat", tracker_fixture(bake_state)]},
               "ceded": [], "shared_touch_not_owned": [], "gates_held_by_manager": ["prod merge"],
               "bindings": [{"ticket": "TKT-4", "bound_at": "2026-11-03T11:00:00Z", "bake": "required",
                             "carriers": [{"type": "lane", "id": "lane-a", "bound_at": "2026-11-03T11:00:00Z"}]}],
               "updated_at": "2026-11-03T11:00:00Z"}
    if repos is not None:
        default["repos"] = repos
    with open(base + ".json", "w") as fh:
        json.dump(default if manifest is None else manifest, fh)
    with open(base + ".state.md", "w") as fh:
        fh.write(AT_WAKE + "\n" + view_block(VIEW) if state is None else state)
    with open(base + ".events.jsonl", "w") as fh:
        fh.write(events if events is not None else '{"ts":"2026-11-03T10:00:00Z","event":"dispatched","note":"go"}\n')
    return base


class GhFake:
    """Recorded-fixture runner for gh and git. One merged PR for TKT-2, deployed at SHA_D whose Deploy stack ran."""

    def __init__(self, merged_at="2026-11-03T11:30:00Z", fail=None, files=("apps/backend/orders.ts",)):
        self.merged_at, self.fail, self.files, self.calls = merged_at, fail, list(files), []

    def __call__(self, argv, capture_output=True, text=True, timeout=None, cwd=None, **_):
        j = " ".join(argv)
        self.calls.append(j)
        if self.fail and argv[0] == "gh":
            return self.res(1, "", self.fail)
        if "pr list" in j and "--search" in j:
            return self.res(0, [{"number": 7, "title": "feat(orders): TKT-2 accept orders", "headRefName": "feat/tkt-2",
                                 "state": "MERGED", "isDraft": False, "mergedAt": self.merged_at,
                                 "mergeCommit": {"oid": SHA_M}, "additions": 10, "deletions": 2, "updatedAt": self.merged_at},
                                {"number": 8, "title": "feat(pay): TKT-4 pay", "headRefName": "feat/tkt-4", "state": "OPEN",
                                 "isDraft": False, "mergedAt": None, "mergeCommit": None, "additions": 5, "deletions": 0,
                                 "updatedAt": "2026-11-03T11:40:00Z"},
                                {"number": 4, "title": "unrelated work", "headRefName": "x", "state": "MERGED",
                                 "mergedAt": "2026-10-01T00:00:00Z"}])
        if "pr list" in j and "--state open" in j:
            return self.res(0, [{"number": 8, "files": [{"path": "apps/pay/a.ts", "additions": 5, "deletions": 0}],
                                 "additions": 5, "deletions": 0}])
        if "pr view 7" in j and "files" in j:
            return self.res(0, {"files": [{"path": f} for f in self.files]})
        if "deployments?environment=prod" in j:
            return self.res(0, [{"id": 1, "sha": SHA_D, "created_at": "2026-11-03T11:45:00Z"}])
        if "deployments/1/statuses" in j:
            return self.res(0, {"state": "success", "log_url": f"https://github.com/{REPO}/actions/runs/5/job/55",
                                "created_at": "2026-11-03T11:50:00Z"})
        if "actions/jobs/55" in j:
            return self.res(0, {"name": "deploy", "steps": [{"name": "Deploy stack", "conclusion": "success"}]})
        if "merge-base --is-ancestor" in j:
            return self.res(0 if argv[-2] == SHA_M and argv[-1] == SHA_D else 1, "")
        return self.res(1, "", "no route: " + j)

    @staticmethod
    def res(rc, out, err=""):
        return types.SimpleNamespace(returncode=rc, stdout=out if isinstance(out, str) else json.dumps(out), stderr=err)


def render(slug, fake=None, argv=()):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = rs.main(["--program", slug, *argv], run=fake or GhFake())
    line = buf.getvalue().strip().splitlines()
    return rc, (json.loads(line[-1]) if line else None)


def payload_of(path):
    with open(path) as fh:
        html = fh.read()
    m = re.search(r'<script id="state-payload" type="application/json">(.*?)</script>', html, re.S)
    return html, json.loads(m.group(1))


def tree_hash(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def clean_derived():
    shutil.rmtree(WS, ignore_errors=True)
    for p in glob.glob(os.path.join(PROGRAMS, "*.state.html")) + glob.glob(os.path.join(PROGRAMS, "*.state.json")):
        os.unlink(p)


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


class Template(unittest.TestCase):
    def setUp(self):
        with open(rs.TEMPLATE) as fh:
            self.text = fh.read()

    def test_loads_nothing_from_the_network(self):
        for pattern in (r"<link\b", r"@import", r"url\(", r"\bsrc\s*=", r"\bfetch\(", r"XMLHttpRequest", r"srcdoc"):
            self.assertIsNone(re.search(pattern, self.text), pattern)

    def test_the_only_iframe_src_is_a_relative_sibling(self):
        sets = re.findall(r"setAttribute\('src',\s*(\w+)\)", self.text)
        self.assertEqual(sets, ["file"])
        guard = re.search(r"var DIAGRAM_SRC = /(.+)/;", self.text).group(1)
        self.assertTrue(re.match(guard, "p.arch/0123456789ab/system.html"))
        for bad in ("https://x.test/a.html", "/etc/a.html", "../p.arch/0123456789ab/a.html", "file:///a.html"):
            self.assertIsNone(re.match(guard, bad), bad)
        self.assertIn("if (DIAGRAM_SRC.test(file)) frame.setAttribute('src', file)", self.text)

    def test_data_never_reaches_markup(self):
        for bad in ("innerHTML", "insertAdjacentHTML", "document.write", "outerHTML"):
            self.assertNotIn(bad, self.text)

    def test_no_em_or_en_dash(self):
        self.assertNotIn("—", self.text)
        self.assertNotIn("–", self.text)

    def test_states_that_must_never_be_upgraded_have_their_words(self):
        for words in ("Exposure unstated", "Deploy not established", "Main health unavailable", "Red, no owner",
                      "Ticket records bake pass", "Bake canceled", "Cannot tell", "unknown"):
            self.assertIn(words, self.text)


class ViewBlock(unittest.TestCase):
    def read(self, text):
        problems = []
        out = sv.read_view(text, NOW, problems)
        return out["view"], out["legacy"], [p["detail"] for p in problems]

    def test_valid_v2_block(self):
        view, legacy, problems = self.read(view_block(VIEW))
        self.assertEqual((view, legacy, problems), (VIEW, [], []))

    def test_last_block_wins(self):
        view, _, _ = self.read(view_block({"destination": "old"}) + "## Other\n" + view_block({"destination": "new"}))
        self.assertEqual(view["destination"], "new")

    def test_every_bad_input_is_reported_never_dropped_silently(self):
        for body, needle in (("{not json", "not valid JSON"), ("[1]", "must be an object"),
                             ('{"surprise": 1}', "unknown key `surprise`"), ('{"outcomes": "x"}', "`outcomes` must be a list"),
                             ('{"destination": 3}', "`destination` must be text"),
                             ('{"design": [{"what": "w", "kind": "essay"}]}', "design[0].kind must be one of"),
                             ('{"exposure": [{"ref": "#1", "state": "on"}]}', "exposure[0].state must be one of"),
                             ('{"decisions": [{"decision": "d", "date": "2026-11-03"}]}', "RFC3339"),
                             ('{"decisions": [{"decision": "d", "date": "2027-01-01T00:00:00Z"}]}', "in the future"),
                             ('{"updated_at": "2026-11-03"}', "RFC3339"),
                             ('{"outcomes": [{"outcome": "o", "extra": 1}]}', "unknown keys ['extra']")):
            _, _, problems = self.read(view_block(body))
            self.assertTrue(any(needle in p for p in problems), (body, problems))

    def test_v1_keys_stay_visible_and_name_their_v2_home(self):
        _, legacy, problems = self.read(view_block({"explanation": "Builds it.", "proven": [{"claim": "c", "evidence": "e"}]}))
        self.assertEqual({(x["key"], x["home"]) for x in legacy},
                         {("explanation", "destination"), ("proven", "the derived Production truth")})
        self.assertEqual(legacy[0]["text"] if legacy[0]["key"] == "explanation" else legacy[1]["text"], ["Builds it."])
        self.assertTrue(any("v1 key; move it to destination" in p for p in problems))


class Grills(unittest.TestCase):
    def setUp(self):
        self.dir = os.path.join(TMP, "orchestrator", "grills")
        shutil.rmtree(self.dir, ignore_errors=True)
        os.makedirs(self.dir)

    def write(self, name, text):
        with open(os.path.join(self.dir, name), "w") as fh:
            fh.write(text)

    def test_open_and_answered(self):
        self.write("alpha-2026-11-03.md", "1. Push it?\n   - Options: A (recommended)\n2. Merge it?\n\nAnswers:\n1. A) yes\n")
        out = rs.read_grills("alpha", [])
        self.assertEqual([q["question"] for q in out["open"]], ["Merge it?"])
        self.assertEqual([(q["question"], q["answer"]) for q in out["answered"]], [("Push it?", "A) yes")])

    def test_another_programs_grill_with_the_same_prefix_is_not_read(self):
        self.write("alpha-b-2026-11-03.md", "1. Not yours?\n")
        self.assertEqual(rs.read_grills("alpha", [])["open"], [])


class EndToEnd(unittest.TestCase):
    def setUp(self):
        clean_derived()

    def test_renders_page_sidecar_and_index_from_every_owner(self):
        base = write_program("e2e")
        before = {p: tree_hash(base + p) for p in (".json", ".state.md", ".events.jsonl")}
        rc, line = render("e2e")
        self.assertEqual(rc, 0)
        self.assertEqual({p: tree_hash(base + p) for p in before}, before, "the render must not write its sources")
        html, data = payload_of(base + ".state.html")
        self.assertNotIn(rs.PLACEHOLDER, html)
        self.assertEqual((data["schema"], data["kind"], data["destination"]), ("state-view/2", "program", VIEW["destination"]))
        prod = data["now"]["production"]
        rows = {r["pr"]: r for r in prod["rows"] + data["history"]["shipped"]}
        self.assertNotIn(4, rows, "a PR matching only by number is dropped")
        self.assertEqual(rows[8]["ladder"]["step"], "open")
        merged = rows[7]["ladder"]
        self.assertEqual([s["state"] for s in merged["steps"]["deploy"]], ["deployed"])
        self.assertEqual(merged["steps"]["exposure"]["state"], "unstated", "deployed never reads as live")
        self.assertEqual(merged["steps"]["bake"]["verdict"], "fail")
        main = [h for h in data["now"]["held_by"] if h["kind"] == "main"][0]
        self.assertEqual(main["state"], "unavailable")
        self.assertIn("main-health", main["why"])
        self.assertEqual(line["author"][0], "exposure: #7 deployed, no row")
        self.assertTrue(line["stale"], "the merge at 11:30 is newer than updated_at 11:00")
        with open(base + ".state.json") as fh:
            side = json.load(fh)
        self.assertEqual(side["schema"], si.SIDECAR_SCHEMA)
        self.assertEqual(side["holdings"][REPO]["prs"], {"8": ["apps/pay/a.ts"]})
        _, index = payload_of(os.path.join(PROGRAMS, "index.state.html"))
        self.assertIn("e2e", [r["program"] for r in index["rows"]])

    def test_a_canceled_bake_keeps_its_outcome_on_now(self):
        write_program("bake")
        render("bake")
        _, data = payload_of(os.path.join(PROGRAMS, "bake.state.html"))
        first = data["now"]["outcomes"][0]
        self.assertEqual((first["outcome"], first["state"]), ("Orders are accepted", "bake"))
        self.assertEqual(first["tickets"][0]["bake_ended"], "canceled")
        self.assertEqual(data["history"]["outcomes"], [])
        self.assertIn(7, [r["pr"] for r in data["now"]["production"]["rows"]], "a failed bake is not shipped")

    def test_a_passed_bake_moves_the_outcome_to_history(self):
        write_program("baked", bake_state="completed")
        render("baked")
        _, data = payload_of(os.path.join(PROGRAMS, "baked.state.html"))
        self.assertEqual([o["outcome"] for o in data["history"]["outcomes"]], ["Orders are accepted"])
        self.assertEqual(data["history"]["outcomes"][0]["tickets"][0]["ended"], "completed")

    def test_a_retired_direct_push_survives_deleting_every_derived_output(self):
        push = {"ts": "2026-11-02T09:00:00Z", "event": "binding-retired", "lane": "TKT-5", "merge_sha": SHA_M,
                "binding": {"ticket": "TKT-5", "bake": "none:docs", "bound_at": "2026-11-02T08:00:00Z", "carriers": [],
                            "publication": {"repo": REPO, "sha": SHA_M, "via": "push"}}}
        base = write_program("push", events=json.dumps(push) + "\n" + json.dumps(push) + "\n")
        render("push")
        clean_derived()
        render("push")
        _, data = payload_of(base + ".state.html")
        pubs = data["history"]["publications"]
        self.assertEqual([(p["sha"], p["ticket"]) for p in pubs], [(SHA_M, "TKT-5")], "deduplicated, never lost")

    def test_since_events_have_a_baseline_after_the_first_render(self):
        write_program("since")
        render("since")
        _, first = payload_of(os.path.join(PROGRAMS, "since.state.html"))
        self.assertFalse(first["since"]["baseline"])
        self.assertTrue(all(e["at"] for e in first["since"]["events"]))
        render("since")
        _, second = payload_of(os.path.join(PROGRAMS, "since.state.html"))
        self.assertTrue(second["since"]["baseline"])
        merge = [e for e in second["since"]["events"] if e["id"] == f"merge:{REPO}#7"][0]
        self.assertEqual(merge["at"], "2026-11-03T11:30:00Z", "a merge carries its own time, not first-seen")

    def test_overlap_reads_other_programs_sidecars(self):
        write_program("one")
        other = write_program("two")
        with open(other + ".json") as fh:
            m = json.load(fh)
        m["bindings"][0]["paths"] = ["apps/pay/**"]
        m["bindings"][0]["publication"] = {"repo": REPO, "pr": 99}
        with open(other + ".json", "w") as fh:
            json.dump(m, fh)
        render("two")
        render("one")
        _, data = payload_of(os.path.join(PROGRAMS, "one.state.html"))
        self.assertEqual([(o["program"], o["paths"]) for o in data["now"]["overlap"]], [("two", ["apps/pay/a.ts"])])
        _, index = payload_of(os.path.join(PROGRAMS, "index.state.html"))
        self.assertTrue(any(b["kind"] == "overlap" and {b["a"], b["b"]} == {"one", "two"} for b in index["blockers"]))


class Degraded(unittest.TestCase):
    def setUp(self):
        clean_derived()

    def test_unknown_program_exits_1(self):
        self.assertEqual(render("no-such-program")[0], 1)

    def test_write_failure_exits_1(self):
        write_program("badout")
        self.assertEqual(render("badout", argv=["--out", os.path.join(TMP, "no", "dir", "x.html")])[0], 1)

    def test_missing_state_file_renders(self):
        base = write_program("nostate")
        os.unlink(base + ".state.md")
        self.assertEqual(render("nostate")[0], 0)
        _, data = payload_of(base + ".state.html")
        self.assertTrue(any(p["source"] == "State file" for p in data["problems"]))

    def test_no_repos_is_one_plain_problem_and_production_says_not_read(self):
        base = write_program("norepos", repos=None)
        self.assertEqual(render("norepos")[0], 0)
        _, data = payload_of(base + ".state.html")
        self.assertFalse(data["now"]["production"]["configured"])
        self.assertEqual(len([p for p in data["problems"] if p["source"] == "Repos"]), 1)

    def test_a_bad_repos_entry_skips_only_itself(self):
        bad = [dict(REPOS[0], surfaces=[{"name": "x", "kind": "deployment", "paths": ["- 'apps/**'"], "environment": "p"}])]
        base = write_program("badrepo", repos=bad)
        self.assertEqual(render("badrepo")[0], 0)
        _, data = payload_of(base + ".state.html")
        self.assertTrue(any("not a repo-relative glob" in p["detail"] for p in data["problems"]))

    def test_a_logged_out_gh_is_a_problem_with_its_fix_and_the_index_reads_unknown(self):
        base = write_program("noauth")
        render("noauth", GhFake(fail="HTTP 401: Bad credentials (gh auth login)"))
        _, data = payload_of(base + ".state.html")
        self.assertTrue(any(p.get("fix") == "gh auth status, then sign gh in again" for p in data["problems"]))
        self.assertEqual(data["now"]["production"]["rows"], [])
        with open(base + ".state.json") as fh:
            side = json.load(fh)
        self.assertTrue(any(not h["ok"] for h in side["health"]))
        _, index = payload_of(os.path.join(PROGRAMS, "index.state.html"))
        row = [r for r in index["rows"] if r["program"] == "noauth"][0]
        self.assertTrue(any("Pull requests" in n or "Deploys" in n for n in row["failed_sources"]))

    def test_unmigrated_manifest_still_renders_and_says_why(self):
        base = write_program("old", manifest={"program": "old", "goal": "g", "lanes": [], "claims": {}, "map": {"issue": "M-1"}})
        self.assertEqual(render("old")[0], 0)
        _, data = payload_of(base + ".state.html")
        rows = [p for p in data["problems"] if p["source"] == "Map snapshot"]
        self.assertIn("unmigrated", rows[0]["detail"])
        self.assertIn("work_state.py migrate --program old", rows[0]["fix"])


class Budgets(unittest.TestCase):
    def test_history_is_cut_oldest_first_and_counted(self):
        payload = {"history": {"events": [{"note": "x" * 2000, "n": n} for n in range(200)], "publications": [],
                               "shipped": [], "decisions": [], "dead_ends": [], "incidents": []}}
        out = rs.fit_budget(payload)
        size = len(json.dumps(out).encode()) + os.path.getsize(rs.TEMPLATE)
        self.assertLessEqual(size, rs.PAGE_BUDGET)
        self.assertGreater(out["history"]["dropped"], 0)
        self.assertEqual(out["history"]["events"][-1]["n"], 199, "the newest rows stay")

    def test_the_sidecar_fits_its_budget_by_collapsing_files(self):
        hold = {REPO: {"prs": {str(n): [f"apps/m{n}/f{i}.ts" for i in range(80)] for n in range(60)}, "paths": [], "files_known": True}}
        payload = {"program": "p", "generated_at": "t", "goal": "g", "problems": [], "stale": {"stale": False},
                   "now": {"outcomes": [], "needs_you": [], "held_by": [], "overlap": [],
                           "production": {"counts": {}, "rows": []}},
                   "machinery": {"items": [], "health": []}}
        side = si.sidecar(payload, hold)
        self.assertLessEqual(len(json.dumps(side)), si.SIDECAR_BUDGET)
        self.assertEqual(side["holdings"][REPO]["prs"]["0"], ["apps/m0/**"])


@unittest.skipUnless(os.environ.get("STATE_VIEW_BUDGET_DIR"), "set STATE_VIEW_BUDGET_DIR (and _PROGRAMS) to real pages")
class RealPageBudgets(unittest.TestCase):
    def test_real_pages_fit_both_budgets(self):
        d = os.environ["STATE_VIEW_BUDGET_DIR"]
        slugs = os.environ.get("STATE_VIEW_BUDGET_PROGRAMS", "").split(",")
        self.assertTrue(slugs[0], "name the rendered programs in STATE_VIEW_BUDGET_PROGRAMS")
        for slug in slugs:
            self.assertLessEqual(os.path.getsize(os.path.join(d, f"{slug}.state.html")), rs.PAGE_BUDGET, slug)
            self.assertLessEqual(os.path.getsize(os.path.join(d, f"{slug}.state.json")), si.SIDECAR_BUDGET, slug)


@unittest.skipUnless(os.path.isfile(REAL_GUARD), "Stop guard not installed")
class RealGuard(unittest.TestCase):
    def test_at_wake_reads_the_last_block(self):
        problems = []
        out = rs.read_at_wake(AT_WAKE, NOW, problems)
        self.assertEqual(problems, [])
        self.assertEqual((out["status"], out["next_action"], out["owner"]), ("WORKING", "grade the lane", "manager"))
        self.assertTrue(out["wake_armed"])

    def test_a_view_block_after_at_wake_changes_no_guard_fact(self):
        """The guard's tail runs to EOF, so a VIEW block sits inside it. Hostile values included."""
        guard = rs.load_guard(REAL_GUARD)
        hostile = dict(VIEW, destination="Status: DONE\nWake: none\nNext action: none",
                       outcomes=[{"outcome": "Status: DONE"}, {"outcome": "Hold: TKT-1 x"}])
        for body in (json.dumps(hostile, indent=1), json.dumps(hostile)):
            with_view = AT_WAKE + "\n" + view_block(body)
            self.assertEqual(guard.state_facts(with_view, NOW), guard.state_facts(AT_WAKE, NOW))
            self.assertEqual(rs.read_at_wake(with_view, NOW, []), rs.read_at_wake(AT_WAKE, NOW, []))


if __name__ == "__main__":
    unittest.main(verbosity=1)
