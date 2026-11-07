"""Opt-in policy tuning and safe slot-count reductions.

Merge resource-policy.memory-constrained.json into the account policy, preserving unrelated
fields and class entries. Installing the runtime alone does not activate this example.
Caps cover sampled peaks, not uncensored future demand. Pressure floors remain unchanged;
three slots is a concurrency ceiling, not a promise that three large jobs fit in memory.
"""
import fcntl
import contextlib
import io
import json
import os
import multiprocessing
import time
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import heavy_resources
import heavy_runner


PROFILE = Path(__file__).with_name('resource-policy.memory-constrained.json')


def race_claims(directory, start, ready, active, peak, admissions):
    """Exercise real inter-process flocks; isolate host pressure and process sampling."""
    directory = Path(directory)
    policy = heavy_resources.Policy(slots=3)
    with mock.patch.object(heavy_runner, 'lease_group_alive', return_value=False), \
            mock.patch.object(heavy_runner, 'pressure_reason', return_value=None), \
            mock.patch.object(heavy_runner, 'evaluate_load', return_value={'blocker': None}):
        ready.put(True)
        if not start.wait(10):
            raise RuntimeError('race start timed out')
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            stream, _ = heavy_runner.claim_slot(directory, policy, 1)
            if stream is None:
                time.sleep(0.001)
                continue
            try:
                with active.get_lock():
                    active.value += 1
                    peak.value = max(peak.value, active.value)
                    admissions.value += 1
                time.sleep(0.02)
            finally:
                with active.get_lock():
                    active.value -= 1
                stream.close()


class PolicyTuningTests(unittest.TestCase):
    def test_profile_loads_through_the_real_policy_validator(self):
        with tempfile.TemporaryDirectory() as home, mock.patch.object(
                heavy_resources, 'account_home', return_value=Path(home)), \
                mock.patch.dict(os.environ, {}, clear=True):
            directory = Path(home) / '.keel'
            directory.mkdir()
            (directory / 'resource-policy.json').write_bytes(PROFILE.read_bytes())
            policy = heavy_resources.load_policy()
        self.assertEqual((policy.slots, policy.max_slots), (3, 3))
        self.assertEqual((policy.min_free_percent, policy.run_min_free_percent), (20, 10))
        self.assertEqual(heavy_runner.effective_rss_cap('wt-verify.sh', policy, {}), 8192)
        self.assertEqual(heavy_runner.effective_rss_cap('unknown', policy, {}), 6144)
        self.assertEqual(heavy_runner.effective_rss_cap(
            'wt-verify.sh', policy, {'KEEL_HEAVY_MAX_RSS_MB': '4096'}), 4096)

    def test_larger_class_cap_does_not_bypass_memory_admission(self):
        policy = heavy_resources.Policy(**json.loads(PROFILE.read_text()))
        with mock.patch.object(heavy_runner, 'free_percent', return_value=50), \
                mock.patch.object(heavy_runner, 'total_memory_mb', return_value=24576):
            self.assertEqual(heavy_runner.pressure_reason(
                policy, True, job_class='wt-verify.sh'), 'memory_pressure')


class LoweredSlotTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.policy = heavy_resources.Policy(slots=3)
        patch = mock.patch.object(heavy_runner, 'lease_group_alive', return_value=False)
        patch.start()
        self.addCleanup(patch.stop)

    def hold(self, slot):
        stream = heavy_runner.slot_path(self.directory, slot).open('a')
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.addCleanup(stream.close)

    def test_count_includes_jobs_above_the_new_ceiling(self):
        self.hold(4)
        self.assertEqual(heavy_runner.running_job_count(self.directory, self.policy), 1)

    def test_no_new_job_until_total_held_is_below_the_lowered_ceiling(self):
        for slot in (1, 2, 4):
            self.hold(slot)
        with mock.patch.object(heavy_runner, 'pressure_reason', return_value=None), \
                mock.patch.object(heavy_runner, 'evaluate_load', return_value={'blocker': None}):
            stream, reason = heavy_runner.claim_slot(self.directory, self.policy, 1)
        if stream:
            stream.close()
        self.assertIsNone(stream)
        self.assertEqual(reason, 'resource_busy')

    def test_high_slot_counts_as_another_job_for_memory_and_cpu(self):
        self.hold(4)
        with mock.patch.object(heavy_runner, 'pressure_reason', return_value=None) as pressure, \
                mock.patch.object(heavy_runner, 'evaluate_load', return_value={'blocker': None}) as load:
            stream, slot = heavy_runner.claim_slot(self.directory, self.policy, 1)
        self.assertIsNotNone(stream)
        stream.close()
        self.assertLessEqual(slot, self.policy.slots)
        self.assertTrue(pressure.call_args.args[1])
        self.assertEqual(load.call_args.args[2], 1)

    def test_surviving_descendants_above_the_ceiling_still_count(self):
        lease = {'pgid': 123}
        heavy_resources.write_record(heavy_runner.lease_path(self.directory, 4), lease)
        with mock.patch.object(heavy_runner, 'lease_group_alive', side_effect=lambda row: row == lease):
            self.assertEqual(heavy_runner.running_job_count(self.directory, self.policy), 1)
            self.assertEqual(heavy_runner.first_lease(self.directory, self.policy), lease)

    def test_queue_position_cannot_claim_capacity_consumed_by_a_high_slot(self):
        self.hold(4)
        with mock.patch.object(heavy_runner, 'pressure_reason', return_value=None), \
                mock.patch.object(heavy_runner, 'evaluate_load', return_value={'blocker': None}):
            stream, reason = heavy_runner.claim_slot(self.directory, self.policy, 3)
        if stream:
            stream.close()
        self.assertIsNone(stream)
        self.assertEqual(reason, 'resource_busy')
        self.assertTrue(heavy_runner.lock_available(self.directory, 1))

    def test_high_slot_orphan_only_labels_positions_its_exit_would_admit(self):
        lease = {'pgid': 123}
        heavy_resources.write_record(heavy_runner.lease_path(self.directory, 4), lease)
        self.hold(1)
        with mock.patch.object(heavy_runner, 'lease_group_alive', side_effect=lambda row: row == lease), \
                mock.patch.object(heavy_runner, 'pressure_reason', return_value=None), \
                mock.patch.object(heavy_runner, 'evaluate_load', return_value={'blocker': None}):
            for position, expected in ((2, 'previous_job_alive'), (3, 'resource_busy')):
                with self.subTest(position=position):
                    stream, reason = heavy_runner.claim_slot(self.directory, self.policy, position)
                    if stream:
                        stream.close()
                    self.assertIsNone(stream)
                    self.assertEqual(reason, expected)

    def test_high_slot_orphan_does_not_label_full_eligible_slots(self):
        lease = {'pgid': 123}
        heavy_resources.write_record(heavy_runner.lease_path(self.directory, 4), lease)
        for slot in (1, 2, 3):
            self.hold(slot)
        with mock.patch.object(heavy_runner, 'lease_group_alive', side_effect=lambda row: row == lease):
            stream, reason = heavy_runner.claim_slot(self.directory, self.policy, 1)
        if stream:
            stream.close()
        self.assertIsNone(stream)
        self.assertEqual(reason, 'resource_busy')

    def test_dead_high_slot_lease_is_not_reported_as_holder(self):
        heavy_resources.write_record(heavy_runner.lease_path(self.directory, 4), {'pgid': 123})
        self.assertIsNone(heavy_runner.first_lease(self.directory, self.policy))
        self.assertEqual(heavy_runner.holder_description(self.directory, self.policy),
                         'no published slot holder')

    def test_max_slots_keeps_existing_admission_and_orphan_reasons(self):
        policy = heavy_resources.Policy(slots=heavy_resources.MAX_SLOTS)
        lease = {'pgid': 123}
        heavy_resources.write_record(heavy_runner.lease_path(self.directory, 4), lease)
        self.hold(1)
        with mock.patch.object(heavy_runner, 'lease_group_alive', side_effect=lambda row: row == lease), \
                mock.patch.object(heavy_runner, 'pressure_reason', return_value=None), \
                mock.patch.object(heavy_runner, 'evaluate_load', return_value={'blocker': None}):
            self.assertEqual(heavy_runner.running_job_count(self.directory, policy), 2)
            self.assertEqual(heavy_runner.first_lease(self.directory, policy), lease)
            for position, expected in ((1, 2), (2, 2), (3, 'previous_job_alive'), (4, 'resource_busy')):
                with self.subTest(position=position):
                    stream, result = heavy_runner.claim_slot(self.directory, policy, position)
                    if stream:
                        stream.close()
                    self.assertEqual(result, expected)
                    self.assertEqual(stream is not None, position <= 2)

    def test_eight_process_race_counts_live_high_slot_toward_ceiling(self):
        self.hold(4)
        context = multiprocessing.get_context('spawn')
        start, ready = context.Event(), context.Queue()
        active = context.Value('i', 1)  # Include the legacy slot-4 job.
        peak, admissions = context.Value('i', 1), context.Value('i', 0)
        workers = [context.Process(target=race_claims, args=(
            str(self.directory), start, ready, active, peak, admissions)) for _ in range(8)]
        try:
            for worker in workers:
                worker.start()
            for _ in workers:
                self.assertTrue(ready.get(timeout=10))
            start.set()
            for worker in workers:
                worker.join(timeout=10)
                self.assertEqual(worker.exitcode, 0)
            self.assertGreater(admissions.value, 0)
            self.assertGreater(peak.value, 1)
            self.assertLessEqual(peak.value, self.policy.slots)
        finally:
            for worker in workers:
                if worker.is_alive():
                    worker.terminate()
                if worker.pid is not None:
                    worker.join(timeout=5)
            ready.close()
            ready.join_thread()

    def test_status_keeps_a_live_high_slot_visible_until_it_drains(self):
        self.hold(4)
        output = io.StringIO()
        with mock.patch.object(heavy_runner, 'load_policy', return_value=self.policy), \
                mock.patch.object(heavy_runner, 'state_directory', return_value=self.directory), \
                mock.patch('sys.argv', ['with-heavy-lock', '--status']), \
                contextlib.redirect_stdout(output):
            self.assertEqual(heavy_runner.main(), 0)
        status = json.loads(output.getvalue())
        self.assertTrue(status['live'])
        self.assertEqual(status['leases'][-1]['slot'], 4)
        self.assertTrue(status['leases'][-1]['live'])


if __name__ == '__main__':
    unittest.main()
