#!/usr/bin/env python3
"""role_brief.py: the computed role version, the load record and its status, the change delta, the keel
behind-origin line on a real git pair, the staged-diff check, and one end-to-end load into a temp programs dir."""
import datetime as dt
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

    def test_page_stale_line(self):
        base = os.path.join(self.programs, "demo")
        _write(base + ".state.html", "x")
        _write(base + ".state.md", "x")
        os.utime(base + ".state.html", (1, 1))
        with mock.patch.object(rb, "keel_behind", return_value=(0, "/k")):
            self.assertTrue(any("State page stale" in x for x in rb.health_lines("demo", self.programs)))

    def test_cli_status_writes_nothing(self):
        out = subprocess.run([sys.executable, "-I", os.path.join(HERE, "role_brief.py"), "--status", "--program",
                              "demo", "--session", "s1"], capture_output=True, text=True,
                             env=dict(os.environ, WORK_STATE_PROGRAMS=self.programs, MANAGER_ROLE_OVERLAY=self.ov))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout)["status"], "missing")
        self.assertFalse(os.path.exists(rb.ack_path("demo", self.programs)))


if __name__ == "__main__":
    unittest.main()
