#!/usr/bin/env python3
"""Rule D, floors and the cheap-class +1 (spec §5.2, §5.3). No literals: every input reads from
`Policy()` and a fixture `class_stats`.
"""
import unittest

from heavy_resources import Policy
from governor import admission

WT_VERIFY = {'run_p50_s': 6, 'run_p90_s': 8, 'rss_p90_mb': 900, 'rss_s_p90': 27704, 'n': 1323}
CYNAP_SANDBOX = {'run_p50_s': 362, 'run_p90_s': 612, 'rss_p90_mb': 4018, 'rss_s_p90': 2372241, 'n': 413}
WT_SETUP = {'run_p50_s': 15, 'run_p90_s': 23, 'rss_p90_mb': 2940, 'rss_s_p90': 67631, 'n': 490}


def snapshot(**overrides):
    base = {'mem_free_percent': 30, 'mem_total_mb': 32768, 'mem_pressure_level': 1,
            'disk_free_gib': 40, 'swap_growth_mb_per_min': 0, 'hang_reports_recent': 0,
            'leases': [], 'class_stats': {'wt-verify': WT_VERIFY, 'cynap-sandbox': CYNAP_SANDBOX,
                                          'wt-setup': WT_SETUP}, 'unknown': []}
    base.update(overrides)
    return base


class RuleDTests(unittest.TestCase):
    def test_formula_admits_when_headroom_covers_one_more_job(self):
        policy = Policy(min_free_percent=20, max_slots=6)
        snap = snapshot(mem_free_percent=40, leases=[])
        result = admission.rule_d('cynap-sandbox', snap, policy, running=1)
        # headroom = (40-20)/100*32768 = 6553.6 MB; fit = floor(6553.6/4018) = 1
        self.assertEqual(result['fit'], 1)
        self.assertEqual(result['slots_now'], 2)
        self.assertTrue(result['admit'])

    def test_reserve_mb_nets_out_running_jobs_unreached_peaks(self):
        policy = Policy(min_free_percent=20, max_slots=6)
        lease = {'class': 'cynap-sandbox', 'rss_mb': 500}  # far from its 4018 MB p90
        snap = snapshot(mem_free_percent=40, leases=[lease])
        result = admission.rule_d('cynap-sandbox', snap, policy, running=1)
        self.assertEqual(result['reserve_mb'], 4018 - 500)
        # headroom = 6553.6 - 3518 = 3035.6; fit = floor(3035.6/4018) = 0
        self.assertEqual(result['fit'], 0)
        self.assertFalse(result['admit'])

    def test_slots_now_clamped_to_max_slots(self):
        policy = Policy(min_free_percent=10, max_slots=3)
        snap = snapshot(mem_free_percent=90, leases=[])
        result = admission.rule_d('wt-verify', snap, policy, running=0)
        self.assertLessEqual(result['slots_now'], 3)

    def test_unknown_memory_input_never_admits(self):
        policy = Policy()
        snap = snapshot(mem_free_percent=None)
        result = admission.rule_d('cynap-sandbox', snap, policy, running=0)
        self.assertFalse(result['admit'])

    def test_class_with_fewer_than_ten_samples_falls_back_to_other_heavy(self):
        policy = Policy(min_free_percent=20, max_slots=6)
        stats = {'other-heavy': CYNAP_SANDBOX, 'new-class': {'rss_p90_mb': 100, 'n': 3}}
        snap = snapshot(mem_free_percent=40, class_stats=stats)
        result = admission.rule_d('new-class', snap, policy, running=1)
        self.assertEqual(result['fit'], 1)  # uses CYNAP_SANDBOX's 4018 MB p90, not 100


class CheapClassBonusTests(unittest.TestCase):
    def test_wt_verify_and_wt_setup_qualify_for_the_plus_one(self):
        policy = Policy(cheap_rss_seconds=131072, max_slots=6)
        snap = snapshot()
        d_result = {'slots_now': 2, 'admit': False, 'fit': 0, 'reserve_mb': 0}
        for job_class in ('wt-verify', 'wt-setup'):
            with self.subTest(job_class=job_class):
                bumped = admission.cheap_class_bonus(job_class, snap, policy, d_result)
                self.assertEqual(bumped['slots_now'], 3)

    def test_cynap_sandbox_does_not_qualify(self):
        policy = Policy(cheap_rss_seconds=131072)
        snap = snapshot()
        d_result = {'slots_now': 2, 'admit': False, 'fit': 0, 'reserve_mb': 0}
        bumped = admission.cheap_class_bonus('cynap-sandbox', snap, policy, d_result)
        self.assertEqual(bumped, d_result)

    def test_no_bonus_at_critical_memory_pressure(self):
        policy = Policy(cheap_rss_seconds=131072)
        snap = snapshot(mem_pressure_level=4)
        d_result = {'slots_now': 2, 'admit': False, 'fit': 0, 'reserve_mb': 0}
        bumped = admission.cheap_class_bonus('wt-verify', snap, policy, d_result)
        self.assertEqual(bumped, d_result)


class FloorsTests(unittest.TestCase):
    def test_each_floor_fires_independently_of_a_permissive_jev(self):
        policy = Policy()
        self.assertEqual(admission.floors_fired(snapshot(disk_free_gib=5), policy), ['disk'])
        self.assertEqual(admission.floors_fired(snapshot(swap_growth_mb_per_min=300), policy),
                         ['swap_growth'])
        self.assertEqual(admission.floors_fired(snapshot(mem_pressure_level=4), policy),
                         ['mem_critical'])
        self.assertEqual(admission.floors_fired(snapshot(hang_reports_recent=1), policy),
                         ['app_hang'])

    def test_unknown_signal_never_fires_a_floor(self):
        policy = Policy()
        self.assertEqual(admission.floors_fired(snapshot(disk_free_gib=None), policy), [])

    def test_no_floors_on_a_healthy_snapshot(self):
        policy = Policy()
        self.assertEqual(admission.floors_fired(snapshot(), policy), [])

    def test_soft_disk_reclaim_threshold_never_denies(self):
        policy = Policy(disk_reclaim_gib=25, disk_floor_gib=10)
        self.assertTrue(admission.needs_reclaim(snapshot(disk_free_gib=20), policy))
        self.assertEqual(admission.floors_fired(snapshot(disk_free_gib=20), policy), [])


if __name__ == '__main__':
    unittest.main()
