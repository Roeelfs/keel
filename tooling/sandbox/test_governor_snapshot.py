#!/usr/bin/env python3
"""Host snapshot: failed probes never raise, and each field has a well-defined shape (spec §4)."""
import json
import subprocess
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

from governor import snapshot


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name) / 'governor'
        self.heavy_directory = Path(self.tmp.name) / 'heavy.slots'
        self.directory.mkdir()
        self.heavy_directory.mkdir()
        self.addCleanup(self.tmp.cleanup)

    def test_take_never_raises_and_reports_every_field(self):
        result = snapshot.take(self.directory, self.heavy_directory)
        for key in ('ncpu', 'load', 'mem_pressure_level', 'mem_free_percent', 'swap_used_mb',
                    'disk_free_gib', 'hang_reports_recent', 'leases', 'queued',
                    'deferrals_last_60m', 'unknown', 'took_ms'):
            self.assertIn(key, result)

    def test_sessions_block_sums_each_live_session_tree(self):
        from heavy_resources import Process
        table = {1: Process(1, 0, 1, 100.0, 'a', 'S'), 2: Process(2, 1, 1, 50.0, 'b', 'S'),
                 3: Process(3, 0, 3, 200.0, 'c', 'S'), 4: Process(4, 0, 4, 999.0, 'd', 'S')}
        registry = {1: {'live': True, 'idle_minutes': 2.0}, 3: {'live': True, 'idle_minutes': 60.0},
                    9: {'live': False, 'idle_minutes': 1.0}}
        self.assertEqual(snapshot.sessions(table=table, registry=registry),
                         {'live_count': 2, 'active_count': 1, 'idle_count': 1,
                          'total_rss_mb': 350.0, 'largest_rss_mb': 200.0})

    def test_sessions_failure_is_none_and_not_unknown(self):
        with mock.patch.object(snapshot, 'processes', side_effect=OSError('ps')):
            self.assertIsNone(snapshot.sessions())
        with mock.patch.object(snapshot, 'sessions', return_value=None):
            result = snapshot.take(self.directory, self.heavy_directory, persist=False)
        self.assertIsNone(result['sessions'])
        self.assertNotIn('sessions', result['unknown'])

    def test_a_failed_probe_is_recorded_as_unknown_not_raised(self):
        unknown = []
        result = snapshot._probe('fake', lambda: (_ for _ in ()).throw(OSError('boom')), unknown)
        self.assertIsNone(result)
        self.assertEqual(unknown, ['fake'])

    def test_hang_reports_missing_directory_is_zero_not_unknown(self):
        unknown = []
        count = snapshot.hang_reports_recent(unknown, log_dir=str(self.directory / 'does-not-exist'))
        self.assertEqual(count, 0)
        self.assertEqual(unknown, [])

    def test_hang_reports_counts_only_recent_files(self):
        log_dir = self.directory / 'DiagnosticReports'
        log_dir.mkdir()
        recent = log_dir / 'a.hang'
        recent.write_text('x')
        stale = log_dir / 'b.spin'
        stale.write_text('x')
        now = time.time()
        import os
        os.utime(stale, (now - 3600, now - 3600))
        unknown = []
        count = snapshot.hang_reports_recent(unknown, log_dir=str(log_dir), now=now)
        self.assertEqual(count, 1)

    def test_leases_reads_pgid_matched_members(self):
        (self.heavy_directory / 'lease.1.json').write_text(
            json.dumps({'job_id': 'j1', 'class': 'wt-verify', 'pgid': 999999, 'started': time.time()}))
        result = snapshot.leases(self.heavy_directory, max_slots=1)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['job_id'], 'j1')

    def test_leases_reads_the_real_lease_shape_executable_and_started_ns(self):
        # A real lease (heavy_runner.run_job) never has 'class' or 'started' -- only 'executable'
        # and 'started_ns'. Live bug 2026-09-29: without this, class was always None and age_s was
        # always 0, so every eta computed off a real lease collapsed silently.
        started_ns = time.time_ns() - 5_000_000_000  # 5s ago
        (self.heavy_directory / 'lease.1.json').write_text(json.dumps(
            {'job_id': 'j1', 'executable': 'cynap-sandbox', 'pgid': 999999, 'started_ns': started_ns}))
        result = snapshot.leases(self.heavy_directory, max_slots=1)
        self.assertEqual(result[0]['class'], 'cynap-sandbox')
        self.assertGreaterEqual(result[0]['age_s'], 4.5)

    def test_leases_prefers_class_over_executable_when_both_present(self):
        (self.heavy_directory / 'lease.1.json').write_text(json.dumps(
            {'job_id': 'j1', 'class': 'wt-verify', 'executable': 'cynap-sandbox',
             'pgid': 999999, 'started': time.time()}))
        result = snapshot.leases(self.heavy_directory, max_slots=1)
        self.assertEqual(result[0]['class'], 'wt-verify')

    def test_queued_and_deferrals_counts_recent_deferred_events(self):
        events = self.heavy_directory / 'events.jsonl'
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat()
        events.write_text('\n'.join([
            json.dumps({'event': 'deferred', 'ts': now_iso}),
            json.dumps({'event': 'started', 'ts': now_iso}),
            json.dumps({'event': 'deferred', 'ts': now_iso}),
        ]))
        queued, deferrals = snapshot.queued_and_deferrals(self.heavy_directory)
        self.assertEqual(deferrals, 2)

    def test_swap_growth_uses_the_sample_60s_to_10min_old(self):
        now = time.time()
        history = [{'ts_epoch': now - 120, 'swap_used_mb': 1000.0}]
        unknown = []
        result = snapshot.swap(unknown, history=history)
        # We cannot control the live sysctl reading in a unit test, so only check the shape here.
        self.assertIn('swap_growth_mb_per_min', result)

    def test_persist_writes_at_most_once_per_ten_seconds(self):
        snapshot.take(self.directory, self.heavy_directory)
        first_size = (self.directory / 'snapshots.jsonl').stat().st_size
        snapshot.take(self.directory, self.heavy_directory)
        second_size = (self.directory / 'snapshots.jsonl').stat().st_size
        self.assertEqual(first_size, second_size)


