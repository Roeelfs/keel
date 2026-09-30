#!/usr/bin/env python3
"""with-heavy-lock --admit-preview: the exact contract cynap's verify-route.mjs consumes (spec §7).

verify-route.mjs's own checks (mirrored here as the "contract"):
  - exit 0 required, or it is read as preview-unavailable (R4);
  - the parsed JSON must be an object with `decision` as a string;
  - `eta_total_s` and `eta_wait_p90_s`, when present, must be JS `number`s (Python int/float,
    never a string, never None) -- verify-route does `typeof p.eta_total_s === 'number'`.
Never queues (no queue/ ticket is written) and never claims a slot (no lease is written).
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from heavy_resources import Policy, write_record
import heavy_runner

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
WRAPPER = HERE / 'with-heavy-lock'


def assert_contract(case, result):
    """The exact field checks verify-route.mjs's admitPreview()/decideRoute() apply."""
    case.assertIsInstance(result, dict)
    case.assertIsInstance(result['decision'], str)
    for key in ('eta_total_s', 'eta_wait_p90_s'):
        if key in result and result[key] is not None:
            case.assertIsInstance(result[key], (int, float))
            case.assertNotIsInstance(result[key], bool)


class AdmitPreviewFunctionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.heavy_dir = Path(self.tmp.name) / 'heavy.slots'
        self.governor_dir = Path(self.tmp.name) / 'governor'
        self.heavy_dir.mkdir()
        (self.heavy_dir / 'queue').mkdir()
        self.env_patch = mock.patch.dict(os.environ, {'KEEL_GOVERNOR_STATE_DIR': str(self.governor_dir)})
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def test_no_leases_admits_via_the_fast_path_and_never_writes_a_ticket_or_lease(self):
        result = heavy_runner.admit_preview(self.heavy_dir, Policy(), 'other-heavy')
        assert_contract(self, result)
        self.assertEqual(result['decision'], 'admit')
        self.assertEqual(result['source'], 'fast_path')
        self.assertEqual(list((self.heavy_dir / 'queue').glob('*')), [])
        self.assertEqual(list(self.heavy_dir.glob('lease.*.json')), [])

    def test_full_slots_denies_and_reports_numeric_eta_fields(self):
        policy = Policy(slots=1, max_slots=1)
        write_record(self.heavy_dir / 'lease.1.json',
                      {'job_id': 'j1', 'class': 'cynap-verify-quick', 'pgid': 999999999,
                       'started': time.time() - 5, 'cwd': None})
        (self.governor_dir).mkdir(parents=True, exist_ok=True)
        (self.governor_dir / 'class-stats.json').write_text(json.dumps({
            'cynap-verify-quick': {'run_p50_s': 362, 'run_p90_s': 600, 'rss_p90_mb': 3100, 'n': 40}}))
        result = heavy_runner.admit_preview(self.heavy_dir, policy, 'cynap-verify-quick')
        assert_contract(self, result)
        self.assertEqual(result['decision'], 'deny')
        self.assertGreaterEqual(result['eta_total_s'], 0)

    def test_live_bug_2026_09_29_real_leases_no_class_stats_file_deny_has_nonzero_eta(self):
        # Reproduces the exact reported shape: `--class cynap-verify-full`, two REAL leases (the
        # 'executable'/'started_ns' shape run_job() actually writes, never 'class'/'started'),
        # class-stats.json absent. Before the fix this returned eta_*_s: 0.0 on a deny.
        policy = Policy(slots=2, max_slots=2)
        for slot in (1, 2):
            write_record(self.heavy_dir / f'lease.{slot}.json', {
                'job_id': f'j{slot}', 'supervisor_pid': 1, 'supervisor_identity': 'x',
                'pgid': 999999990 + slot, 'cwd': '/repo', 'executable': 'cynap-sandbox',
                'slot': slot, 'started_ns': time.time_ns() - 60_000_000_000})
        # A real completed job in this machine's history -- the only source of real numbers,
        # since class-stats.json is never written by any code in this repo.
        events = self.heavy_dir / 'events.jsonl'
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        with events.open('a') as stream:
            for i in range(10):
                started = now - timedelta(seconds=600 + i)
                completed = started + timedelta(seconds=400)
                stream.write(json.dumps({'event': 'started', 'job_id': f'hist{i}',
                                         'executable': 'cynap-sandbox', 'ts': started.isoformat()}) + '\n')
                stream.write(json.dumps({'event': 'completed', 'job_id': f'hist{i}', 'reason': 'exit',
                                         'peak_rss_mb': 4000, 'exit_code': 0,
                                         'ts': completed.isoformat()}) + '\n')
        result = heavy_runner.admit_preview(self.heavy_dir, policy, 'cynap-verify-full')
        assert_contract(self, result)
        self.assertEqual(result['decision'], 'deny')
        self.assertEqual(result['running'], 2)
        self.assertGreater(result['eta_total_s'], 0)
        self.assertGreater(result['eta_wait_p90_s'], 0)

    def test_a_disk_floor_always_denies_even_if_d_rule_would_admit(self):
        policy = Policy(slots=1, max_slots=6, disk_floor_gib=999999)  # always fires
        result = heavy_runner.admit_preview(self.heavy_dir, policy, 'other-heavy')
        assert_contract(self, result)
        self.assertEqual(result['decision'], 'deny')

    def test_a_cached_jev_verdict_can_flip_a_d_rule_deny_to_admit_without_a_live_call(self):
        policy = Policy(slots=1, max_slots=1, jev_admission='enforce', governor_mode='enforce')
        write_record(self.heavy_dir / 'lease.1.json',
                      {'job_id': 'j1', 'class': 'other-heavy', 'pgid': 999999999,
                       'started': time.time(), 'cwd': None})
        self.governor_dir.mkdir(parents=True, exist_ok=True)
        (self.governor_dir / 'decision.other-heavy.json').write_text(json.dumps(
            {'cached_at': time.time(), 'decision': {'admit': True, 'slots_now': 2, 'source': 'jev'}}))
        calls = []
        with mock.patch('governor.jev_client._default_http_post', side_effect=lambda *a, **k: calls.append(1)):
            result = heavy_runner.admit_preview(self.heavy_dir, policy, 'other-heavy')
        self.assertEqual(calls, [])  # never a fresh live call from the preview path
        assert_contract(self, result)
        self.assertEqual(result['decision'], 'admit')
        self.assertEqual(result['source'], 'jev')

    def test_shadow_mode_reports_a_cached_jev_verdict_but_never_applies_it(self):
        # 2026-09-30: in shadow the slot loop admits only below policy.slots, so a preview that
        # applied JEV's admit promised a slot the loop would not give.
        policy = Policy(slots=1, max_slots=6, jev_admission='shadow')
        write_record(self.heavy_dir / 'lease.1.json',
                      {'job_id': 'j1', 'class': 'other-heavy', 'pgid': 999999999,
                       'started': time.time(), 'cwd': None})
        self.governor_dir.mkdir(parents=True, exist_ok=True)
        (self.governor_dir / 'decision.other-heavy.json').write_text(json.dumps(
            {'cached_at': time.time(), 'decision': {'admit': True, 'slots_now': 3, 'source': 'jev'}}))
        result = heavy_runner.admit_preview(self.heavy_dir, policy, 'other-heavy')
        assert_contract(self, result)
        self.assertEqual(result['decision'], 'deny')
        self.assertEqual(result['source'], 'shadow_queue')
        self.assertEqual(result['slots_now'], 1)
        self.assertEqual(result['jev']['admit'], True)

    def _history(self, executable, run_s, n=10):
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        with (self.heavy_dir / 'events.jsonl').open('a') as stream:
            for i in range(n):
                started = now - timedelta(seconds=3600 + i)
                stream.write(json.dumps({'event': 'started', 'job_id': f'{executable}{i}',
                                         'executable': executable, 'ts': started.isoformat()}) + '\n')
                stream.write(json.dumps({'event': 'completed', 'job_id': f'{executable}{i}', 'reason': 'exit',
                                         'peak_rss_mb': 1000, 'exit_code': 0,
                                         'ts': (started + timedelta(seconds=run_s)).isoformat()}) + '\n')

    def _ticket(self, name, job_class):
        me = heavy_runner.processes()[os.getpid()]
        record = {'pid': me.pid, 'identity': me.identity, 'job_id': name, 'enqueued': time.time()}
        if job_class:
            record['class'] = job_class
        write_record(self.heavy_dir / 'queue' / f'{time.time_ns():020d}-{name}.json', record)

    def test_eta_prices_the_queue_by_each_tickets_own_class_not_the_callers(self):
        # Live 2026-09-30: 7 queued seconds-long jobs were priced at cynap-sandbox's p90 each,
        # reporting a 76-minute wait against a real worst case of ~8 minutes.
        policy = Policy(slots=1, max_slots=1)
        self._history('cynap-sandbox', 600)
        self._history('pnpm', 10)
        write_record(self.heavy_dir / 'lease.1.json',
                      {'job_id': 'j1', 'executable': 'pnpm', 'pgid': 999999999,
                       'started_ns': time.time_ns(), 'cwd': None})
        for i in range(4):
            self._ticket(f'cheap{i}', 'pnpm')
        result = heavy_runner.admit_preview(self.heavy_dir, policy, 'cynap-verify-full')
        assert_contract(self, result)
        self.assertEqual(result['decision'], 'deny')
        self.assertEqual(result['queued'], 4)
        self.assertLess(result['eta_wait_p90_s'], 60)  # 10s lease + 4 x 10s, never 4 x 600s

    def test_eta_prices_a_classless_ticket_as_the_callers_class(self):
        policy = Policy(slots=1, max_slots=1)
        self._history('cynap-sandbox', 600)
        write_record(self.heavy_dir / 'lease.1.json',
                      {'job_id': 'j1', 'executable': 'cynap-sandbox', 'pgid': 999999999,
                       'started_ns': time.time_ns(), 'cwd': None})
        self._ticket('old', None)
        result = heavy_runner.admit_preview(self.heavy_dir, policy, 'cynap-verify-full')
        self.assertGreaterEqual(result['eta_wait_p90_s'], 1200)  # lease 600 + one ticket 600

    def test_never_writes_a_snapshot_sample_persist_false(self):
        heavy_runner.admit_preview(self.heavy_dir, Policy(), 'other-heavy')
        self.assertFalse((self.governor_dir / 'snapshots.jsonl').exists())


