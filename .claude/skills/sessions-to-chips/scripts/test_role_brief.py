#!/usr/bin/env python3
"""role_brief.py: the computed role version, the load record and its status, the change delta, the keel
behind-origin line on a real git pair, the staged-diff check, and one end-to-end load into a temp programs dir."""
import datetime as dt
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import role_brief as rb  # noqa: E402

ROLE = """# Manager role
## Role card
- **Never implement.**
## Wake steps
1. Role.
## Changes
- 2026-11-01 | old change
- 2026-11-05 | same-day change
- 2026-11-05T18:00Z | evening change
"""
OVERLAY = """# overlay
## Role card
- private verb line
## Changes
- 2026-11-03 | overlay change
"""
LEDGER = """# Rulings ledger (private overlay)
## Rulings
- 2026-11-04 | a ruling | founder
"""
ME = "local_5e551011-0000-4000-8000-000000000001"
HEAD = f"updated_at: 2026-11-05T10:00:00Z\nwriter: {ME} (account acct-1)\nsince-last-session: first head\n"
GIT_ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@t", GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1")


def _git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=GIT_ENV)


def _write(path, text):
    with open(path, "w") as fh:
        fh.write(text)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="role-brief-")
        self.role = os.path.join(self.tmp, "role.md")
        self.pub = os.path.join(self.tmp, "public-ledger.md")
        self.ov = os.path.join(self.tmp, "overlay")
        os.makedirs(self.ov)
        _write(self.role, ROLE)
        _write(self.pub, "# Rulings ledger\n## Rulings\n")
        _write(os.path.join(self.ov, "rulings-ledger.md"), LEDGER)
        _write(os.path.join(self.ov, "role-overlay.md"), OVERLAY)
        self.programs = os.path.join(self.tmp, "programs")
        os.makedirs(self.programs)
        self.patches = [mock.patch.object(rb, "ROLE", self.role), mock.patch.object(rb, "PUBLIC_LEDGER", self.pub),
                        mock.patch.dict(os.environ, {"MANAGER_ROLE_OVERLAY": self.ov,
                                                     "WORK_STATE_PROGRAMS": self.programs})]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()


class Version(Base):
    def test_version_is_stable_and_moves_with_any_source(self):
        v1, shas = rb.role_version()
        self.assertEqual(v1, rb.role_version()[0])
        self.assertEqual(len(v1), 8)
        self.assertEqual(set(shas), {"role", "ledger", "rulings", "overlay"})
        with open(os.path.join(self.ov, "rulings-ledger.md"), "a") as fh:
            fh.write("- 2026-11-05 | new ruling | founder\n")
        self.assertNotEqual(v1, rb.role_version()[0])

    def test_absent_overlay_hashes_as_absent(self):
        os.remove(os.path.join(self.ov, "role-overlay.md"))
        self.assertEqual(rb.role_version()[1]["overlay"], "absent")


class Status(unittest.TestCase):
    ACK = {"version": "abcd1234", "loaded_at": "2026-11-05T10:00:00Z", "session_id": "s1"}

    def test_each_status(self):
        self.assertEqual(rb.ack_status(None, "abcd1234"), "missing")
        self.assertEqual(rb.ack_status(self.ACK, "ffff0000", "s1"), "changed")
        self.assertEqual(rb.ack_status(self.ACK, "abcd1234", "s2"), "new_session")
        self.assertEqual(rb.ack_status(self.ACK, "abcd1234", "s1"), "current")
        later = dt.datetime(2026, 11, 5, 11, tzinfo=dt.timezone.utc)
        self.assertEqual(rb.ack_status(self.ACK, "abcd1234", "s1", compacted_at=later), "compacted")
        earlier = dt.datetime(2026, 11, 5, 9, tzinfo=dt.timezone.utc)
        self.assertEqual(rb.ack_status(self.ACK, "abcd1234", "s1", compacted_at=earlier), "current")

    def test_an_ack_without_a_session_is_not_held_to_one(self):
        self.assertEqual(rb.ack_status(dict(self.ACK, session_id=None), "abcd1234", "s9"), "current")


