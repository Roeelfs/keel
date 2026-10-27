#!/usr/bin/env python3
"""Consistency checks for the spec-review skill: lanes.json is the
single source of lane data, and everything else (prompt files, SKILL.md) must agree with it.

Run: python3 -m unittest discover -s .claude/skills/spec-review/scripts
"""
import json
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
# 2026-10-13: 8925 -> 9254. Added the legalSurface gate to Step 1 and the hardStopReasons sentence to Step 5
# (the legal-auditor lane); both are launcher decisions the main loop makes, so they cannot live elsewhere.
# 2026-10-20: 9254 -> 9647. Added the decisionSurface gate to Step 1, its investigation theme to Step 3 and the
# S1 research hand-off step to Step 5 (the system1-elevation lane); all three are main-loop decisions.
# 2026-10-22: 9647 -> 10029. The dependency-currency supplement (versions, CVE/KEV advisories, vendor docs)
# runs in every profile; Step 1 names it and its advisory-feed failure rule, both main-loop decisions.
# 2026-10-25: 10029 -> 11800. Mandatory-by-tier review: Step 1 now owns the tier choice and the lanePlan
# (main-loop decisions), the plan command, and the no-skip process gate; the Opt-in and When-NOT-to-use text is gone.
# 2026-10-27 (CYN-3219): 11800 -> 13500. The script-runner wrapper agents are gone, so the Bash gates (stage.py) and the
# stage-by-stage launch sequence are main-loop steps that must be named here; the old Step 2-4 prose is deleted.
# 2026-10-27 (CYN-3222): 13500 -> 13950. Depth ladder R1-R4 (critical only for a cynap floor-domain spec, fix-verify vs
# delta re-review, frame.json repo/harnessOnly/floorDomain) is a Step 1/2 launcher decision; superseded text was trimmed.
MAX_SKILL_BYTES = 13950

