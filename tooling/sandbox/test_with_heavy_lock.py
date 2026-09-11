#!/usr/bin/env python3
"""Regression tests for heavy-op admission and its shell preflight hook.

stdlib only: ``python3 tooling/sandbox/test_with_heavy_lock.py``.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

from resource_test_support import isolated_wrapper


HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
WRAPPER = os.path.join(REPO, "tooling", "sandbox", "with-heavy-lock")
HOOK = os.path.join(REPO, ".claude", "hooks", "serialize-heavy-ops.py")


def run_hook(command, with_wrapper_on_path=True):
    """Feed a command to the hook; exit 2 means the shell call is denied."""
    with tempfile.TemporaryDirectory() as bindir:
        env = dict(os.environ)
        if with_wrapper_on_path:
            os.symlink(WRAPPER, os.path.join(bindir, "with-heavy-lock"))
            env["PATH"] = bindir + os.pathsep + env.get("PATH", "")
        else:
            env["PATH"] = bindir
        completed = subprocess.run(
            [sys.executable, HOOK], input=json.dumps({"tool_input": {"command": command}}),
            capture_output=True, text=True, env=env,
        )
    return completed


def isolated_runner(home, **updates):
    """Make a fixture-only account home and matching runner executable."""
    keel = os.path.join(home, ".keel")
    os.mkdir(keel)
    with open(os.path.join(keel, "resource-policy.json"), "w", encoding="utf-8") as handle:
        json.dump({"min_free_percent": 0}, handle)
    env = dict(os.environ, HOME=home, KEEL_HEAVY_POLL_SECONDS="0.05")
    env.update(updates)
    return isolated_wrapper(home), env


class OneSlotOnly(unittest.TestCase):
    def test_slot_count_cannot_be_inflated_by_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            first_started = os.path.join(directory, "first-started")
            first_finished = os.path.join(directory, "first-finished")
            second_started = os.path.join(directory, "second-started")
            wrapper, env = isolated_runner(directory, KEEL_HEAVY_SLOTS="99")
            first_body = (
                "import pathlib,time; pathlib.Path(%r).touch(); time.sleep(.35); pathlib.Path(%r).touch()"
                % (first_started, first_finished)
            )
            second_body = "import pathlib; pathlib.Path(%r).touch()" % second_started
            first = subprocess.Popen([wrapper, sys.executable, "-c", first_body], env=env)
            second = None
            try:
                deadline = time.monotonic() + 4
                while not os.path.exists(first_started) and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(os.path.exists(first_started))
                second = subprocess.Popen([wrapper, sys.executable, "-c", second_body], env=env)
                time.sleep(.12)
                self.assertFalse(os.path.exists(second_started),
                                 "KEEL_HEAVY_SLOTS must not allow a second command body")
                self.assertEqual(first.wait(timeout=5), 0)
                self.assertEqual(second.wait(timeout=5), 0)
                self.assertTrue(os.path.exists(first_finished))
                self.assertTrue(os.path.exists(second_started))
            finally:
                for child in (first, second):
                    if child is not None and child.poll() is None:
                        child.kill()
                        child.wait(timeout=5)


class HeredocNotCommand(unittest.TestCase):
    def test_heredoc_body_mentioning_heavy_ops_is_allowed(self):
        for body_command in ("pnpm install", "pnpm test", "npx cdk deploy --all",
                             "next build", "npx vitest run x.test.ts"):
            command = "cat > notes.md <<EOF\nSetup:\n%s\nEOF" % body_command
            self.assertEqual(run_hook(command).returncode, 0, body_command)

    def test_quoted_delimiter_and_dash_form_are_allowed(self):
        self.assertEqual(run_hook("cat > r.md <<'DOC'\npnpm install\nDOC").returncode, 0)
        self.assertEqual(run_hook("cat > r.md <<-DOC\n\tpnpm test\n\tDOC").returncode, 0)

    def test_real_command_after_a_heredoc_still_fires(self):
        self.assertEqual(run_hook("cat > n.md <<EOF\nhello\nEOF\npnpm test").returncode, 2)


class QuotedDataVsExecution(unittest.TestCase):
    def test_quoted_search_data_is_allowed(self):
        self.assertEqual(run_hook('grep -rn "pnpm install" docs/').returncode, 0)
        self.assertEqual(run_hook('grep -E "lint|pnpm test:unit" package.json').returncode, 0)
        self.assertEqual(run_hook('echo "remember to run pnpm install later"').returncode, 0)

    def test_shell_c_payload_is_executed_and_denied(self):
        self.assertEqual(run_hook("bash -c 'pnpm test'").returncode, 2)
        self.assertEqual(run_hook('zsh -lc "pnpm install"').returncode, 2)
        self.assertEqual(run_hook("eval 'pnpm test'").returncode, 2)


class HeavyCommandCorpus(unittest.TestCase):
    def test_package_root_flag_and_env_unset_are_not_command_names(self):
        for command in ('pnpm -w test', 'env -u DEBUG pnpm test', 'node node_modules/vitest/vitest.js run'):
            with self.subTest(command=command):
                self.assertEqual(run_hook(command).returncode, 2)

    def test_unwrapped_heavy_commands_are_denied(self):
        commands = (
            "pnpm test", "pnpm --filter @acme/backend test", "pnpm --silent test",
            "npx vitest run a.test.ts", "node node_modules/vitest/vitest.mjs run",
            "npx cdk synth", "pnpm install", "yarn", "yarn --immutable",
            "next build", "turbo run build --filter=web",
        )
        for command in commands:
            self.assertEqual(run_hook(command).returncode, 2, command)

    def test_marker_forgery_and_partial_wrapping_do_not_bypass_the_hook(self):
        commands = (
            "KEEL_HEAVY_LOCK_HELD=1 pnpm test",
            "with-heavy-lock pnpm test; pnpm test",
            "with-heavy-lock pnpm test && node node_modules/vitest/vitest.mjs run",
        )
        for command in commands:
            self.assertEqual(run_hook(command).returncode, 2, command)

    def test_one_fully_wrapped_heavy_command_is_allowed(self):
        self.assertEqual(run_hook("with-heavy-lock pnpm --filter @acme/backend test").returncode, 0)


class FailClosed(unittest.TestCase):
    def test_missing_wrapper_denies_heavy_command(self):
        result = run_hook("pnpm test", with_wrapper_on_path=False)
        self.assertEqual(result.returncode, 2)

    def test_light_commands_remain_allowed_without_wrapper(self):
        for command in ("git status --porcelain", "pnpm typecheck", "pnpm lint", "yarn --version", "ls -la"):
            self.assertEqual(run_hook(command, with_wrapper_on_path=False).returncode, 0, command)


if __name__ == "__main__":
    unittest.main(verbosity=2)