class Delta(Base):
    def test_since_a_load_shows_newer_changes_newest_first(self):
        out = rb.delta_lines(rb.parse_when("2026-11-05T12:00Z"))
        self.assertTrue(out[0].endswith("evening change"), out)
        self.assertIn("same-day change", "\n".join(out))  # date-only lines show to every load stamped that day
        self.assertNotIn("old change", "\n".join(out))
        self.assertNotIn("a ruling", "\n".join(out))

    def test_first_load_shows_the_newest_of_every_kind(self):
        out = "\n".join(rb.delta_lines(None))
        for want in ("evening change", "overlay change", "[ruling] a ruling", "old change"):
            self.assertIn(want, out)

    def test_role_only_kind_filter(self):
        self.assertNotIn("a ruling", "\n".join(rb.delta_lines(None, kinds=("role",))))


class KeelBehind(unittest.TestCase):
    def test_counts_commits_on_the_fetched_upstream(self):
        tmp = tempfile.mkdtemp(prefix="role-keel-")
        origin, clone, other = (os.path.join(tmp, x) for x in ("origin.git", "clone", "other"))
        _git("init", "--bare", "-b", "master", origin)
        _git("clone", origin, other)
        _write(os.path.join(other, "a"), "1")
        _git("add", "a", cwd=other)
        _git("commit", "-m", "one", cwd=other)
        _git("push", "origin", "master", cwd=other)
        _git("clone", origin, clone)
        self.assertEqual(rb.keel_behind(path=clone)[0], 0)
        for n in ("2", "3"):
            _write(os.path.join(other, "a"), n)
            _git("commit", "-am", n, cwd=other)
        _git("push", "origin", "master", cwd=other)
        self.assertEqual(rb.keel_behind(path=clone)[0], 0)  # no network: an unfetched push is invisible
        _git("fetch", "origin", cwd=clone)
        self.assertEqual(rb.keel_behind(path=clone)[0], 2)

    def test_not_a_checkout_is_unknown(self):
        self.assertIsNone(rb.keel_behind(path=tempfile.mkdtemp())[0])


class Staged(unittest.TestCase):
    def test_a_change_needs_a_changes_line(self):
        self.assertTrue(rb.staged_role_change_ok(""))
        self.assertFalse(rb.staged_role_change_ok("+++ b/role.md\n-- old line\n+- **Never implement.** now\n"))
        self.assertTrue(rb.staged_role_change_ok("+- **x**\n+- 2026-11-06 | x now reads y\n"))

    def test_hook_on_a_real_repo(self):
        repo = tempfile.mkdtemp(prefix="role-staged-")
        _git("init", "-b", "master", repo)
        rel = os.path.join(repo, ".claude/skills/sessions-to-chips/references")
        os.makedirs(rel)
        _write(os.path.join(rel, "role.md"), ROLE)
        _git("add", ".", cwd=repo)
        _git("commit", "-m", "base", cwd=repo)
        _write(os.path.join(rel, "role.md"), ROLE.replace("Never implement.", "Never implement anything."))
        _git("add", ".", cwd=repo)
        run = lambda cmd, **kw: subprocess.run(cmd, cwd=repo, env=GIT_ENV, **kw)  # noqa: E731
        self.assertEqual(rb.check_staged(run=run), 1)
        with open(os.path.join(rel, "role.md"), "a") as fh:
            fh.write("- 2026-11-06 | never implement anything\n")
        _git("add", ".", cwd=repo)
        self.assertEqual(rb.check_staged(run=run), 0)


