#!/usr/bin/env python3
"""CPU admission: a load-average gate and a protected-interactive-app reserve (2026-10-19)."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import heavy_resources
import heavy_runner
from heavy_resources import Policy

GAME = '/Applications/Some Game.app/Contents/MacOS/Some Game'


def ps_output(rows):
    return subprocess.CompletedProcess([], 0, stdout=''.join(f'{cpu:5.1f} {comm}\n' for cpu, comm in rows))


def state(policy, running, load1, rows=(), ncpu=12):
    with mock.patch.object(heavy_resources.os, 'getloadavg', return_value=(load1, 0, 0)), \
            mock.patch.object(heavy_resources.os, 'cpu_count', return_value=ncpu), \
            mock.patch.object(heavy_resources.subprocess, 'run', return_value=ps_output(rows)):
        return heavy_resources.cpu_state(policy, running)


class LoadGateTests(unittest.TestCase):
    def test_admits_below_the_per_core_threshold(self):
        self.assertIsNone(state(Policy(), 0, 10.0)['reason'])  # 10 <= 0.85 x 12 = 10.2

    def test_queues_above_the_per_core_threshold(self):
        self.assertEqual(state(Policy(), 0, 10.5)['reason'], 'cpu_pressure')

    def test_zero_threshold_disables_the_gate(self):
        self.assertIsNone(state(Policy(max_load_per_core=0), 0, 99.0)['reason'])

    def test_read_error_fails_open(self):
        with mock.patch.object(heavy_resources.os, 'getloadavg', side_effect=OSError('no load')):
            result = heavy_resources.cpu_state(Policy(), 0)
        self.assertIsNone(result['reason'])
        self.assertIn('no load', result['error'])

    def test_ps_failure_fails_open(self):
        policy = Policy(protected_apps=('Some Game',))
        with mock.patch.object(heavy_resources.subprocess, 'run',
                               side_effect=subprocess.CalledProcessError(1, 'ps')):
            self.assertIsNone(heavy_resources.cpu_state(policy, 3)['reason'])


class ProtectedAppTests(unittest.TestCase):
    policy = Policy(protected_apps=('Some Game',), protected_reserve_cores=2, protected_max_jobs=1)

    def test_absent_app_reserves_nothing(self):
        result = state(self.policy, 2, 9.0, rows=[(50.0, '/usr/bin/other')])
        self.assertEqual((result['reason'], result['reserve_cores'], result['protected_apps']), (None, 0.0, []))

    def test_present_app_reserves_fixed_cores(self):
        result = state(self.policy, 0, 9.0, rows=[(30.0, GAME)])
        self.assertEqual(result['capacity'], 8.2)  # 10.2 - 2 reserved
        self.assertEqual(result['reason'], 'cpu_pressure')

    def test_reserve_grows_to_the_apps_observed_cpu(self):
        result = state(self.policy, 0, 6.0, rows=[(150.0, GAME), (200.0, GAME + ' Helper')])
        self.assertEqual(result['reserve_cores'], 3.5)
        self.assertIsNone(result['reason'])  # 6 <= 10.2 - 3.5

    def test_present_app_caps_concurrent_heavy_jobs(self):
        self.assertIsNone(state(self.policy, 0, 1.0, rows=[(90.0, GAME)])['reason'])
        self.assertEqual(state(self.policy, 1, 1.0, rows=[(90.0, GAME)])['reason'], 'protected_app')


class PolicyLoadTests(unittest.TestCase):
    def test_protected_apps_load_from_the_policy_file(self):
        with tempfile.TemporaryDirectory() as home, mock.patch.object(
                heavy_resources, 'account_home', return_value=Path(home)):
            (Path(home) / '.keel').mkdir()
            (Path(home) / '.keel' / 'resource-policy.json').write_text(json.dumps(
                {'protected_apps': ['Some Game'], 'max_load_per_core': 0.7}))
            policy = heavy_resources.load_policy()
        self.assertEqual((list(policy.protected_apps), policy.max_load_per_core), (['Some Game'], 0.7))

    def test_protected_apps_must_be_strings(self):
        with tempfile.TemporaryDirectory() as home, mock.patch.object(
                heavy_resources, 'account_home', return_value=Path(home)):
            (Path(home) / '.keel').mkdir()
            (Path(home) / '.keel' / 'resource-policy.json').write_text(json.dumps({'protected_apps': [1]}))
            with self.assertRaises(ValueError):
                heavy_resources.load_policy()


class ClaimSlotWiringTests(unittest.TestCase):
    def claim(self, cpu_reason, held_slots=()):
        policy = Policy(slots=2, min_free_percent=0)
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            seen = {}
            available = heavy_runner.fcntl.flock

            def flock(stream, flags):
                if any(stream.name.endswith(f'slot.{s}') for s in held_slots):
                    raise BlockingIOError
                return available(stream, flags)

            def cpu(_policy, held):
                seen['held'] = held
                return {'reason': cpu_reason}
            with mock.patch.object(heavy_runner.fcntl, 'flock', side_effect=flock), \
                    mock.patch.object(heavy_runner, 'cpu_state', side_effect=cpu):
                stream, result = heavy_runner.claim_slot(directory, policy, 1)
            if stream:
                stream.close()
            return result, seen['held']

    def test_cpu_reason_queues_the_job(self):
        self.assertEqual(self.claim('cpu_pressure'), ('cpu_pressure', 0))

    def test_held_slots_are_counted_for_the_protected_cap(self):
        self.assertEqual(self.claim('protected_app', held_slots=(1,)), ('protected_app', 1))

    def test_no_cpu_reason_claims_a_slot(self):
        self.assertEqual(self.claim(None), (1, 0))


if __name__ == '__main__':
    unittest.main()
