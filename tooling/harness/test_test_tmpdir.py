"""Test-command environment selection and disposable latency probe behavior."""
import os
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

import test_tmpdir
import tmpdir_latency


class ResolverTests(unittest.TestCase):
    def test_external_tmpdir_is_not_preserved_after_unplug(self):
        env = {"TMPDIR": "/Volumes/T9/stale", "KEEL_TEST_TMPDIR_ENABLED": "1"}
        with patch.object(os.path, "ismount", return_value=False), patch.object(
                subprocess, "check_output", return_value="/internal\n"):
            self.assertEqual(test_tmpdir.command_env(env)["TMPDIR"], "/internal")

    def test_mount_probe_permission_error_preserves_internal(self):
        env = {"TMPDIR": "/internal", "KEEL_TEST_TMPDIR_ENABLED": "1"}
        with patch.object(os.path, "ismount", side_effect=PermissionError("denied")):
            self.assertEqual(test_tmpdir.command_env(env), env)

    def test_keeper_reaps_only_aged_fixtures(self):
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent)
            stale = tuple(root / name for name in (
                "cdk-real-app-old", "synth-det-old", "lambda-asset-size-old"))
            kept = tuple(root / name for name in ("cdk-real-app-fresh", "unrelated-old"))
            for path in (*stale, *kept):
                path.mkdir()
                (path / "payload").write_text("fixture")
            old = time.time() - 3 * 3600
            for path in (*stale, kept[1]):
                os.utime(path, (old, old))
            config = Path(test_tmpdir.__file__).with_name("disk-keeper-tmpdir.env.sh")
            subprocess.run(["/bin/bash", "-c", '. "$1"; disk_keeper_external_fixtures',
                            "keeper", str(config)], check=True,
                           env={**os.environ, "DK_LEAK_ROOT": str(root)})
            self.assertTrue(all(not path.exists() for path in stale))
            self.assertTrue(all(path.exists() for path in kept))

    def test_default_off_preserves_internal_environment(self):
        env = {"TMPDIR": "/internal", "OTHER": "kept"}
        self.assertEqual(test_tmpdir.command_env(env), env)

    def test_unmounted_volume_never_creates_a_stub(self):
        env = {"TMPDIR": "/internal", "KEEL_TEST_TMPDIR_ENABLED": "1"}
        with tempfile.TemporaryDirectory() as parent:
            volume = Path(parent) / "absent"
            self.assertEqual(test_tmpdir.command_env(env, volume), env)
            self.assertFalse(volume.exists())

    def test_mounted_writable_volume_uses_owned_private_directory(self):
        with tempfile.TemporaryDirectory() as parent:
            with patch.object(os.path, "ismount", return_value=True):
                env = test_tmpdir.command_env({"KEEL_TEST_TMPDIR_ENABLED": "1"}, Path(parent))
            root = Path(env["TMPDIR"])
            self.assertEqual(root.parent, Path(parent))
            self.assertEqual(list(root.iterdir()), [])
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)

    def test_write_failure_falls_back_without_changing_internal_tmpdir(self):
        env = {"TMPDIR": "/internal", "KEEL_TEST_TMPDIR_ENABLED": "1"}
        with patch.object(os.path, "ismount", return_value=True), \
                patch.object(Path, "mkdir", side_effect=PermissionError("read only")):
            self.assertEqual(test_tmpdir.command_env(env), env)

    def test_real_file_probe_failure_falls_back(self):
        for operation in ("write_bytes", "unlink"):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as parent:
                env = {"TMPDIR": "/internal", "KEEL_TEST_TMPDIR_ENABLED": "1"}
                with patch.object(os.path, "ismount", return_value=True), patch.object(
                        Path, operation, side_effect=PermissionError("denied")):
                    self.assertEqual(test_tmpdir.command_env(env, Path(parent)), env)

    def test_disabled_switch_discards_inherited_external_path(self):
        env = {"TMPDIR": "/Volumes/T9/stale"}
        with patch.object(subprocess, "check_output", side_effect=OSError("unavailable")):
            self.assertEqual(test_tmpdir.command_env(env)["TMPDIR"], "/tmp")

    def test_symlink_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as parent:
            volume = Path(parent)
            (volume / f"keel-test-tmp-{os.getuid()}").symlink_to(volume, target_is_directory=True)
            with patch.object(os.path, "ismount", return_value=True):
                env = {"KEEL_TEST_TMPDIR_ENABLED": "1"}
                self.assertEqual(test_tmpdir.command_env(env, volume), env)

    def test_shared_root_is_not_adopted_or_chmodded(self):
        with tempfile.TemporaryDirectory() as parent:
            root = test_tmpdir.private_root(Path(parent))
            root.mkdir(mode=0o755)
            with patch.object(os.path, "ismount", return_value=True):
                env = {"KEEL_TEST_TMPDIR_ENABLED": "1"}
                self.assertEqual(test_tmpdir.command_env(env, Path(parent)), env)
            self.assertEqual(root.stat().st_mode & 0o777, 0o755)

    def test_foreign_owned_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as parent:
            with patch.object(os.path, "ismount", return_value=True), \
                    patch.object(os, "getuid", return_value=os.getuid() + 1):
                env = {"KEEL_TEST_TMPDIR_ENABLED": "1"}
                self.assertEqual(test_tmpdir.command_env(env, Path(parent)), env)

    def test_detach_during_probe_preserves_internal_tmpdir(self):
        with tempfile.TemporaryDirectory() as parent:
            with patch.object(os.path, "ismount", side_effect=[True, False]):
                env = {"TMPDIR": "/internal", "KEEL_TEST_TMPDIR_ENABLED": "1"}
                self.assertEqual(test_tmpdir.command_env(env, Path(parent)), env)

    def test_command_gets_original_tmpdir_and_arguments(self):
        env = {**os.environ, "TMPDIR": "/internal", "KEEL_TEST_TMPDIR_ENABLED": "0"}
        script = Path(test_tmpdir.__file__)
        result = subprocess.run(
            [sys.executable, str(script), "--", sys.executable, "-c",
             "import os,sys; print(os.environ['TMPDIR']); print(sys.argv[1])", "two words"],
            env=env, text=True, capture_output=True, check=True)
        self.assertEqual(result.stdout, "/internal\ntwo words\n")

    def test_node_tmpdir_and_child_exit_code(self):
        with tempfile.TemporaryDirectory() as internal:
            env = {**os.environ, "TMPDIR": internal, "KEEL_TEST_TMPDIR_ENABLED": "0"}
            result = subprocess.run(
                [sys.executable, test_tmpdir.__file__, "--", "node", "-e",
                 'console.log(require("os").tmpdir()); process.exit(7)'],
                env=env, text=True, capture_output=True)
            self.assertEqual(result.stdout.strip(), internal)
            self.assertEqual(result.returncode, 7)

    def test_disk_keeper_config_targets_same_root(self):
        config = Path(test_tmpdir.__file__).with_name("disk-keeper-tmpdir.env.sh")
        result = subprocess.run(
            ["/bin/sh", "-c", '. "$1"; printf "%s" "$DK_LEAK_ROOT"', "sh", str(config)],
            text=True, capture_output=True, check=True)
        self.assertEqual(result.stdout, str(test_tmpdir.private_root(test_tmpdir.VOLUME)))