class Load(Base):
    def test_a_load_prints_the_role_and_records_the_ack_even_when_degraded(self):
        now = dt.datetime(2026, 11, 5, 12, tzinfo=dt.timezone.utc)
        with mock.patch.object(rb, "keel_behind", return_value=(3, "/k")):
            text, version, shas, degraded = rb.brief("demo", "s1", now, self.programs)
        self.assertIn(f"Manager role v{version} for demo", text)
        self.assertIn("KEEL CHECKOUT BEHIND ORIGIN BY 3", text)
        self.assertIn("- **Never implement.**", text)
        self.assertIn("private verb line", text)
        self.assertIn("/manager-role demo -- on fire:", text)
        self.assertIn(f"Role: v{version}", text)
        self.assertTrue(degraded)  # no manifest: the context brief degrades, the load still records
        rb.write_ack("demo", version, shas, "s1", degraded, now, self.programs)
        ack = rb.read_ack("demo", self.programs)
        self.assertEqual((ack["version"], ack["session_id"], ack["degraded"]), (version, "s1", True))
        self.assertEqual(rb.ack_status(ack, rb.role_version()[0], "s1"), "current")

    def test_the_peers_block_prints_and_a_broken_one_degrades_the_load(self):
        import coordinate
        now = dt.datetime(2026, 11, 5, 12, tzinfo=dt.timezone.utc)
        with mock.patch.object(coordinate, "peers_block", return_value="Other managers (0 live, 0 abandoned):"), \
                mock.patch.object(rb, "context_brief", return_value=("ctx", False)):
            text, _, _, degraded = rb.brief("demo", "s1", now, self.programs)
        self.assertIn("Other managers (0 live", text)
        self.assertFalse(degraded)
        with mock.patch.object(coordinate, "peers_block", side_effect=RuntimeError("boom")), \
                mock.patch.object(rb, "context_brief", return_value=("ctx", False)):
            text, _, _, degraded = rb.brief("demo", "s1", now, self.programs)
        self.assertIn("Other managers unreadable (RuntimeError: boom)", text)
        self.assertTrue(degraded)

    def test_page_stale_line(self):
        base = os.path.join(self.programs, "demo")
        _write(base + ".state.html", "x")
        _write(base + ".state.md", "x")
        os.utime(base + ".state.html", (1, 1))
        with mock.patch.object(rb, "keel_behind", return_value=(0, "/k")):
            self.assertTrue(any("State page stale" in x for x in rb.health_lines("demo", self.programs)))

    def head_case(self, head, events=""):
        base = os.path.join(self.programs, "demo")
        _write(base + ".state.md", head + "# Demo state\n")
        _write(base + ".state.html", "x")
        _write(base + ".events.jsonl", events)
        now = dt.datetime(2026, 11, 5, 12, tzinfo=dt.timezone.utc)
        with mock.patch.object(rb, "keel_behind", return_value=(0, "/k")):
            return [x for x in rb.health_lines("demo", self.programs, session=ME, now=now) if "head" in x]

    def test_head_health_line_fires_for_missing_foreign_and_older_than_an_event(self):
        self.assertIn("State file head missing", self.head_case("")[0])
        foreign = HEAD.replace(ME, "local_5e551011-0000-4000-8000-0000000000ff")
        self.assertIn("names another session", self.head_case(foreign)[0])
        late = '{"ts":"2026-11-05T11:00:00Z","event":"merged"}\n'
        self.assertIn("older than the newest event", self.head_case(HEAD, late)[0])
        self.assertEqual(self.head_case(HEAD, '{"ts":"2026-11-05T09:00:00Z","event":"merged"}\n'), [])
        self.assertTrue(all("--write-head demo --since" in x for x in self.head_case("")))

    def test_wake_steps_print_the_write_head_command_and_no_template(self):
        now = dt.datetime(2026, 11, 5, 12, tzinfo=dt.timezone.utc)
        with mock.patch.object(rb, "keel_behind", return_value=(0, "/k")):
            text = rb.brief("demo", ME, now, self.programs)[0]
        steps = text.split("Wake steps:", 1)[1].split("----- context brief -----")[0]
        self.assertIn('state_view.py --write-head demo --since "<what changed>"', steps)
        self.assertNotIn("updated_at:", steps)

    def test_cli_status_writes_nothing(self):
        out = subprocess.run([sys.executable, "-I", os.path.join(HERE, "role_brief.py"), "--status", "--program",
                              "demo", "--session", "s1"], capture_output=True, text=True,
                             env=dict(os.environ, WORK_STATE_PROGRAMS=self.programs, MANAGER_ROLE_OVERLAY=self.ov))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout)["status"], "missing")
        self.assertFalse(os.path.exists(rb.ack_path("demo", self.programs)))


