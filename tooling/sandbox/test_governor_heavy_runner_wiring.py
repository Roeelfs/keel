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


if __name__ == '__main__':
    unittest.main()
