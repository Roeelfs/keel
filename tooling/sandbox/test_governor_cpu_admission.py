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

FRONT = 100  # synthetic pids: the frontmost app, a busy bystander, a heavy-job member, an idle one
BUSY, JOB, IDLE = 200, 300, 400
JOB_SESSION = 300


def ps_output(rows):
    return subprocess.CompletedProcess([], 0, stdout=''.join(f'{pid} {cpu:5.1f}\n' for pid, cpu in rows))


def state(policy, running, load1, rows=(), ncpu=12, front=FRONT):
    with mock.patch.object(heavy_resources.os, 'getloadavg', return_value=(load1, 0, 0)), \
            mock.patch.object(heavy_resources.os, 'cpu_count', return_value=ncpu), \
            mock.patch.object(heavy_resources, 'frontmost_pid', return_value=front), \
            mock.patch.object(heavy_resources, 'session_of', side_effect=lambda pid: pid), \
            mock.patch.object(heavy_resources.subprocess, 'run', return_value=ps_output(rows)):
        return heavy_resources.cpu_state(policy, running, {JOB_SESSION})


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
        self.assertEqual(result['error'], 'OSError')  # type only: a message could name a process

    def test_ps_failure_fails_open(self):
        with mock.patch.object(heavy_resources, 'frontmost_pid', return_value=FRONT), \
                mock.patch.object(heavy_resources.subprocess, 'run',
                                  side_effect=subprocess.CalledProcessError(1, 'ps')):
            self.assertIsNone(heavy_resources.cpu_state(Policy(), 3)['reason'])


class InteractiveForegroundTests(unittest.TestCase):
    def test_idle_frontmost_app_reserves_nothing(self):
        result = state(Policy(), 2, 9.0, rows=[(FRONT, 10.0), (BUSY, 80.0)])
        self.assertEqual((result['reason'], result['reserve_cores'], result['foreground_busy']), (None, 0.0, False))

    def test_busy_frontmost_app_reserves_the_minimum(self):
        result = state(Policy(), 0, 9.0, rows=[(FRONT, 90.0), (IDLE, 1.0)])
        self.assertEqual((result['capacity'], result['reason']), (8.2, 'cpu_pressure'))  # 10.2 - 2

    def test_reserve_counts_busy_bystanders_but_not_heavy_jobs(self):
        result = state(Policy(), 0, 6.0, rows=[(FRONT, 150.0), (BUSY, 200.0), (JOB, 300.0), (IDLE, 10.0)])
        self.assertEqual(result['interactive_cores'], 3.5)
        self.assertIsNone(result['reason'])  # 6 <= 10.2 - 3.5

    def test_busy_frontmost_app_caps_concurrent_heavy_jobs(self):
        self.assertIsNone(state(Policy(), 0, 1.0, rows=[(FRONT, 90.0)])['reason'])
        self.assertEqual(state(Policy(), 1, 1.0, rows=[(FRONT, 90.0)])['reason'], 'interactive_foreground')

    def test_no_window_server_is_load_only(self):
        result = state(Policy(), 3, 1.0, rows=[(BUSY, 90.0)], front=None)
        self.assertEqual((result['reason'], result['foreground_busy']), (None, False))

    def test_output_is_anonymous(self):
        result = state(Policy(), 0, 1.0, rows=[(FRONT, 90.0)])
        self.assertNotIn(str(FRONT), json.dumps({k: v for k, v in result.items() if k != 'load1'}))


class PolicyLoadTests(unittest.TestCase):
    def test_interactive_fields_load_from_the_policy_file(self):
        with tempfile.TemporaryDirectory() as home, mock.patch.object(
                heavy_resources, 'account_home', return_value=Path(home)):
            (Path(home) / '.keel').mkdir()
            (Path(home) / '.keel' / 'resource-policy.json').write_text(json.dumps(
                {'interactive_max_jobs': 2, 'max_load_per_core': 0.7}))
            policy = heavy_resources.load_policy()
        self.assertEqual((policy.interactive_max_jobs, policy.max_load_per_core), (2, 0.7))

    def test_protected_apps_load_from_the_policy_file(self):
        with tempfile.TemporaryDirectory() as home, mock.patch.object(
                heavy_resources, 'account_home', return_value=Path(home)):
            (Path(home) / '.keel').mkdir()
            (Path(home) / '.keel' / 'resource-policy.json').write_text(json.dumps({'protected_apps': ['x']}))
            self.assertEqual(heavy_resources.load_policy().protected_apps, ['x'])

    def test_protected_apps_must_be_strings(self):
        with tempfile.TemporaryDirectory() as home, mock.patch.object(
                heavy_resources, 'account_home', return_value=Path(home)):
            (Path(home) / '.keel').mkdir()
            (Path(home) / '.keel' / 'resource-policy.json').write_text(json.dumps({'protected_apps': [1]}))
            with self.assertRaises(ValueError):
                heavy_resources.load_policy()


class ProtectedAppTests(unittest.TestCase):
    def run_state(self, policy, comms, load1=1.0):
        def run(cmd, **_kwargs):
            if cmd[-1] == 'comm=':
                return subprocess.CompletedProcess([], 0, stdout=comms)
            return ps_output([])
        with mock.patch.object(heavy_resources.os, 'getloadavg', return_value=(load1, 0, 0)), \
                mock.patch.object(heavy_resources.os, 'cpu_count', return_value=12), \
                mock.patch.object(heavy_resources, 'frontmost_pid', return_value=None), \
                mock.patch.object(heavy_resources.subprocess, 'run', side_effect=run):
            return heavy_resources.cpu_state(policy, 0)

    GAME = '/Applications/MapleStory Launcher.app/Contents/MacOS/MapleStory Launcher\n/bin/zsh\n'

    def test_default_policy_defers_while_maplestory_runs_even_at_low_load(self):
        self.assertEqual(self.run_state(Policy(), self.GAME)['reason'], 'protected_app:MapleStory')

    def test_admits_when_no_protected_app_runs(self):
        self.assertIsNone(self.run_state(Policy(), '/bin/zsh\n/usr/bin/node\n')['reason'])

    def test_empty_list_disables_the_check(self):
        self.assertIsNone(self.run_state(Policy(protected_apps=()), self.GAME)['reason'])

    def test_configured_list_replaces_the_default(self):
        policy = Policy(protected_apps=('Steam',))
        self.assertIsNone(self.run_state(policy, self.GAME)['reason'])
        self.assertEqual(self.run_state(policy, '/Applications/Steam.app/x\n')['reason'], 'protected_app:Steam')

    def test_high_load_per_core_still_defers_without_a_protected_app(self):
        self.assertEqual(self.run_state(Policy(), '/bin/zsh\n', load1=17.0)['reason'], 'cpu_pressure')

    def test_ps_failure_fails_open(self):
        with mock.patch.object(heavy_resources.os, 'getloadavg', return_value=(1, 0, 0)), \
                mock.patch.object(heavy_resources, 'interactive_load', return_value=(0.0, 0.0)), \
                mock.patch.object(heavy_resources.subprocess, 'run',
                                  side_effect=subprocess.CalledProcessError(1, 'ps')):
            self.assertIsNone(heavy_resources.cpu_state(Policy(), 0)['reason'])


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

            def cpu(_policy, held, _sessions):
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
        self.assertEqual(self.claim('interactive_foreground', held_slots=(1,)), ('interactive_foreground', 1))

    def test_no_cpu_reason_claims_a_slot(self):
        self.assertEqual(self.claim(None), (1, 0))


if __name__ == '__main__':
    unittest.main()
