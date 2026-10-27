#!/usr/bin/env python3
"""CYN-3161: one load evaluator shared by the lock and --admit-preview (machine-governor spec §7)."""
import fcntl
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import heavy_resources
import heavy_runner
from heavy_resources import Policy

FRONT, BYSTANDER, TINY = 100, 200, 300  # synthetic pids


def ps_output(rows):
    return subprocess.CompletedProcess([], 0, stdout=''.join(f'{pid} {cpu:5.1f}\n' for pid, cpu in rows))


class LoadEvaluatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.heavy_dir = Path(self.tmp.name) / 'heavy.slots'
        self.heavy_dir.mkdir()
        (self.heavy_dir / 'queue').mkdir()
        patch = mock.patch.dict(os.environ, {'KEEL_GOVERNOR_STATE_DIR': str(Path(self.tmp.name) / 'governor')})
        patch.start()
        self.addCleanup(patch.stop)

    def hold_slot(self, slot):
        stream = heavy_runner.slot_path(self.heavy_dir, slot).open('a')
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.addCleanup(stream.close)

    def machine(self, load1=1.0, front_cores=0.0, background=(0.0, 0.0)):
        patches = [
            mock.patch.object(heavy_resources.os, 'getloadavg', return_value=(load1, 0, 0)),
            mock.patch.object(heavy_resources.os, 'cpu_count', return_value=12),
            mock.patch.object(heavy_resources, 'interactive_load', return_value=(front_cores, front_cores)),
            mock.patch.object(heavy_resources, 'protected_app_running', return_value=None),
            mock.patch.object(heavy_runner, 'background_load', return_value=background),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def preview(self, policy):
        return heavy_runner.admit_preview(self.heavy_dir, policy, 'cynap-verify-full')

    def test_admit_has_load_fields_and_no_deny_reason(self):
        self.machine(load1=1.0)
        result = self.preview(Policy(min_free_percent=0))
        self.assertEqual(result['decision'], 'admit')
        self.assertIsNone(result['deny_reason'])
        self.assertEqual(result['load']['ncpu'], 12)
        self.assertEqual(result['load']['running_jobs'], 0)
        self.assertEqual(result['load']['memory'], 'ok')

    def test_cpu_pressure_deny_reason_is_present_in_shadow_and_enforce(self):
        self.machine(load1=14.2)
        for mode in ('shadow', 'enforce'):
            with self.subTest(mode=mode):
                result = self.preview(Policy(min_free_percent=0, governor_mode=mode))
                self.assertEqual(result['decision'], 'deny')
                self.assertEqual(result['deny_reason'], 'cpu_pressure')
                self.assertEqual(result['load']['cpu_reason'], 'cpu_pressure')

    def test_memory_pressure_is_the_effective_blocker_and_cpu_is_still_observed(self):
        self.machine(load1=14.2)
        with mock.patch.object(heavy_runner, 'pressure_reason', return_value='memory_pressure'):
            result = self.preview(Policy())
        self.assertEqual(result['deny_reason'], 'memory_pressure')
        self.assertEqual(result['load']['memory'], 'pressure')
        self.assertEqual(result['load']['cpu_reason'], 'cpu_pressure')

    def test_a_queue_only_deny_reports_queue(self):
        self.machine(load1=1.0)
        self.hold_slot(1)
        result = self.preview(Policy(slots=1, max_slots=1, min_free_percent=0))
        self.assertEqual(result['decision'], 'deny')
        self.assertEqual(result['deny_reason'], 'queue')

    def test_a_cpu_read_error_is_preserved_not_collapsed(self):
        with mock.patch.object(heavy_resources.os, 'getloadavg', side_effect=OSError('x')):
            result = self.preview(Policy(min_free_percent=0))
        self.assertEqual(result['load']['error'], 'OSError')
        self.assertIsNone(result['load']['cpu_reason'])

    def test_preview_and_lock_agree_on_running_jobs_and_verdict(self):
        # One held slot plus a busy frontmost app: the preview's old count (leases) was 0 here,
        # so it admitted while the lock deferred on interactive_foreground.
        self.machine(load1=3.0, front_cores=0.8)
        self.hold_slot(1)
        policy = Policy(slots=2, max_slots=2, min_free_percent=0, interactive_max_jobs=1)
        result = self.preview(policy)
        self.assertEqual(result['load']['running_jobs'], 1)
        self.assertEqual(result['deny_reason'], 'interactive_foreground')
        stream, reason = heavy_runner.claim_slot(self.heavy_dir, policy, 1)
        self.assertIsNone(stream)
        self.assertEqual(reason, 'interactive_foreground')

    def test_preview_logs_counted_and_uncounted_background_cpu(self):
        self.machine(load1=1.0, background=(1.55, 0.5))
        self.preview(Policy(min_free_percent=0))
        events = [json.loads(line) for line in (self.heavy_dir / 'events.jsonl').read_text().splitlines()]
        row = next(item for item in events if item['event'] == 'background_cpu')
        self.assertEqual(row['counted_cores'], 1.55)
        self.assertEqual(row['uncounted_cores'], 0.5)


if __name__ == '__main__':
    unittest.main()


class BackgroundLoadTests(unittest.TestCase):
    def test_splits_counted_from_uncounted_and_skips_front_and_job_members(self):
        rows = [(FRONT, 90.0), (BYSTANDER, 155.0), (TINY, 30.0), (TINY + 1, 20.0), (900, 400.0)]
        with mock.patch.object(heavy_resources, 'frontmost_pid', return_value=FRONT), \
                mock.patch.object(heavy_resources, 'session_of', side_effect=lambda pid: pid), \
                mock.patch.object(heavy_resources.subprocess, 'run', return_value=ps_output(rows)):
            counted, uncounted = heavy_resources.background_load(Policy(), {900})
        self.assertEqual((round(counted, 2), round(uncounted, 2)), (1.55, 0.5))
