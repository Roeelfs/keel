#!/usr/bin/env python3
"""The CONTEXT block: deny/defer surfaces state to machine-steward; it never kills or deletes."""
import json
import types
import tempfile
import unittest
from pathlib import Path

from heavy_resources import Policy
from governor import context


def snapshot():
    return {'mem_free_percent': 15, 'mem_pressure_level': 2, 'swap_used_mb': 4000,
            'swap_growth_mb_per_min': 10, 'disk_free_gib': 30, 'load1_per_core': 2.1,
            'leases': [{'members': [123], 'rss_mb': 900, 'class': 'wt-verify', 'age_s': 12}],
            'class_stats': {}, 'unknown': []}


class ContextTests(unittest.TestCase):
    def test_build_never_recommends_a_kill_or_delete(self):
        built = context.build('resource_busy', 'wt-verify', snapshot(), Policy())
        rendered = json.dumps(built)
        self.assertNotIn('"kill"', rendered.lower())
        self.assertIn('do not kill or delete anything yourself', built['instruction'])

    def test_instruction_names_the_machine_steward_session(self):
        built = context.build('resource_busy', 'wt-verify', snapshot(), Policy())
        self.assertIn('machine-steward', built['instruction'])

    def test_no_runtime_is_asked_to_relay_the_context(self):
        # Sessions correctly refuse instructions that arrive in tool output (2026-09-30), so the
        # runner delivers the context itself and the line only informs.
        for runtime in ('claude', 'codex', None):
            built = context.build('resource_busy', 'wt-verify', snapshot(), Policy(), runtime=runtime)
            self.assertNotIn('SendMessage', built['instruction'])
            self.assertNotIn('codex queue', built['instruction'])
            self.assertIn('Nothing for you to do', built['instruction'])
            self.assertIn('do not kill or delete anything yourself', built['instruction'])

    def test_append_inbox_queues_one_line_per_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for reason in ('resource_busy', 'memory_pressure'):
                context.append_inbox(directory, context.build(reason, 'wt-verify', snapshot(), Policy()))
            lines = (directory / context.INBOX_NAME).read_text().splitlines()
            self.assertEqual([json.loads(line)['reason'] for line in lines], ['resource_busy', 'memory_pressure'])

    def test_stderr_block_includes_floors_and_candidates(self):
        built = context.build('memory_pressure', 'other-heavy', snapshot(), Policy())
        block = context.render_stderr_block(built)
        self.assertIn('floors_fired', block)
        self.assertIn('candidate:', block)

    def test_write_last_context_persists_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            built = context.build('resource_busy', 'wt-verify', snapshot(), Policy())
            path = context.write_last_context(directory, built)
            self.assertEqual(json.loads(path.read_text())['reason'], 'resource_busy')

    def test_top_candidates_are_ordered_by_rss_richest_first(self):
        snap = snapshot()
        snap['leases'] = [
            {'members': [1], 'rss_mb': 100, 'class': 'a', 'age_s': 1},
            {'members': [2], 'rss_mb': 900, 'class': 'b', 'age_s': 1},
        ]
        candidates = context.top_candidates(snap)
        self.assertEqual(candidates[0]['pid'], 2)

    def test_reused_pid_drops_stale_owner_and_uses_live_identity(self):
        snap = snapshot()
        snap['leases'] = [{'members': [7], 'rss_mb': 10, 'class': 'a', 'age_s': 1}]
        table = {7: types.SimpleNamespace(pid=7, ppid=1, identity='Thu Oct  1 10:00:00 2026')}
        registry = {7: {'identity': 'Thu Oct  1 10:00:00 2026', 'sessionId': 'old', 'name': 'dead',
                        'cwd': '/x', 'idle_minutes': 5, 'live': False}}
        candidate = context.top_candidates(snap, registry, table)[0]
        self.assertIsNone(candidate['session'])
        self.assertIsNone(candidate['session_name'])
        self.assertEqual(candidate['identity'], 'Thu Oct  1 10:00:00 2026')


if __name__ == '__main__':
    unittest.main()
