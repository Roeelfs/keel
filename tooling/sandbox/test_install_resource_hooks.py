#!/usr/bin/env python3
"""Fixture tests for install-resource-hooks.py; never touch the real home."""
import importlib.util, json
from pathlib import Path
import os, subprocess, tempfile, unittest

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("installer", HERE / "install-resource-hooks.py")
installer = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(installer)

class InstallerTests(unittest.TestCase):
    def write_json(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(value), encoding="utf-8")

    def test_spaces_preserve_configs_and_second_apply_is_noop(self):
        with tempfile.TemporaryDirectory(prefix="resource hooks ") as tmp:
            home = Path(tmp) / "home with spaces"; codex_path = home / ".codex" / "hooks.json"; claude_path = home / ".claude" / "settings.json"
            codex = {"keep": {"nested": [1]}, "hooks": {"PreToolUse": [{"matcher": "Agent", "hooks": [{"type": "command", "command": "keep-codex"}]}]}}
            claude = {"keep": {"nested": [2]}, "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "keep-claude"}]}]}}
            self.write_json(codex_path, codex); self.write_json(claude_path, claude)
            plan = installer.install(home, False); self.assertTrue(plan["codex_changed"]); self.assertEqual(json.loads(codex_path.read_text()), codex)
            first = installer.install(home, True); self.assertTrue(first["backups"])
            installed_codex, installed_claude = json.loads(codex_path.read_text()), json.loads(claude_path.read_text())
            self.assertEqual(installed_codex["keep"], codex["keep"]); self.assertEqual(installed_claude["keep"], claude["keep"])
            command = next(h["command"] for g in installed_codex["hooks"]["PreToolUse"] for h in g["hooks"] if "serialize-heavy-ops" in h["command"])
            self.assertIn("home with spaces", command); self.assertIn("'", command)
            probe = subprocess.run(command, shell=True, input=json.dumps({"tool_input": {"command": "git status"}}), capture_output=True, text=True)
            self.assertEqual(probe.returncode, 0, probe.stderr)
            second = installer.install(home, True); self.assertFalse(second["codex_changed"]); self.assertFalse(second["claude_changed"]); self.assertFalse(second["wrapper_changed"]); self.assertNotIn("backups", second)

    def test_existing_codex_handler_is_kept_and_legacy_wrapper_is_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp); self.write_json(home / ".codex" / "hooks.json", {"hooks": {"PreToolUse": [installer.hook_entry("python stale/serialize-heavy-ops.py"), {"matcher": "Agent", "hooks": [{"type": "command", "command": "keep"}]}]}})
            codex_bytes = (home / ".codex" / "hooks.json").read_bytes()
            self.write_json(home / ".claude" / "settings.json", {"hooks": {"PreToolUse": [{"matcher": "Comment", "hooks": [{"type": "command", "command": "serialize-heavy-ops.py"}]}]}})
            wrapper = home / ".local" / "bin" / "with-heavy-lock"; wrapper.parent.mkdir(parents=True); wrapper.write_text("legacy"); wrapper.chmod(0o700)
            result = installer.install(home, True); self.assertFalse(result["codex_changed"]); self.assertTrue(result["claude_changed"]); self.assertTrue(wrapper.is_symlink())
            self.assertEqual((home / ".codex" / "hooks.json").read_bytes(), codex_bytes)
            self.assertEqual(wrapper.resolve(), (home / ".keel" / "resource-hooks" / "with-heavy-lock").resolve()); self.assertTrue(any("with-heavy-lock.resource-hooks" in item for item in result["backups"]))

    def test_existing_claude_shell_guard_is_upgraded_without_a_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            path = home / '.claude/settings.json'
            self.write_json(path, {'hooks': {'PreToolUse': [{'matcher': 'Bash', 'hooks': [
                {'type': 'command', 'command': 'bash ~/.claude/hooks/_run.sh serialize-heavy-ops.sh'},
                {'type': 'command', 'command': 'echo "serialize-heavy-ops.py is documentation"'}]}]}})
            installer.install(home, True)
            handlers = json.loads(path.read_text())['hooks']['PreToolUse'][0]['hooks']
            self.assertEqual(len(handlers), 2)
            self.assertIn('resource-hook', handlers[0]['command'])
            self.assertTrue(handlers[1]['command'].startswith('echo'))

    def test_missing_executable_mode_is_reported_and_repaired(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            installer.install(home, True)
            wrapper = home / '.local/bin/with-heavy-lock'
            wrapper.resolve().chmod(0o600)
            check = installer.install(home, False)
            self.assertTrue(check['wrapper_changed'])
            self.assertIn(str(wrapper.resolve()), check['stale_files'])
            fixed = installer.install(home, True)
            self.assertTrue(os.access(wrapper, os.X_OK))
            self.assertTrue(fixed['backups'])

    def test_claude_gets_the_runtime_argument_and_an_existing_codex_entry_stays_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp); codex_path = home / ".codex" / "hooks.json"; claude_path = home / ".claude" / "settings.json"
            legacy = installer.command_for("/usr/bin/python3", home / ".claude/hooks/serialize-heavy-ops.py")
            codex_path.parent.mkdir(parents=True)
            codex_path.write_text(json.dumps({"hooks": {"PreToolUse": [installer.hook_entry(legacy), {"matcher": "Agent", "hooks": [{"type": "command", "command": "keep-codex"}]}]}}, indent=4) + "\n\n")
            codex_bytes = codex_path.read_bytes()
            self.write_json(claude_path, {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": legacy}, {"type": "command", "command": "keep-claude"}]}]}})
            plan = installer.install(home, False); self.assertTrue(plan["claude_changed"]); self.assertFalse(plan["codex_changed"])
            for _ in range(2):
                result = installer.install(home, True)
                self.assertFalse(result["codex_changed"]); self.assertEqual(codex_path.read_bytes(), codex_bytes)
            self.assertFalse(result["claude_changed"])
            handlers = [h for g in json.loads(claude_path.read_text())["hooks"]["PreToolUse"] for h in g["hooks"]]
            resource = [h["command"] for h in handlers if installer.resource_handler(h)]
            self.assertEqual(len(resource), 1, handlers)
            self.assertTrue(resource[0].endswith(" --runtime claude"), resource[0])
            self.assertIn("keep-claude", [h["command"] for h in handlers])
            probe = subprocess.run(resource[0], shell=True, input=json.dumps({"tool_input": {"command": "git status"}}), capture_output=True, text=True)
            self.assertEqual(probe.returncode, 0, probe.stderr)

    def test_fresh_codex_registration_has_no_runtime_argument(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            self.assertTrue(installer.install(home, True)["codex_changed"])
            commands = [h["command"] for g in json.loads((home / ".codex/hooks.json").read_text())["hooks"]["PreToolUse"] for h in g["hooks"]]
            self.assertEqual(len(commands), 1)
            self.assertNotIn("--runtime", commands[0])
            probe = subprocess.run(commands[0], shell=True, input=json.dumps({"tool_input": {"command": "git status"}}), capture_output=True, text=True)
            self.assertEqual(probe.returncode, 0, probe.stderr)

    def test_missing_hook_interpreter_fails_closed(self):
        for runtime in (None, 'claude'):
            command = installer.command_for('/missing/resource-python', '/missing/resource-hook.py', runtime)
            result = subprocess.run(command, shell=True, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('resource guard unavailable', result.stderr)

if __name__ == "__main__": unittest.main(verbosity=2)
