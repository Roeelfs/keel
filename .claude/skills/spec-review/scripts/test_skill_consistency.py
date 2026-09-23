#!/usr/bin/env python3
"""SR3: internal-consistency checks for spec-review/SKILL.md.

Catches the class of bug where SKILL.md's own copies of a fact (a lane's
dispatch Type, the reviewer headcount, a numbering footnote) drift apart or
drift from the prompt file that is the actual source of truth for a lane.
"""
import re
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SKILL_PATH = SKILL_DIR / "SKILL.md"
SKILL = SKILL_PATH.read_text()
PROMPTS_DIR = SKILL_DIR / "prompts"

# Byte ratchet -- bump only in the same change that documents why SKILL.md
# had to grow (e.g. a new reviewer lane), never to silently re-absorb creep.
# Recorded 2026-09-23: 74440B after the SR5 reference.md subtraction, then
# 75842B after SR1/SR4 added the canonical falsifier-wave line, stable F-N
# finding IDs, and the "## Carried obligations" report section, then 66806B
# after the lane-KA split moved the "Why This Exists" 10-point rationale,
# Step 4b (Progressive Drift Investigation), and Step 5b (Cross-Examination
# Debate Protocol) verbatim into reference.md behind one-line pointers, then
# 67050B in the same change once SR2 added its one-line pointer to
# plan_falsifier_batches.py at the Step 5a falsifier-wave step (see
# reference.md for the material this and SR5 moved out; SR1/SR4's additions
# were real new process, not creep, so the ceiling moved with them then too).
MAX_SKILL_BYTES = 67050


def declared_agent_types():
    """{prompt_filename: declared type} for every prompts/*.md with an
    '**Agent type:**' line."""
    out = {}
    for path in sorted(PROMPTS_DIR.glob("*.md")):
        text = path.read_text()
        m = re.search(r"\*\*Agent type:\*\*\s*`([^`]+)`", text)
        if m:
            out[path.name] = m.group(1)
    return out


def _types_by_preceding_prompt_ref(text, type_line_re):
    """For every line matching type_line_re, walk backward (within the same
    paragraph, i.e. until a blank line) to the nearest `prompts/<file>.md`
    reference and record {file: declared_type}. Robust to the varying amount
    of prose between the lane's header and its Type/Agent-type line."""
    lines = text.splitlines()
    out = {}
    prompt_ref_re = re.compile(r"prompts/([\w-]+\.md)")
    for i, line in enumerate(lines):
        m = type_line_re.match(line)
        if not m:
            continue
        for j in range(i, -1, -1):
            if j != i and lines[j].strip() == "":
                break
            ref = prompt_ref_re.search(lines[j])
            if ref:
                out.setdefault(ref.group(1), m.group(1))
                break
    return out


def step4_dispatch_types():
    """{prompt_filename: type} from the Step 4 '- **Type:** `x`' dispatch
    lines (one per primary reviewer lane)."""
    return _types_by_preceding_prompt_ref(
        SKILL, re.compile(r"^- \*\*Type:\*\* `([^`]+)`")
    )


def summary_table_types():
    """{prompt_filename: type} from the '## Agent Summary' markdown table."""
    start = SKILL.index("## Agent Summary")
    end = SKILL.index("## Process Gates")
    table_text = SKILL[start:end]
    out = {}
    prompt_ref_re = re.compile(r"`prompts/([\w-]+\.md)`")
    for line in table_text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 4:
            continue
        ref = prompt_ref_re.search(cells[2])
        if not ref:
            continue
        out[ref.group(1)] = cells[3].strip("*").strip("`")
    return out


class SkillConsistencyTests(unittest.TestCase):
    def test_prompt_agent_type_matches_step4_dispatch(self):
        declared = declared_agent_types()
        step4 = step4_dispatch_types()
        mismatches = [
            f"{fname}: Step-4 says `{step4[fname]}`, prompt says `{want}`"
            for fname, want in declared.items()
            if fname in step4 and step4[fname] != want
        ]
        self.assertEqual(mismatches, [], "\n" + "\n".join(mismatches))

    def test_prompt_agent_type_matches_agent_summary_table(self):
        declared = declared_agent_types()
        table = summary_table_types()
        mismatches = [
            f"{fname}: Agent-Summary table says `{table[fname]}`, prompt says `{want}`"
            for fname, want in declared.items()
            if fname in table and table[fname] != want
        ]
        self.assertEqual(mismatches, [], "\n" + "\n".join(mismatches))

    def test_reviewer_count_is_13_everywhere(self):
        frontmatter = SKILL.split("---", 2)[1]
        self.assertIn("13 parallel reviewers", frontmatter)

        intro = SKILL.split("## Skill Memory")[0]
        self.assertIn("13 focused reviewers", intro)
        self.assertIn("Codex Frontier Judgment", intro)
        self.assertIn("prompts/codex-frontier-judge.md", intro)

        qr_line = next(l for l in SKILL.splitlines() if l.startswith("| 4 |"))
        self.assertIn("13 Reviewers", qr_line)
        self.assertIn("Codex Frontier Judgment", qr_line)

    def test_numbering_note_agrees_with_agent_summary_table(self):
        self.assertNotIn("no agent bears the number 10", SKILL)
        # Agent 10 (Codex Frontier Judgment) must actually appear as a row.
        self.assertRegex(SKILL, r"\|\s*10\s*\|\s*\*\*Codex Frontier Judgment\*\*")

    def test_skill_byte_ratchet(self):
        size = len(SKILL.encode("utf-8"))
        self.assertLessEqual(
            size,
            MAX_SKILL_BYTES,
            f"SKILL.md grew to {size}B, over the recorded ceiling of "
            f"{MAX_SKILL_BYTES}B -- move new material to reference.md behind "
            "a one-line pointer, or raise the ceiling deliberately in the "
            "same change that explains the growth.",
        )


if __name__ == "__main__":
    unittest.main()
