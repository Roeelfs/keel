#!/usr/bin/env python3
"""The CONTEXT block: deny/defer surfaces state to machine-steward; it never kills or deletes."""
import json
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

    def test_codex_is_told_to_report_it_not_to_sendmessage(self):
        # Codex has no SendMessage to the Claude desktop steward (2026-09-30).
        built = context.build('resource_busy', 'wt-verify', snapshot(), Policy(), runtime='codex')
        self.assertNotIn('SendMessage', built['instruction'])
        self.assertIn('final report', built['instruction'])
        self.assertIn('machine-steward', built['instruction'])
        self.assertIn('do not kill or delete anything yourself', built['instruction'])
        self.assertEqual(built['runtime'], 'codex')

    def test_claude_and_unknown_runtimes_keep_the_sendmessage_line(self):
        for runtime in ('claude', None):
            built = context.build('resource_busy', 'wt-verify', snapshot(), Policy(), runtime=runtime)
            self.assertIn('SendMessage', built['instruction'])

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


if __name__ == '__main__':
    unittest.main()
