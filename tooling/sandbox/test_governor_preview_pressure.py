#!/usr/bin/env python3
"""`preview_pressure()`: machine pressure as a routing signal in `--admit-preview` only.

Pins: the states and reasons, app_hang reported in `shadow` and never acted on, an unknown probe
never fast-path admits, and `evaluate_load()` / `claim_slot()` stay byte-identical to the versions
the lock shipped with (the preview floors never reach the lock: machine-governor spec §5.3, §7).
"""
import ast
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from heavy_resources import Policy
import heavy_runner

QUIET_CPU = {'reason': None, 'load1': 1.0, 'ncpu': 8, 'capacity': 8.0, 'reserve_cores': 0.0, 'running_jobs': 0}


def snapshot(**fields):
    return {'unknown': [], 'leases': [], 'class_stats': {}, **fields}


class PreviewPressureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.policy = Policy(disk_floor_gib=10)
        for name, value in (('cpu_state', QUIET_CPU), ('pressure_reason', None)):
            patch = mock.patch.object(heavy_runner, name, return_value=value)
            patch.start()
            self.addCleanup(patch.stop)

    def pressure(self, snap, running=0):
        return heavy_runner.preview_pressure(self.directory, self.policy, snap, running, 'cynap-verify-quick')[0]

    def test_clear(self):
        self.assertEqual(self.pressure(snapshot(disk_free_gib=500)),
                         {'state': 'clear', 'reasons': [], 'shadow': []})

    def test_cpu_and_interactive_reasons_come_from_evaluate_load(self):
        for reason in ('cpu_pressure', 'interactive_foreground'):
            with self.subTest(reason=reason), \
                    mock.patch.object(heavy_runner, 'cpu_state', return_value={**QUIET_CPU, 'reason': reason}):
                self.assertEqual(self.pressure(snapshot()), {'state': 'pressure', 'reasons': [reason], 'shadow': []})

    def test_memory_pressure_is_a_reason(self):
        with mock.patch.object(heavy_runner, 'pressure_reason', return_value='memory_pressure'):
            self.assertEqual(self.pressure(snapshot())['reasons'], ['memory_pressure'])

    def test_preview_floors_are_reasons(self):
        result = self.pressure(snapshot(disk_free_gib=1, swap_growth_mb_per_min=10_000, mem_pressure_level=4))
        self.assertEqual(result, {'state': 'pressure', 'reasons': ['disk', 'swap_growth', 'mem_critical'],
                                  'shadow': []})

    def test_app_hang_is_shadow_only(self):
        self.assertEqual(self.pressure(snapshot(hang_reports_recent=3)),
                         {'state': 'clear', 'reasons': [], 'shadow': ['app_hang']})

    def test_an_unknown_needed_probe_is_unknown(self):
        self.assertEqual(self.pressure(snapshot(unknown=['swap']))['state'], 'unknown')
        with mock.patch.object(heavy_runner, 'cpu_state', return_value={'reason': None, 'error': 'OSError'}):
            self.assertEqual(self.pressure(snapshot())['state'], 'unknown')

    def test_an_unknown_hang_probe_does_not_gate(self):
        self.assertEqual(self.pressure(snapshot(unknown=['hang_reports']))['state'], 'clear')

    def test_unknown_memory_skips_the_memory_test(self):
        with mock.patch.object(heavy_runner, 'pressure_reason', side_effect=AssertionError('memory is unknown')):
            self.assertEqual(self.pressure(snapshot(unknown=['memory']))['state'], 'unknown')

    def test_a_fired_reason_wins_over_an_unknown_probe(self):
        with mock.patch.object(heavy_runner, 'cpu_state', return_value={**QUIET_CPU, 'reason': 'cpu_pressure'}):
            self.assertEqual(self.pressure(snapshot(unknown=['swap']))['state'], 'pressure')


class AdmitPreviewPressureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.heavy_dir = Path(self.tmp.name) / 'heavy.slots'
        (self.heavy_dir / 'queue').mkdir(parents=True)
        for patch in (mock.patch.dict(os.environ, {'KEEL_GOVERNOR_STATE_DIR': str(Path(self.tmp.name) / 'gov')}),
                      mock.patch.object(heavy_runner, 'cpu_state', return_value=QUIET_CPU),
                      mock.patch.object(heavy_runner, 'pressure_reason', return_value=None)):
            patch.start()
            self.addCleanup(patch.stop)

    def preview(self, snap, policy=None):
        with mock.patch('governor.snapshot.take', return_value=snap):
            return heavy_runner.admit_preview(self.heavy_dir, policy or Policy(slots=2), 'cynap-verify-quick')

    def test_a_clear_machine_fast_admits_and_reports_pressure(self):
        result = self.preview(snapshot(disk_free_gib=500))
        self.assertEqual((result['decision'], result['source']), ('admit', 'fast_path'))
        self.assertEqual(result['pressure'], {'state': 'clear', 'reasons': [], 'shadow': []})

    def test_an_unknown_probe_never_fast_admits(self):
        result = self.preview(snapshot(unknown=['memory']))
        self.assertNotEqual(result['source'], 'fast_path')
        self.assertEqual(result['decision'], 'deny')
        self.assertEqual(result['pressure']['state'], 'unknown')

    def test_app_hang_never_denies(self):
        result = self.preview(snapshot(hang_reports_recent=2))
        self.assertEqual((result['decision'], result['source']), ('admit', 'fast_path'))
        self.assertEqual(result['pressure']['shadow'], ['app_hang'])

    def test_cpu_pressure_denies_with_its_reason_and_an_empty_queue(self):
        with mock.patch.object(heavy_runner, 'cpu_state', return_value={**QUIET_CPU, 'reason': 'cpu_pressure'}):
            result = self.preview(snapshot())
        self.assertEqual(result['decision'], 'deny')
        self.assertEqual(result['queued'], 0)
        self.assertEqual(result['deny_reason'], 'cpu_pressure')
        self.assertEqual(result['pressure'], {'state': 'pressure', 'reasons': ['cpu_pressure'], 'shadow': []})


# sha256 of each function's source as shipped before the preview gained pressure routing. The
# preview floors and unknown-gating must never reach the lock (non-goal: changing claim_slot moves
# admission for every repo on the machine), so these two functions stay byte-identical.
PINNED = {
    'evaluate_load': '96c694ec5365d4c784adf64645e55a460a58ca88274f1604108ab7dc72a0bcf7',
    'claim_slot': '50bded2fffa784823f16f738adf7f1e92732a4727717d0b14e2cbe090e44dff6',
}


class LockUnchangedTests(unittest.TestCase):
    def test_evaluate_load_and_claim_slot_are_byte_identical(self):
        source = Path(heavy_runner.__file__).read_text()
        functions = {node.name: ast.get_source_segment(source, node)
                     for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)}
        for name, digest in PINNED.items():
            with self.subTest(function=name):
                self.assertEqual(hashlib.sha256(functions[name].encode()).hexdigest(), digest)


if __name__ == '__main__':
    unittest.main()
