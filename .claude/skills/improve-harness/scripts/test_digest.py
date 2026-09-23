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


if __name__ == "__main__":
    unittest.main()