# Lanes that are gated supplements / substitutes, not part of the "13 reviewers".
SUPPLEMENTS = {"adr-auditor", "legal-auditor", "cutover-architect", "runtime-wiring", "performance-architect", "operator-plane-architect", "system1-elevation", "critic-hotfix", "critic-adversarial", "critic-frontier", "dependency-currency"}


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
        self.assertEqual((len(claude), len(codex), len(reviewers)), (7, 6, 13))
        self.assertIn("13 parallel reviewers", SKILL.split("---", 2)[1])

    def test_astra_runs_in_every_profile_and_hotfix_shape(self):
        frontier = next(e for e in MANIFEST["lanes"] if e["label"] == "codex-frontier")
        self.assertEqual(sorted(frontier["profiles"]), sorted(MANIFEST["profiles"]))
        self.assertTrue(frontier.get("fallback"))
        for sub in ("critic-frontier", "critic-adversarial"):
            e = next(x for x in MANIFEST["lanes"] if x["label"] == sub)
            self.assertEqual((e["agentType"], e["model"]), ("critic", "opus"))
        hotfix = {e["label"] for e in MANIFEST["lanes"] if "hotfix" in e["profiles"]}
        # 2026-10-22 (founder): module shape and dependency/CVE currency are checked even in a hotfix.
        self.assertEqual(hotfix, {"codebase-verifier", "critic-hotfix", "codex-frontier",
                                  "architecture-auditor", "dependency-currency"})

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

    def test_performance_architect_is_a_live_surface_supplement_with_a_real_lens(self):
        e = next(x for x in MANIFEST["lanes"] if x["label"] == "performance-architect")
        self.assertEqual((e["kind"], e["gate"], e["profiles"]), ("claude", "liveSurface", []))
        self.assertTrue((SKILL_DIR.parent / "improve-codebase-architecture" / "SKILL.md").is_file(),
                        "the lane reads the improve-codebase-architecture skill as its lens")

    def test_legal_auditor_runs_in_every_full_review_and_by_gate_elsewhere(self):
        e = next(x for x in MANIFEST["lanes"] if x["label"] == "legal-auditor")
        self.assertEqual((e["kind"], e["agentType"], e["gate"], e["profiles"]), ("claude", "legal-auditor", "legalSurface", ["full"]))
        for field in ("register_found", "sources_read", "legal_commitment_breach", "founder_approval_marker_present"):
            self.assertIn(field, e["brief"], f"the brief must ask for envelope field {field}")
            self.assertIn(field + ":", WORKFLOW_JS.read_text(), f"the ENVELOPE schema must carry {field}")

    def test_every_named_agent_lane_has_an_agent_file_with_a_model(self):
        agents_dir = SKILL_DIR.parents[1] / "agents"
        generic = {"general-purpose", "codex-dispatch"}
        named = sorted({e["agentType"] for e in MANIFEST["lanes"] if e["agentType"] not in generic})
        self.assertIn("legal-auditor", named)
        for name in named:
            path = agents_dir / f"{name}.md"
            self.assertTrue(path.is_file(), f"lane agentType {name} has no agent file at {path}")
            self.assertRegex(path.read_text().split("---", 2)[1], r"(?m)^model: \S+", f"{name}.md frontmatter must pin a model")

    def test_operator_plane_architect_owns_the_operator_surface_gate(self):
        e = next(x for x in MANIFEST["lanes"] if x["label"] == "operator-plane-architect")
        self.assertEqual((e["kind"], e["gate"], e["profiles"], e["model"]), ("claude", "operatorSurface", [], "sonnet"))
        text = (SKILL_DIR / "prompts" / e["prompt"]).read_text(encoding="utf-8")
        self.assertIn("Read-only:** strictly", text)
        self.assertIn("{{ARCH_LENS_PATH}}", text)

    def test_system1_elevation_owns_the_decision_surface_gate_and_reports_everything(self):
        e = next(x for x in MANIFEST["lanes"] if x["label"] == "system1-elevation")
        self.assertEqual((e["kind"], e["gate"], e["profiles"], e["model"], e["idPrefix"]), ("claude", "decisionSurface", [], "opus", "S1"))
        self.assertTrue(e["reportEveryFinding"] and e["researchHandoffs"])
        self.assertIn("ELEVATE", e["severities"].split("|"))
        self.assertIn("system1", e["tags"])
        self.assertIn("research_handoffs:", WORKFLOW_JS.read_text(), "the ENVELOPE schema must carry research_handoffs")
        text = (SKILL_DIR / "prompts" / e["prompt"]).read_text(encoding="utf-8")
        for needle in ("Read-only:** strictly", "{{ARCH_LENS_PATH}}", "{{LEARNINGS_LIST}}", "KEEP-RULE", "Fallback:", "Evaluation:", "research_handoffs"):
            self.assertIn(needle, text)
        self.assertIn("system1", (SKILL_DIR / "prompts" / "context-dossier-miner.md").read_text(), "the dossier miner must be able to route questions to it")
        self.assertIn("### System 1 Intelligence", (SKILL_DIR / "report-template.md").read_text())

    def test_tiers_map_onto_profiles_and_the_manifest_validates(self):
        self.assertEqual(run_dir.validate_manifest(MANIFEST), [])
        self.assertEqual({t: v["profile"] for t, v in MANIFEST["tiers"].items()},
                         {"critical": "full", "standard": "standard", "light": "light", "hotfix": "hotfix"})
        by = lambda p: {e["label"] for e in MANIFEST["lanes"] if p in e["profiles"]}
        self.assertEqual(by("standard"), {"completeness-reviewer", "codebase-verifier", "edge-case-miner", "dependency-currency", "codex-frontier", "adr-auditor"})
        self.assertEqual(by("light"), {"codebase-verifier", "edge-case-miner", "codex-frontier"})
        self.assertEqual({t: v["budget"]["falsifier"] for t, v in MANIFEST["tiers"].items()},
                         {"critical": "uncorroborated", "standard": "critical", "light": "off", "hotfix": "all"})

    def test_workflow_runs_no_commands_and_reads_no_plan(self):
        """A Workflow script has no shell: every command is a Bash gate (stage.py) the main loop runs.
        No LLM agent exists just to run a command or relay JSON."""
        src = WORKFLOW_JS.read_text()
        for gone in ("MANIFEST", "script-runner", "show-plan", "put-envelope", "PYOUT", "textSum", "py("):
            self.assertNotIn(gone, src, f"{gone} was deleted with the wrapper agents")
        self.assertIn("stage.py", src)
        self.assertNotIn("script-runner", [e["label"] for e in MANIFEST["support"]])

    def test_ceilings_are_calibrated_and_enforced(self):
        ceilings = {t: v["budget"]["tokenCeiling"] for t, v in MANIFEST["tiers"].items()}
        self.assertEqual(ceilings, {"critical": 45_000_000, "standard": 22_000_000, "light": 2_000_000, "hotfix": 3_000_000})
        stage = (HERE / "stage.py").read_text()
        self.assertIn("lane_spend.STOP_RATIO", stage)
        self.assertEqual(__import__("lane_spend").STOP_RATIO, 1.5)

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

    def test_codex_envelope_extraction_is_codex_first_with_claude_fallback_only(self):
        src = WORKFLOW_JS.read_text()
        self.assertEqual(src.count("ROLE: codex-envelope-extractor"), 1, "one fallback prompt, in the critics stage")
        self.assertIn("Fallback only", src)
        sh = (HERE / "run-codex-lanes.sh").read_text()
        for needle in ("extract-plan", "extract-envelopes", "extract-finish", "extract.tsv"):
            self.assertIn(needle, sh)
        self.assertIn('"luna"', (HERE / "stage.py").read_text())

    def test_shell_wrapper_parses(self):
        r = subprocess.run(["bash", "-n", str(HERE / "run-codex-lanes.sh")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_stage_cli_parses_every_gate(self):
        import stage
        for gate in ("prepare", "finish-prepare", "post-review", "synth-prep", "falsify-prep", "falsify-check", "report-check",
                     "mark-applied", "extract-plan", "extract-envelopes", "spend"):
            self.assertIn(f"  {gate}", stage.__doc__, f"{gate} is undocumented in stage.py")


class SkillMdTests(unittest.TestCase):
    def test_skill_byte_ratchet(self):
        size = len(SKILL.encode("utf-8"))
        self.assertLessEqual(size, MAX_SKILL_BYTES, f"SKILL.md grew to {size}B over the {MAX_SKILL_BYTES}B ceiling")

    def test_deleted_sections_stay_deleted(self):
        for header in ("## Quick Reference", "## Agent Summary"):
            self.assertNotIn(header, SKILL)

    def test_review_is_mandatory_with_a_tier_floor(self):
        self.assertNotIn("When NOT to use", SKILL)
        self.assertNotIn("not a cap", SKILL)
        for needle in ("skipping is not an option", "lanePlan", "run_dir.py plan", "never `light`", "critical", "standard", "light"):
            self.assertIn(needle, SKILL)

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
