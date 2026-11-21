#!/usr/bin/env python3
"""program_family.state_file: the one resolver from a program to its state file, as the mine plan uses it.

Fixtures (fixtures/state_file/) are de-identified copies of the programs dir on two dates. The old plan
built `<slug>.state.md` from whatever slug it held: on nov04 it pointed release-v1-and-billing-go-live at
a file that did not exist (the state lived in release-billing.state.md) and handed `release` and `crm`
made-up paths; on nov21 a `release-billing` slug read the `Moved:` stub instead of the real file."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mine_all  # noqa: E402
import program_family as pf  # noqa: E402

FIX = os.path.join(HERE, "fixtures", "state_file")
NOV04, NOV21 = os.path.join(FIX, "nov04"), os.path.join(FIX, "nov21")
REAL = "release-v1-and-billing-go-live"


def fold(slug, programs_dir):
    man = next((m for m in pf.load_manifests(programs_dir) if m["slug"] == slug), None)
    return mine_all.state_fold(slug, programs_dir, 0.0, man)


class StateFileResolution(unittest.TestCase):
    def test_manifest_slug_finds_the_file_that_declares_it(self):
        f = fold(REAL, NOV04)
        self.assertEqual(f["state"], os.path.join(NOV04, "release-billing.state.md"))
        self.assertEqual(f["state_note"], "state_declared:release-billing.state.md")
        self.assertNotEqual(f["verdict"], "MISSING")

    def test_old_name_follows_its_moved_stub_to_the_real_file(self):
        f = fold("release-billing", NOV21)
        self.assertEqual(f["state"], os.path.join(NOV21, f"{REAL}.state.md"))
        self.assertEqual(f["state_note"], f"state_moved:release-billing.state.md->{REAL}.state.md")
        self.assertGreater(f["events_mtime"], 0.0)  # the events log beside the resolved file

    def test_canonical_name_resolves_directly(self):
        f = fold(REAL, NOV21)
        self.assertEqual((f["state"], f["state_note"]), (os.path.join(NOV21, f"{REAL}.state.md"), None))

    def test_title_only_programs_get_no_path_not_a_made_up_one(self):
        for d in (NOV04, NOV21):
            for slug in ("release", "crm"):
                f = fold(slug, d)
                self.assertIsNone(f["state"], (d, slug))  # never `release-b.state.md`, never `release.state.md`
                self.assertEqual((f["state_note"], f["verdict"]), (f"state_missing:{slug}", "MISSING"))

    def test_moved_cycle_and_ambiguity_fail_closed(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            for name, body in (("a", "Moved: see b.state.md\n"), ("b", "Moved: see a.state.md\n"),
                               ("x1", "# Program x1 (alias: dup)\n"), ("x2", "# Program x2 (alias: dup)\n")):
                with open(os.path.join(d, f"{name}.state.md"), "w") as fh:
                    fh.write(body)
            self.assertEqual(pf.state_file("a", d), (None, "state_moved_broken:a.state.md->b.state.md->a.state.md"))
            self.assertEqual(pf.state_file("dup", d), (None, "state_ambiguous:x1.state.md,x2.state.md"))


if __name__ == "__main__":
    unittest.main()
