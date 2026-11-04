#!/usr/bin/env python3
"""leak-check.py: each class fires on a real shape, stays silent on its placeholder, and the staged mode reads
only added lines. Leak samples are built by concatenation so this file never carries one literally."""
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "leak-check.py")
spec = importlib.util.spec_from_file_location("leak_check", SCRIPT)
lc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lc)

AT = "@"
EMAIL = "pat.owner" + AT + "corp-mail.io"
HOME = "/" + "Users/" + "patowner/code/app"
TICKET = "ABC" + "-1234"


def kinds(text, private=None):
    return [k for k, _ in lc.scan_line(text, private)]


class Classes(unittest.TestCase):
    def test_email_fires_and_placeholders_pass(self):
        self.assertEqual(kinds("mail " + EMAIL), ["email"])
        for ok in ("mock" + AT + "example.invalid", "a" + AT + "example.com", "git" + AT + "github.com",
                   "noreply" + AT + "anthropic.com", "@types/node", "pkg" + AT + "1.2.3"):
            self.assertEqual(kinds(ok), [], ok)

    def test_home_path_fires_and_placeholders_pass(self):
        self.assertEqual(kinds("see " + HOME), ["home path"])
        for ok in ("/Users/x/.claude", "/Users/dev/code/app/", "/home/runner/work/", "~/code/keel/"):
            self.assertEqual(kinds(ok), [], ok)

    def test_credential_formats(self):
        samples = {
            "anthropic or openai key": "sk-" + "ant-" + "a1B2" * 8,
            "aws access key": "AKIA" + "ABCDEFGHIJKLMNOP",
            "github token": "ghp_" + "a1B2c3D4" * 5,
            "slack token": "xoxb-" + "1234567890-abcdef",
            "jwt": "eyJ" + "hbGciOiJIUzI1" + ".eyJ" + "zdWIiOiIxMjM0" + "." + "SflKxwRJSMeKKF2QT4",
            "private key": "-----BEGIN " + "RSA PRIVATE KEY-----",
        }
        for kind, text in samples.items():
            self.assertEqual(kinds(text), [kind], kind)
        self.assertEqual(kinds("sk-short"), [])

    def test_private_denylist_is_case_insensitive_and_optional(self):
        private = [lc.re.compile(r"\bABC-\d+", lc.re.I)]
        self.assertEqual(kinds("fixes " + TICKET.lower(), private), ["private denylist"])
        self.assertEqual(kinds("fixes " + TICKET, None), [])  # mutation control: no denylist, no hit

    def test_allow_marker_skips_the_line(self):
        self.assertEqual(kinds(EMAIL + "  # leak-check: allow"), [])

    def test_denylist_file_comments_and_absence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "deny.txt")
            with open(path, "w") as fh:
                fh.write("# comment\n\n\\bABC-\\d+\n")
            self.assertEqual([r.pattern for r in lc.load_denylist(path)], [r"\bABC-\d+"])
            self.assertIsNone(lc.load_denylist(os.path.join(tmp, "absent.txt")))


class Staged(unittest.TestCase):
    def run_check(self, cwd, deny):
        env = {**os.environ, "KEEL_LEAK_DENYLIST": deny}
        return subprocess.run([sys.executable, SCRIPT, "--staged"], cwd=cwd, env=env, capture_output=True, text=True)

    def test_staged_reads_added_lines_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            git = lambda *a: subprocess.run(["git", "-c", "core.hooksPath=/dev/null", *a], cwd=tmp, check=True,
                                            capture_output=True)
            git("init", "-q")
            git("config", "user.email", "t" + AT + "example.invalid")
            git("config", "user.name", "t")
            deny = os.path.join(tmp, "deny.txt")
            with open(deny, "w") as fh:
                fh.write("\\bABC-\\d+\n")
            doc = os.path.join(tmp, "doc.md")
            with open(doc, "w") as fh:
                fh.write("old line " + TICKET + "\n")
            git("add", "doc.md")
            git("commit", "-qm", "seed")
            with open(doc, "a") as fh:
                fh.write("clean new line\n")
            git("add", "doc.md")
            clean = self.run_check(tmp, deny)
            self.assertEqual(clean.returncode, 0, clean.stdout + clean.stderr)  # the old hit is not re-flagged
            self.assertIn("1 patterns from", clean.stderr)
            with open(doc, "a") as fh:
                fh.write("new " + TICKET + " and " + EMAIL + "\n")
            git("add", "doc.md")
            dirty = self.run_check(tmp, deny)
            self.assertEqual(dirty.returncode, 1)
            self.assertIn("doc.md:3: private denylist", dirty.stdout)
            self.assertIn("doc.md:3: email", dirty.stdout)
            missing = self.run_check(tmp, os.path.join(tmp, "absent.txt"))
            self.assertIn("NOT FOUND", missing.stderr)  # the receipt says the private checks did not run


if __name__ == "__main__":
    unittest.main()
