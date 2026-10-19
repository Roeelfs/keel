"""Stdlib unittest for digest.py: builds one tiny Claude JSONL and one tiny Codex
JSONL fixture in a temp dir, runs the script as a subprocess (exercising the real
--window CLI contract), and asserts the digest surfaces the human turn, a tool
error, and a REPEATED CALLS line for an identical call made 3x."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "digest.py"

CLAUDE_LINES = [
    {"type": "user", "message": {"role": "user", "content": "please fix the auth bug in login.py"}},
    {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": "ls -la"}},
        {"type": "tool_use", "name": "Bash", "input": {"command": "ls -la"}},
        {"type": "tool_use", "name": "Bash", "input": {"command": "ls -la"}},
    ]}},
    {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "is_error": True, "content": "Error: permission denied writing to /etc/passwd"},
    ]}},
]

CODEX_LINES = [
    {"payload": {"type": "message", "role": "user", "content": "describe the codex human turn about the deploy script"}},
    {"payload": {"type": "function_call", "name": "exec_command", "arguments": {"command": "npm test"}}},
    {"payload": {"type": "function_call", "name": "exec_command", "arguments": {"command": "npm test"}}},
    {"payload": {"type": "function_call", "name": "exec_command", "arguments": {"command": "npm test"}}},
    {"payload": {"type": "function_call_output", "output": "Error: exit code 1: test suite failed"}},
]


def codex_output(inner):
    """The real Codex shape: a list of input_text blocks wrapping a JSON result."""
    return {"payload": {"type": "function_call_output", "output": [
        {"type": "input_text", "text": "Script completed\nWall time 0.4 seconds\nOutput:\n"},
        {"type": "input_text", "text": inner}]}}


def run_digest(lines, root_name=".codex"):
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / root_name / "sessions"
        d.mkdir(parents=True)
        path = d / "rollout-x.jsonl"
        path.write_text("\n".join(json.dumps(l) for l in lines) + "\n")
        buckets = Path(tmp) / "b.json"
        buckets.write_text(json.dumps([[str(path)]]))
        out = Path(tmp) / "out"
        r = subprocess.run([sys.executable, str(SCRIPT), "--window", "w", str(buckets), str(out)],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        return (out / "bucket-0.md").read_text()


class DigestTest(unittest.TestCase):
    def test_digest_contains_human_turn_tool_error_and_repeated_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            claude_dir = Path(tmp) / "claude-project"
            claude_dir.mkdir()
            claude_path = claude_dir / "session.jsonl"
            claude_path.write_text("\n".join(json.dumps(l) for l in CLAUDE_LINES) + "\n")

            # Path must contain "/.codex/" — that substring is how digest.py picks the parser.
            codex_dir = Path(tmp) / ".codex" / "sessions"
            codex_dir.mkdir(parents=True)
            codex_path = codex_dir / "rollout-session.jsonl"
            codex_path.write_text("\n".join(json.dumps(l) for l in CODEX_LINES) + "\n")

            buckets_path = Path(tmp) / "buckets.json"
            buckets_path.write_text(json.dumps([[str(claude_path), str(codex_path)]]))

            outdir = Path(tmp) / "out"
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--window", "test-window-label", str(buckets_path), str(outdir)],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)

            digest_path = outdir / "bucket-0.md"
            self.assertTrue(digest_path.exists(), msg=f"missing {digest_path}; stdout={result.stdout}")
            content = digest_path.read_text()

            self.assertIn("test-window-label", content, "the --window label must reach the bucket header")
            self.assertIn("please fix the auth bug in login.py", content, "human turn missing")
            self.assertIn("TOOL ERRORS", content, "tool error section missing")
            self.assertIn("permission denied", content, "tool error body missing")
            self.assertIn("REPEATED CALLS", content, "friction-loop section missing")
            self.assertIn("3x", content, "the identical 3x call should be counted as a repeated call")


class CodexErrorCountingTest(unittest.TestCase):
    """The old rule flagged any output that merely CONTAINED "error"/"denied"/"rejected"
    (7741 of 13132 outputs over 10-13..19); an error is a non-zero inner exit code."""

    def test_a_successful_command_that_prints_error_words_is_not_an_error(self):
        out = run_digest([
            {"payload": {"type": "message", "role": "user", "content": "grep for the error handler"}},
            codex_output('{"i":0,"result":{"value":{"exit_code":0,"output":"throw new Error; denied; rejected"}}}'),
        ])
        self.assertNotIn("TOOL ERRORS (", out)
        self.assertNotIn("HOOK DENIALS (", out)

    def test_a_non_zero_inner_exit_code_is_an_error(self):
        out = run_digest([codex_output('{"i":0,"result":{"value":{"exit_code":2,"output":"npm ERR"}}}')])
        self.assertIn("TOOL ERRORS (1)", out)

    def test_an_escaped_exit_code_in_a_string_output_is_parsed(self):
        out = run_digest([{"payload": {"type": "function_call_output",
                                       "output": 'wrapped {\\"exit_code\\":1,\\"output\\":\\"x\\"}'}}])
        self.assertIn("TOOL ERRORS (1)", out)

    def test_script_failed_is_an_error(self):
        out = run_digest([{"payload": {"type": "function_call_output", "output": "Script failed\nboom"}}])
        self.assertIn("TOOL ERRORS (1)", out)

    def test_a_pretooluse_hook_block_is_a_denial_not_an_error(self):
        out = run_digest([{"payload": {"type": "function_call_output",
                                       "output": "Command blocked by PreToolUse hook: heavy command"}}])
        self.assertIn("HOOK DENIALS (1)", out)
        self.assertNotIn("TOOL ERRORS (", out)


if __name__ == "__main__":
    unittest.main()
