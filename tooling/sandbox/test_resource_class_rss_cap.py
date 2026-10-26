#!/usr/bin/env python3
"""Per-class RSS cap (CYN-3159): the resolver, the loader field, and every site that reads the cap."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from heavy_resources import Policy, class_rss_caps
import heavy_runner
from heavy_runner import effective_rss_cap, job_class_of
from resource_test_support import isolated_wrapper

TOTAL = 24576.0
ALLOC = "import time; x = b'x' * (300 * 1024 * 1024); time.sleep(0.6)"


class EffectiveRssCapTests(unittest.TestCase):
    def test_class_value_default_and_unknown_or_empty_command(self):
        policy = Policy(class_max_rss_mb={'wt-verify.sh': 8192.0})
        self.assertEqual(effective_rss_cap('wt-verify.sh', policy, {}), 8192)
        self.assertEqual(effective_rss_cap('vitest', policy, {}), 6144)
        self.assertEqual(effective_rss_cap(job_class_of([]), policy, {}), 6144)
        self.assertEqual(effective_rss_cap(None, policy, {}), 6144)
        self.assertEqual(job_class_of(['/repo/tooling/wt-verify.sh', 'all']), 'wt-verify.sh')

    def test_environment_ceiling_tightens_a_class_cap_and_never_loosens_it(self):
        policy = Policy(class_max_rss_mb={'wt-verify.sh': 8192.0})
        cap = lambda env: effective_rss_cap('wt-verify.sh', policy, env)  # noqa: E731
        self.assertEqual(cap({}), 8192)
        self.assertEqual(cap({'KEEL_HEAVY_MAX_RSS_MB': '4096'}), 4096)
        self.assertEqual(cap({'KEEL_HEAVY_MAX_RSS_MB': '16384'}), 8192)

    def test_the_process_environment_is_the_default_source(self):
        policy = Policy(class_max_rss_mb={'wt-verify.sh': 8192.0})
        with mock.patch.dict(os.environ, {'KEEL_HEAVY_MAX_RSS_MB': '4096'}):
            self.assertEqual(effective_rss_cap('wt-verify.sh', policy), 4096)


class AdmissionSitesTests(unittest.TestCase):
    def pressure(self, free, **kwargs):
        policy = Policy(class_max_rss_mb={'wt-verify.sh': 1256.0})
        with mock.patch.object(heavy_runner, 'free_percent', return_value=free), \
                mock.patch.object(heavy_runner, 'total_memory_mb', return_value=TOTAL):
            return heavy_runner.pressure_reason(policy, True, **kwargs)

    def test_pressure_reason_clamps_to_the_class_cap_not_the_default(self):
        # 33% free: the 6144 default leaves 8% (refused); a 1256 class cap leaves 27.9% (fits).
        self.assertEqual(self.pressure(33), 'memory_pressure')
        self.assertIsNone(self.pressure(33, job_class='wt-verify.sh'))
        self.assertIsNone(self.pressure(33, job_class='wt-verify.sh', budget_mb=99999))
        self.assertEqual(self.pressure(33, job_class='vitest', budget_mb=99999), 'memory_pressure')

    def test_job_budget_is_capped_at_the_class_cap_and_falls_back_to_it(self):
        policy = Policy(class_max_rss_mb={'wt-verify.sh': 8192.0})
        snapshot = {'class_stats': {'wt-verify.sh': {'n': 40, 'rss_p90_mb': 7000.0},
                                    'vitest': {'n': 40, 'rss_p90_mb': 7000.0}}, 'leases': []}
        with mock.patch('governor.snapshot.take', return_value=snapshot):
            self.assertEqual(heavy_runner.job_budget(['wt-verify.sh'], policy), (7000.0, 0.0))
            self.assertEqual(heavy_runner.job_budget(['vitest'], policy), (6144.0, 0.0))
        with mock.patch('governor.snapshot.take', side_effect=RuntimeError('boom')):
            self.assertEqual(heavy_runner.job_budget(['wt-verify.sh'], policy), (8192.0, 0.0))
            self.assertEqual(heavy_runner.job_budget(['vitest'], policy), (6144.0, 0.0))

    def test_admit_preview_prices_the_canonical_class(self):
        # A synthetic preview class maps to the executable the policy entry is keyed by.
        policy = Policy(class_max_rss_mb={'cynap-sandbox': 1256.0}, max_load_per_core=0, protected_apps=())
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {'KEEL_GOVERNOR_STATE_DIR': str(Path(tmp) / 'gov')}), \
                mock.patch.object(heavy_runner, 'pressure_reason', return_value=None) as pressure:
            directory = Path(tmp) / 'heavy.slots'
            (directory / 'queue').mkdir(parents=True)
            heavy_runner.admit_preview(directory, policy, 'cynap-verify-quick')
        self.assertEqual(pressure.call_args.kwargs['job_class'], 'cynap-sandbox')


class LoaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.keel = os.path.join(self.tmp.name, '.keel')
        os.makedirs(self.keel)
        self.wrapper = isolated_wrapper(self.tmp.name)

    def status(self, **values):
        with open(os.path.join(self.keel, 'resource-policy.json'), 'w', encoding='utf-8') as handle:
            json.dump({'min_free_percent': 0, 'max_load_per_core': 0, 'protected_apps': [], **values}, handle)
        env = {**os.environ, 'HOME': self.tmp.name, 'KEEL_HEAVY_MIN_FREE_PERCENT': '0'}
        return subprocess.run([self.wrapper, '--status'], env=env, capture_output=True, text=True, timeout=15)

    def test_absent_field_is_the_old_behaviour(self):
        result = self.status()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['class_max_rss_mb'], {})

    def test_valid_entries_load(self):
        result = self.status(class_max_rss_mb={'wt-verify.sh': 8192, 'node': 4096.5})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['class_max_rss_mb'], {'wt-verify.sh': 8192, 'node': 4096.5})

    def test_a_bad_entry_is_dropped_with_a_log_line_and_the_wrapper_still_runs(self):
        result = self.status(class_max_rss_mb={
            'good': 8192, 'zero': 0, 'negative': -1, 'text': '8192', 'flag': True, 'null': None,
            '/usr/bin/tool': 100, 'two words': 100, '': 100})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['class_max_rss_mb'], {'good': 8192})
        for dropped in ('zero', 'negative', 'text', 'flag', 'null', '/usr/bin/tool', 'two words', ''):
            self.assertIn('class_max_rss_mb entry ' + repr(dropped), result.stderr)

    def test_a_non_object_field_is_ignored_not_fatal(self):
        for bad in ([], 'x', 5, None):
            result = self.status(class_max_rss_mb=bad)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['class_max_rss_mb'], {})
            self.assertIn('ignoring class_max_rss_mb', result.stderr)

    def test_non_finite_values_are_dropped(self):
        self.assertEqual(class_rss_caps({'a': float('inf'), 'b': float('nan'), 'c': 1}), {'c': 1.0})


class RunTimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.keel = os.path.join(self.tmp.name, '.keel')
        os.makedirs(self.keel)
        self.wrapper = isolated_wrapper(self.tmp.name)
        self.klass = os.path.basename(sys.executable)

    def run_job(self, **policy):
        with open(os.path.join(self.keel, 'resource-policy.json'), 'w', encoding='utf-8') as handle:
            json.dump({'min_free_percent': 0, 'max_load_per_core': 0, 'protected_apps': [], **policy}, handle)
        env = {**os.environ, 'HOME': self.tmp.name, 'KEEL_HEAVY_POLL_SECONDS': '0.05',
               'KEEL_HEAVY_MIN_FREE_PERCENT': '0'}
        return subprocess.run([self.wrapper, sys.executable, '-c', ALLOC], env=env,
                              capture_output=True, text=True, timeout=30)

    def events(self):
        with open(os.path.join(self.keel, 'heavy.slots', 'events.jsonl'), encoding='utf-8') as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def test_the_kill_compare_and_its_message_use_the_class_cap(self):
        result = self.run_job(class_max_rss_mb={self.klass: 100})
        self.assertEqual(result.returncode, 137, result.stderr)
        self.assertIn('(budget 100 MiB)', result.stderr)
        self.assertEqual([e['reason'] for e in self.events() if e['event'] == 'completed'], ['resource_limit'])

    def test_a_class_without_an_entry_is_still_capped_at_the_default(self):
        result = self.run_job(class_max_rss_mb={'other': 100}, max_rss_mb=100)
        self.assertEqual(result.returncode, 137, result.stderr)
        self.assertIn('(budget 100 MiB)', result.stderr)

    def test_a_completed_job_above_85_percent_of_its_cap_writes_rss_headroom_low(self):
        result = self.run_job(class_max_rss_mb={self.klass: 340})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('rss_headroom_low', result.stderr)
        low = [e for e in self.events() if e['event'] == 'rss_headroom_low']
        self.assertEqual(len(low), 1, self.events())
        self.assertEqual(low[0]['cap_mb'], 340)
        self.assertGreater(low[0]['peak_rss_mb'], 0.85 * 340)

    def test_a_job_under_85_percent_writes_no_headroom_event(self):
        result = self.run_job(class_max_rss_mb={self.klass: 4096})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([e for e in self.events() if e['event'] == 'rss_headroom_low'], [])


class HeadroomTests(unittest.TestCase):
    def test_threshold_is_exclusive_at_85_percent(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            heavy_runner.warn_headroom_low(directory, 'j', 'x', 850.0, 1000.0)
            self.assertFalse((directory / 'events.jsonl').exists())
            heavy_runner.warn_headroom_low(directory, 'j', 'x', 850.1, 1000.0)
            row = json.loads((directory / 'events.jsonl').read_text())
            self.assertEqual((row['event'], row['cap_mb'], row['job_class']), ('rss_headroom_low', 1000.0, 'x'))


if __name__ == '__main__':
    unittest.main()
