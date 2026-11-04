#!/usr/bin/env python3
"""hook-syntax-sentinel: a broken hook reached by symlink from ~/.claude/hooks is reported at its real path;
the same broken file not wired there stays silent."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

SENTINEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hook-syntax-sentinel.py")


class Symlinked(unittest.TestCase):
    def run_sentinel(self, home, path):
        payload = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": path}})
        out = subprocess.run([sys.executable, SENTINEL], input=payload, capture_output=True, text=True,
                             env={**os.environ, "HOME": home}, timeout=10)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout

    def test_linked_hook_is_checked_and_unlinked_file_is_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = os.path.realpath(tmp)
            home, clone = os.path.join(tmp, "home"), os.path.join(tmp, "clone", "hooks")
            os.makedirs(os.path.join(home, ".claude", "hooks"))
            os.makedirs(clone)
            broken = os.path.join(clone, "guard.py")
            with open(broken, "w") as fh:
                fh.write("def x(:\n")
            os.symlink(broken, os.path.join(home, ".claude", "hooks", "guard.py"))
            self.assertIn("NO LONGER PARSES", self.run_sentinel(home, broken))
            stray = os.path.join(clone, "unwired.py")
            with open(stray, "w") as fh:
                fh.write("def x(:\n")
            self.assertEqual(self.run_sentinel(home, stray), "")  # mutation control: not wired, not checked


if __name__ == "__main__":
    unittest.main()
