#!/usr/bin/env python3
"""Regression tests for the heavy-op semaphore and its enforcement hook.

stdlib only, no pytest:   python3 tooling/sandbox/test_with_heavy_lock.py

Every case here pins a bug that was actually observed, not a hypothetical:

  BoundsConcurrency   the load-bearing invariant. The predecessor silently
                      no-op'd when `flock` was missing, so "the lock is
                      installed" and "the lock works" looked identical.
  ReleaseOnCrash      a slot must free even when the command dies hard, or one
                      segfaulting runner wedges the machine permanently.
  NestedNoDeadlock    wrapping a command that self-locks must not hang.
  HeredocNotCommand   writing a doc whose body mentions `pnpm install` must be
                      ALLOWED. Measured: 56 of 85 fires over a 4000-call real
                      transcript corpus were this false positive. A guard that
                      fires on the negative set is worse than no guard.
  QuotedRunVsEcho     `bash -c 'pnpm test'` runs the op (deny);
                      `echo "pnpm test"` only prints it (allow).
  FailsOpen           no wrapper on PATH -> never refuse; a guard must not
                      hard-break a machine that has not installed it yet.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
WRAPPER = os.path.join(REPO, "tooling", "sandbox", "with-heavy-lock")
HOOK = os.path.join(REPO, ".claude", "hooks", "serialize-heavy-ops.py")


def run_hook(command, with_wrapper_on_path=True):
    """Feed one command through the hook; return its exit code (2 == deny)."""
    env = dict(os.environ)
    bindir = tempfile.mkdtemp()
    if with_wrapper_on_path:
        link = os.path.join(bindir, "with-heavy-lock")
        try:
            os.symlink(WRAPPER, link)
        except OSError:
            pass
        env["PATH"] = bindir + os.pathsep + env.get("PATH", "")
    else:
        # A PATH with nothing on it at all -> which() finds no wrapper.
        env["PATH"] = bindir
    p = subprocess.run(
        [sys.executable, HOOK],
        input=json.dumps({"tool_input": {"command": command}}),
        capture_output=True, text=True, env=env,
    )
    return p.returncode


class BoundsConcurrency(unittest.TestCase):
    def test_never_exceeds_slot_count(self):
        slots = 2
        n = 6
        with tempfile.TemporaryDirectory() as d:
            marker = os.path.join(d, "live")
            os.makedirs(marker)
            env = dict(os.environ)
            env["KEEL_HEAVY_LOCK_DIR"] = os.path.join(d, "slots")
            env["KEEL_HEAVY_SLOTS"] = str(slots)
            # Each op creates a file, sleeps, removes it. Peak file count == peak
            # concurrency, recorded by the ops themselves (no sampling race).
            script = (
                'f="$1/$$"; touch "$f"; ls "$1" | wc -l > "$1/../peak.$$"; '
                'sleep 1; rm -f "$f"'
            )
            procs = [
                subprocess.Popen(
                    [WRAPPER, "bash", "-c", script, "_", marker],
                    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                for _ in range(n)
            ]
            for p in procs:
                p.wait(timeout=90)
            peaks = []
            for name in os.listdir(d):
                if name.startswith("peak."):
                    with open(os.path.join(d, name)) as fh:
                        peaks.append(int(fh.read().strip()))
            self.assertEqual(len(peaks), n, "every op must have run, not been refused")
            self.assertLessEqual(max(peaks), slots,
                                 "semaphore did not bound concurrency: peaks=%s" % peaks)


class ReleaseOnCrash(unittest.TestCase):
    def test_slot_frees_after_sigkill(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ)
            env["KEEL_HEAVY_LOCK_DIR"] = os.path.join(d, "slots")
            env["KEEL_HEAVY_SLOTS"] = "1"
            victim = subprocess.Popen([WRAPPER, "sleep", "60"], env=env,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1.0)
            victim.kill()
            victim.wait(timeout=30)
            start = time.time()
            after = subprocess.run([WRAPPER, "true"], env=env, timeout=30,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.assertEqual(after.returncode, 0)
            self.assertLess(time.time() - start, 15, "slot was wedged by the killed op")


class NestedNoDeadlock(unittest.TestCase):
    def test_nested_wrap_does_not_hang(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ)
            env["KEEL_HEAVY_LOCK_DIR"] = os.path.join(d, "slots")
            env["KEEL_HEAVY_SLOTS"] = "1"
            r = subprocess.run([WRAPPER, WRAPPER, "true"], env=env, timeout=30,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.assertEqual(r.returncode, 0)


class HeredocNotCommand(unittest.TestCase):
    """The measured false-positive class: doc bodies are data, not commands."""

    def test_heredoc_body_mentioning_heavy_ops_is_allowed(self):
        for body_cmd in ("pnpm install", "pnpm test", "npx cdk deploy --all",
                         "next build", "npx vitest run x.test.ts"):
            cmd = 'cat > notes.md <<EOF\nSetup:\n%s\nEOF' % body_cmd
            self.assertEqual(run_hook(cmd), 0,
                             "heredoc body %r must not fire" % body_cmd)

    def test_quoted_delimiter_and_dash_form(self):
        self.assertEqual(run_hook("cat > r.md <<'DOC'\npnpm install\nDOC"), 0)
        self.assertEqual(run_hook("cat > r.md <<-DOC\n\tpnpm test\n\tDOC"), 0)

    def test_real_command_after_a_heredoc_still_fires(self):
        # The heredoc must not swallow the rest of the command.
        cmd = 'cat > n.md <<EOF\nhello\nEOF\npnpm test'
        self.assertEqual(run_hook(cmd), 2)

    def test_grep_for_a_heavy_op_is_allowed(self):
        self.assertEqual(run_hook('grep -rn "pnpm install" docs/'), 0)


class QuotedRegexIsData(unittest.TestCase):
    """Corpus-measured: a `|` inside a quoted regex is not a shell pipe."""

    def test_grep_for_a_runner_name_is_allowed(self):
        self.assertEqual(run_hook(
            'ps aux | grep -E "cynap-sandbox|vitest" | grep -v grep | head -10'), 0)
        self.assertEqual(run_hook(
            r'grep -n "test:ci\|typecheck\|turbo run build\|ephemeral" .githooks/pre-push'), 0)

    def test_quoted_alternation_with_test_script(self):
        self.assertEqual(run_hook('grep -E "lint|pnpm test:unit" package.json'), 0)


class QuotedRunVsEcho(unittest.TestCase):
    def test_dash_c_runs_it(self):
        self.assertEqual(run_hook("bash -c 'pnpm test'"), 2)
        self.assertEqual(run_hook('zsh -lc "pnpm install"'), 2)
        self.assertEqual(run_hook("scripts/pg.sh bash -c 'pnpm test'"), 2)

    def test_echo_only_prints_it(self):
        self.assertEqual(run_hook('echo "pnpm test"'), 0)
        self.assertEqual(run_hook('echo "remember to run pnpm install later"'), 0)


class PositiveSet(unittest.TestCase):
    def test_heavy_ops_fire(self):
        for cmd in ("pnpm test", "pnpm test:figma-site", "npx vitest run a.test.ts",
                    "npx cdk synth", "npx cdk deploy --all", "pnpm install",
                    "next build", "turbo run build --filter=web",
                    "pnpm --filter @acme/backend build", "pnpm -r build"):
            self.assertEqual(run_hook(cmd), 2, "must fire: %r" % cmd)


class NegativeSet(unittest.TestCase):
    def test_light_ops_allowed(self):
        for cmd in ("git status --porcelain", "gh pr list", "pnpm typecheck",
                    "pnpm lint", "pnpm exec tsc --noEmit", "pnpm add -D vitest",
                    "cat build/output.txt", "cdk --version", "ls -la",
                    "npm view vitest version", "rm -rf build/",
                    "with-heavy-lock pnpm test"):
            self.assertEqual(run_hook(cmd), 0, "must NOT fire: %r" % cmd)


class FailsOpen(unittest.TestCase):
    def test_no_wrapper_on_path_never_refuses(self):
        self.assertEqual(run_hook("pnpm test", with_wrapper_on_path=False), 0)

    def test_garbage_input_never_refuses(self):
        p = subprocess.run([sys.executable, HOOK], input="not json",
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0)
        p = subprocess.run([sys.executable, HOOK], input="",
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
