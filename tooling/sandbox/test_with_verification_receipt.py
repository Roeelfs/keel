#!/usr/bin/env python3
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("with-verification-receipt")


class VerificationReceiptTests(unittest.TestCase):
    def run_wrapper(self, root, key, command, *extra):
        env = {
            **os.environ,
            "VERIFICATION_RECEIPT_ROOT": str(root / "receipts"),
        }
        return subprocess.run(
            [str(SCRIPT), "--name", "fixture", "--key", key, *extra, "--", *command],
            cwd=root,
            env=env,
            text=True,
            capture_output=True,
        )

    def test_reuses_only_an_identical_green_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            counter = root / "counter"
            command = ("sh", "-c", f"echo run >> {counter}")
            first = self.run_wrapper(root, "key-a", command)
            second = self.run_wrapper(root, "key-a", command)
            changed = self.run_wrapper(root, "key-b", command)
            self.assertEqual((0, 0, 0), (first.returncode, second.returncode, changed.returncode))
            self.assertEqual(2, len(counter.read_text().splitlines()))
            self.assertIn("reusing green receipt", second.stderr)

    def test_concurrent_writers_share_one_receipt_lease(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            counter = root / "counter"
            env = {
                **os.environ,
                "VERIFICATION_RECEIPT_ROOT": str(root / "receipts"),
            }
            args = [
                str(SCRIPT),
                "--name",
                "fixture",
                "--key",
                "race",
                "--",
                "sh",
                "-c",
                f"sleep 0.2; echo run >> {counter}",
            ]
            first = subprocess.Popen(args, cwd=root, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            second = subprocess.Popen(args, cwd=root, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            first_out, first_err = first.communicate(timeout=5)
            second_out, second_err = second.communicate(timeout=5)

            self.assertEqual((0, 0), (first.returncode, second.returncode))
            self.assertEqual(1, len(counter.read_text().splitlines()))
            combined = first_out + first_err + second_out + second_err
            self.assertIn("queued behind fixture", combined)
            self.assertIn("reusing green receipt", combined)

    def test_failure_never_writes_a_green_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            failed = self.run_wrapper(root, "key-a", ("sh", "-c", "exit 7"))
            self.assertEqual(7, failed.returncode)
            receipts = list((root / "receipts").glob("*.json")) if (root / "receipts").exists() else []
            self.assertEqual([], receipts)

    def test_force_runs_even_when_receipt_is_green(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            counter = root / "counter"
            command = ("sh", "-c", f"echo run >> {counter}")
            self.assertEqual(0, self.run_wrapper(root, "key-a", command).returncode)
            self.assertEqual(0, self.run_wrapper(root, "key-a", command, "--force").returncode)
            self.assertEqual(2, len(counter.read_text().splitlines()))

    def test_missing_semantic_output_never_writes_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = self.run_wrapper(
                root,
                "key-a",
                ("sh", "-c", "echo superficially-green"),
                "--require-output",
                "Tasks: [0-9]+ successful",
            )
            self.assertEqual(65, result.returncode)
            self.assertIn("semantic success assertion missing", result.stderr)
            self.assertEqual([], list((root / "receipts").glob("*.json")))

    def test_corrupt_receipt_is_not_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            counter = root / "counter"
            command = ("sh", "-c", f"echo run >> {counter}")
            self.assertEqual(0, self.run_wrapper(root, "key-a", command).returncode)
            receipt = next((root / "receipts").glob("*.json"))
            receipt.write_text("{}\n")
            self.assertEqual(0, self.run_wrapper(root, "key-a", command).returncode)
            self.assertEqual(2, len(counter.read_text().splitlines()))

    def test_output_assertions_are_part_of_receipt_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            counter = root / "counter"
            command = ("sh", "-c", f"echo run | tee -a {counter}")
            self.assertEqual(0, self.run_wrapper(root, "key-a", command).returncode)
            asserted = self.run_wrapper(
                root, "key-a", command, "--require-output", "^run$"
            )
            self.assertEqual(0, asserted.returncode)
            self.assertEqual(2, len(counter.read_text().splitlines()))

    def test_name_and_key_are_required_and_key_is_not_a_shell_expression(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = subprocess.run([str(SCRIPT), "--name", "fixture", "--", "true"], cwd=root)
            self.assertEqual(64, result.returncode)


if __name__ == "__main__":
    unittest.main()
