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

from resource_test_support import isolated_hook, isolated_wrapper


HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
WRAPPER = os.path.join(REPO, "tooling", "sandbox", "with-heavy-lock")
HOOK = os.path.join(REPO, ".claude", "hooks", "serialize-heavy-ops.py")


def run_hook(command, with_wrapper_on_path=True, hook=None, arguments=(), cwd=None, **tool_input):
    """Feed a command to the hook; exit 2 means the shell call is denied.

    `cwd` (when given) is sent at the top level of the payload, matching the real
    PreToolUse request shape from both Claude and Codex.
    """
    with tempfile.TemporaryDirectory() as bindir:
        env = dict(os.environ)
        if with_wrapper_on_path:
            os.symlink(WRAPPER, os.path.join(bindir, "with-heavy-lock"))
            env["PATH"] = bindir + os.pathsep + env.get("PATH", "")
        else:
            env["PATH"] = bindir
        payload = {"tool_input": {"command": command, **tool_input}}
        if cwd is not None:
            payload["cwd"] = cwd
        completed = subprocess.run(
            [*([hook] if hook else [sys.executable, HOOK]), *arguments],
            input=json.dumps(payload),
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


class UnparseableCommand(unittest.TestCase):
    def test_light_command_with_unbalanced_quoting_is_allowed(self):
        for command in ('grep -n "could not parse .claude/hooks/serialize-heavy-ops.py',
                        "git commit -m 'fix install docs", "echo it's done", "ls \\",
                        "pnpm typecheck 'x", 'eval "echo \'unclosed"'):
            with self.subTest(command=command):
                result = run_hook(command)
                self.assertEqual((result.returncode, result.stdout), (0, ""), result.stderr)

    def test_heavy_token_in_unparseable_text_is_denied(self):
        for command in ('grep "x && pnpm test', "npx vitest run 'a.test.ts", "bash -c 'pnpm install",
                        'cdk deploy "x', 'with-heavy-lock pnpm test "x', 'yarn "', "next build 'x",
                        'turbo run build "', 'pn""pm --filter web test "', "node_modules/.bin/jest '",
                        'bash -c "pnpm test \'x"', 'grep "pnpm install docs/'):
            with self.subTest(command=command):
                result = run_hook(command)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("could not parse this command", result.stderr)


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


TODAY_RULES = {"project-verify": ["verify", "e2e"], "slow-setup": ["*"]}
BACKGROUND_RULES = {**TODAY_RULES,
                    "background_required": {"project-verify": ["verify"], "slow-setup": ["*"]}}
CLAUDE_TEXT = "re-run with run_in_background: true; the harness re-invokes you when it exits."


class BackgroundRequired(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.mkdir(os.path.join(self.tmp.name, ".keel"))
        self.write_rules(BACKGROUND_RULES)
        self.hook = isolated_hook(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write_rules(self, rules):
        with open(os.path.join(self.tmp.name, ".keel", "resource-commands.json"), "w") as handle:
            handle.write(rules if isinstance(rules, str) else json.dumps(rules))

    def check(self, command, *arguments, cwd=None, **tool_input):
        return run_hook(command, hook=self.hook, arguments=arguments, cwd=cwd, **tool_input)

    def test_claude_runtime_denies_a_foreground_background_required_command(self):
        commands = ("with-heavy-lock project-verify verify",
                    "with-heavy-lock -- project-verify verify --scope all",
                    "cd repo && with-heavy-lock ./tools/project-verify verify 2>&1 | tail -40",
                    "FLAG=1 with-heavy-lock slow-setup")
        for command in commands:
            for extra in ({}, {"run_in_background": False}):
                with self.subTest(command=command, extra=extra):
                    result = self.check(command, "--runtime", "claude", **extra)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertIn(CLAUDE_TEXT, result.stderr)

    def test_claude_runtime_allows_the_same_command_backgrounded(self):
        result = self.check("with-heavy-lock project-verify verify", "--runtime", "claude",
                            run_in_background=True)
        self.assertEqual((result.returncode, result.stdout), (0, ""), result.stderr)

    def test_codex_runtime_gets_running_cell_guidance(self):
        result = self.check("with-heavy-lock project-verify verify", "--runtime", "codex")
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertNotIn("permissionDecision", output)
        text = output["additionalContext"]
        self.assertIn("Keep reading the running cell until it exits; never start a second copy.", text)
        self.assertNotIn("poll", text.lower())
        self.assertNotIn("run_in_background", text)

    def test_no_runtime_argument_keeps_todays_behavior(self):
        result = self.check("with-heavy-lock project-verify verify")
        self.assertEqual((result.returncode, result.stdout), (0, ""), result.stderr)
        self.assertEqual(self.check("project-verify verify").returncode, 2)

    def test_wrapped_single_file_vitest_stays_allowed_in_the_foreground(self):
        for command in ("with-heavy-lock pnpm exec vitest run src/a.test.ts",
                        "with-heavy-lock npx vitest run -t 'one case' src/a.test.ts"):
            for runtime in ("claude", "codex"):
                with self.subTest(command=command, runtime=runtime):
                    result = self.check(command, "--runtime", runtime)
                    self.assertEqual((result.returncode, result.stdout), (0, ""), result.stderr)

    def test_unwrapped_heavy_command_keeps_the_existing_denial(self):
        result = self.check("project-verify verify", "--runtime", "claude")
        self.assertEqual(result.returncode, 2)
        self.assertIn("requires the shared resource runner", result.stderr)
        self.assertNotIn("run_in_background", result.stderr)

    def test_other_verbs_quoted_prose_and_rules_without_the_map_are_unaffected(self):
        for command in ("with-heavy-lock project-verify e2e", "git status",
                        'echo "with-heavy-lock project-verify verify"'):
            with self.subTest(command=command):
                self.assertEqual(self.check(command, "--runtime", "claude").returncode, 0)
        self.write_rules(TODAY_RULES)
        self.assertEqual(self.check("with-heavy-lock project-verify verify", "--runtime", "claude").returncode, 0)
        self.assertEqual(self.check("project-verify verify", "--runtime", "claude").returncode, 2)

    def test_exclusion_entries_keep_a_verb_prefix_in_the_foreground(self):
        self.write_rules({"project-verify": ["verify", "e2e", "!verify --quick"],
                          "slow-setup": ["*", "!status"],
                          "background_required": {"project-verify": ["verify", "e2e", "!verify --quick"],
                                                  "slow-setup": ["*", "!status"]}})
        cases = {"with-heavy-lock project-verify verify": 2,
                 "with-heavy-lock project-verify verify --full": 2,
                 "with-heavy-lock project-verify e2e": 2,
                 "with-heavy-lock project-verify verify --quick": 0,
                 "with-heavy-lock project-verify verify --quick --scope api": 0,
                 "with-heavy-lock project-verify --quick verify": 0,
                 "with-heavy-lock slow-setup": 2,
                 "with-heavy-lock slow-setup status": 0}
        for command, expected in cases.items():
            with self.subTest(command=command):
                self.assertEqual(self.check(command, "--runtime", "claude").returncode, expected)
        # The heavy-command map honours the same exclusions: the excluded form needs no wrapper.
        self.assertEqual(self.check("project-verify verify --quick").returncode, 0)
        self.assertEqual(self.check("project-verify verify --full").returncode, 2)
        self.assertEqual(self.check("slow-setup status").returncode, 0)

    def test_invalid_registration_or_background_map_fails_closed(self):
        for arguments in (("--runtime", "other"), ("--runtime",), ("claude",)):
            with self.subTest(arguments=arguments):
                result = self.check("git status", *arguments)
                self.assertEqual(result.returncode, 2)
                self.assertIn("Reinstall resource hooks", result.stderr)
        self.write_rules({**TODAY_RULES, "background_required": ["project-verify"]})
        result = self.check("git status", "--runtime", "claude")
        self.assertEqual(result.returncode, 2)
        self.assertIn("background_required must map command names", result.stderr)

    def test_malformed_rules_file_fails_closed_even_for_unparseable_light_text(self):
        self.write_rules('{"project-verify": ["verify"')
        for command in ("git status", 'grep "x'):
            with self.subTest(command=command):
                result = self.check(command, "--runtime", "claude")
                self.assertEqual(result.returncode, 2)
                self.assertIn("could not read resource command rules", result.stderr)

    def test_unparseable_text_is_checked_against_configured_rules(self):
        self.write_rules({**TODAY_RULES, "background_required": {"slow-report": ["*"]}})
        result = self.check('./tools/project-verify verify "x', "--runtime", "claude")
        self.assertEqual(result.returncode, 2)
        self.assertIn("names heavy command project-verify", result.stderr)
        result = self.check("slow-report --since 'today", "--runtime", "claude")
        self.assertEqual(result.returncode, 2)
        self.assertIn(CLAUDE_TEXT, result.stderr)
        result = self.check("slow-report --since 'today", "--runtime", "claude", run_in_background=True)
        self.assertEqual((result.returncode, result.stdout), (0, ""), result.stderr)
        self.assertEqual(self.check("other-tool 'x", "--runtime", "claude").returncode, 0)


class SelfLockingMarker(unittest.TestCase):
    """A project-command script that owns its own heavy-slot lock can opt out of the runner."""

    RULES = {"project-verify": ["verify", "e2e"]}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.mkdir(os.path.join(self.tmp.name, ".keel"))
        self.write_rules(self.RULES)
        self.hook = isolated_hook(self.tmp.name)
        self.repo = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()
        self.repo.cleanup()

    def write_rules(self, rules):
        with open(os.path.join(self.tmp.name, ".keel", "resource-commands.json"), "w", encoding="utf-8") as handle:
            handle.write(rules if isinstance(rules, str) else json.dumps(rules))

    def write_script(self, relative_path, marker=True, padding_bytes=0):
        path = os.path.join(self.repo.name, relative_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        body = ""
        if padding_bytes:
            body += "# " + ("x" * padding_bytes) + "\n"
        if marker:
            body += "# keel:self-locking\n"
        body += "#!/usr/bin/env bash\necho hi\n"
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)
        os.chmod(path, 0o700)
        return path

    def check(self, command, *arguments, cwd=None, **tool_input):
        return run_hook(command, hook=self.hook, arguments=arguments, cwd=cwd, **tool_input)

    def test_marker_present_relative_path_and_payload_cwd_is_allowed(self):
        self.write_script("tooling/sandbox/project-verify")
        result = self.check("tooling/sandbox/project-verify verify", cwd=self.repo.name)
        self.assertEqual((result.returncode, result.stdout), (0, ""), result.stderr)

    def test_marker_present_foreground_under_claude_runtime_still_needs_background(self):
        self.write_rules({**self.RULES, "background_required": {"project-verify": ["verify"]}})
        self.write_script("tooling/sandbox/project-verify")
        result = self.check("tooling/sandbox/project-verify verify", "--runtime", "claude", cwd=self.repo.name)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(CLAUDE_TEXT, result.stderr)
        backgrounded = self.check("tooling/sandbox/project-verify verify", "--runtime", "claude",
                                  cwd=self.repo.name, run_in_background=True)
        self.assertEqual((backgrounded.returncode, backgrounded.stdout), (0, ""), backgrounded.stderr)

    def test_marker_absent_is_denied(self):
        self.write_script("tooling/sandbox/project-verify", marker=False)
        result = self.check("tooling/sandbox/project-verify verify", cwd=self.repo.name)
        self.assertEqual(result.returncode, 2)

    def test_marker_past_8192_bytes_is_denied(self):
        self.write_script("tooling/sandbox/project-verify", marker=True, padding_bytes=8200)
        result = self.check("tooling/sandbox/project-verify verify", cwd=self.repo.name)
        self.assertEqual(result.returncode, 2)

    def test_cd_before_the_command_makes_the_payload_cwd_stale(self):
        self.write_script("tooling/sandbox/project-verify")
        command = "cd %s && tooling/sandbox/project-verify verify" % self.repo.name
        result = self.check(command, cwd=self.repo.name)
        self.assertEqual(result.returncode, 2)

    def test_bare_name_is_never_exempt(self):
        result = self.check("project-verify verify", cwd=self.repo.name)
        self.assertEqual(result.returncode, 2)

    def test_absolute_path_with_marker_is_allowed_without_a_payload_cwd(self):
        path = self.write_script("tooling/sandbox/project-verify")
        result = self.check(path + " verify")
        self.assertEqual((result.returncode, result.stdout), (0, ""), result.stderr)

    def test_symlink_to_a_marked_file_is_allowed(self):
        target = self.write_script("tooling/sandbox/project-verify")
        link = os.path.join(self.repo.name, "tooling", "sandbox", "project-verify-link")
        os.symlink(target, link)
        result = self.check("tooling/sandbox/project-verify-link verify", cwd=self.repo.name)
        self.assertEqual((result.returncode, result.stdout), (0, ""), result.stderr)

    def test_wrapped_marked_command_stays_allowed(self):
        self.write_script("tooling/sandbox/project-verify")
        result = self.check("with-heavy-lock tooling/sandbox/project-verify verify", cwd=self.repo.name)
        self.assertEqual((result.returncode, result.stdout), (0, ""), result.stderr)

    def test_builtin_kind_is_never_exempt_even_with_a_marker_file(self):
        self.write_script("pnpm")  # marker on a file that shares a built-in kind's name
        result = self.check("./pnpm test", cwd=self.repo.name)
        self.assertEqual(result.returncode, 2)

    def test_env_dash_capital_c_disables_the_exemption(self):
        # A marker under the payload cwd must not exempt a script actually resolved elsewhere.
        self.write_script("tooling/sandbox/project-verify")
        command = "env -C /tmp/elsewhere tooling/sandbox/project-verify verify"
        result = self.check(command, cwd=self.repo.name)
        self.assertEqual(result.returncode, 2)

    def test_env_chdir_flag_disables_the_exemption(self):
        self.write_script("tooling/sandbox/project-verify")
        command = "env --chdir=/tmp/elsewhere tooling/sandbox/project-verify verify"
        result = self.check(command, cwd=self.repo.name)
        self.assertEqual(result.returncode, 2)

    def test_pnpm_dir_equals_flag_disables_the_exemption(self):
        self.write_script("tooling/sandbox/project-verify")
        command = "pnpm --dir=/tmp/elsewhere exec tooling/sandbox/project-verify verify"
        result = self.check(command, cwd=self.repo.name)
        self.assertEqual(result.returncode, 2)

    def test_env_var_assignment_is_not_a_chdir_flag(self):
        self.write_script("tooling/sandbox/project-verify")
        result = self.check("env FOO=1 tooling/sandbox/project-verify verify", cwd=self.repo.name)
        self.assertEqual((result.returncode, result.stdout), (0, ""), result.stderr)

    def test_git_dash_capital_c_segment_makes_the_payload_cwd_stale(self):
        self.write_script("tooling/sandbox/project-verify")
        command = "git -C /tmp/elsewhere status && tooling/sandbox/project-verify verify"
        result = self.check(command, cwd=self.repo.name)
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
