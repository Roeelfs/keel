#!/usr/bin/env python3
"""SKILL.md byte ratchet: the dispatcher's skill body only shrinks. The must-fire manager rules moved to
references/role.md (one owner, loaded by /manager-role); nothing may grow back here. Lower MAX_SKILL_BYTES
whenever the file shrinks; never raise it."""
import os
import unittest

SKILL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "SKILL.md")
# 2026-11-05: 27200 -> 19576 when the must-fire bullets moved to references/role.md.
MAX_SKILL_BYTES = 19576


class SkillSize(unittest.TestCase):
    def test_skill_body_only_shrinks(self):
        size = os.path.getsize(SKILL)
        self.assertLessEqual(size, MAX_SKILL_BYTES, f"SKILL.md is {size} bytes, over the {MAX_SKILL_BYTES} ratchet")


if __name__ == "__main__":
    unittest.main()
