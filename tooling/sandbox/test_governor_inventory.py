#!/usr/bin/env python3
"""The shared read-only inventory: acquisition, the preview and the snapshot count alike.

A zero-member lease in an unlocked slot and a dead queue ticket never count; the preview never
touches an admission file (slot, lease or ticket); only acquisition prunes a dead ticket.
"""
import fcntl
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from heavy_resources import Policy, processes, write_record
import heavy_runner
from governor import inventory, snapshot

QUIET_CPU = {'reason': None, 'load1': 1.0, 'ncpu': 8, 'capacity': 8.0, 'reserve_cores': 0.0, 'running_jobs': 0}


class FrozenFixtureTests(unittest.TestCase):
    """Slot 1 held by a supervisor's flock; slot 2 a finished job's lease; one live, one dead ticket."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.heavy_dir = Path(self.tmp.name) / 'heavy.slots'
        queue = self.heavy_dir / 'queue'
        queue.mkdir(parents=True)
        stream = inventory.slot_path(self.heavy_dir, 1).open('a')
        self.addCleanup(stream.close)
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        write_record(inventory.lease_path(self.heavy_dir, 1),
                     {'job_id': 'running', 'executable': 'vitest', 'pgid': 999999991, 'started_ns': time.time_ns()})
        write_record(inventory.lease_path(self.heavy_dir, 2),
                     {'job_id': 'finished', 'executable': 'tsc', 'pgid': 999999992, 'started_ns': time.time_ns()})
        me = processes()[os.getpid()]
        self.live = queue / '00000000000000000001-live.json'
        self.dead = queue / '00000000000000000002-dead.json'
        write_record(self.live, {'pid': me.pid, 'identity': me.identity, 'class': 'vitest'})
        write_record(self.dead, {'pid': 999999993, 'identity': 'gone', 'class': 'vitest'})
        env = mock.patch.dict(os.environ, {'KEEL_GOVERNOR_STATE_DIR': str(Path(self.tmp.name) / 'gov')})
        env.start()
        self.addCleanup(env.stop)

    def admission_files(self):
        """Name, bytes and mtime of every slot, lease and ticket file."""
        return {str(path.relative_to(self.heavy_dir)): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in sorted(self.heavy_dir.rglob('*')) if path.is_file() and path.name != 'events.jsonl'}

    def test_only_the_held_slot_and_the_live_ticket_count(self):
        self.assertEqual(inventory.held_slots(self.heavy_dir), [1])
        self.assertEqual(inventory.running_job_count(self.heavy_dir), 1)
        self.assertEqual(inventory.live_tickets(self.heavy_dir / 'queue'), [self.live])

    def test_preview_snapshot_and_acquisition_agree(self):
        with mock.patch.object(heavy_runner, 'cpu_state', return_value=QUIET_CPU):
            preview = heavy_runner.admit_preview(self.heavy_dir, Policy(slots=2), 'vitest')
        snap = snapshot.take(Path(self.tmp.name) / 'gov', self.heavy_dir, persist=False)
        self.assertEqual(preview['running'], 1)
        self.assertEqual([lease['slot'] for lease in snap['leases']], [1])
        self.assertEqual(preview['queued'], 1)
        self.assertEqual(snap['queued'], 1)
        self.assertIs(heavy_runner.running_job_count, inventory.running_job_count)
        self.assertEqual(heavy_runner.prune_tickets(self.heavy_dir / 'queue'), [self.live])  # acquisition's view

    def test_the_preview_leaves_admission_files_untouched(self):
        before = self.admission_files()
        with mock.patch.object(heavy_runner, 'cpu_state', return_value=QUIET_CPU):
            heavy_runner.admit_preview(self.heavy_dir, Policy(slots=2), 'vitest')
        snapshot.take(Path(self.tmp.name) / 'gov', self.heavy_dir, persist=False)
        self.assertEqual(self.admission_files(), before)
        self.assertTrue(self.dead.exists())
        self.assertFalse(inventory.slot_path(self.heavy_dir, 3).exists())  # the lock probe creates nothing

    def test_only_acquisition_prunes_a_dead_ticket(self):
        self.assertEqual(heavy_runner.prune_tickets(self.heavy_dir / 'queue'), [self.live])
        self.assertFalse(self.dead.exists())
        self.assertTrue(self.live.exists())


class ContendingTests(unittest.TestCase):
    def test_stalled_and_yielding_tickets_do_not_contend(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = Path(tmp)
            fresh, stalled, yielding = (queue / f'{n}.json' for n in ('1', '2', '3'))
            for path, record in ((fresh, {}), (stalled, {}), (yielding, {'yield': True})):
                path.write_text(json.dumps(record))
            os.utime(stalled, (time.time() - 60, time.time() - 60))
            cutoff = inventory.fresh_after(Policy())
            self.assertEqual(inventory.contending([fresh, stalled, yielding], cutoff), [fresh])


if __name__ == '__main__':
    unittest.main()