class MissionHealth(Base):
    """Row 11: one health line per undriven open mission, read from the engine's snapshot cache."""

    def lines(self, missions=None, write=True):
        ws_dir = os.path.join(self.tmp, "ws")
        os.makedirs(ws_dir, exist_ok=True)
        if write:
            _write(os.path.join(ws_dir, "demo.json"), json.dumps({} if missions is None else {"missions": missions}))
        now = dt.datetime(2026, 11, 5, 12, tzinfo=dt.timezone.utc)
        with mock.patch.dict(os.environ, {"WORK_STATE_DIR": ws_dir}), \
                mock.patch.object(rb, "keel_behind", return_value=(0, "/k")):
            return [x for x in rb.health_lines("demo", self.programs, now=now) if x.startswith("mission")]

    def test_undriven_row_prints_driven_row_does_not(self):
        rows = [{"program": "lost", "undriven": True}, {"program": "kept", "undriven": False}]
        self.assertEqual(self.lines({"taken_at": "2026-11-05T11:30:00Z", "rows": rows}),
                         ["mission lost: undriven (snapshot 30m old)"])
        self.assertEqual(self.lines({"taken_at": "2026-11-05T11:30:00Z", "rows": rows[1:]}), [])

    def test_no_cache_key_reads_unknown(self):
        self.assertEqual(self.lines(None), ["missions: unknown (no snapshot)"])
        self.assertEqual(self.lines(write=False), ["missions: unknown (no snapshot)"])


class TruncatedReadAndDigest(Base):
    """2026-11-19: managers piped the brief through `| head -2` and the load still recorded. The ack is now the
    last act after the whole brief reached the reader, and line 2 carries the changes."""

    def run_cli(self, pipe_cmd, session="s1"):
        env = dict(os.environ, WORK_STATE_PROGRAMS=self.programs, MANAGER_ROLE_OVERLAY=self.ov,
                   WORK_STATE_DIR=os.path.join(self.tmp, "ws"))
        cmd = f'"{sys.executable}" -I "{os.path.join(HERE, "role_brief.py")}" --program demo --session {session}'
        return subprocess.run(f"{cmd} 2>&1 | {pipe_cmd}", shell=True, capture_output=True, text=True, env=env,
                              timeout=60)

    def test_head_two_records_nothing(self):
        out = self.run_cli("head -2")
        self.assertEqual(len(out.stdout.splitlines()), 2)
        self.assertFalse(os.path.exists(rb.ack_path("demo", self.programs)), out.stdout)

    def test_a_full_read_records_the_load(self):
        out = self.run_cli("cat")
        self.assertIn("End of role brief v", out.stdout)
        self.assertTrue(os.path.exists(rb.ack_path("demo", self.programs)), out.stdout[-400:])

    def test_line_two_is_the_digest_of_new_rules(self):
        now = dt.datetime(2026, 11, 5, 12, tzinfo=dt.timezone.utc)
        with mock.patch.object(rb, "keel_behind", return_value=(0, "/k")):
            first = rb.brief("demo", "s1", now, self.programs)[0].splitlines()[1]
        self.assertTrue(first.startswith("NEW SINCE YOUR LAST LOAD"), first)
        self.assertIn("evening change", first)
        since = dt.datetime(2026, 11, 5, 17, tzinfo=dt.timezone.utc)
        line = rb.digest_line(since)
        self.assertIn("evening change", line)
        self.assertNotIn("old change", line)
        self.assertIn("nothing", rb.digest_line(dt.datetime(2026, 11, 6, 0, tzinfo=dt.timezone.utc)))


