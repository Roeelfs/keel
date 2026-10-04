import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from governor import snapshot  # noqa: E402
from heavy_resources import Process  # noqa: E402


class DesktopAppsTests(unittest.TestCase):
    def test_own_footprint_is_read_and_nonzero(self):
        self.assertGreater(snapshot._footprint_mb(os.getpid()), 1.0)

    def test_unknown_pid_has_no_footprint(self):
        self.assertIsNone(snapshot._footprint_mb(2 ** 22 + 7))

    def test_app_path_pattern_matches_only_the_main_binary(self):
        self.assertTrue(snapshot.DESKTOP_APP_RE.match('/Applications/ChatGPT.app/Contents/MacOS/ChatGPT'))
        self.assertIsNone(snapshot.DESKTOP_APP_RE.match(
            '/Applications/ChatGPT.app/Contents/Frameworks/Codex Helper.app/Contents/MacOS/Codex Helper'))

    def test_live_snapshot_is_a_dict_or_none(self):
        result = snapshot.desktop_apps()
        self.assertTrue(result is None or isinstance(result, dict))


if __name__ == '__main__':
    unittest.main()
