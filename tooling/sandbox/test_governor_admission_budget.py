#!/usr/bin/env python3
"""Class-aware, JEV-bounded admission (2026-09-30).

Measured: a flat 6 GB budget per job left one usable slot on a 24 GB machine (a second job needed
>=45% free), so 1 GB vitest runs queued behind 6-minute verifies. Each job now reserves its own
class p90 RSS; a fresh JEV admit may take a grey-zone job, never past the run-interrupt floor; and
a memory-refused waiter yields its place to smaller jobs for up to YIELD_MAX_SECONDS.
"""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from heavy_resources import Policy, write_record
import heavy_runner

TOTAL = 24576.0


def pressure(free, others_held=True, budget_mb=None, jev_admit=False, reserve_mb=0.0, **policy):
    with mock.patch.object(heavy_runner, 'free_percent', return_value=free), \
            mock.patch.object(heavy_runner, 'total_memory_mb', return_value=TOTAL):
        return heavy_runner.pressure_reason(Policy(**policy), others_held, budget_mb=budget_mb, jev_admit=jev_admit,
                                        reserve_mb=reserve_mb)


class PressureReasonTests(unittest.TestCase):
    def test_a_small_class_runs_beside_others_where_the_flat_budget_refused(self):
        # 33% free: flat 6144 MB -> 8% left (refused); a 1256 MB pnpm run -> 27.9% left (fits).
        self.assertEqual(pressure(33), 'memory_pressure')
        self.assertIsNone(pressure(33, budget_mb=1256))

    def test_a_big_class_still_serializes_on_memory(self):
        self.assertEqual(pressure(33, budget_mb=4522), 'memory_pressure')

    def test_a_job_alone_needs_only_min_free(self):
        self.assertIsNone(pressure(25, others_held=False))
        self.assertEqual(pressure(15, others_held=False), 'memory_pressure')

    def test_a_jev_admit_takes_a_grey_zone_job(self):
        # 33% free - 4522 MB (18.4%) = 14.6% left: under 20, above the 12% JEV floor.
        self.assertIsNone(pressure(33, budget_mb=4522, jev_admit=True))

    def test_a_jev_admit_never_goes_below_the_run_interrupt_floor(self):
        # 28% free - 18.4% = 9.6% left: below run_min_free_percent (10) + 2.
        self.assertEqual(pressure(28, budget_mb=4522, jev_admit=True), 'memory_pressure')

    def test_running_jobs_unreached_peak_denies_though_current_free_passes(self):
        # 40% free, 1256 MB job -> 34.9% left passes; 6144 MB of running-job growth leaves 9.9%.
        self.assertIsNone(pressure(40, budget_mb=1256))
        self.assertEqual(pressure(40, budget_mb=1256, reserve_mb=6144), 'memory_pressure')

    def test_the_jev_override_floor_includes_the_reserve(self):
        # 33% - 18.4% = 14.6% passes the JEV floor alone; 4000 MB reserve drops it to 8.3%.
        self.assertIsNone(pressure(33, budget_mb=4522, jev_admit=True))
        self.assertEqual(pressure(33, budget_mb=4522, jev_admit=True, reserve_mb=4000), 'memory_pressure')

    def test_a_budget_is_capped_at_max_rss(self):
        self.assertEqual(pressure(33, budget_mb=99999), pressure(33))


class JevAdmitsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.governor_dir = Path(self.tmp.name)
        patch = mock.patch.dict(os.environ, {'KEEL_GOVERNOR_STATE_DIR': str(self.governor_dir)})
        patch.start()
        self.addCleanup(patch.stop)

    def _cache(self, decision, age=0):
        (self.governor_dir / 'decision.pnpm.json').write_text(json.dumps(
            {'cached_at': time.time() - age, 'decision': decision}))

    def test_only_enforce_honours_a_verdict(self):
        self._cache({'admit': True, 'source': 'jev'})
        self.assertFalse(heavy_runner.jev_admits(['pnpm'], Policy(jev_admission='shadow')))
        self.assertTrue(heavy_runner.jev_admits(['pnpm'], Policy(jev_admission='enforce')))

    def test_a_fallback_or_stale_verdict_is_not_a_jev_admit(self):
        self._cache({'admit': True, 'source': 'fallback:no_credential'})
        self.assertFalse(heavy_runner.jev_admits(['pnpm'], Policy(jev_admission='enforce')))
        self._cache({'admit': True, 'source': 'jev'}, age=3600)
        self.assertFalse(heavy_runner.jev_admits(['pnpm'], Policy(jev_admission='enforce')))


class AdmitIsOneJobTests(JevAdmitsTests):
    def test_invalidate_drops_the_class_verdict_so_the_next_waiter_consults(self):
        self._cache({'admit': True, 'source': 'jev'})
        self.assertTrue(heavy_runner.jev_admits(['pnpm'], Policy(jev_admission='enforce')))
        heavy_runner.invalidate_jev_admit(['pnpm'])
        self.assertFalse(heavy_runner.jev_admits(['pnpm'], Policy(jev_admission='enforce')))

    def test_a_jev_admitted_claim_invalidates_the_cache(self):
        self._cache({'admit': True, 'source': 'jev'})
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(heavy_runner, 'job_budget', return_value=(1000.0, 0.0)), \
                mock.patch.object(heavy_runner, 'claim_slot', return_value=('stream', 1)):
            stream, slot = heavy_runner.acquire(Path(tmp), Policy(jev_admission='enforce'), 'job1', ['pnpm'])
        self.assertEqual(slot, 1)
        self.assertFalse((self.governor_dir / 'decision.pnpm.json').exists())


class BudgetAndBackfillTests(unittest.TestCase):
    def test_a_budget_read_failure_falls_back_to_max_rss(self):
        with mock.patch('governor.snapshot.take', side_effect=RuntimeError('boom')):
            self.assertEqual(heavy_runner.job_budget(['pnpm'], Policy()), (6144.0, 0.0))

    def test_a_yielding_ticket_ahead_does_not_count_toward_position(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = Path(tmp)
            big, small = queue / '00000000000000000001-1.json', queue / '00000000000000000002-2.json'
            write_record(big, {'job_id': 'big', 'yield': True})
            write_record(small, {'job_id': 'small'})
            fresh = time.time() - 10
            self.assertEqual(heavy_runner.queue_position([big, small], small, fresh), 1)
            write_record(big, {'job_id': 'big', 'yield': False})
            self.assertEqual(heavy_runner.queue_position([big, small], small, fresh), 2)


if __name__ == '__main__':
    unittest.main()
