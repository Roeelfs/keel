#!/usr/bin/env python3
"""Typecheckers are heavy, and `with-heavy-lock --classify` reports it read-only (verify-route entrypoint admission)."""
import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import heavy_runner
from governor import broker

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / '.claude' / 'hooks'))
import heavy_command  # noqa: E402

WRAPPER = HERE / 'with-heavy-lock'


class TypecheckerClassificationTests(unittest.TestCase):
    def test_typecheckers_classify_heavy(self):
        for command in ('tsc', 'tsc7 -p .', 'tsgo', 'vue-tsc --noEmit', 'node a/b/tsc7/bin/tsc',
                        'node node_modules/typescript/lib/tsc.js', 'npx tsc', 'pnpm exec tsc --noEmit',
                        'pnpm typecheck', 'pnpm run typecheck', 'pnpm --filter x typecheck'):
            with self.subTest(command=command):
                self.assertIsNotNone(heavy_command.classify(command))

    def test_info_flags_stay_light(self):
        for command in ('tsc --version', 'tsc -v', 'tsgo --help', 'npx tsc --version',
                        'node a/tsc7/bin/tsc --version', 'echo tsc'):
            with self.subTest(command=command):
                self.assertIsNone(heavy_command.classify(command))

    def test_unparsed_text_names_a_typechecker(self):
        self.assertEqual(heavy_command.unparsed_heavy_token('tsc7 -p "x'), 'tsc7')

    def test_classify_is_a_read_only_with_heavy_lock_verb(self):
        self.assertIsNone(heavy_command.background_required('with-heavy-lock --classify -- tsc',
                                                            {'with-heavy-lock': ['*']}))

    def test_shims_cover_every_typechecker(self):
        for name in heavy_command.TYPECHECKERS:
            with self.subTest(name=name):
                self.assertIn(name, broker.SHIMMED_NAMES)
                self.assertTrue(broker.shim_is_heavy(name, []))


class ClassifyVerbTests(unittest.TestCase):
    def run_main(self, *argv):
        out = io.StringIO()
        refuse = mock.Mock(side_effect=AssertionError('--classify must not touch admission state'))
        with mock.patch.object(sys, 'argv', ['with-heavy-lock', *argv]), \
                mock.patch.object(heavy_runner, 'state_directory', refuse), \
                mock.patch.object(heavy_runner, 'load_policy', refuse), \
                mock.patch.object(heavy_runner, 'acquire', refuse), \
                contextlib.redirect_stdout(out):
            code = heavy_runner.main()
        return code, out.getvalue().strip()

    def test_prints_heavy_or_light_and_exits_zero(self):
        self.assertEqual(self.run_main('--classify', '--', 'tsc', '-p', '.'), (0, 'heavy'))
        self.assertEqual(self.run_main('--classify', '--', 'pnpm', 'typecheck'), (0, 'heavy'))
        self.assertEqual(self.run_main('--classify', '--', 'tsc', '--version'), (0, 'light'))
        self.assertEqual(self.run_main('--classify', '--', 'git', 'status'), (0, 'light'))

    def test_the_launcher_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            result = subprocess.run([sys.executable, str(WRAPPER), '--classify', '--', 'tsc'],
                                    capture_output=True, text=True, cwd=tmp,
                                    env={**os.environ, 'HOME': str(home)})
            self.assertEqual((result.returncode, result.stdout.strip()), (0, 'heavy'), result.stderr)
            self.assertEqual(list(home.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
