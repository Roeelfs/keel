"""wire-skills.sh --kind scripts: keel bin/ entries are linked into the script root, and a
REAL file at a destination fails the run, because a second hand-maintained copy is the
defect this kind exists to end (spawn-lane.sh, diverged 07-29 → 09-23).

Hermetic: KEEL_SCRIPT_ROOTS points at a temp dir; skills/agents are not synced.
Run: python3 tooling/test_wire_skills_scripts.py
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

KEEL = Path(__file__).resolve().parent.parent
WIRE = KEEL / "tooling" / "wire-skills.sh"
BIN = KEEL / "bin"


class WireScripts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "home" / ".claude" / "scripts"
        self.root.parent.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def wire(self):
        env = {**os.environ, "KEEL_SCRIPT_ROOTS": str(self.root)}
        return subprocess.run(["bash", str(WIRE), "--kind", "scripts"],
                              capture_output=True, text=True, env=env)

    def entries(self):
        return sorted(p.name for p in BIN.iterdir() if p.is_file())

    def test_every_bin_entry_is_linked_into_the_script_root(self):
        self.assertIn("spawn-lane.sh", self.entries(), "bin/ must carry the spawn-lane owner link")
        r = self.wire()
        self.assertEqual(r.returncode, 0, r.stderr)
        for name in self.entries():
            dest = self.root / name
            self.assertTrue(dest.is_symlink(), f"{name} must be a symlink")
            self.assertEqual(dest.resolve(), (BIN / name).resolve())

    def test_a_real_file_at_a_destination_fails_the_run_and_is_left_untouched(self):
        self.root.mkdir()
        copy = self.root / "spawn-lane.sh"
        copy.write_text("#!/bin/sh\n# a stale second copy\n")
        r = self.wire()
        self.assertEqual(r.returncode, 1, "a surviving real copy must fail loudly, not be skipped")
        self.assertIn("second copy", r.stderr)
        self.assertFalse(copy.is_symlink())
        self.assertEqual(copy.read_text(), "#!/bin/sh\n# a stale second copy\n")

    def test_a_dangling_managed_link_is_pruned(self):
        self.root.mkdir()
        gone = self.root / "retired.sh"
        gone.symlink_to(BIN / "retired.sh")          # points into keel bin/, target absent
        r = self.wire()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(gone.is_symlink(), "a link whose keel source was removed must be pruned")


if __name__ == "__main__":
    unittest.main()
