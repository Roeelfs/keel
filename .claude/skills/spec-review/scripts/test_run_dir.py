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

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_dir  # noqa: E402

PROMPTS = HERE.parent / "prompts"
MANIFEST = run_dir.load_manifest()
ALL_VALUES = {k: "X" for k in (
    "SPEC_PATH", "PROJECT_ROOT", "DOSSIER_CONTENT", "CONTEXT_BLOCK", "GOAL", "TRIGGER", "TARGET_OUTCOME",
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
    FULL = ("completeness-reviewer,codebase-verifier,architecture-auditor,adr-auditor,provider-fit-auditor,edge-case-miner,"
            "security-miner,observability-auditor,spec-drift-scout,codex-standard,codex-adversarial,codex-research,codex-frontier")

    def test_full_set_materializes_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = make_run(tmp)
            rc, out = call("lanes", "--run", str(run), "--spec", "docs/specs/x.md", "--lanes", self.FULL)
            self.assertEqual(rc, 0, out)
            self.assertEqual(sorted(out["codex"]), ["codex-adversarial", "codex-frontier", "codex-research", "codex-standard"])
            for label in out["claude"]:
                text = (run / "prompts" / f"{label}.md").read_text()
                self.assertTrue(text.startswith(f"ROLE: {label}\n"), label)
                self.assertEqual(run_dir.find_placeholders(text), [], label)
                self.assertIn("Run contract", text)
            for label in out["codex"]:
                text = (run / "codex" / f"{label}.prompt.md").read_text()
                self.assertTrue(text.startswith(f"ROLE: {label}\n"))
                self.assertEqual(run_dir.find_placeholders(text), [])
            tsv = (run / "codex" / "plan.tsv").read_text().splitlines()
            self.assertEqual(len(tsv), 4)
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

    def test_falsify_plan_covers_every_critical_major_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = make_run(tmp)
            envelope(run, "edge-case-miner", [("EC-1", "CRITICAL"), ("EC-2", "MINOR")], ["Q1"])
            envelope(run, "codex-research", [("ELV-1", "ELEVATE")], [])
            envelope(run, "codex-frontier", [("AST-1", "MAJOR")], [])
            rc, out = call("falsify-plan", "--run", str(run), "--spec", "s.md", "--lanes", "edge-case-miner,codex-research,codex-frontier")
            self.assertEqual(rc, 0, out)
            self.assertEqual(sorted(i for b in out["plan"] for i in b["ids"]), ["AST-1", "EC-1"])
            texts = [Path(b["prompt"]).read_text() for b in out["plan"]]
            for text in texts:
                self.assertTrue(text.startswith("ROLE: finding-falsifier\n"))
                self.assertEqual(run_dir.find_placeholders(text), [])
            self.assertTrue(any("EC-1" in x for x in texts))

    def test_dry_plan_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = make_run(tmp)
            envelope(run, "edge-case-miner", [("EC-1", "CRITICAL")], [])
            rc, out = call("falsify-plan", "--run", str(run), "--spec", "s.md", "--lanes", "edge-case-miner", "--dry")
            self.assertEqual(rc, 0)
            self.assertEqual(list((run / "prompts").glob("falsifier-*")), [])


class BatchingTests(unittest.TestCase):
    def F(self, i, title, lane="x"):
        return {"id": i, "lane": lane, "severity": "MAJOR", "title": title}

    def test_near_duplicates_cluster_across_lanes_and_keep_every_id(self):
        fs = [self.F("A-1", "Install write-back is a second writer of schema.json under ADR-0088 D2", "arch"),
              self.F("B-1", "Install write-back makes a second writer of schema.json straying from ADR-0088", "adr"),
              self.F("C-1", "Retry of the webhook dedup key double-writes the ledger row", "sec")]
        clusters = run_dir.cluster_findings(fs)
        sets = sorted(sorted(c["ids"]) for c in clusters)
        self.assertEqual(sets, [["A-1", "B-1"], ["C-1"]])

    def test_batches_capped_cover_each_id_once(self):
        fs = [self.F(f"F-{i}", f"distinct topic number {i} alpha{i} beta{i} gamma{i}") for i in range(68)]
        batches = run_dir.plan_batches(fs, 6)
        self.assertLessEqual(len(batches), 6)
        flat = [i for b in batches for i in b["ids"]]
        self.assertEqual(sorted(flat), sorted(f["id"] for f in fs))
        self.assertEqual(len(flat), len(set(flat)))

    def test_small_set_and_duplicate_merge_in_one_batch(self):
        fs = [self.F("A-1", "second writer of schema.json under ADR-0088 install"), self.F("B-1", "install second writer of schema.json under ADR-0088")]
        batches = run_dir.plan_batches(fs, 6)
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0]["clusters"], [["A-1", "B-1"]])

    def test_max_batches_must_be_positive(self):
        with self.assertRaises(run_dir.StageError):
            run_dir.plan_batches([self.F("A-1", "t")], 0)


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
            self.assertEqual(out["raw"]["CRITICAL"], 1)
            self.assertEqual(out["missingVerdicts"], ["ADR-1"])


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