class OwnerClaim(Base):
    """A load points the owner manifest at the running session, following `absorbed_by`."""

    def manifest(self, slug, **kw):
        _write(os.path.join(self.programs, slug + ".json"), json.dumps(dict({"program": slug}, **kw)))

    def read(self, slug):
        with open(os.path.join(self.programs, slug + ".json")) as fh:
            return json.load(fh)

    def test_the_absorber_gets_the_running_session(self):
        self.manifest("harness", manager_session="local_2d34eeca (old account)", orchestrator_session="old-cli",
                      updated_at="2026-11-16T12:00:00Z")
        self.manifest("repo-hygiene", manager_session="new-cli", absorbed_by="harness", fold={})
        now = dt.datetime(2026, 11, 19, 12, tzinfo=dt.timezone.utc)
        with mock.patch.object(rb, "own_ids", return_value={"new-cli", "local_a1cfd2ad-0000"}):
            owner, note = rb.claim_owner("repo-hygiene", "new-cli", now, self.programs, rows={})
        self.assertEqual((owner, note), ("harness", None))
        m = self.read("harness")
        self.assertEqual(m["manager_session"], "local_a1cfd2ad-0000 (cli new-cli)")
        self.assertEqual(m["orchestrator_session"], "new-cli")
        self.assertEqual(m["updated_at"], "2026-11-19T12:00:00Z")
        self.assertNotIn("updated_at", self.read("repo-hygiene"))

    def test_no_manifest_or_no_session_writes_nothing(self):
        now = dt.datetime(2026, 11, 19, 12, tzinfo=dt.timezone.utc)
        self.assertEqual(rb.claim_owner("demo", "s1", now, self.programs), (None, None))
        self.manifest("demo", manager_session="x")
        self.assertEqual(rb.claim_owner("demo", "", now, self.programs), (None, None))
        self.assertEqual(self.read("demo")["manager_session"], "x")


class FoldedChildClaim(Base):
    """A folded child's load never steals the owner from another live manager; the owner's own load still claims."""
    NOW = dt.datetime(2026, 11, 23, 12, tzinfo=dt.timezone.utc)
    APPS = "local_341f08b6-78ea-412b-a27c-94308e80ef85"
    APPS_CLI = "aaaaaaaa-0000-4000-8000-000000000001"
    IDS = "local_adb9778d-1735-4c14-8963-689f8ee6975e"
    IDS_CLI = "cc23b82a-cba5-487f-b3a4-8aa3ec9daaf3"

    def setUp(self):
        super().setUp()
        _write(os.path.join(self.programs, "identities.json"),
               json.dumps({"program": "identities", "manager_session": self.IDS_CLI, "absorbed_by": "apps", "fold": {}}))
        self.rows = {sid: {"sessionId": sid, "cliSessionId": cli, "title": title, "lastActivityAt": seen}
                     for sid, cli, title, seen in (
                         (self.APPS, self.APPS_CLI, "[Manager] Apps", "2026-11-23T11:30:00Z"),
                         (self.IDS, self.IDS_CLI, "[Manager] Identities", "2026-11-23T11:55:00Z"))}

    def apps(self, manager_session):
        m = {"program": "apps", "updated_at": "2026-11-20T00:00:00Z"}
        if manager_session is not None:
            m["manager_session"] = manager_session
        _write(os.path.join(self.programs, "apps.json"), json.dumps(m))

    def read(self, slug="apps"):
        with open(os.path.join(self.programs, slug + ".json")) as fh:
            return json.load(fh)

    def load(self, slug, cli, local):
        with mock.patch.object(rb, "own_ids", return_value={cli, local}):
            return rb.claim_owner(slug, cli, self.NOW, self.programs, rows=self.rows)

    def test_owner_slug_load_claims_even_from_a_live_manager(self):
        self.apps(f"{self.IDS} (cli {self.IDS_CLI})")
        self.assertEqual(self.load("apps", self.APPS_CLI, self.APPS), ("apps", None))
        self.assertEqual(self.read()["manager_session"], f"{self.APPS} (cli {self.APPS_CLI})")

    def test_folded_child_claims_when_the_owner_has_no_or_empty_manager(self):
        for held in (None, ""):
            self.apps(held)
            self.assertEqual(self.load("identities", self.IDS_CLI, self.IDS), ("apps", None))
            self.assertEqual(self.read()["manager_session"], f"{self.IDS} (cli {self.IDS_CLI})")

    def test_folded_child_claims_from_a_stale_or_unknown_holder(self):
        self.rows[self.APPS]["lastActivityAt"] = "2026-11-22T00:00:00Z"  # past HOLDER_WINDOW_S: an account switch
        for held in (f"{self.APPS} (cli {self.APPS_CLI})", "local_2d34eeca (old account)"):
            self.apps(held)
            self.load("identities", self.IDS_CLI, self.IDS)
            self.assertEqual(self.read()["manager_session"], f"{self.IDS} (cli {self.IDS_CLI})")

    def test_folded_child_does_not_steal_from_a_live_manager(self):
        for held in (f"{self.APPS} (cli {self.APPS_CLI})", self.APPS_CLI, "local_341f08b6 (apps account)"):
            self.apps(held)
            self.assertEqual(self.load("identities", self.IDS_CLI, self.IDS), ("apps", None))
            m = self.read()
            self.assertEqual((m["manager_session"], m["updated_at"]), (held, "2026-11-20T00:00:00Z"))

    def test_unreadable_session_index_counts_as_live(self):
        with mock.patch.dict(sys.modules, {"program_family": None}):
            self.assertTrue(rb.holder_live(self.APPS, {self.IDS}, self.NOW))

    def test_no_ping_pong_across_two_consecutive_loads(self):
        self.apps(f"{self.IDS} (cli {self.IDS_CLI})")  # the stolen state of 2026-11-23
        self.load("apps", self.APPS_CLI, self.APPS)  # the apps manager reloads: claims back
        self.load("identities", self.IDS_CLI, self.IDS)  # the identities manager reloads: leaves it
        self.load("identities", self.IDS_CLI, self.IDS)
        self.assertEqual(self.read()["manager_session"], f"{self.APPS} (cli {self.APPS_CLI})")
        self.assertEqual(self.read("identities")["manager_session"], self.IDS_CLI)


