#!/usr/bin/env python3
"""Behavioral tests for `spawn-lane.sh` runtimes (Codex by default) and the codex-first gate.

Not phrase-matching: a stub `codex` earlier on PATH records the real argv, so these
assert the command the script actually builds."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "spawn-lane.sh"
STUB = '#!/bin/bash\nprintf "%s\\n" "$@" > "$STUB_OUT"\n'
# The claude stub also records the two env settings a headless lane must carry, and can
# answer with a canned JSON envelope + exit code (an auth death is is_error:true, rc=1).
# `claude auth status` answers STUB_AUTH_JSON / STUB_AUTH_RC and leaves the lane argv file alone.
CLAUDE_AUTH = ('[ "${1:-}" = auth ] && { printf "%s\\n" "$*" >> "${STUB_AUTH_LOG:-/dev/null}"; '
               'printf "%s" "${STUB_AUTH_JSON:-}"; exit "${STUB_AUTH_RC:-0}"; }\n')
CLAUDE_STUB = "#!/bin/bash\n" + CLAUDE_AUTH + STUB.split("\n", 1)[1] + (
    'printf "FORK=%s\\nHEADLESS=%s\\n" "${CLAUDE_CODE_FORK_SUBAGENT-unset}" '
    '"${CYNAP_HEADLESS_LANE-unset}" > "$STUB_ENV"\n'
    '[ -n "${STUB_ENVELOPE:-}" ] && printf "%s" "$STUB_ENVELOPE"\n'
    'exit "${STUB_RC:-0}"\n'
)


def git(*args, cwd=None):
    subprocess.run(["git", *args], cwd=cwd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin"; self.bin.mkdir()
        for name in ("codex", "claude"):
            p = self.bin / name
            p.write_text(CLAUDE_STUB if name == "claude" else STUB); p.chmod(0o755)
        self.home = self.root / "home"
        gate = self.home / ".claude/scripts/codex-headroom.sh"
        gate.parent.mkdir(parents=True)
        gate.write_text('#!/bin/bash\nprintf "%s\\n" "$@" > "$STUB_GATE_ARGS"\nprintf "%s\\n" "${STUB_ROUTE:-gpt-6-sol medium}"\nexit "${STUB_GATE_RC:-0}"\n')
        gate.chmod(0o755)
        self.gate = gate
        self.gate_env = {}
        self.run_env = {}
        self.out = self.root / "argv.txt"
        self.base = self.root / "base"; self.base.mkdir()
        git("init", "-q", ".", cwd=self.base)
        (self.base / "s.txt").write_text("seed")
        git("add", "-A", cwd=self.base)
        git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "seed", cwd=self.base)
        self.mission = self.root / "m.md"; self.mission.write_text("do the thing")

    def tearDown(self):
        self.tmp.cleanup()

    def spawn(self, cwd, *extra):
        env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", STUB_OUT=str(self.out),
                   HOME=str(self.home), CODEX_HEADROOM_LOG="/dev/null",
                   STUB_GATE_ARGS=str(self.root / "gate-args.txt"),
                   STUB_ENV=str(self.root / "env.txt"), **self.gate_env, **self.run_env)
        for k in ("WORK_STATE_LANE_ROWS", "S2C_CLAUDE_HOME"):  # the lane row must land under this HOME
            env.pop(k, None)
        r = subprocess.run([str(SCRIPT), "--mission", str(self.mission), "--cwd", str(cwd), *extra],
                           capture_output=True, text=True, env=env)
        argv = self.out.read_text().splitlines() if self.out.exists() else []
        return r, argv

    def roots(self, argv):
        for a in argv:
            if a.startswith("sandbox_workspace_write.writable_roots="):
                return a.split("=", 1)[1]
        return ""

    def test_default_runtime_is_codex(self):
        # Codex-first: a lane with no runtime and no model goes to Codex.
        result, argv = self.spawn(self.base)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("workspace-write", argv)

    def test_no_runtime_with_a_mechanical_model_keeps_claude(self):
        for model in ("sonnet", "haiku"):
            with self.subTest(model=model):
                result, argv = self.spawn(self.base, "--model", model)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(argv[argv.index("--model") + 1], model)
                self.assertIn("-p", argv)

    def test_opus_on_claude_needs_a_reason(self):
        for extra in (("--model", "opus"), ("--runtime", "claude", "--model", "opus"),
                      ("--runtime", "claude", "--model", "claude-opus-5-5"),
                      ("--runtime", "claude", "--model", "opus", "--claude-reason", "short")):
            with self.subTest(extra=extra):
                r, argv = self.spawn(self.base, *extra)
                self.assertEqual(r.returncode, 2)
                self.assertEqual(argv, [])
                self.assertIn("--claude-reason", r.stderr)
                self.assertIn("codex-dispatch.sh standard <promptfile> <outfile> [workdir]", r.stderr)

    def test_opus_with_a_reason_runs_on_claude_and_records_it(self):
        rows_path = self.home / ".claude/state/lane-parents.jsonl"
        self.run_env = {"CLAUDE_SESSION_ID": "mgr-cli-2"}
        reason = "edits harness hooks a cold Codex lane cannot reach"
        r, argv = self.spawn(self.base, "--runtime", "claude", "--model", "opus", "--claude-reason", reason)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(argv[argv.index("--model") + 1], "opus")
        self.assertIn("Codex-no: " + reason, r.stderr)
        row = json.loads(rows_path.read_text().splitlines()[-1])
        self.assertEqual((row["runtime"], row["claude_reason"]), ("claude", reason))

    def test_a_spec_mission_is_not_gated(self):
        self.mission.write_text("Role: spec\nWrite the spec.")
        r, argv = self.spawn(self.base, "--runtime", "claude", "--model", "opus")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("-p", argv)

    def test_kill_switch_lifts_the_reason_requirement(self):
        (self.home / ".claude/run").mkdir(parents=True)
        (self.home / ".claude/run/codex-first-gate.off").write_text("")
        r, _ = self.spawn(self.base, "--runtime", "claude", "--model", "opus")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_claude_reason_is_refused_on_codex(self):
        r, argv = self.spawn(self.base, "--claude-reason", "some long enough reason")
        self.assertEqual(r.returncode, 2)
        self.assertIn("claude-only", r.stderr)

    def test_a_claude_only_option_without_runtime_is_refused(self):
        for extra in (("--worktree", "x"), ("--max-turns", "3"), ("--mode", "acceptEdits")):
            with self.subTest(extra=extra):
                r, argv = self.spawn(self.base, *extra)
                self.assertEqual(r.returncode, 2)
                self.assertEqual(argv, [])
                self.assertIn("--runtime claude", r.stderr)

    def test_explicit_claude_runtime_builds_the_claude_argv(self):
        result, argv = self.spawn(self.base, "--runtime", "claude")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("-p", argv)
        self.assertIn("--output-format", argv)
        # A headless lane has no one to answer a prompt; without this a restrictive --mode hangs.
        self.assertEqual(argv[argv.index("--permission-prompts") + 1], "none")

    def test_claude_lane_pins_fork_off_and_carries_the_headless_marker(self):
        # Since 2.1.302 `-p` forks subagents by default and a fork bypasses the Model-why
        # gate; the marker is what makes serialize-heavy-ops.py keep its deny for lanes.
        self.spawn(self.base, "--runtime", "claude")
        seen = dict(l.split("=", 1) for l in (self.root / "env.txt").read_text().splitlines())
        self.assertEqual(seen["FORK"], "0")
        self.assertEqual(seen["HEADLESS"], "1")

    def test_both_runtimes_record_a_full_lane_row(self):
        # The work-state engine proves a lane live by pid + start time and binds it by lane id; a
        # row with only lane/parent/ts (the legacy shape) is unevaluable.
        rows_path = self.home / ".claude/state/lane-parents.jsonl"
        self.run_env = {"CLAUDE_SESSION_ID": "mgr-cli-1", "LANE_RECORD_OUTFILE": str(self.root / "lane.out")}
        self.spawn(self.base, "--runtime", "claude")
        self.spawn(self.base, "--runtime", "codex")
        rows = [json.loads(x) for x in rows_path.read_text().splitlines()]
        self.assertEqual([r["runtime"] for r in rows], ["claude", "codex"])
        for r in rows:
            self.assertEqual(r["parent"], "mgr-cli-1")
            self.assertIsInstance(r["pid"], int)
            self.assertTrue(r["pid_start"])
            self.assertTrue(r["lane"])
        self.assertEqual(rows[0]["outfile"], str(self.root / "lane.out"))
        self.assertTrue(rows[1]["outfile"])

    def test_auth_death_exits_3_with_the_one_human_step(self):
        # Probed: an empty CLAUDE_CONFIG_DIR run answers envelope subtype:success,
        # is_error:true, rc=1, which a caller cannot tell from a work failure.
        for text in ("Failed to authenticate. API Error: 401", "Not logged in - Please run /login"):
            with self.subTest(text=text):
                self.run_env = {"STUB_RC": "1", "STUB_ENVELOPE": json.dumps(
                    {"type": "result", "subtype": "success", "is_error": True, "result": text})}
                r, _ = self.spawn(self.base, "--runtime", "claude")
                self.assertEqual(r.returncode, 3, r.stderr)
                self.assertIn("claude /login", r.stderr)
                self.assertNotIn(text, r.stdout)

    def test_a_non_auth_error_envelope_is_re_emitted_and_fails(self):
        env = json.dumps({"type": "result", "subtype": "success", "is_error": True,
                          "result": "Failed to push the branch"})
        for rc in ("0", "1"):
            with self.subTest(rc=rc):
                self.run_env = {"STUB_RC": rc, "STUB_ENVELOPE": env}
                r, _ = self.spawn(self.base, "--runtime", "claude")
                self.assertEqual(r.returncode, 1, r.stderr)
                self.assertEqual(r.stdout, env)

    # ---- Claude account preflight: preferred login is named in a private file -----------
    # Synthetic addresses only (example.invalid): this repo is public.
    PREFERRED = "lane-owner@example.invalid"
    OTHER = "someone-else@example.invalid"

    def account_spawn(self, auth_json=None, auth_rc="0", pref=PREFERRED, runtime="claude"):
        rows_path = self.home / ".claude/state/lane-parents.jsonl"
        if rows_path.exists():
            rows_path.unlink()
        pref_file = self.home / ".claude/run/preferred-claude-account"
        pref_file.parent.mkdir(parents=True, exist_ok=True)
        if pref is None:
            pref_file.unlink(missing_ok=True)
        else:
            pref_file.write_text(pref + "\n")
        self.run_env = {"CLAUDE_SESSION_ID": "mgr-acct", "STUB_AUTH_RC": auth_rc,
                        "STUB_AUTH_LOG": str(self.root / "auth.log"),
                        "STUB_AUTH_JSON": auth_json if auth_json is not None else ""}
        r, argv = self.spawn(self.base, "--runtime", runtime)
        row = json.loads(rows_path.read_text().splitlines()[-1])
        return r, argv, row

    def assert_no_email(self, r, row):
        for text in (r.stdout, r.stderr, json.dumps(row)):
            self.assertNotIn("@example.invalid", text)

    def test_preferred_login_matches_quietly(self):
        r, argv, row = self.account_spawn(json.dumps({"loggedIn": True, "email": self.PREFERRED.upper()}))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("-p", argv)
        self.assertNotIn("non-preferred", r.stderr)
        self.assertIs(row["account_preferred"], True)
        self.assertEqual((self.root / "auth.log").read_text().split(), ["auth", "status", "--json"])
        self.assert_no_email(r, row)

    def test_non_preferred_login_warns_once_and_continues(self):
        r, argv, row = self.account_spawn(json.dumps({"loggedIn": True, "email": self.OTHER}))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("-p", argv, "a mismatch must never block the lane")
        self.assertEqual(r.stderr.count("lane runs on a non-preferred Claude login; run "
                                        "`claude auth login` as the preferred account"), 1)
        self.assertIs(row["account_preferred"], False)
        self.assert_no_email(r, row)

    def test_absent_preference_file_skips_silently(self):
        r, argv, row = self.account_spawn(json.dumps({"email": self.OTHER}), pref=None)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("-p", argv)
        self.assertNotIn("non-preferred", r.stderr)
        self.assertNotIn("account_preferred", row)
        self.assertFalse((self.root / "auth.log").exists(), "no file → no auth probe at all")

    def test_failing_or_unusable_auth_status_is_skipped(self):
        for auth_json, rc in (("", "1"), (json.dumps({"email": self.OTHER}), "1"),
                              ("not json", "0"), (json.dumps({"loggedIn": False}), "0"),
                              (json.dumps(["x"]), "0")):
            with self.subTest(auth_json=auth_json, rc=rc):
                r, argv, row = self.account_spawn(auth_json, auth_rc=rc)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("-p", argv)
                self.assertNotIn("non-preferred", r.stderr)
                self.assertNotIn("account_preferred", row)

    def test_codex_lane_does_not_probe_the_claude_login(self):
        r, _, row = self.account_spawn(json.dumps({"email": self.OTHER}), runtime="codex")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("account_preferred", row)
        self.assertFalse((self.root / "auth.log").exists())

    def test_codex_runtime_grants_the_git_dir(self):
        _, argv = self.spawn(self.base, "--runtime", "codex")
        self.assertIn("workspace-write", argv)
        self.assertIn(str((self.base / ".git").resolve()), self.roots(argv))

    def test_linked_worktree_grants_BOTH_git_dirs(self):
        # The bug this pins: in a linked worktree, objects and refs/heads live in the
        # COMMON dir, outside the workspace. Granting only --absolute-git-dir writes the
        # file and then dies on `Operation not permitted`. Verified against a real lane.
        lane = self.root / "lane"
        git("worktree", "add", "-q", str(lane), "-b", "lane-b", cwd=self.base)
        _, argv = self.spawn(lane, "--runtime", "codex")
        roots = self.roots(argv)
        self.assertIn("worktrees/lane", roots, "per-worktree git dir must be granted")
        self.assertIn(f'"{(self.base / ".git").resolve()}"', roots,
                      "the COMMON git dir must be granted or the lane cannot commit")
        # CLOSED SET, not a floor. The two assertIn calls above name WHICH paths must be
        # granted; on their own they are blind to a THIRD root being added later — a
        # silent widening of the sandbox. Measured 2026-08-25: adding an unconditional
        # third root is caught by test_writable_roots_are_json_encoded_not_interpolated's
        # existing assertEqual(len(parsed), 1), but adding one inside the linked-worktree
        # branch left all 13 tests green. Cardinality closes that hole; keep both
        # assertIn calls, because cardinality alone would not say which two.
        parsed = json.loads(roots)
        self.assertEqual(len(parsed), 2,
                         "a linked worktree must grant exactly the per-worktree dir and "
                         "the common dir, nothing else")

    def test_network_is_DENIED_by_default(self):
        # The lane must not hold push authority. With HOME preserved, shared git config
        # granted and network open, it could `git push origin HEAD:main` as easily as its
        # own branch, gated only by prompt text. Denying egress removes the question.
        _, argv = self.spawn(self.base, "--runtime", "codex")
        self.assertNotIn("sandbox_workspace_write.network_access=true", argv)
        self.assertIn("sandbox_workspace_write.network_access=false", argv)

    def test_network_is_opt_in_and_explicit(self):
        _, argv = self.spawn(self.base, "--runtime", "codex", "--allow-network")
        self.assertIn("sandbox_workspace_write.network_access=true", argv)

    def test_writable_roots_are_json_encoded_not_interpolated(self):
        # A `"` in a path previously injected ADDITIONAL writable roots (demonstrated
        # granting ~/.ssh, exit 0, no shell metacharacter needed).
        evil = self.root / 'ev"il'
        evil.mkdir()
        git("init", "-q", ".", cwd=evil)
        (evil / "s.txt").write_text("s")
        git("add", "-A", cwd=evil)
        git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "s", cwd=evil)
        _, argv = self.spawn(evil, "--runtime", "codex")
        roots = self.roots(argv)
        self.assertTrue(roots.startswith("["), roots)
        parsed = json.loads(roots)
        self.assertTrue(all(isinstance(r, str) for r in parsed))
        self.assertTrue(any('ev"il' in r for r in parsed), "the real path must survive encoding")
        self.assertEqual(len(parsed), 1, "a quote in the path must not inject extra roots")

    def test_a_lane_output_file_is_requested(self):
        # Claude gets --output-format json so empty output + exit 0 proves it never ran.
        # docs/codex-lane-contract.md requires -o <outfile> for the same classification.
        _, argv = self.spawn(self.base, "--runtime", "codex")
        self.assertIn("-o", argv)

    def test_the_mission_carries_the_session_id_and_no_push_rule(self):
        _, argv = self.spawn(self.base, "--runtime", "codex")
        # The stub records one argv element per LINE, so a multi-line mission spans lines;
        # search the joined text rather than the last line.
        mission = "\n".join(argv)
        self.assertIn("Session-Id: codex-lane-", mission)
        self.assertIn("Do NOT push", mission)

    def test_mcp_config_is_refused_rather_than_silently_dropped(self):
        cfg = self.root / "m.json"; cfg.write_text("{}")
        r, _ = self.spawn(self.base, "--runtime", "codex", "--mcp-config", str(cfg))
        self.assertEqual(r.returncode, 2)
        self.assertIn("claude-only", r.stderr)

    def test_mode_is_refused_rather_than_silently_dropped(self):
        r, _ = self.spawn(self.base, "--runtime", "codex", "--mode", "acceptEdits")
        self.assertEqual(r.returncode, 2)
        self.assertIn("claude-only", r.stderr)

    def test_codex_runtime_never_uses_the_home_isolating_wrapper(self):
        # That wrapper strips git identity; a shipping lane must keep it.
        _, argv = self.spawn(self.base, "--runtime", "codex")
        self.assertNotIn("codex-dispatch.sh", " ".join(argv))

    def test_class_effort_reaches_codex_and_explicit_model_is_preserved(self):
        self.gate_env = {"STUB_ROUTE": "gpt-6-astra high"}
        r, argv = self.spawn(self.base, "--runtime", "codex", "--class", "security",
                             "--model", "gpt-6-sol")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(argv[argv.index("-m") + 1], "gpt-6-sol")
        self.assertIn("model_reasoning_effort=high", argv)
        self.assertEqual((self.root / "gate-args.txt").read_text().splitlines(), ["--route", "security"])

    def test_warning_and_unknown_cap_routes_dispatch(self):
        for rc in ("0", "1"):
            with self.subTest(rc=rc):
                self.gate_env = {"STUB_GATE_RC": rc}
                r, argv = self.spawn(self.base, "--runtime", "codex")
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("model_reasoning_effort=medium", argv)

    def test_refusal_and_errors_prevent_even_explicit_model_launch(self):
        for rc in ("2", "3", "127"):
            with self.subTest(rc=rc):
                self.gate_env = {"STUB_GATE_RC": rc}
                r, argv = self.spawn(self.base, "--runtime", "codex", "--model", "gpt-6-astra")
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertEqual(argv, [])

    def test_missing_gate_and_malformed_routes_refuse(self):
        for route in ("CLAUDE high", "gpt-6-sol", "gpt-6-sol bogus", "gpt-6-sol medium extra",
                      "gpt-6-sol medium\ngpt-6-astra high", ""):
            with self.subTest(route=route):
                self.gate.write_text('#!/bin/bash\nprintf "%s" ' + __import__("shlex").quote(route) + '\n')
                r, argv = self.spawn(self.base, "--runtime", "codex")
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertEqual(argv, [])
        self.gate.unlink()
        r, argv = self.spawn(self.base, "--runtime", "codex")
        self.assertEqual(r.returncode, 2)
        self.assertEqual(argv, [])

    def test_claude_rejects_unsupported_class(self):
        r, argv = self.spawn(self.base, "--runtime", "claude", "--class", "security")
        self.assertEqual(r.returncode, 2)
        self.assertEqual(argv, [])

    def test_an_unknown_runtime_is_rejected(self):
        r, _ = self.spawn(self.base, "--runtime", "bogus")
        self.assertEqual(r.returncode, 2)
        self.assertIn("claude|codex", r.stderr)

    def test_worktree_flag_is_refused_on_codex(self):
        # Codex has no --worktree equivalent; failing loudly beats spawning in the wrong dir.
        r, _ = self.spawn(self.base, "--runtime", "codex", "--worktree", "x")
        self.assertEqual(r.returncode, 2)
        self.assertIn("claude-only", r.stderr)


if __name__ == "__main__":
    unittest.main()