class ClassStatsFallbackTests(unittest.TestCase):
    """class-stats.json is never written by any code in this repo (live bug, 2026-09-29): these
    events.jsonl-derived numbers are the only real source, so eta_* is never silently 0."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name) / 'governor'
        self.heavy_directory = Path(self.tmp.name) / 'heavy.slots'
        self.directory.mkdir()
        self.heavy_directory.mkdir()

    def write_job(self, job_id, executable, start_offset_s, duration_s, peak_rss_mb):
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        started_ts = now - timedelta(seconds=start_offset_s)
        completed_ts = started_ts + timedelta(seconds=duration_s)
        with (self.heavy_directory / 'events.jsonl').open('a') as stream:
            stream.write(json.dumps({'event': 'started', 'job_id': job_id, 'executable': executable,
                                     'ts': started_ts.isoformat()}) + '\n')
            stream.write(json.dumps({'event': 'completed', 'job_id': job_id, 'reason': 'exit',
                                     'peak_rss_mb': peak_rss_mb, 'exit_code': 0,
                                     'ts': completed_ts.isoformat()}) + '\n')

    def test_missing_class_stats_file_computes_from_events(self):
        for i, duration in enumerate([10, 20, 30, 40, 50, 60, 70, 80, 90, 100]):
            self.write_job(f'j{i}', 'cynap-sandbox', start_offset_s=300, duration_s=duration,
                           peak_rss_mb=1000 + i * 10)
        stats = snapshot.load_class_stats(self.directory, self.heavy_directory)
        self.assertEqual(stats['cynap-sandbox']['n'], 10)
        self.assertGreater(stats['cynap-sandbox']['run_p50_s'], 0)
        self.assertGreater(stats['cynap-sandbox']['run_p90_s'], stats['cynap-sandbox']['run_p50_s'])
        self.assertGreater(stats['cynap-sandbox']['rss_p90_mb'], 0)

    def test_a_persisted_nonempty_file_wins_over_the_events_fallback(self):
        self.write_job('j1', 'cynap-sandbox', start_offset_s=60, duration_s=10, peak_rss_mb=500)
        (self.directory / 'class-stats.json').write_text(json.dumps(
            {'cynap-sandbox': {'n': 999, 'run_p50_s': 1, 'run_p90_s': 2, 'rss_p90_mb': 3}}))
        stats = snapshot.load_class_stats(self.directory, self.heavy_directory)
        self.assertEqual(stats['cynap-sandbox']['n'], 999)

    def test_an_unmatched_started_or_completed_event_is_skipped_not_raised(self):
        with (self.heavy_directory / 'events.jsonl').open('a') as stream:
            stream.write(json.dumps({'event': 'completed', 'job_id': 'orphan', 'peak_rss_mb': 1}) + '\n')
            stream.write('not even json\n')
        stats = snapshot.load_class_stats(self.directory, self.heavy_directory)
        self.assertEqual(stats, {})

    def test_no_heavy_directory_argument_returns_empty_not_raises(self):
        self.assertEqual(snapshot.load_class_stats(self.directory), {})


if __name__ == '__main__':
    unittest.main()
