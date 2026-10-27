#!/usr/bin/env python3
"""Tests for run_dir.py: template filling, placeholder guard, question assignment and the
envelope / report mechanical checks the Workflow script relies on."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_dir  # noqa: E402

PROMPTS = HERE.parent / "prompts"
MANIFEST = run_dir.load_manifest()
ALL_VALUES = {k: "X" for k in (
    "SPEC_PATH", "PROJECT_ROOT", "ARCH_LENS_PATH", "LEARNINGS_LIST", "DOSSIER_CONTENT", "CONTEXT_BLOCK", "GOAL", "TRIGGER", "TARGET_OUTCOME",
    "OUT_OF_SCOPE", "DECISIONS_JSON_PATH", "RUNTIME", "LANE", "SEVERITY", "FINDING_TEXT", "CITED_EVIDENCE",
    "PROPOSED_FIX", "DRIFT_ID", "SCOUT_FINDING", "TARGETED_PATHS", "NARROW_QUESTION", "SPEC_PATH_REL",
    "DOSSIER_PATH", "FOCUS_TEXT")}


def call(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = run_dir.main(list(argv))
    return rc, json.loads(buf.getvalue())


def make_run(tmp, questions=None):
    run = Path(tmp)
    for d in ("inputs", "lanes", "envelopes", "falsifiers", "codex", "prompts"):
        (run / d).mkdir(exist_ok=True)
    (run / "inputs" / "context.md").write_text("Goal: g\nTrigger: t\nTarget outcome: o\nScope boundaries: s\n")
    (run / "inputs" / "root.txt").write_text(str(HERE))
    (run / "inputs" / "learnings.txt").write_text(str(HERE.parent / "LEARNINGS.md"))
    (run / "dossier.md").write_text("# Dossier\n" + "fact\n" * 80)
    qs = questions or [
        {"id": "Q1", "lane": "edge-case", "text": "what about max+1?"},
        {"id": "Q2", "lane": "security", "text": "authz source?"},
        {"id": "Q3", "lane": "codex-adversarial", "text": "race on retry?"},
        {"id": "Q4", "lane": "made-up-tag", "text": "orphan question"},
    ]
    (run / "questions.json").write_text(json.dumps(qs))
    return run


GATES_OFF = {g: {"run": False, "reason": "n/a"} for g in MANIFEST["gates"]}


def gates(**fired):
    return {g: {"run": g in fired, "reason": fired.get(g, "n/a")} for g in MANIFEST["gates"]}


def plan(tier, g=None, add=(), drop=(), reasons=None, m=MANIFEST):
    return run_dir.plan_lanes(m, tier, g or GATES_OFF, {"add": list(add), "drop": list(drop), "reasons": reasons or {}})


class LanePlanTests(unittest.TestCase):
    def test_tier_default_sets_and_gate_lanes(self):
        p, errs = plan("standard", gates(security="adds authz"))
        self.assertEqual(errs, [])
        self.assertEqual({e["label"] for e in p["run"]}, {"completeness-reviewer", "codebase-verifier", "edge-case-miner", "dependency-currency", "codex-frontier", "adr-auditor", "security-miner"})
        self.assertEqual((p["planned"], p["plannedCodex"], p["overBudget"]), (7, 2, []))
        self.assertEqual(p["laneReasons"]["security-miner"], "gate security fired: adds authz")

    def test_light_is_refused_when_any_gate_fired(self):
        _, errs = plan("light", gates(liveSurface="touches prod"))
        self.assertTrue(any("below the floor" in e for e in errs))
        self.assertEqual(plan("light")[1], [])

    def test_drop_rules(self):
        self.assertTrue(plan("critical", drop=["codex-research"], reasons={"codex-research": "x"})[1])
        self.assertTrue(any("non-droppable" in e for e in plan("standard", drop=["codex-frontier"], reasons={"codex-frontier": "x"})[1]))
        _, errs = plan("standard", gates(security="s"), drop=["security-miner"], reasons={"security-miner": "x"})
        self.assertTrue(any("non-droppable" in e for e in errs))
        p, errs = plan("standard", drop=["dependency-currency"], reasons={"dependency-currency": "no deps touched"})
        self.assertEqual(errs, [])
        self.assertIn("dependency-currency", [s["label"] for s in p["skipped"]])

    def test_unknown_label_and_missing_reason_are_errors(self):
        self.assertTrue(any("unknown lane label" in e for e in plan("standard", add=["nope"], reasons={"nope": "x"})[1]))
        self.assertTrue(any("needs a reason" in e for e in plan("standard", add=["codex-research"])[1]))

    def test_add_over_budget_is_advisory_only(self):
        p, errs = plan("light", add=["codex-research", "codex-adversarial"], reasons={"codex-research": "a", "codex-adversarial": "b"})
        self.assertEqual(errs, [])
        self.assertEqual(len(p["overBudget"]), 2)

    def test_override_merge_and_validation(self):
        ov = {"lanes": {"retune": {"edge-case-miner": {"model": "sonnet"}}, "disable": ["codex-research"],
                        "add": [{"label": "pii-check", "kind": "claude", "agentType": "general-purpose", "model": "sonnet", "prompt": None,
                                 "brief": "b {{SPEC_PATH}}", "profiles": ["standard"], "gate": None, "idPrefix": "PII", "tags": []}]},
              "tiers": {"standard": {"budget": {"maxLanes": 9}}}}
        m, errs = run_dir.merge_override(MANIFEST, ov)
        self.assertEqual((errs, run_dir.validate_manifest(m)), ([], []))
        self.assertEqual(m["tiers"]["standard"]["budget"]["maxLanes"], 9)
        self.assertNotIn("codex-research", [e["label"] for e in m["lanes"]])
        self.assertIn("PII", [e["idPrefix"] for e in m["lanes"]])
        self.assertEqual(MANIFEST["tiers"]["standard"]["budget"]["maxLanes"], 11, "the default must not be mutated")
        for bad in ({"lanes": {"disable": ["codex-frontier"]}}, {"lanes": {"disable": ["security-miner"]}},
                    {"lanes": {"retune": {"edge-case-miner": {"gate": "security"}}}}, {"bogus": 1},
                    {"lanes": {"add": [{"label": "edge-case-miner"}]}}):
            self.assertTrue(run_dir.merge_override(MANIFEST, bad)[1], bad)
        m2, _ = run_dir.merge_override(MANIFEST, {"lanes": {"retune": {"codex-frontier": {"profiles": ["full"]}}}})
        self.assertTrue(any("floor lane" in e for e in run_dir.validate_manifest(m2)))

    def test_plan_command_writes_manifest_plan_and_scopes_the_falsifier(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, root = Path(tmp) / "run", Path(tmp) / "root"
            (root / ".claude").mkdir(parents=True)
            (root / ".claude" / "spec-review.lanes.json").write_text(json.dumps({"tiers": {"standard": {"budget": {"maxLanes": 4}}}}))
            frame = Path(tmp) / "frame.json"
            frame.write_text(json.dumps({"gates": GATES_OFF, "lanePlan": {"tier": "standard", "add": [], "drop": [], "reasons": {}}}))
            rc, out = call("plan", "--run", str(run), "--root", str(root), "--input", str(frame))
            self.assertEqual(rc, 0, out)
            self.assertEqual(len(out["files"]), 2)
            self.assertEqual(out["budget"]["maxLanes"], 4)
            self.assertTrue(out["overBudget"])
            self.assertEqual(run_dir.falsifier_severities(run), ("CRITICAL",))
            self.assertEqual(run_dir.load_manifest(run)["tiers"]["standard"]["budget"]["maxLanes"], 4)
            frame.write_text(json.dumps({"gates": GATES_OFF, "lanePlan": {"tier": "bogus"}}))
            self.assertEqual(call("plan", "--run", str(run), "--root", str(root), "--input", str(frame))[0], 1)

    def test_scoped_findings_follow_the_tier(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = make_run(tmp)
            (run / "envelopes" / "edge-case-miner.json").write_text(json.dumps({"lane": "edge-case-miner", "answered_questions": [],
                "findings": [{"id": "EC-1", "severity": "CRITICAL", "title": "a"}, {"id": "EC-2", "severity": "MAJOR", "title": "b"}]}))
            ids = lambda scoped: [f["id"] for f in run_dir.all_critical_major(run, ["edge-case-miner"], scoped=scoped)]
            self.assertEqual(ids(True), ["EC-1", "EC-2"], "no plan.json: full scope")
            (run / "plan.json").write_text(json.dumps({"budget": {"falsifier": "critical"}}))
            self.assertEqual((ids(True), ids(False)), (["EC-1"], ["EC-1", "EC-2"]))
            (run / "plan.json").write_text(json.dumps({"budget": {"falsifier": "off"}}))
            self.assertEqual(ids(True), [])
            rc, out = call("merge-check", "--run", str(run), "--lanes", "edge-case-miner")
            self.assertEqual((rc, out["totalIds"], out["clusters"]), (0, 0, 0))


class TemplateTests(unittest.TestCase):
    def test_every_template_fills_to_zero_placeholders(self):
        for e in run_dir.all_entries(MANIFEST):
            if not e.get("prompt"):
                continue
            body = run_dir.extract_body((PROMPTS / e["prompt"]).read_text())
            self.assertTrue(body.strip(), e["label"])
            left = run_dir.find_placeholders(run_dir.fill(body, ALL_VALUES))
            self.assertEqual(left, [], f"{e['label']}: unknown placeholder survives filling")

    def test_unfilled_placeholders_are_detected(self):
        self.assertEqual(run_dir.find_placeholders("a {{SPEC_PATH}} b"), ["{{SPEC_PATH}}"])
        self.assertTrue(run_dir.find_placeholders("see <FOCUS_TEXT_FROM_COORDINATOR_IF_ANY> here"))
        self.assertTrue(run_dir.find_placeholders("at <RELATIVE_SPEC_PATH>"))
        self.assertEqual(run_dir.find_placeholders("after <PR N> lands, `{x}` ok"), [])

    def test_codex_templates_have_no_heredoc_pattern(self):
        for e in MANIFEST["lanes"]:
            if e["kind"] == "codex":
                text = (PROMPTS / e["prompt"]).read_text()
                self.assertNotIn("<<'PROMPT'", text)
                self.assertNotIn("cat >", text)


class AssignmentTests(unittest.TestCase):
    def lanes(self, *labels):
        return [run_dir.entry_by_label(MANIFEST, l) for l in labels]

    def test_tag_match_and_fallback(self):
        qs = [{"id": "Q1", "lane": "edge-case", "text": "a"}, {"id": "Q2", "lane": "weird", "text": "b"},
              {"id": "Q3", "lane": "codex-adversarial", "text": "c"}]
        out = run_dir.assign_questions(qs, self.lanes("edge-case-miner", "codex-adversarial", "codex-frontier"))
        self.assertEqual([q["id"] for q in out["edge-case-miner"]], ["Q1"])
        self.assertEqual([q["id"] for q in out["codex-frontier"]], ["Q2", "Q3"])
        self.assertEqual([q["id"] for q in out["codex-adversarial"]], ["Q3"])

    def test_skipped_lane_questions_fall_back_to_frontier(self):
        qs = [{"id": "Q1", "lane": "security", "text": "a"}]
        out = run_dir.assign_questions(qs, self.lanes("codebase-verifier", "codex-frontier"))
        self.assertEqual([q["id"] for q in out["codex-frontier"]], ["Q1"])

    def test_no_owner_is_an_error(self):
        with self.assertRaises(run_dir.StageError):
            run_dir.assign_questions([{"id": "Q1", "lane": "security", "text": "a"}], self.lanes("codebase-verifier"))


class LanesCommandTests(unittest.TestCase):
    FULL = ("completeness-reviewer,codebase-verifier,architecture-auditor,adr-auditor,legal-auditor,provider-fit-auditor,edge-case-miner,"
            "security-miner,observability-auditor,spec-drift-scout,codex-standard,codex-adversarial,codex-research,codex-frontier")

    def test_full_set_materializes_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = make_run(tmp)
            rc, out = call("lanes", "--run", str(run), "--spec", "docs/specs/x.md", "--lanes", self.FULL)
            self.assertEqual(rc, 0, out)
            self.assertEqual(sorted(out["codex"]), ["architecture-auditor", "codebase-verifier", "codex-adversarial", "codex-frontier", "codex-research", "codex-standard"])
            for label in out["claude"]:
                text = (run / "prompts" / f"{label}.md").read_text()
                self.assertTrue(text.startswith(f"ROLE: {label}\n"), label)
                self.assertEqual(run_dir.find_placeholders(text), [], label)
                self.assertIn("Run contract", text)
                self.assertNotIn("LEARNINGS", text, f"{label}: review lanes must not be handed LEARNINGS")
            for label in out["codex"]:
                text = (run / "codex" / f"{label}.prompt.md").read_text()
                self.assertTrue(text.startswith(f"ROLE: {label}\n"))
                self.assertEqual(run_dir.find_placeholders(text), [])
            tsv = (run / "codex" / "plan.tsv").read_text().splitlines()
            self.assertEqual(len(tsv), 6)
            for moved in ("codebase-verifier", "architecture-auditor"):
                t = (run / "codex" / f"{moved}.prompt.md").read_text()
                self.assertIn("You run as a Codex lane", t, moved)
                self.assertIn("FINAL MESSAGE is the complete deliverable", t, moved)
            assigned = {q for qs in out["assignments"].values() for q in qs}
            self.assertEqual(assigned, {"Q1", "Q2", "Q3", "Q4"}, "every question is owned by some lane")
            self.assertIn("Q4", out["assignments"]["codex-frontier"])
            self.assertIn("Q1 [edge-case]: what about max+1?", (run / "prompts" / "edge-case-miner.md").read_text())
            adv = (run / "codex" / "codex-adversarial.prompt.md").read_text()
            self.assertIn("Q3: race on retry?", adv)

    def test_missing_dossier_fails_the_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = make_run(tmp)
            (run / "dossier.md").write_text("tiny")
            rc, out = call("lanes", "--run", str(run), "--spec", "s.md", "--lanes", "codebase-verifier,codex-frontier")
            self.assertEqual(rc, 1)
            self.assertIn("dossier.md", out["errors"][0])

    def test_substitute_inherits_assignment(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = make_run(tmp)
            call("lanes", "--run", str(run), "--spec", "s.md", "--lanes", "codebase-verifier,codex-adversarial,codex-frontier")
            rc, out = call("lanes", "--run", str(run), "--spec", "s.md", "--lanes", "critic-frontier")
            self.assertEqual(rc, 0, out)
            self.assertEqual(out["assignments"]["critic-frontier"], json.loads((run / "assignments.json").read_text())["codex-frontier"])


def envelope(run, label, findings, answered):
    (Path(run) / "envelopes" / f"{label}.json").write_text(json.dumps(
        {"lane": label, "verdict": "", "answered_questions": answered,
         "findings": [{"id": i, "severity": s, "title": "t " + i} for i, s in findings]}))


class EnvelopeAndReportTests(unittest.TestCase):
    def test_coverage_gap_fails_for_claude_but_only_warns_for_codex(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = make_run(tmp)
            call("lanes", "--run", str(run), "--spec", "s.md", "--lanes", "edge-case-miner,codex-adversarial,codex-frontier")
            envelope(run, "edge-case-miner", [("EC-1", "CRITICAL")], [])
            envelope(run, "codex-adversarial", [], [])
            rc, out = call("check-envelopes", "--run", str(run), "--lanes", "edge-case-miner,codex-adversarial", "--codex", "codex-adversarial")
            self.assertEqual(rc, 1)
            self.assertEqual(out["unanswered"], {"edge-case-miner": ["Q1"]})
            self.assertEqual(out["codexUnanswered"], {"codex-adversarial": ["Q3"]})

    def test_duplicate_ids_and_bad_severity_are_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = make_run(tmp)
            envelope(run, "edge-case-miner", [("X-1", "MAJOR")], ["Q1"])
            envelope(run, "security-miner", [("X-1", "MAJOR")], ["Q2"])
            envelope(run, "codebase-verifier", [("CB-1", "HIGH")], [])
            rc, out = call("check-envelopes", "--run", str(run), "--lanes", "edge-case-miner,security-miner,codebase-verifier", "--codex", "")
            self.assertEqual(rc, 1)
            self.assertEqual(len(out["invalid"]), 2)

    def _merge(self, run, clusters, lanes):
        (run / "merged.raw.json").write_text(json.dumps(clusters))
        return call("merge-check", "--run", str(run), "--lanes", lanes)

    def test_merge_check_lists_ids_when_merger_has_not_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = make_run(tmp)
            envelope(run, "edge-case-miner", [("EC-1", "CRITICAL"), ("EC-2", "MINOR")], ["Q1"])
            rc, out = call("merge-check", "--run", str(run), "--lanes", "edge-case-miner")
            self.assertEqual(rc, 1)
            self.assertNotIn("ids", out)
            lines = open(out["indexPath"]).read().splitlines()
            self.assertEqual(len(lines), 1)
            self.assertIn("EC-1 [edge-case-miner, CRITICAL]", lines[0])

    def test_merge_check_rejects_gaps_and_double_membership(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = make_run(tmp)
            envelope(run, "edge-case-miner", [("EC-1", "CRITICAL"), ("EC-2", "MAJOR")], ["Q1"])
            envelope(run, "codex-frontier", [("AST-1", "MAJOR")], [])
            rc, out = self._merge(run, [{"members": ["EC-1", "AST-1"]}, {"members": ["AST-1"]}], "edge-case-miner,codex-frontier")
            self.assertEqual(rc, 1)
            text = " ".join(out["errors"])
            self.assertIn("AST-1 is already in F-1", text)
            self.assertIn("EC-2", text)
            self.assertFalse((run / "merged.json").exists())

    def test_falsify_plan_batches_units_and_verdicts_fan_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = make_run(tmp)
            envelope(run, "edge-case-miner", [("EC-1", "MAJOR"), ("EC-2", "MINOR")], ["Q1"])
            envelope(run, "codex-research", [("ELV-1", "ELEVATE")], [])
            envelope(run, "codex-frontier", [("AST-1", "CRITICAL"), ("AST-2", "MAJOR")], [])
            lanes = "edge-case-miner,codex-research,codex-frontier"
            rc, out = self._merge(run, [{"title": "same defect", "seam": "schema-apply.ts", "members": ["EC-1", "AST-1"]}, {"members": ["AST-2"]}], lanes)
            self.assertEqual(rc, 0, out)
            self.assertEqual((out["totalIds"], out["clusters"]), (3, 2))
            units = json.loads((run / "merged.json").read_text())["units"]
            self.assertEqual(units[0]["severity"], "CRITICAL")
            rc, out = call("falsify-plan", "--run", str(run), "--spec", "s.md", "--lanes", lanes)
            self.assertEqual(rc, 0, out)
            self.assertEqual((out["totalUnits"], out["totalIds"]), (2, 3))
            self.assertEqual(sorted(i for b in out["plan"] for i in b["ids"]), ["F-1", "F-2"])
            texts = [Path(b["prompt"]).read_text() for b in out["plan"]]
            for text in texts:
                self.assertTrue(text.startswith("ROLE: finding-falsifier\n"))
                self.assertEqual(run_dir.find_placeholders(text), [])
            self.assertTrue(any("EC-1 in" in x and "AST-1 in" in x for x in texts))
            (run / "falsifiers").mkdir(exist_ok=True)
            (run / "falsifiers" / "F-1.json").write_text(json.dumps({"id": "F-1", "verdict": "REFUTED", "evidence": "x"}))
            rc, out = call("summary", "--run", str(run), "--lanes", lanes)
            self.assertEqual(out["missingVerdicts"], ["F-2"])
            self.assertEqual((out["falsifierDispatched"], out["refuted"]), (2, 2))
            (run / "falsifiers" / "F-2.json").write_text(json.dumps({"id": "F-2", "verdict": "SURVIVES", "evidence": "x"}))
            (run / "falsifiers" / "AST-1.json").write_text(json.dumps({"id": "AST-1", "verdict": "SURVIVES", "evidence": "member differs"}))
            rc, out = call("summary", "--run", str(run), "--lanes", lanes)
            self.assertEqual((out["missingVerdicts"], out["refuted"]), ([], 1), "member override beats its unit verdict")

    def test_ledger_row_goes_to_the_caller_path_only_and_is_idempotent(self):
        lanes = "edge-case-miner"
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "run").mkdir()
            run = make_run(Path(tmp) / "run")
            envelope(run, lanes, [("F-1", "CRITICAL"), ("F-2", "MAJOR"), ("F-3", "MAJOR"), ("F-4", "MAJOR")], [])
            call("merge-check", "--run", str(run), "--lanes", lanes)
            for fid, verdict in (("F-1", "REFUTED"), ("F-2", "SURVIVES"), ("F-3", "SURVIVES-BUT-FIX-REJECTED"),
                                 ("F-4", "NEEDS-LIVE-EVIDENCE")):
                (run / "falsifiers" / f"{fid}.json").write_text(json.dumps({"id": fid, "verdict": verdict, "evidence": "x"}))
            rc, out = call("ledger", "--run", str(run), "--lanes", lanes)
            self.assertEqual(rc, 1, "no path and no env var must refuse, never guess a location")
            self.assertIn("no ledger path", out["errors"][0])
            ledger = Path(tmp) / "nested" / "ledger.jsonl"
            rc, out = call("ledger", "--run", str(run), "--lanes", lanes, "--spec", "s.md", "--path", str(ledger))
            self.assertEqual(rc, 0, out)
            self.assertEqual({k: out["row"][k] for k in ("spec", "dispatched", "refuted", "survives", "fix_rejected", "needs_live")},
                             {"spec": "s.md", "dispatched": 4, "refuted": 1, "survives": 1, "fix_rejected": 1, "needs_live": 1})
            call("ledger", "--run", str(run), "--lanes", lanes, "--spec", "s.md", "--path", str(ledger))
            rows = [json.loads(l) for l in ledger.read_text().splitlines()]
            self.assertEqual(len(rows), 1, "a retried stage must not double-count a run")
            self.assertEqual(set(rows[0]), {"date", "spec", "dispatched", "refuted", "survives", "fix_rejected", "needs_live"})

    def test_ledger_path_can_come_from_the_environment(self):
        lanes = "edge-case-miner"
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "run").mkdir()
            run = make_run(Path(tmp) / "run")
            envelope(run, lanes, [("F-1", "CRITICAL")], [])
            call("merge-check", "--run", str(run), "--lanes", lanes)
            ledger = Path(tmp) / "env.jsonl"
            with mock.patch.dict("os.environ", {"SPEC_REVIEW_LEDGER": str(ledger)}):
                rc, out = call("ledger", "--run", str(run), "--lanes", lanes)
            self.assertEqual(rc, 0, out)
            self.assertTrue(ledger.is_file())

    def test_falsify_plan_requires_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = make_run(tmp)
            envelope(run, "edge-case-miner", [("EC-1", "CRITICAL")], [])
            rc, out = call("falsify-plan", "--run", str(run), "--spec", "s.md", "--lanes", "edge-case-miner")
            self.assertEqual(rc, 1)
            self.assertIn("merge-check", out["errors"][0])

    def test_dry_plan_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = make_run(tmp)
            envelope(run, "edge-case-miner", [("EC-1", "CRITICAL")], [])
            self._merge(run, [{"members": ["EC-1"]}], "edge-case-miner")
            rc, out = call("falsify-plan", "--run", str(run), "--spec", "s.md", "--lanes", "edge-case-miner", "--dry")
            self.assertEqual(rc, 0)
            self.assertEqual(list((run / "prompts").glob("falsifier-*")), [])


class BatchingTests(unittest.TestCase):
    def U(self, i, seam=""):
        return {"id": i, "severity": "MAJOR", "title": "t", "seam": seam, "members": [i], "cites": []}

    def test_batches_capped_cover_each_unit_once(self):
        units = [self.U(f"F-{i}", f"seam{i % 9}") for i in range(40)]
        batches = run_dir.plan_batches(units, 6)
        self.assertLessEqual(len(batches), 6)
        flat = [i for b in batches for i in b["ids"]]
        self.assertEqual(sorted(flat), sorted(u["id"] for u in units))
        self.assertEqual(len(flat), len(set(flat)))

    def test_same_seam_stays_together_while_it_fits(self):
        units = [self.U("F-1", "schema.json"), self.U("F-2", "schema.json"), self.U("F-3", "other")]
        batches = run_dir.plan_batches(units, 6)
        self.assertIn(["F-1", "F-2"], [sorted(b["ids"])[:2] for b in batches if "F-1" in b["ids"]])

    def test_max_batches_must_be_positive(self):
        with self.assertRaises(run_dir.StageError):
            run_dir.plan_batches([self.U("F-1")], 0)


    def _report(self, extra=""):
        return ("## Spec Review - Final Report\n\n### Falsifier wave: 2 dispatched over 2 CRITICAL/MAJOR — 1 REFUTED, 1 SURVIVES.\n\n"
                "### Lane manifest\n| edge-case-miner | run | x |\n| security-miner | SKIPPED (gate: no authz surface) | - |\n| codex-frontier | run | x |\n\n"
                "### Edge Cases\n| EC-ID | E | B | Spec Coverage | R | Severity |\n|---|---|---|---|---|---|\n"
                "| EC-1 | w | m | MISSING | fix | CRITICAL | SURVIVES\n\n"
                "### Consensus Issues\n1. [F-1] [MAJOR] frontier risk (AST-1) REFUTED by falsifier\n" + extra + "x" * 400)

    def test_check_report_passes_and_publishes_then_catches_missing_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = make_run(tmp)
            envelope(run, "edge-case-miner", [("EC-1", "CRITICAL")], ["Q1"])
            envelope(run, "codex-frontier", [("AST-1", "MAJOR")], [])
            (run / "falsifiers" / "EC-1.json").write_text(json.dumps({"id": "EC-1", "verdict": "SURVIVES", "evidence": "e"}))
            (run / "falsifiers" / "AST-1.json").write_text(json.dumps({"id": "AST-1", "verdict": "REFUTED", "evidence": "e"}))
            (run / "report.md").write_text(self._report())
            pub = Path(tmp) / "out.review.md"
            flags = ["--run", str(run), "--lanes", "edge-case-miner,codex-frontier", "--manifest", "edge-case-miner,security-miner,codex-frontier",
                     "--skipped", "security-miner", "--publish", str(pub)]
            rc, out = call("check-report", *flags)
            self.assertEqual(rc, 0, out)
            self.assertTrue(pub.is_file())
            (run / "report.md").write_text(self._report().replace("AST-1", "AST-9"))
            rc, out = call("check-report", *flags)
            self.assertEqual(rc, 1)
            self.assertTrue(any("AST-1" in e for e in out["errors"]))

    def test_check_report_requires_every_system1_id_and_handoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = make_run(tmp)
            envelope(run, "codex-frontier", [], [])
            env = {"lane": "system1-elevation", "verdict": "", "answered_questions": [],
                   "findings": [{"id": "S1-1", "severity": "ELEVATE", "title": "t"}],
                   "research_handoffs": [{"id": "S1-H1", "question": "q"}]}
            (run / "envelopes" / "system1-elevation.json").write_text(json.dumps(env))
            body = ("## Spec Review - Final Report\n\n### Falsifier wave: 0 dispatched over 0 CRITICAL/MAJOR — 0 REFUTED, 0 SURVIVES.\n\n"
                    "### Lane manifest\n| system1-elevation | run | x |\n| codex-frontier | run | x |\n\n"
                    "### System 1 Intelligence\n- [S1-1] [ELEVATE] x\n- [S1-H1] q\n" + "x" * 400)
            flags = ["--run", str(run), "--lanes", "system1-elevation,codex-frontier", "--manifest", "system1-elevation,codex-frontier", "--skipped", ""]
            (run / "report.md").write_text(body)
            rc, out = call("check-report", *flags)
            self.assertEqual(rc, 0, out)
            (run / "report.md").write_text(body.replace("[S1-H1]", "[hand-off]"))
            rc, out = call("check-report", *flags)
            self.assertEqual(rc, 1)
            self.assertTrue(any("S1-H1" in e for e in out["errors"]), out)

    def test_run_contract_carries_lane_severities_and_handoffs(self):
        e = run_dir.entry_by_label(MANIFEST, "system1-elevation")
        text = run_dir.run_contract("/r", e, [])
        self.assertIn('"severity": "CRITICAL|MAJOR|MINOR|ELEVATE"', text)
        self.assertIn('"research_handoffs": [{"id": "S1-H1"', text)
        plain = run_dir.run_contract("/r", run_dir.entry_by_label(MANIFEST, "edge-case-miner"), [])
        self.assertIn('"severity": "CRITICAL|MAJOR|MINOR"', plain)
        self.assertNotIn("research_handoffs", plain)

    def test_check_report_rejects_unlisted_lane_and_placeholder(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = make_run(tmp)
            envelope(run, "codex-frontier", [], [])
            (run / "report.md").write_text("### Falsifier wave: 0 dispatched over 0 CRITICAL/MAJOR — 0 REFUTED, 0 SURVIVES.\n{{LEFTOVER}} codex-frontier\n" + "x" * 500)
            rc, out = call("check-report", "--run", str(run), "--lanes", "codex-frontier", "--manifest", "codex-frontier,edge-case-miner", "--skipped", "")
            self.assertEqual(rc, 1)
            joined = " ".join(out["errors"])
            self.assertIn("edge-case-miner is not listed", joined)
            self.assertIn("unfilled placeholders", joined)

    def test_missing_astra_envelope_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = make_run(tmp)
            (run / "report.md").write_text("### Falsifier wave: 0 dispatched over 0 CRITICAL/MAJOR — 0 REFUTED, 0 SURVIVES.\n" + "x" * 500)
            rc, out = call("check-report", "--run", str(run), "--lanes", "", "--manifest", "", "--skipped", "")
            self.assertTrue(any("Astra" in e for e in out["errors"]))

    def test_summary_hard_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = make_run(tmp)
            envelope(run, "adr-auditor", [("ADR-1", "CRITICAL")], [])
            data = json.loads((run / "envelopes" / "adr-auditor.json").read_text())
            data.update({"founder_approval_needed": True, "founder_approval_marker_present": False})
            (run / "envelopes" / "adr-auditor.json").write_text(json.dumps(data))
            rc, out = call("summary", "--run", str(run), "--lanes", "adr-auditor")
            self.assertTrue(out["hardStop"])
            self.assertEqual(out["hardStopReasons"], ["adr"])
            self.assertEqual(out["raw"]["CRITICAL"], 1)
            self.assertEqual(out["missingVerdicts"], ["ADR-1"])

    def legal_summary(self, extra, findings=(), planned="legal-auditor", write=True):
        with tempfile.TemporaryDirectory() as tmp:
            run = make_run(tmp)
            if write:
                envelope(run, "legal-auditor", list(findings), [])
                path = run / "envelopes" / "legal-auditor.json"
                path.write_text(json.dumps({**json.loads(path.read_text()), **extra}))
            lanes = "legal-auditor" if write else ""
            return call("summary", "--run", str(run), "--lanes", lanes, "--planned", planned)[1]

    def test_legal_breach_without_marker_hard_stops(self):
        out = self.legal_summary({"register_found": True, "sources_read": ["docs/terms.md"], "legal_commitment_breach": True,
                                  "founder_approval_marker_present": False}, [("LEG-1", "CRITICAL")])
        self.assertEqual((out["hardStop"], out["hardStopReasons"]), (True, ["legal"]))

    def test_legal_breach_with_marker_does_not_stop(self):
        out = self.legal_summary({"register_found": True, "sources_read": ["docs/terms.md"], "legal_commitment_breach": True,
                                  "founder_approval_marker_present": True}, [("LEG-1", "CRITICAL")])
        self.assertEqual((out["hardStop"], out["hardStopReasons"]), (False, []))

    def test_legal_non_breach_finding_does_not_stop(self):
        out = self.legal_summary({"register_found": True, "sources_read": ["docs/privacy.md"], "legal_commitment_breach": False},
                                 [("LEG-1", "MAJOR")])
        self.assertFalse(out["hardStop"])
        self.assertEqual(out["raw"]["MAJOR"], 1)

    def test_planned_legal_lane_with_no_envelope_is_a_stop_reason(self):
        out = self.legal_summary({}, write=False)
        self.assertEqual((out["hardStop"], out["hardStopReasons"]), (True, ["legal-auditor-envelope-missing"]))

    def test_clean_legal_verdict_that_read_nothing_is_rejected(self):
        out = self.legal_summary({"register_found": True, "sources_read": []})
        self.assertEqual(out["hardStopReasons"], ["legal-auditor-read-no-sources"])

    def test_no_register_receipt_is_not_a_stop(self):
        out = self.legal_summary({"register_found": False, "sources_read": []}, [("LEG-1", "CAUTION")])
        self.assertEqual((out["hardStop"], out["hardStopReasons"]), (False, []))

    def test_unplanned_gate_lanes_are_not_demanded(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = make_run(tmp)
            envelope(run, "edge-case-miner", [], [])
            out = call("summary", "--run", str(run), "--lanes", "edge-case-miner", "--planned", "edge-case-miner")[1]
            self.assertEqual((out["hardStop"], out["hardStopReasons"]), (False, []))

    def test_adr_and_legal_stop_together(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = make_run(tmp)
            for label, extra in (("adr-auditor", {"founder_approval_needed": True}),
                                 ("legal-auditor", {"register_found": True, "sources_read": ["a.md"], "legal_commitment_breach": True})):
                envelope(run, label, [], [])
                path = run / "envelopes" / f"{label}.json"
                path.write_text(json.dumps({**json.loads(path.read_text()), **extra}))
            out = call("summary", "--run", str(run), "--lanes", "adr-auditor,legal-auditor", "--planned", "adr-auditor,legal-auditor")[1]
            self.assertEqual(out["hardStopReasons"], ["adr", "legal"])


class DriftBriefTests(unittest.TestCase):
    def test_investigator_briefs_use_pointers_and_cap_at_five(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = make_run(tmp)
            scout = {"lane": "spec-drift-scout", "answered_questions": [], "findings": [],
                     "drift_investigations": [{"drift_id": f"DRIFT-{i}", "narrow_question": f"does {i} collide?"} for i in range(1, 8)]}
            (run / "envelopes" / "spec-drift-scout.json").write_text(json.dumps(scout))
            rc, out = call("drift-briefs", "--run", str(run), "--spec", "s.md")
            self.assertEqual(rc, 0, out)
            self.assertEqual(len(out["briefs"]), 5)
            self.assertEqual(out["dropped"], 2)
            text = (run / "prompts" / "spec-drift-investigator-DRIFT-1.md").read_text()
            self.assertTrue(text.startswith("ROLE: spec-drift-investigator\n"))
            self.assertEqual(run_dir.find_placeholders(text), [])
            self.assertIn("DI-1", text)


if __name__ == "__main__":
    unittest.main()
