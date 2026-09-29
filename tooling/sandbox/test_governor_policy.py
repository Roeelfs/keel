#!/usr/bin/env python3
"""Governor Policy fields load, validate and stay override-tightening-only (spec §5.5)."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import heavy_resources
from heavy_resources import Policy


class PolicyDefaultsTests(unittest.TestCase):
    def test_defaults_match_the_spec_table(self):
        p = Policy()
        self.assertEqual(p.governor_mode, 'shadow')
        self.assertEqual(p.jev_admission, 'shadow')
        self.assertEqual(p.max_slots, 6)
        self.assertEqual(p.cheap_rss_seconds, 131072)
        self.assertEqual((p.disk_floor_gib, p.disk_reclaim_gib, p.swap_growth_floor_mb_per_min), (10, 25, 256))
        self.assertEqual((p.jev_deadline_ms, p.decision_ttl_s, p.admit_p_hi, p.admit_p_lo, p.saturation_deny),
                         (1500, 20, 0.60, 0.40, 3.5))

    def test_no_off_value_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
                heavy_resources, 'account_home', return_value=Path(tmp)):
            (Path(tmp) / '.keel').mkdir()
            (Path(tmp) / '.keel' / 'resource-policy.json').write_text(json.dumps({'governor_mode': 'off'}))
            with self.assertRaises(ValueError):
                heavy_resources.load_policy()

    def test_env_var_may_only_move_enforce_to_shadow(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
                heavy_resources, 'account_home', return_value=Path(tmp)):
            (Path(tmp) / '.keel').mkdir()
            (Path(tmp) / '.keel' / 'resource-policy.json').write_text(json.dumps({'governor_mode': 'enforce'}))
            with mock.patch.dict(os.environ, {'KEEL_GOVERNOR_MODE': 'shadow'}):
                self.assertEqual(heavy_resources.load_policy().governor_mode, 'shadow')
            self.assertEqual(heavy_resources.load_policy().governor_mode, 'enforce')

    def test_unknown_field_is_still_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
                heavy_resources, 'account_home', return_value=Path(tmp)):
            (Path(tmp) / '.keel').mkdir()
            (Path(tmp) / '.keel' / 'resource-policy.json').write_text(json.dumps({'not_a_real_field': 1}))
            with self.assertRaises(ValueError):
                heavy_resources.load_policy()


if __name__ == '__main__':
    unittest.main()
