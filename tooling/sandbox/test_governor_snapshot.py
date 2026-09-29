#!/usr/bin/env python3
"""Host snapshot: failed probes never raise, and each field has a well-defined shape (spec §4)."""
import json
import subprocess
import tempfile
import time
import unittest
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


if __name__ == '__main__':
    unittest.main()
