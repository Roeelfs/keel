#!/usr/bin/env python3
"""Session-registry join for the CONTEXT block (spec §4). Fixture-only; never touches the real
~/.claude/sessions or ~/.claude/projects.
"""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from heavy_resources import Process
from governor import registry


def fixture_table():
    return {
        100: Process(pid=100, ppid=1, pgid=100, rss_mb=50, identity='Mon Jan  1 00:00:00 2026', state='S'),
        101: Process(pid=101, ppid=100, pgid=100, rss_mb=20, identity='ident-101', state='S'),
        200: Process(pid=200, ppid=1, pgid=200, rss_mb=10, identity='ident-200', state='S'),
    }


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sessions_dir = Path(self.tmp.name) / 'sessions'
        self.projects_dir = Path(self.tmp.name) / 'projects'
        self.sessions_dir.mkdir()
        self.projects_dir.mkdir()

    def write_session(self, filename, **fields):
        (self.sessions_dir / filename).write_text(json.dumps(fields))

    def test_a_live_entry_reports_identity_and_liveness(self):
        self.write_session('100.json', pid=100, sessionId='sid-1', cwd='/repo/a',
                            procStart='Mon Jan  1 00:00:00 2026', name='my session', status='idle')
        result = registry.build(self.sessions_dir, self.projects_dir, table=fixture_table())
        self.assertTrue(result[100]['live'])
        self.assertEqual(result[100]['identity'], 'Mon Jan  1 00:00:00 2026')
        self.assertEqual(result[100]['name'], 'my session')

    def test_a_stale_procstart_is_not_live_but_still_recorded(self):
        self.write_session('100.json', pid=100, sessionId='sid-1', cwd='/repo/a',
                            procStart='Tue Jan  1 00:00:00 2030', name='stale')
        result = registry.build(self.sessions_dir, self.projects_dir, table=fixture_table())
        self.assertFalse(result[100]['live'])

    def test_a_malformed_session_file_is_skipped_not_fatal(self):
        (self.sessions_dir / 'bad.json').write_text('{not json')
        self.write_session('100.json', pid=100, sessionId='sid-1', cwd='/repo/a',
                            procStart='Mon Jan  1 00:00:00 2026')
        result = registry.build(self.sessions_dir, self.projects_dir, table=fixture_table())
        self.assertIn(100, result)

    def test_a_missing_pid_field_is_skipped(self):
        self.write_session('bad2.json', sessionId='sid-1')
        result = registry.build(self.sessions_dir, self.projects_dir, table=fixture_table())
        self.assertEqual(result, {})

    def test_idle_minutes_comes_from_transcript_mtime(self):
        project = self.projects_dir / '-repo-a'
        project.mkdir()
        transcript = project / 'sid-1.jsonl'
        transcript.write_text('{}')
        old = time.time() - 600
        os.utime(transcript, (old, old))
        self.write_session('100.json', pid=100, sessionId='sid-1', cwd='/repo/a',
                            procStart='Mon Jan  1 00:00:00 2026')
        result = registry.build(self.sessions_dir, self.projects_dir, table=fixture_table())
        self.assertAlmostEqual(result[100]['idle_minutes'], 10.0, delta=0.5)

    def test_missing_transcript_is_none_not_fatal(self):
        self.write_session('100.json', pid=100, sessionId='sid-missing', cwd='/repo/a',
                            procStart='Mon Jan  1 00:00:00 2026')
        result = registry.build(self.sessions_dir, self.projects_dir, table=fixture_table())
        self.assertIsNone(result[100]['idle_minutes'])

    def test_missing_sessions_dir_returns_empty_never_raises(self):
        result = registry.build(self.sessions_dir / 'does-not-exist', self.projects_dir,
                                 table=fixture_table())
        self.assertEqual(result, {})

    def test_time_budget_is_honoured(self):
        for i in range(20):
            self.write_session(f'{i}.json', pid=i, sessionId=f'sid-{i}', cwd='/repo/a',
                                procStart='x')
        started = time.monotonic()
        registry.build(self.sessions_dir, self.projects_dir, table=fixture_table(), budget_s=0.0)
        self.assertLess(time.monotonic() - started, 0.5)


class OwnerOfTests(unittest.TestCase):
    def test_ancestry_walk_finds_a_registered_grandparent(self):
        table = fixture_table()
        reg = {100: {'sessionId': 'sid-1', 'cwd': '/repo/a'}}
        owner = registry.owner_of(101, None, table, reg)
        self.assertEqual(owner['sessionId'], 'sid-1')

    def test_no_ancestor_falls_back_to_cwd_match(self):
        table = fixture_table()
        reg = {200: {'sessionId': 'sid-2', 'cwd': '/repo/worktree-x'}}
        owner = registry.owner_of(999, '/repo/worktree-x/apps/backend', table, reg)
        self.assertEqual(owner['sessionId'], 'sid-2')

    def test_no_match_returns_none_not_raise(self):
        table = fixture_table()
        self.assertIsNone(registry.owner_of(999, None, table, {}))
        self.assertIsNone(registry.owner_of(None, None, table, {100: {}}))

    def test_empty_registry_returns_none(self):
        self.assertIsNone(registry.owner_of(100, '/x', fixture_table(), None))


if __name__ == '__main__':
    unittest.main()
