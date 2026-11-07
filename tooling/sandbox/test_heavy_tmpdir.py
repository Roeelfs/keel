"""The heavy runner selects external temp storage only for test wrappers."""
from pathlib import Path
import os
import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from heavy_resources import Policy
import heavy_runner
from resource_test_support import isolated_wrapper


class HeavyTmpdirTests(unittest.TestCase):
    def environment(self, command, overrides=None):
        env = {'TMPDIR': '/internal', **(overrides or {})}
        with patch.dict(os.environ, env, clear=True):
            return heavy_runner.child_environment(Policy(), 'job', command)

    def test_test_classes_default_on_with_real_probe(self):
        for name in ('wt-verify.sh', 'cynap-sandbox'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as parent:
                # Redirect only the volume; keep the selector's real file I/O.
                import keel_test_tmpdir
                select = keel_test_tmpdir.command_env
                with patch.object(os.path, 'ismount', return_value=True), patch.object(
                        keel_test_tmpdir, 'command_env', side_effect=lambda env: select(env, Path(parent))):
                    env = self.environment(['/bin/' + name])
                root = Path(env['TMPDIR'])
                self.assertEqual(root.parent, Path(parent))
                self.assertEqual(root.stat().st_mode & 0o777, 0o700)
                self.assertEqual(list(root.iterdir()), [])
                self.assertNotIn('KEEL_TEST_TMPDIR_ENABLED', env)

    def test_unmounted_or_unwritable_preserves_internal(self):
        for name in ('wt-verify.sh', 'cynap-sandbox'):
            for mounted in (False, True):
                with self.subTest(name=name, mounted=mounted), patch.object(
                        os.path, 'ismount', return_value=mounted), patch.object(
                        Path, 'mkdir', side_effect=PermissionError('read only')):
                    self.assertEqual(self.environment([name])['TMPDIR'], '/internal')

    def test_launched_child_receives_selected_tmpdir(self):
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent)
            volume = root / 'volume'
            volume.mkdir()
            setup = ("import keel_test_tmpdir\n"
                     "_select = keel_test_tmpdir.command_env\n"
                     "keel_test_tmpdir.os.path.ismount = lambda path: True\n"
                     f"keel_test_tmpdir.command_env = lambda env: _select(env, Path({str(volume)!r}))\n")
            wrapper = isolated_wrapper(root, setup)
            config = root / '.keel' / 'resource-policy.json'
            config.parent.mkdir()
            config.write_text(json.dumps({'min_free_percent': 0, 'run_min_free_percent': 0,
                                          'max_load_per_core': 0, 'protected_apps': [],
                                          'poll_seconds': 0.02}))
            for name in ('wt-verify.sh', 'cynap-sandbox'):
                script = root / name
                script.write_text('#!/bin/sh\nprintf "%s" "$TMPDIR"\n')
                script.chmod(0o700)
                env = {key: value for key, value in os.environ.items()
                       if key not in {'KEEL_TEST_TMPDIR_ENABLED', 'KEEL_HEAVY_JOB_ID'}}
                result = subprocess.run([wrapper, str(script)], env={**env, 'TMPDIR': '/internal'},
                                        capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(Path(result.stdout).parent, volume)

    def test_kill_switch_does_not_probe(self):
        with patch.object(os.path, 'ismount', side_effect=AssertionError('must not probe')):
            for name in ('wt-verify.sh', 'cynap-sandbox'):
                env = self.environment([name], {'KEEL_TEST_TMPDIR_ENABLED': '0'})
                self.assertEqual(env['TMPDIR'], '/internal')
                self.assertEqual(env['KEEL_TEST_TMPDIR_ENABLED'], '0')

    def test_other_classes_unchanged_even_with_explicit_enable(self):
        with patch.object(os.path, 'ismount', side_effect=AssertionError('must not probe')):
            for name in ('vitest', 'node', 'bash', 'other-heavy'):
                env = self.environment([name], {'TMPDIR': '/Volumes/T9/inherited',
                                               'KEEL_TEST_TMPDIR_ENABLED': '1'})
                self.assertEqual(env['TMPDIR'], '/Volumes/T9/inherited')


if __name__ == '__main__':
    unittest.main()