class ReportContract(unittest.TestCase):
    """The session report contract (founder 2026-11-26): a WORKING or DONE AT-WAKE carries Next, Blocked by,
    Research and Run; GRILLING is exempt; only the LAST AT-WAKE block counts, and only up to the next heading."""
    FULL = ("## AT-WAKE\nStatus: WORKING\nWake: bg:abc fires on exit\nNext: grade lane abc\n"
            "Blocked by: none\nResearch: none\nRun:\n```bash\ngh pr view 1\n```\n")

    def test_full_block_has_no_gaps(self):
        self.assertEqual(rb.report_gaps(self.FULL), ("WORKING", []))

    def test_working_block_missing_fields_names_them(self):
        text = "## AT-WAKE\nStatus: WORKING\nWake: bg:abc\nNext action: grade it\nResearch: none\n"
        self.assertEqual(rb.report_gaps(text), ("WORKING", ["Next", "Blocked by", "Run"]))

    def test_done_is_checked_and_grilling_is_exempt(self):
        self.assertEqual(rb.report_gaps("## AT-WAKE\nStatus: DONE\n")[1], list(rb.REPORT_FIELDS))
        self.assertEqual(rb.report_gaps("## AT-WAKE\nStatus: GRILLING\n"), ("GRILLING", []))

    def test_only_the_last_block_counts_up_to_the_next_heading(self):
        text = self.FULL + "\n## AT-WAKE\n- **Status**: DONE\n- **Next**: none\n\n## VIEW\nBlocked by: x\nResearch: y\nRun: z\n"
        self.assertEqual(rb.report_gaps(text), ("DONE", ["Blocked by", "Research", "Run"]))

    def test_no_block_or_no_status_is_left_to_the_arm_check(self):
        self.assertEqual(rb.report_gaps("# state\n"), (None, []))
        self.assertEqual(rb.report_gaps("## AT-WAKE\nWake: x\n"), (None, []))

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            ok, bad = os.path.join(d, "ok.state.md"), os.path.join(d, "bad.state.md")
            _write(ok, self.FULL)
            _write(bad, "## AT-WAKE\nStatus: WORKING\n")
            out = subprocess.run([sys.executable, "-I", os.path.join(HERE, "role_brief.py"), "--check-report", bad],
                                 capture_output=True, text=True)
            self.assertEqual(out.returncode, 1)
            self.assertEqual(json.loads(out.stdout)["missing"], list(rb.REPORT_FIELDS))
            with mock.patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(rb.main(["--check-report", ok]), 0)
                self.assertEqual(rb.main(["--check-report", os.path.join(d, "absent.state.md")]), 2)


if __name__ == "__main__":
    unittest.main()
