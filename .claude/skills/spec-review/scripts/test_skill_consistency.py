#!/usr/bin/env python3
"""Consistency checks for the spec-review skill: the Workflow script's lane manifest is the
single source of lane data, and everything else (prompt files, SKILL.md) must agree with it.

Run: python3 -m unittest discover -s .claude/skills/spec-review/scripts
"""
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_dir  # noqa: E402

SKILL_DIR = HERE.parent
SKILL_PATH = SKILL_DIR / "SKILL.md"
SKILL = SKILL_PATH.read_text()
PROMPTS_DIR = SKILL_DIR / "prompts"
WORKFLOW_JS = HERE / "spec-review.workflow.js"
MANIFEST = run_dir.load_manifest()

# Byte ratchet -- SKILL.md is a short launcher now. Bump only in the same change that documents
# why it had to grow; never to re-absorb lane briefs, tables or the report template (those live
# in scripts/spec-review.workflow.js, prompts/ and report-template.md).
# Recorded 2026-10-04: 67488B (pre-rewrite) -> launcher size below.
MAX_SKILL_BYTES = 8372

# Lanes that are gated supplements / substitutes, not part of the "13 reviewers".
SUPPLEMENTS = {"adr-auditor", "cutover-architect", "runtime-wiring", "critic-hotfix", "critic-adversarial", "critic-frontier"}


def declared(text, key):
    m = re.search(r"\*\*" + key + r":\*\*\s*`?([^`\n(]+)", text)
    return m.group(1).strip() if m else None


class ManifestTests(unittest.TestCase):
    def test_manifest_is_non_empty_and_labels_unique(self):
        entries = run_dir.all_entries(MANIFEST)
        self.assertGreaterEqual(len(MANIFEST["lanes"]), 13)
        labels = [e["label"] for e in entries]
        self.assertEqual(len(labels), len(set(labels)), "duplicate lane labels")

    def test_every_manifest_prompt_exists_and_agrees(self):
        checked = 0
        for e in run_dir.all_entries(MANIFEST):
            if not e.get("prompt"):
                continue
            path = PROMPTS_DIR / e["prompt"]
            self.assertTrue(path.is_file(), f"{e['label']}: missing {path}")
            text = path.read_text()
            self.assertEqual(text.splitlines()[0], f"ROLE: {e['label']}", f"{path.name}: first line must be the fixed ROLE label")
            self.assertEqual(declared(text, "Agent type"), e["agentType"], f"{path.name}: Agent type vs manifest")
            model = declared(text, "Model")
            if model == "default":
                model = "sonnet"
            if e.get("model"):
                self.assertEqual(model, e["model"], f"{path.name}: Model vs manifest")
            checked += 1
        self.assertGreaterEqual(checked, 17, "non-empty lane-set assertion: expected every prompt-backed lane to be checked")

    def test_every_prompt_file_is_in_the_manifest_and_starts_with_role(self):
        in_manifest = {e["prompt"] for e in run_dir.all_entries(MANIFEST) if e.get("prompt")}
        files = sorted(p.name for p in PROMPTS_DIR.glob("*.md"))
        self.assertTrue(files)
        self.assertEqual(set(files), in_manifest, "prompts/*.md and the manifest disagree")
        for name in files:
            first = (PROMPTS_DIR / name).read_text().splitlines()[0]
            self.assertRegex(first, r"^ROLE: [a-z][a-z0-9-]+$", f"{name} must start with a ROLE: label")

    def test_reviewer_count_is_13(self):
        reviewers = [e for e in MANIFEST["lanes"] if e["label"] not in SUPPLEMENTS]
        claude = [e for e in reviewers if e["kind"] == "claude"]
        codex = [e for e in reviewers if e["kind"] == "codex"]
        self.assertEqual((len(claude), len(codex), len(reviewers)), (9, 4, 13))
        self.assertIn("13 parallel reviewers", SKILL.split("---", 2)[1])

    def test_astra_runs_in_every_profile_and_hotfix_shape(self):
        frontier = next(e for e in MANIFEST["lanes"] if e["label"] == "codex-frontier")
        self.assertEqual(sorted(frontier["profiles"]), sorted(MANIFEST["profiles"]))
        self.assertTrue(frontier.get("fallback"))
        for sub in ("critic-frontier", "critic-adversarial"):
            e = next(x for x in MANIFEST["lanes"] if x["label"] == sub)
            self.assertEqual((e["agentType"], e["model"]), ("critic", "fable"))
        hotfix = {e["label"] for e in MANIFEST["lanes"] if "hotfix" in e["profiles"]}
        self.assertEqual(hotfix, {"codebase-verifier", "critic-hotfix", "codex-frontier"})

    def test_gated_lanes_use_declared_gates(self):
        for e in MANIFEST["lanes"]:
            if e.get("gate"):
                self.assertIn(e["gate"], MANIFEST["gates"])
        for g in MANIFEST["gates"]:
            self.assertTrue(any(e.get("gate") == g for e in MANIFEST["lanes"]), f"gate {g} gates no lane")

    def test_codex_lanes_have_class_and_prompts(self):
        for e in MANIFEST["lanes"]:
            if e["kind"] == "codex":
                self.assertIn(e["codexClass"], {"verify", "falsifier", "research", "frontier"})
                self.assertEqual(e["agentType"], "codex-dispatch")

    def test_lanes_without_prompt_file_have_a_brief(self):
        for e in MANIFEST["lanes"]:
            if not e.get("prompt"):
                self.assertTrue(e.get("brief"), f"{e['label']} has neither prompt nor brief")


class ScriptSyntaxTests(unittest.TestCase):
    def test_workflow_js_parses(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        src = WORKFLOW_JS.read_text().replace("export const meta", "const meta", 1)
        tmp = Path(__import__("tempfile").mkdtemp()) / "check.js"
        tmp.write_text("async function main(){\n" + src + "\n}\n")
        r = subprocess.run([node, "--check", str(tmp)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_shell_wrapper_parses(self):
        r = subprocess.run(["bash", "-n", str(HERE / "run-codex-lanes.sh")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


class SkillMdTests(unittest.TestCase):
    def test_skill_byte_ratchet(self):
        size = len(SKILL.encode("utf-8"))
        self.assertLessEqual(size, MAX_SKILL_BYTES, f"SKILL.md grew to {size}B over the {MAX_SKILL_BYTES}B ceiling")

    def test_deleted_sections_stay_deleted(self):
        for header in ("## Quick Reference", "## Agent Summary"):
            self.assertNotIn(header, SKILL)

    def test_launcher_states_opt_in_and_contract(self):
        for needle in ("opt-in", "spec-review.workflow.js", "run-codex-lanes.sh", "report-template.md",
                       "stage", "runDir", "gates", "Session-Id"):
            self.assertIn(needle, SKILL)

    def test_learnings_not_read_at_startup(self):
        self.assertNotIn("Before starting:** Read `LEARNINGS.md`", SKILL)

    def test_step_5c_anchor_exists_for_the_validator(self):
        self.assertIn("Step 5c", SKILL)

    def test_report_template_exists_with_canonical_falsifier_line(self):
        tpl = (SKILL_DIR / "report-template.md").read_text()
        self.assertIn("### Falsifier wave:", tpl)


if __name__ == "__main__":
    unittest.main()