class AdmitPreviewCliTests(unittest.TestCase):
    """End to end through the real `with-heavy-lock --admit-preview --class X --json` CLI, exactly
    as cynap's verify-route.mjs shells out to it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        from resource_test_support import isolated_wrapper
        self.wrapper = isolated_wrapper(self.tmp.name)

    def env(self, **extra):
        result = dict(os.environ)
        result.update({'HOME': self.tmp.name, 'KEEL_GOVERNOR_STATE_DIR': str(Path(self.tmp.name) / 'gov')})
        result.update(extra)
        return result

    def test_exit_0_with_parseable_json_and_a_string_decision(self):
        result = subprocess.run([self.wrapper, '--admit-preview', '--class', 'other-heavy', '--json'],
                                capture_output=True, text=True, timeout=5, env=self.env())
        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = json.loads(result.stdout.strip())
        assert_contract(self, parsed)

    def test_missing_class_argument_fails_closed_non_zero(self):
        result = subprocess.run([self.wrapper, '--admit-preview'], capture_output=True, text=True,
                                timeout=5, env=self.env())
        self.assertNotEqual(result.returncode, 0)

    def test_never_queues_or_claims_a_slot_as_a_side_effect(self):
        home = Path(self.tmp.name)
        subprocess.run([self.wrapper, '--admit-preview', '--class', 'other-heavy', '--json'],
                      capture_output=True, text=True, timeout=5, env=self.env())
        status = subprocess.run([self.wrapper, '--status'], capture_output=True, text=True,
                                timeout=5, env=self.env())
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertFalse(json.loads(status.stdout)['live'])


if __name__ == '__main__':
    unittest.main()
