#!/usr/bin/env python3
"""`heavy_runner.announce_governor_context`: the deferral-path CONTEXT wiring (founder rescope).

Uses `KEEL_GOVERNOR_STATE_DIR` so this never touches the real `~/.keel/governor`.
"""
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from heavy_resources import Policy
import heavy_runner


class AnnounceGovernorContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.governor_dir = Path(self.tmp.name) / 'governor'
        self.heavy_dir = Path(self.tmp.name) / 'heavy.slots'
        self.heavy_dir.mkdir()
        self.env_patch = mock.patch.dict(os.environ, {'KEEL_GOVERNOR_STATE_DIR': str(self.governor_dir)})
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def test_never_raises_and_writes_last_context(self):
        buffer = io.StringIO()
        with redirect_stderr(buffer):
            heavy_runner.announce_governor_context(self.heavy_dir, 'resource_busy',
                                                     ['bash', 'x.sh'], Policy())
        self.assertIn('machine-steward', buffer.getvalue())
        last_context = json.loads((self.governor_dir / 'last-context.json').read_text())
        self.assertEqual(last_context['reason'], 'resource_busy')

    def test_a_governor_failure_never_crashes_the_deferral(self):
        buffer = io.StringIO()
        with mock.patch('governor.snapshot.take', side_effect=RuntimeError('boom')), \
                redirect_stderr(buffer):
            heavy_runner.announce_governor_context(self.heavy_dir, 'memory_pressure', ['x'], Policy())
        self.assertIn('governor context unavailable', buffer.getvalue())

    def test_emits_a_governor_decision_event(self):
        with redirect_stderr(io.StringIO()):
            heavy_runner.announce_governor_context(self.heavy_dir, 'resource_busy', ['x'], Policy())
        events = (self.heavy_dir / 'events.jsonl').read_text().splitlines()
        self.assertTrue(any(json.loads(line)['event'] == 'governor_decision' for line in events))


class DiskReclaimInboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.governor_dir = Path(self.tmp.name) / 'governor'
        self.heavy_dir = Path(self.tmp.name) / 'heavy.slots'
        self.heavy_dir.mkdir()
        env = mock.patch.dict(os.environ, {'KEEL_GOVERNOR_STATE_DIR': str(self.governor_dir)})
        env.start()
        self.addCleanup(env.stop)

    def inbox(self):
        path = self.governor_dir / 'steward-inbox.jsonl'
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []

    def test_low_disk_appends_one_disk_reclaim_per_window(self):
        snap = {'disk_free_gib': 5, 'leases': []}
        with mock.patch('governor.snapshot.take', return_value=snap):
            heavy_runner.announce_disk_reclaim(self.heavy_dir, ['x'], Policy())
            heavy_runner.announce_disk_reclaim(self.heavy_dir, ['x'], Policy())
        self.assertEqual([r['reason'] for r in self.inbox()], ['disk_reclaim'])

    def test_stale_entry_does_not_dedupe(self):
        self.governor_dir.mkdir()
        old = {'ts': '2020-01-01T00:00:00+00:00', 'reason': 'disk_reclaim'}
        (self.governor_dir / 'steward-inbox.jsonl').write_text(json.dumps(old) + '\n')
        with mock.patch('governor.snapshot.take', return_value={'disk_free_gib': 5, 'leases': []}):
            heavy_runner.announce_disk_reclaim(self.heavy_dir, ['x'], Policy())
        self.assertEqual(len(self.inbox()), 2)

    def test_ample_disk_writes_nothing(self):
        with mock.patch('governor.snapshot.take', return_value={'disk_free_gib': 500, 'leases': []}):
            heavy_runner.announce_disk_reclaim(self.heavy_dir, ['x'], Policy())
        self.assertEqual(self.inbox(), [])

    def test_interrupted_is_appended(self):
        heavy_runner.append_interrupted_inbox(15)
        self.assertEqual([(r['reason'], r['signal']) for r in self.inbox()], [('interrupted', 15)])


class ConsultJevTests(unittest.TestCase):
    """2026-09-30: `jev_client.decide()` had no caller, so JEV was never asked (0/7 decisions)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.governor_dir = Path(self.tmp.name) / 'governor'
        self.heavy_dir = Path(self.tmp.name) / 'heavy.slots'
        self.heavy_dir.mkdir()
        self.env_patch = mock.patch.dict(os.environ, {'KEEL_GOVERNOR_STATE_DIR': str(self.governor_dir)})
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def _events(self):
        path = self.heavy_dir / 'events.jsonl'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_asks_jev_and_records_both_verdicts_for_shadow_grading(self):
        verdict = {'admit': True, 'slots_now': 3, 'source': 'jev', 'latency_ms': 400}
        with mock.patch('governor.jev_client.decide', return_value=verdict) as decide:
            heavy_runner.consult_jev(self.heavy_dir, 'job1', ['/x/wt-verify.sh', 'backend'], Policy())
        decide.assert_called_once()
        self.assertEqual(decide.call_args.args[0], 'wt-verify.sh')
        [decision] = [e for e in self._events() if e['event'] == 'governor_decision']
        self.assertEqual(decision['stage'], 'queued')
        self.assertEqual(decision['job_id'], 'job1')
        self.assertEqual(decision['jev'], verdict)
        self.assertIn('slots_now', decision['d_rule'])
        self.assertFalse(decision['enforced'])

    def test_a_fired_floor_skips_the_jev_call(self):
        with mock.patch('governor.jev_client.decide') as decide:
            heavy_runner.consult_jev(self.heavy_dir, 'job1', ['x'], Policy(disk_floor_gib=999999))
        decide.assert_not_called()
        [decision] = [e for e in self._events() if e['event'] == 'governor_decision']
        self.assertIsNone(decision['jev'])

    def test_a_jev_failure_never_raises(self):
        buffer = io.StringIO()
        with mock.patch('governor.jev_client.decide', side_effect=RuntimeError('boom')), redirect_stderr(buffer):
            heavy_runner.consult_jev(self.heavy_dir, 'job1', ['x'], Policy())
        self.assertIn('JEV consult unavailable', buffer.getvalue())

    def test_start_jev_consult_runs_off_the_heartbeat_thread(self):
        with mock.patch.object(heavy_runner, 'consult_jev') as consult:
            thread = heavy_runner.start_jev_consult(self.heavy_dir, 'job1', ['x'], Policy())
            thread.join(5)
        self.assertTrue(thread.daemon)
        consult.assert_called_once()

    def test_the_deferral_context_carries_the_cached_jev_verdict(self):
        import time
        self.governor_dir.mkdir(parents=True, exist_ok=True)
        (self.governor_dir / 'decision.x.json').write_text(json.dumps(
            {'cached_at': time.time(), 'decision': {'admit': False, 'slots_now': 1, 'source': 'jev'}}))
        with redirect_stderr(io.StringIO()):
            heavy_runner.announce_governor_context(self.heavy_dir, 'resource_busy', ['x'], Policy())
        last_context = json.loads((self.governor_dir / 'last-context.json').read_text())
        self.assertEqual(last_context['jev']['source'], 'jev')
        [decision] = [e for e in self._events() if e['event'] == 'governor_decision']
        self.assertEqual(decision['jev']['admit'], False)


if __name__ == '__main__':
    unittest.main()
