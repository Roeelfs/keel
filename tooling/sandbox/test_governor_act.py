#!/usr/bin/env python3
"""governor_kill: the one tiny always-safe kill helper (spec §9.3 B1, founder rescope 2026-09-29)."""
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from heavy_resources import Process
from governor import act


def fixture_table(**overrides):
    table = {
        100: Process(pid=100, ppid=1, pgid=100, rss_mb=50, identity='ident-100', state='S'),
        101: Process(pid=101, ppid=100, pgid=100, rss_mb=20, identity='ident-101', state='S'),
        200: Process(pid=200, ppid=1, pgid=200, rss_mb=10, identity='ident-200', state='S'),
    }
    table.update(overrides)
    return table


class GovernorKillTests(unittest.TestCase):
    def test_identity_mismatch_is_refused(self):
        table = fixture_table()
        result = act.governor_kill(100, 'wrong-identity', 'test', table=table, live_pgids=set())
        self.assertEqual(result['result'], 'refused:identity_mismatch')

    def test_missing_pid_is_refused(self):
        table = fixture_table()
        result = act.governor_kill(999, 'ident-999', 'test', table=table, live_pgids=set())
        self.assertEqual(result['result'], 'refused:identity_mismatch')

    def test_shared_pgid_with_a_live_session_is_refused(self):
        table = fixture_table()
        result = act.governor_kill(100, 'ident-100', 'test', table=table, live_pgids={100})
        self.assertEqual(result['result'], 'refused:shared_session_pgid')

    def test_dry_run_reports_the_victim_set_without_signalling(self):
        table = fixture_table()
        result = act.governor_kill(100, 'ident-100', 'test', table=table, live_pgids=set(), dry_run=True)
        self.assertEqual(result['result'], 'would_kill')
        self.assertIn(100, result['members'])

    def test_a_real_kill_signals_the_victim_and_not_its_neighbour(self):
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                                 start_new_session=True)
        try:
            neighbour = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                                         start_new_session=True)
            try:
                time.sleep(0.2)
                from heavy_resources import processes
                table = processes()
                identity = table[child.pid].identity
                result = act.governor_kill(child.pid, identity, 'test', table=table, live_pgids=set(),
                                            dry_run=False)
                self.assertEqual(result['result'], 'killed')
                child.wait(timeout=5)
                self.assertIsNotNone(child.poll())
                self.assertIsNone(neighbour.poll())
            finally:
                neighbour.terminate()
                neighbour.wait(timeout=5)
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=5)

    def test_live_registry_pgids_reads_the_session_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path(tmp)
            import json
            (sessions_dir / '1.json').write_text(json.dumps({'pid': os.getpid()}))
            from heavy_resources import processes
            table = processes()
            pgids = act.live_registry_pgids(sessions_dir=sessions_dir, table=table)
            self.assertIn(table[os.getpid()].pgid, pgids)

    def test_cli_defaults_to_dry_run_and_exits_nonzero_on_refusal(self):
        import json
        code = act.main(['0', 'not-a-real-identity'])
        self.assertEqual(code, 1)


if __name__ == '__main__':
    unittest.main()
