#!/usr/bin/env python3
"""Wrapper classification and shim heaviness (spec §6, §14.1)."""
import json
import tempfile
import unittest
from pathlib import Path

from heavy_resources import Policy
from governor import broker


class IsWrapperTests(unittest.TestCase):
    def test_a_bash_wrapper_is_a_wrapper(self):
        policy = Policy()
        self.assertTrue(broker.is_wrapper(['bash', 'round5.sh'], policy))

    def test_a_dot_sh_script_is_a_wrapper(self):
        policy = Policy()
        self.assertTrue(broker.is_wrapper(['/repo/round5.sh'], policy))

    def test_a_non_shell_command_is_not_a_wrapper(self):
        policy = Policy()
        self.assertFalse(broker.is_wrapper(['vitest', 'run'], policy))

    def test_a_custom_rule_keeps_its_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / 'resource-commands.json').write_text(json.dumps({'wt-verify.sh': {}}))
            policy = Policy()
            self.assertFalse(broker.is_wrapper(['wt-verify.sh'], policy, home=home))

    def test_a_self_locking_script_keeps_its_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / 'self.sh'
            script.write_text('#!/bin/sh\n# keel:self-locking\necho hi\n')
            policy = Policy()
            self.assertFalse(broker.is_wrapper([str(script)], policy, cwd=tmp))

    def test_empty_command_is_not_a_wrapper(self):
        self.assertFalse(broker.is_wrapper([], Policy()))


class ShimIsHeavyTests(unittest.TestCase):
    def test_always_heavy_names(self):
        for name in ('tsc', 'turbo', 'cdk', 'next', 'node'):
            with self.subTest(name=name):
                self.assertTrue(broker.shim_is_heavy(name, []))

    def test_test_runners_are_always_heavy(self):
        self.assertTrue(broker.shim_is_heavy('vitest', ['run']))

    def test_package_manager_heavy_verb(self):
        self.assertTrue(broker.shim_is_heavy('pnpm', ['test']))
        self.assertTrue(broker.shim_is_heavy('pnpm', ['--filter', 'x', 'build']))

    def test_package_manager_light_verb_is_not_heavy(self):
        self.assertFalse(broker.shim_is_heavy('pnpm', ['exec', 'eslint']))
        self.assertFalse(broker.shim_is_heavy('npm', ['run', 'lint']))

    def test_unrelated_name_is_not_heavy(self):
        self.assertFalse(broker.shim_is_heavy('cat', ['file']))


class WriteShimsTests(unittest.TestCase):
    def test_writes_one_executable_shim_per_heavy_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / 'shims'
            written = broker.write_shims(directory)
            self.assertEqual(len(written), len(broker.SHIMMED_NAMES))
            for path in written:
                self.assertTrue(path.is_file())
                self.assertTrue(path.stat().st_mode & 0o100)


if __name__ == '__main__':
    unittest.main()