class LatencyTests(unittest.TestCase):
    def test_default_probe_only_measures_internal_disk(self):
        with patch.object(sys, "argv", ["tmpdir_latency.py"]), patch.object(
                subprocess, "check_output", return_value="/internal\n"), patch.object(
                tmpdir_latency, "measure", return_value={"status": "measured"}) as measure, \
                patch.object(os.path, "ismount", side_effect=AssertionError("external probe")), \
                redirect_stdout(io.StringIO()) as output:
            tmpdir_latency.main()
        measure.assert_called_once_with("/internal", 2000)
        result = json.loads(output.getvalue())
        self.assertEqual(result["external"]["status"], "not_run")
        self.assertEqual(result["gate"], "UNVERIFIED")

    def test_probe_removes_files_and_scratch_directory(self):
        with tempfile.TemporaryDirectory() as parent:
            result = tmpdir_latency.measure(parent, 8)
            self.assertEqual(result["status"], "measured")
            self.assertEqual(result["files"], 8)
            self.assertEqual(list(Path(parent).iterdir()), [])

    def test_write_failure_cleans_up_and_records_failure(self):
        with tempfile.TemporaryDirectory() as parent:
            with patch.object(Path, "write_bytes", side_effect=PermissionError("denied")):
                result = tmpdir_latency.measure(parent, 8)
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(list(Path(parent).iterdir()), [])

    def test_failed_probe_never_passes_gate(self):
        result = tmpdir_latency.compare({"status": "blocked"}, {"status": "measured"})
        self.assertEqual(result["gate"], "UNVERIFIED")

    def test_both_p99_operations_must_meet_two_times_gate(self):
        internal = {"status": "measured", "create": {"p99_us": 10}, "delete": {"p99_us": 20}}
        external = {"status": "measured", "create": {"p99_us": 20}, "delete": {"p99_us": 40}}
        self.assertEqual(tmpdir_latency.compare(internal, external)["gate"], "PASS")
        slower = {**external, "delete": {"p99_us": 41}}
        self.assertEqual(tmpdir_latency.compare(internal, slower)["gate"], "FAIL")


if __name__ == "__main__":
    unittest.main()
