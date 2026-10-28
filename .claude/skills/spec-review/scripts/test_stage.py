#!/usr/bin/env python3
"""Tests for stage.py: the Bash gates the main loop runs between Workflow stages (prepare, Codex
miner fallback, delta re-review, uncorroborated falsifier scope, spend ceiling, applied flag)."""
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
import lane_spend  # noqa: E402
import run_dir  # noqa: E402
import stage  # noqa: E402

MANIFEST = run_dir.load_manifest()
SPEC_V1 = "# Title\n\n## 1. Intro\nintro text\n\n## 2. Design\nthe design\n\n## 3. Rollout\nroll out\n"
SPEC_V2 = SPEC_V1.replace("the design", "the NEW design")
QUESTIONS = [{"id": f"Q{i}", "lane": tag, "text": f"question {i}?"} for i, tag in
             enumerate(["completeness", "codebase", "edge-case", "edge-case", "security", "observability", "architecture", "codex-adversarial"], 1)]
GOOD_DOSSIER = "# Dossier\n" + "ground-truth fact line\n" * 100


def call(mod, *argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mod.main(list(argv))
    return rc, json.loads(buf.getvalue().strip().splitlines()[-1])


def rcall(*argv):
    return call(run_dir, *argv)


def scall(*argv):
    return call(stage, *argv)


def gates(**fired):
    return {g: {"run": g in fired, "reason": (fired[g] + " (apps/x/y.ts:1)") if g in fired else "n/a"} for g in MANIFEST["gates"]}


def new_run(tmp, tier="standard", name="run", spec=SPEC_V1, fired=None, repo="cynap-monorepo-next", **scope):
    run, root = Path(tmp) / name, Path(tmp) / "root"
    root.mkdir(exist_ok=True)
    (root / "spec.md").write_text(spec)
    frame = Path(tmp) / f"{name}-frame.json"
    frame.write_text(json.dumps({"repo": repo, **({"floorDomain": "test floor"} if tier == "critical" else {}), **scope, "gates": gates(**(fired or {})), "lanePlan": {"tier": tier, "add": [], "drop": [], "reasons": {}}}))
    rc, out = rcall("plan", "--run", str(run), "--root", str(root), "--input", str(frame))
    assert rc == 0, out
    for d in ("inputs", "envelopes", "lanes", "codex", "prompts", "falsifiers"):
        (run / d).mkdir(parents=True, exist_ok=True)
    (run / "inputs" / "root.txt").write_text(str(root))
    (run / "inputs" / "context.md").write_text("Goal: g\nTrigger: t\nTarget outcome: o\nScope boundaries: s\n")
    return run, root


def prepare(run, root, *extra):
    return scall("prepare", "--run", str(run), "--spec", "spec.md", "--root", str(root), "--sid", "", *extra)


def write_codex_miner(run, dossier=GOOD_DOSSIER, questions=QUESTIONS, mark=run_dir.QUESTIONS_MARK, status="OK"):
    (run / "codex" / "context-dossier-miner.out.md").write_text(dossier + (f"\n{mark}\n```json\n{json.dumps(questions)}\n```\n" if mark else ""))
    (run / "codex" / "extract-status.tsv").write_text(f"context-dossier-miner\t{status}\t5000\t0\n")


def envelope(run, label, findings, answered=(), **extra):
    (Path(run) / "envelopes" / f"{label}.json").write_text(json.dumps(
        {"lane": label, "verdict": "", "answered_questions": list(answered),
         "findings": [{"id": i, "severity": s, "title": "t " + i} for i, s in findings], **extra}))


def full_prepare(run, root):
    prepare(run, root)
    write_codex_miner(run)
    rc, out = rcall("extract-finish", "--run", str(run))
    assert rc == 0 and out["fallback"] == [], out
    rc, out = scall("finish-prepare", "--run", str(run), "--spec", "spec.md")
    assert rc == 0, out
    return out


def answer_all(run, findings=None):
    """Write a claude-lane envelope answering every assigned question."""
    assign = json.loads((run / "assignments.json").read_text())
    st = stage.load_state(run)
    for label in st["claude"]:
        envelope(run, label, (findings or {}).get(label, []), assign.get(label, []))


def fake_workflow_dir(tmp, run, tokens):
    d = Path(tmp) / "wf"
    d.mkdir(exist_ok=True)
    rec = [{"type": "user", "message": {"role": "user", "content": f"ROLE: edge-case-miner\nbrief in {run}/prompts/x.md"}},
           {"type": "assistant", "message": {"id": "m1", "role": "assistant", "usage": {"cache_read_input_tokens": tokens}}}]
    (d / "agent-a.jsonl").write_text("\n".join(json.dumps(r) for r in rec))
    return d


class ExtractTests(unittest.TestCase):
    def test_prepare_writes_codex_miner_prompts_and_a_dossier_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, root = new_run(tmp)
            rc, out = prepare(run, root)
            self.assertEqual((rc, out["next"]), (0, "extract"), out)
            rows = (run / "codex" / "extract.tsv").read_text().splitlines()
            self.assertEqual([r.split("\t")[:2] for r in rows], [["context-dossier-miner", "verify"]])
            text = (run / "codex" / "context-dossier-miner.prompt.md").read_text()
            self.assertIn(run_dir.QUESTIONS_MARK, text)
            self.assertIn("No MCP tools exist for you", text)
            self.assertEqual(run_dir.find_placeholders(text), [])
            self.assertTrue((run / "prompts" / "context-dossier-miner.md").is_file(), "the Claude fallback brief stays")
            self.assertEqual((run / "inputs" / "spec.snapshot.md").read_text(), SPEC_V1)
            self.assertTrue(json.loads((run / "inputs" / "gates.json").read_text()), "gates taken from plan.json")

    def test_valid_codex_dossier_is_used_and_no_claude_miner_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, root = new_run(tmp)
            prepare(run, root)
            write_codex_miner(run)
            rc, out = rcall("extract-finish", "--run", str(run))
            self.assertEqual((out["codex"], out["fallback"]), (["context-dossier-miner"], []))
            self.assertEqual(len(json.loads((run / "questions.json").read_text())), 8)
            self.assertTrue((run / "dossier.md").read_text().startswith("# Dossier"))

    def test_dead_quota_or_invalid_codex_miner_falls_back_to_claude(self):
        for status, mark, dossier in (("DEAD", run_dir.QUESTIONS_MARK, GOOD_DOSSIER), ("QUOTA", run_dir.QUESTIONS_MARK, GOOD_DOSSIER),
                                      ("OK", "", GOOD_DOSSIER), ("OK", run_dir.QUESTIONS_MARK, "too short")):
            with self.subTest(status=status, mark=bool(mark), dossier=dossier[:5]):
                with tempfile.TemporaryDirectory() as tmp:
                    run, root = new_run(tmp)
                    prepare(run, root)
                    write_codex_miner(run, dossier=dossier, mark=mark, status=status)
                    rc, out = rcall("extract-finish", "--run", str(run))
                    self.assertEqual(out["fallback"], ["context-dossier-miner"], out)
                    self.assertFalse((run / "dossier.md").exists(), "nothing half-written")

    def test_bad_question_tags_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, root = new_run(tmp)
            prepare(run, root)
            write_codex_miner(run, questions=[{**q, "lane": "nonsense"} for q in QUESTIONS])
            self.assertEqual(rcall("extract-finish", "--run", str(run))[1]["fallback"], ["context-dossier-miner"])

    def test_decisions_json_is_parsed_from_free_text(self):
        obj = run_dir.last_json('Here you go:\n```json\n{"decisions": [{"text": "a", "evidence": "b"}], "gaps": []}\n```\n', dict)
        self.assertEqual(obj["decisions"][0]["text"], "a")
        self.assertIsNone(run_dir.last_json("no json here", dict))


class ReviewFlowTests(unittest.TestCase):
    def test_finish_prepare_post_review_and_coverage_repair(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, root = new_run(tmp)
            out = full_prepare(run, root)
            labels = {m["label"]: m for m in out["reviewLanes"]}
            self.assertIn("edge-case-miner", labels)
            self.assertEqual(labels["edge-case-miner"]["agentType"], "general-purpose")
            self.assertIn("codebase-verifier", out["codexLanes"])
            self.assertIn("bash ", out["codexCommand"])
            rc, out = scall("post-review", "--run", str(run), "--spec", "spec.md")
            self.assertFalse(out["ok"], "a lane with no envelope must fail the gate loudly")
            self.assertEqual(rc, 1)
            self.assertIn("edge-case-miner", out["failed"])
            self.assertEqual(out["relaunch"]["stage"], "review")
            self.assertIn("FAILED (no envelope written)", out["errors"][0])
            # edge-case-miner answers nothing -> a repair job is asked for
            assign = json.loads((run / "assignments.json").read_text())
            for label in stage.load_state(run)["claude"]:
                envelope(run, label, [], [] if label == "edge-case-miner" else assign[label])
            rc, out = scall("post-review", "--run", str(run), "--spec", "spec.md")
            self.assertTrue(out["needReview2"], out)
            self.assertEqual(out["repair"][0]["label"], "edge-case-miner")
            self.assertEqual(out["review2Args"]["stage"], "review2")
            envelope(run, "edge-case-miner", [], assign["edge-case-miner"])
            rc, out = scall("post-review", "--run", str(run), "--spec", "spec.md", "--final")
            self.assertEqual((rc, out["needReview2"], out["hardStop"]), (0, False, False), out)

    def test_final_pass_fails_when_coverage_is_still_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, root = new_run(tmp)
            full_prepare(run, root)
            for label in stage.load_state(run)["claude"]:
                envelope(run, label, [], [])
            rc, out = scall("post-review", "--run", str(run), "--spec", "spec.md", "--final")
            self.assertEqual(rc, 1)

    def test_spend_stop_drops_optional_second_wave_but_not_protected_repair(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, root = new_run(tmp, fired={"security": "adds authz"})
            full_prepare(run, root)
            assign = json.loads((run / "assignments.json").read_text())
            claude = stage.load_state(run)["claude"]
            self.assertIn("security-miner", claude)
            for label in claude:
                envelope(run, label, [], [] if label in ("security-miner", "completeness-reviewer") else assign[label])
            wf = fake_workflow_dir(tmp, run, 40_000_000)
            with mock.patch.object(lane_spend, "workflow_dirs", return_value=[wf]):
                rc, out = scall("post-review", "--run", str(run), "--spec", "spec.md")
            self.assertTrue(out["spend"]["stop"], out)
            repaired = [r["label"] for r in out["repair"]]
            self.assertIn("security-miner", repaired, "a fired-gate lane is never dropped")
            self.assertNotIn("completeness-reviewer", repaired)
            self.assertIn("completeness-reviewer", out["dropped"])
            self.assertTrue(any("SPEND STOP" in n for n in out["notes"]))
            sp = json.loads((run / "lane-spend.json").read_text())
            self.assertIn("completeness-reviewer", sp["stoppedLanes"])
            self.assertEqual(sp["tokenCeiling"], 22_000_000)


class QuotaStopTests(unittest.TestCase):
    LIMIT = "You've hit your session limit \u00b7 resets 1:30am (Asia/Jerusalem)"

    def limit_agent(self, tmp, run, ts="2026-10-25T23:15:43.774Z"):
        wf = Path(tmp) / "wf"
        wf.mkdir(exist_ok=True)
        recs = [{"type": "user", "message": {"role": "user", "content": f"ROLE: legal-auditor\nrun {run}"}},
                {"type": "assistant", "timestamp": ts, "error": "rate_limit", "message": {"id": "m", "model": "<synthetic>", "role": "assistant",
                 "usage": {"input_tokens": 0, "output_tokens": 0}, "content": [{"type": "text", "text": self.LIMIT}]}}]
        (wf / "agent-q.jsonl").write_text("\n".join(json.dumps(r) for r in recs))
        return wf

    def test_claude_limit_message_stops_every_gate_and_lists_not_run_lanes(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, root = new_run(tmp)
            full_prepare(run, root)
            wf = self.limit_agent(tmp, run)
            with mock.patch.object(lane_spend, "workflow_dirs", return_value=[wf]):
                rc, out = scall("post-review", "--run", str(run), "--spec", "spec.md")
            self.assertEqual(rc, 1)
            self.assertTrue(out["quotaStopped"])
            self.assertIn("QUOTA STOP", out["stop"])
            self.assertNotIn("relaunch", out)
            self.assertNotIn("review2Args", out)
            self.assertIn("legal-auditor", out["claude"])
            self.assertTrue(any(n.endswith("not run: quota") for n in out["notRun"]))
            st = stage.load_state(run)
            self.assertIn("message", st["quotaStopped"])
            self.assertTrue(json.loads((run / "lane-spend.json").read_text())["stoppedLanes"])
            # sticky: with no transcripts left, every later gate still refuses
            for gate in ("synth-prep", "falsify-prep", "falsify-check"):
                rc, out = scall(gate, "--run", str(run), "--spec", "spec.md")
                self.assertEqual((rc, out.get("quotaStopped")), (1, True), gate)

    def test_codex_blocked_on_quota_counts_and_quota_clear_resumes(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, root = new_run(tmp)
            full_prepare(run, root)
            (run / "codex" / "status.tsv").write_text("codex-adversarial\tQUOTA\t0\t1\n")
            rc, out = scall("synth-prep", "--run", str(run), "--spec", "spec.md")
            self.assertEqual((rc, out["quotaStopped"], out["codex"]), (1, True, ["codex-adversarial"]))
            rc, out = scall("quota-clear", "--run", str(run))
            self.assertEqual(rc, 0)
            self.assertNotIn("quotaStopped", stage.load_state(run))
            self.assertIsNone(stage.quota_gate(run, "x", wf_dirs=[]))

    def test_old_limit_message_before_the_clear_is_ignored_and_prose_never_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, root = new_run(tmp)
            full_prepare(run, root)
            wf = self.limit_agent(tmp, run, ts="2026-10-25T23:15:43.774Z")
            scall("quota-clear", "--run", str(run), "--after", "2026-10-26T00:00:00.000Z")
            self.assertIsNone(stage.quota_gate(run, "x", wf_dirs=[wf]))
            recs = [{"type": "user", "message": {"role": "user", "content": f"ROLE: x\n{run}"}},
                    {"type": "assistant", "timestamp": "2026-10-27T00:00:00Z", "message": {"role": "assistant", "model": "claude-opus-5-5",
                     "content": [{"type": "text", "text": "finding: the retry must handle 'you've hit your session limit' text"}]}}]
            (wf / "agent-q.jsonl").write_text("\n".join(json.dumps(r) for r in recs))
            self.assertIsNone(stage.quota_gate(run, "x", wf_dirs=[wf]))

    def test_report_args_carry_the_dead_agent_turn_caps(self):
        caps = run_dir.load_manifest()["agentTurnCaps"]
        self.assertEqual(caps, {"synthesis-writer": 40, "context-dossier-miner": 80})


class SpendTests(unittest.TestCase):
    def test_run_spend_counts_only_this_runs_agents_and_codex_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "run"
            (run / "codex").mkdir(parents=True)
            (run / "codex" / "codebase-verifier.out.md.log").write_text("noise\ntokens used\n1,234\n")
            wf = fake_workflow_dir(tmp, run, 1000)
            other = {"type": "user", "message": {"role": "user", "content": "ROLE: edge-case-miner\n/some/other/run"}}
            (wf / "agent-b.jsonl").write_text(json.dumps(other))
            sp = lane_spend.run_spend(str(run), "", 2000, wf_dirs=[wf])
            self.assertEqual((sp["claudeTotal"], sp["codexTotal"], sp["total"]), (1000, 1234, 2234))
            self.assertTrue(sp["warn"] and not sp["stop"])
            self.assertTrue(lane_spend.run_spend(str(run), "", 1000, wf_dirs=[wf])["stop"])

    def test_spend_command_writes_lane_spend_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, root = new_run(tmp, tier="light")
            wf = fake_workflow_dir(tmp, run, 500)
            rc, out = scall("spend", "--run", str(run), "--checkpoint", "t", "--wf-dirs", str(wf))
            self.assertEqual((rc, out["spend"]["total"], out["spend"]["ceiling"]), (0, 500, 2_000_000))
            self.assertEqual(json.loads((run / "lane-spend.json").read_text())["checkpoints"][0]["at"], "t")


class FalsifierScopeTests(unittest.TestCase):
    def merged_run(self, tmp, tier="critical"):
        run, root = new_run(tmp, tier=tier)
        envelope(run, "edge-case-miner", [("EC-1", "CRITICAL"), ("EC-2", "MAJOR"), ("EC-3", "MAJOR"), ("EC-4", "MINOR")])
        envelope(run, "security-miner", [("Sec-1", "MAJOR"), ("Sec-2", "MAJOR")])
        raw = [{"title": "crit", "seam": "a.ts", "members": ["EC-1"]},
               {"title": "corroborated major", "seam": "b.ts", "members": ["EC-2", "Sec-1"]},
               {"title": "single-lane major", "seam": "c.ts", "members": ["EC-3"]},
               {"title": "other single", "seam": "d.ts", "members": ["Sec-2"]}]
        (run / "merged.raw.json").write_text(json.dumps(raw))
        return run

    def test_uncorroborated_mode_falsifies_criticals_and_single_lane_majors_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = self.merged_run(tmp)
            self.assertEqual(run_dir.falsifier_mode(run), "uncorroborated")
            rc, out = rcall("merge-check", "--run", str(run), "--lanes", "edge-case-miner,security-miner")
            self.assertEqual((rc, out["totalIds"], out["clusters"]), (0, 5, 4), out)
            units = {u["id"]: u for u in json.loads((run / "merged.json").read_text())["units"]}
            self.assertEqual([units[k]["falsify"] for k in ("F-1", "F-2", "F-3", "F-4")], [True, False, True, True])
            self.assertEqual(units["F-2"]["lanes"], ["edge-case-miner", "security-miner"])
            self.assertTrue(all(u["applied"] is None for u in units.values()), "applied defaults to null")
            rc, fp = rcall("falsify-plan", "--run", str(run), "--spec", "s.md", "--lanes", "edge-case-miner,security-miner")
            self.assertEqual((fp["totalUnits"], fp["totalIds"]), (3, 3))
            self.assertEqual(sorted(i for b in fp["plan"] for i in b["ids"]), ["F-1", "F-3", "F-4"])
            ids = run_dir.falsified_ids(run, ["edge-case-miner", "security-miner"])
            self.assertEqual(sorted(ids), ["EC-1", "EC-3", "Sec-2"])

    def test_report_line_counts_dispatched_over_the_whole_universe(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = self.merged_run(tmp)
            lanes = "edge-case-miner,security-miner,codex-frontier"
            envelope(run, "codex-frontier", [])
            rcall("merge-check", "--run", str(run), "--lanes", lanes)
            (run / "falsifiers").mkdir(exist_ok=True)
            for uid, v in (("F-1", "SURVIVES"), ("F-3", "REFUTED"), ("F-4", "SURVIVES")):
                (run / "falsifiers" / f"{uid}.json").write_text(json.dumps({"id": uid, "verdict": v, "evidence": "e"}))
            (run / "report.md").write_text(
                "### Falsifier wave: 3 dispatched over 5 CRITICAL/MAJOR — 1 REFUTED, 2 SURVIVES.\n"
                "EC-1 SURVIVES EC-2 SURVIVES (corroborated) EC-3 REFUTED Sec-1 SURVIVES Sec-2 SURVIVES codex-frontier edge-case-miner security-miner\n" + "x" * 600)
            rc, out = rcall("check-report", "--run", str(run), "--lanes", lanes, "--manifest", lanes, "--skipped", "")
            self.assertFalse(any("falsifier line" in e for e in out["errors"]), out["errors"])

    def test_standard_stays_critical_only_and_hotfix_all(self):
        self.assertEqual({t: v["budget"]["falsifier"] for t, v in MANIFEST["tiers"].items()},
                         {"critical": "uncorroborated", "standard": "critical", "light": "off", "hotfix": "all"})

    def test_ceiling_stop_skips_major_falsification_but_never_critical(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = self.merged_run(tmp)
            lanes = ["edge-case-miner", "security-miner", "codex-frontier"]
            envelope(run, "codex-frontier", [])
            st = {"synth": {"ok": lanes}, "claude": [], "codex": [], "carried": []}
            stage.save_state(run, st)
            wf = fake_workflow_dir(tmp, run, 80_000_000)
            with mock.patch.object(lane_spend, "workflow_dirs", return_value=[wf]):
                rc, out = scall("falsify-prep", "--run", str(run), "--spec", "s.md")
            self.assertEqual(rc, 0, out)
            self.assertEqual(sorted(i for b in out["falsifyArgs"]["batches"] for i in [b["batch"]]), [1], out)
            plan = json.loads((run / "state.json").read_text())["falsifyBatches"]
            self.assertEqual(sorted(i for b in plan for i in b["ids"]), ["F-1"], "only the CRITICAL unit is falsified at the stop")
            units = {u["id"]: u for u in json.loads((run / "merged.json").read_text())["units"]}
            self.assertTrue(units["F-3"]["stopSkipped"] and units["F-4"]["stopSkipped"])
            self.assertTrue(any("not falsified at the ceiling stop" in n for n in out["notes"]))

    def test_invalid_merge_asks_for_a_repair_then_gives_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = self.merged_run(tmp)
            (run / "merged.raw.json").write_text(json.dumps([{"members": ["EC-1"]}]))
            stage.save_state(run, {"synth": {"ok": ["edge-case-miner", "security-miner"]}})
            rc, out = scall("falsify-prep", "--run", str(run), "--spec", "s.md")
            self.assertTrue(out["mergeNeeded"] and out["mergeArgs"]["repairErrors"], out)
            scall("falsify-prep", "--run", str(run), "--spec", "s.md")
            rc, out = scall("falsify-prep", "--run", str(run), "--spec", "s.md")
            self.assertEqual(rc, 1)


class AppliedTests(unittest.TestCase):
    def test_mark_applied_records_per_unit_and_refuses_unknown_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = FalsifierScopeTests().merged_run(tmp)
            rcall("merge-check", "--run", str(run), "--lanes", "edge-case-miner,security-miner")
            rc, out = scall("mark-applied", "--run", str(run), "--ids", "F-1,F-3")
            self.assertEqual((rc, out["applied"], out["unmarked"]), (0, 2, 2))
            rc, out = scall("mark-applied", "--run", str(run), "--ids", "F-4", "--status", "false")
            self.assertEqual((out["applied"], out["notApplied"], out["unmarked"]), (2, 1, 1))
            self.assertEqual(scall("mark-applied", "--run", str(run), "--ids", "F-99")[0], 1)


class DeltaReviewTests(unittest.TestCase):
    def prior_run(self, tmp):
        run, root = new_run(tmp, name="prior")
        full_prepare(run, root)
        assign = json.loads((run / "assignments.json").read_text())
        for label in stage.load_state(run)["claude"]:
            envelope(run, label, [], assign[label])
        envelope(run, "edge-case-miner", [("EC-1", "MAJOR"), ("EC-2", "MAJOR"), ("EC-3", "MINOR")], assign["edge-case-miner"])
        (run / "lanes" / "edge-case-miner.md").write_text("EC-1 concerns the Design section\n")
        (run / "lanes" / "completeness-reviewer.md").write_text("nothing relevant\n")
        (run / "merged.json").write_text(json.dumps({"units": [
            {"id": "F-1", "severity": "MAJOR", "title": "t", "seam": "", "members": ["EC-1"], "lanes": ["edge-case-miner"], "applied": True, "falsify": True},
            {"id": "F-2", "severity": "MAJOR", "title": "t", "seam": "", "members": ["EC-2"], "lanes": ["edge-case-miner"], "applied": None, "falsify": True}]}))
        (run / "falsifiers").mkdir(exist_ok=True)
        (run / "falsifiers" / "F-2.json").write_text(json.dumps({"id": "F-2", "verdict": "REFUTED", "evidence": "e"}))
        return run, root

    def test_changed_sections_are_found_by_heading_and_hash(self):
        changed, removed = stage.changed_sections(SPEC_V1, SPEC_V2)
        self.assertEqual([c["heading"] for c in changed], ["2. Design"])
        self.assertEqual(removed, [])
        self.assertEqual(stage.changed_sections(SPEC_V1, SPEC_V1)[0], [])
        added, gone = stage.changed_sections(SPEC_V1, SPEC_V1.replace("## 3. Rollout", "## 4. Other"))
        self.assertEqual(([c["heading"] for c in added], gone), (["4. Other"], ["3. Rollout"]))

    def test_rereview_reuses_dossier_reruns_floors_and_touched_lanes_and_carries_the_rest(self):
        with tempfile.TemporaryDirectory() as tmp:
            prior, root = self.prior_run(tmp)
            run, _ = new_run(tmp, name="again", spec=SPEC_V2)
            rc, out = prepare(run, root, "--prior", str(prior))
            self.assertEqual((rc, out["next"]), (0, "finish-prepare"), out)
            self.assertEqual((run / "dossier.md").read_text(), (prior / "dossier.md").read_text())
            d = out["delta"]
            self.assertIn("codebase-verifier", d["rerun"])
            self.assertIn("codex-frontier", d["rerun"])
            self.assertIn("edge-case-miner", d["rerun"], "it raised an applied finding")
            self.assertIn("completeness-reviewer", d["carried"])
            self.assertEqual(sorted(d["rerun"] + d["carried"]), sorted(e["label"] for e in stage.load_plan(run)["run"]))
            # a carried lane's envelope arrives without REFUTED / applied findings
            env = json.loads((run / "envelopes" / "completeness-reviewer.json").read_text())
            self.assertEqual(env["carried_from"], str(prior))
            out = scall("finish-prepare", "--run", str(run), "--spec", "spec.md")[1]
            self.assertNotIn("completeness-reviewer", out["claudeLanes"])
            self.assertIn("edge-case-miner", out["claudeLanes"])
            self.assertEqual(sorted(out["carried"]), sorted(d["carried"]))
            prompt = (run / "prompts" / "edge-case-miner.md").read_text()
            self.assertIn("Delta re-review", prompt)
            self.assertIn("2. Design", prompt)
            self.assertIn("EC-1", prompt)
            self.assertTrue((run / "inputs" / "spec.delta.diff").read_text().count("NEW design"))
            codex_plan = (run / "codex" / "plan.tsv").read_text()
            self.assertNotIn("codex-standard", codex_plan.replace("\n", " ") if "codex-standard" in d["carried"] else "")

    def test_carried_lane_findings_drop_refuted_and_applied(self):
        with tempfile.TemporaryDirectory() as tmp:
            prior, root = self.prior_run(tmp)
            plan = stage.load_plan(prior)
            run, _ = new_run(tmp, name="again2", spec=SPEC_V2)
            prepare(run, root, "--prior", str(prior))
            # edge-case-miner reruns; a lane that carried would lose EC-1 (applied) and EC-2 (refuted)
            env_prior = json.loads((prior / "envelopes" / "edge-case-miner.json").read_text())
            refuted = {"EC-2"}
            applied = {"EC-1"}
            kept = [f["id"] for f in env_prior["findings"] if f["id"] not in refuted | applied]
            self.assertEqual(kept, ["EC-3"])
            self.assertTrue(plan["run"])

    def test_small_edit_is_fix_verify_only_and_large_edit_is_delta(self):
        with tempfile.TemporaryDirectory() as tmp:
            prior, root = self.prior_run(tmp)
            plan = stage.load_plan(prior)
            fired = next(e for e in plan["run"] if e.get("gate")) if any(e.get("gate") for e in plan["run"]) else None
            run, _ = new_run(tmp, name="small", spec=SPEC_V2)
            out = prepare(run, root, "--prior", str(prior))[1]
            self.assertEqual(out["delta"]["mode"], "fix-verify")
            self.assertEqual(sorted(out["delta"]["rerun"]), ["codebase-verifier", "codex-frontier", "edge-case-miner"])
            self.assertIn("fix-verify", (run / "inputs" / "delta.md").read_text())
            big = SPEC_V1.replace("the design", "the design\n" + "\n".join(f"line {i}" for i in range(stage.FIX_VERIFY_MAX_LINES + 5)))
            run2, _ = new_run(tmp, name="big", spec=big)
            out = prepare(run2, root, "--prior", str(prior))[1]
            self.assertEqual(out["delta"]["mode"], "delta")
            self.assertIn("edge-case-miner", out["delta"]["rerun"])
            self.assertEqual(fired, None)

    def test_newly_fired_gate_forces_delta_and_reruns_that_lane(self):
        with tempfile.TemporaryDirectory() as tmp:
            prior, root = self.prior_run(tmp)
            run, _ = new_run(tmp, name="gate", spec=SPEC_V2, fired={"security": "adds authz"})
            out = prepare(run, root, "--prior", str(prior))[1]
            self.assertEqual(out["delta"]["mode"], "delta")
            self.assertIn("security-miner", out["delta"]["rerun"])

    def test_unseedable_prior_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, root = new_run(tmp)
            rc, out = prepare(run, root, "--prior", str(Path(tmp) / "nothing"))
            self.assertEqual(rc, 1)
            self.assertIn("cannot seed a delta re-review", out["errors"][0])


class SynthesizeTests(unittest.TestCase):
    def setup_review(self, tmp, dead=("codex-frontier",)):
        run, root = new_run(tmp)
        full_prepare(run, root)
        assign = json.loads((run / "assignments.json").read_text())
        for label in stage.load_state(run)["claude"]:
            envelope(run, label, [], assign[label])
        st = stage.load_state(run)
        rows = []
        for label in st["codex"]:
            rows.append(f"{label}\t{'DEAD' if label in dead else 'OK'}\t{0 if label in dead else 5000}\t0")
        (run / "codex" / "status.tsv").write_text("\n".join(rows) + "\n")
        return run, root

    def test_dead_astra_lane_gets_a_critic_and_pending_agents_block_the_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, root = self.setup_review(tmp)
            rc, out = scall("synth-prep", "--run", str(run), "--spec", "spec.md")
            self.assertTrue(out["pending"], out)
            self.assertEqual([c["label"] for c in out["criticsArgs"]["critics"]], ["critic-frontier"])
            self.assertEqual([e["label"] for e in out["criticsArgs"]["extractors"]], ["codebase-verifier"], "codex lane without an envelope falls back to a Claude extractor")
            self.assertTrue(any("timed-out/DEAD" in n for n in out["notes"]))
            self.assertTrue((run / "prompts" / "critic-frontier.md").is_file())

    def test_codex_envelope_extraction_is_validated_and_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, root = self.setup_review(tmp, dead=())
            rc, out = scall("extract-plan", "--run", str(run))
            self.assertIn("codebase-verifier", out["lanes"])
            tsv = (run / "codex" / "extract-env.tsv").read_text()
            self.assertIn("\tluna\t", tsv, "extraction runs on the cheap Codex class")
            prompt = (run / "codex" / "codebase-verifier.extract.prompt.md").read_text()
            self.assertIn("medium -> MAJOR if user-facing", prompt)
            (run / "codex" / "codebase-verifier.extract.out.md").write_text(
                'Here:\n{"lane": "codebase-verifier", "verdict": "", "answered_questions": [], "findings": [{"id": "CB-1", "severity": "MAJOR", "title": "t"}]}')
            (run / "codex" / "codex-frontier.extract.out.md").write_text('{"lane": "codex-frontier", "findings": "bad"}')
            rc, out = scall("extract-envelopes", "--run", str(run))
            self.assertIn("codebase-verifier", out["written"])
            self.assertIn("codex-frontier", out["failed"])
            self.assertEqual(run_dir.read_envelope(run, "codebase-verifier")[0]["findings"][0]["id"], "CB-1")

    def test_all_good_goes_straight_to_the_merge_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, root = self.setup_review(tmp, dead=())
            for label in stage.load_state(run)["codex"]:
                envelope(run, label, [("CB-1", "CRITICAL")] if label == "codebase-verifier" else [], [])
            rc, out = scall("synth-prep", "--run", str(run), "--spec", "spec.md")
            self.assertFalse(out["pending"], out)
            self.assertIn("codex-frontier", out["lanesOk"])
            self.assertTrue(out["mergeNeeded"])
            self.assertEqual(out["mergeArgs"]["stage"], "merge")

    def test_full_synthesis_path_writes_brief_checks_report_and_lane_spend(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, root = self.setup_review(tmp, dead=())
            for label in stage.load_state(run)["codex"]:
                envelope(run, label, [("CB-1", "CRITICAL")] if label == "codebase-verifier" else [], [])
            self.assertFalse(scall("synth-prep", "--run", str(run), "--spec", "spec.md")[1]["pending"])
            (run / "merged.raw.json").write_text(json.dumps([{"title": "bad", "seam": "x.ts", "members": ["CB-1"]}]))
            rc, out = scall("falsify-prep", "--run", str(run), "--spec", "spec.md")
            self.assertEqual((rc, out["falsifyNeeded"]), (0, True), out)
            rc, out = scall("falsify-check", "--run", str(run), "--spec", "spec.md")
            self.assertTrue(out["redo"] and out["falsifyArgs"]["batches"], "a missing verdict asks for ONE retry of that batch")
            self.assertEqual(scall("falsify-check", "--run", str(run), "--spec", "spec.md")[0], 1)
            (run / "falsifiers" / "F-1.json").write_text(json.dumps({"id": "F-1", "verdict": "SURVIVES", "evidence": "e"}))
            st = stage.load_state(run)
            st.pop("falsifyRetried", None)
            stage.save_state(run, st)
            review_path = Path(tmp) / "root" / "spec.review.md"
            rc, out = scall("falsify-check", "--run", str(run), "--spec", "spec.md", "--review-path", str(review_path))
            self.assertEqual((rc, out["redo"]), (0, False), out)
            brief = Path(out["reportArgs"]["briefPath"]).read_text()
            self.assertIn("### Falsifier wave: 1 dispatched over 1 CRITICAL/MAJOR — 0 REFUTED, 1 SURVIVES.", brief)
            self.assertIn("token ceiling 22000000", brief)
            self.assertIn("| codebase-verifier | run |", brief)
            self.assertEqual(run_dir.find_placeholders(brief), [])
            manifest = ",".join(stage.load_state(run)["manifestLabels"])
            skipped = set(stage.load_state(run)["skippedLabels"])
            labels = "\n".join(f"| {l} | SKIPPED (gate: n/a) | - |" if l in skipped else f"| {l} | run | x |" for l in stage.load_state(run)["manifestLabels"])
            (run / "report.md").write_text(
                "## Spec Review - Final Report\n\n### Falsifier wave: 1 dispatched over 1 CRITICAL/MAJOR — 0 REFUTED, 1 SURVIVES.\n\n"
                f"### Lane manifest\n{labels}\n\n1. [F-1] [CRITICAL] CB-1 SURVIVES\n" + "x" * 500)
            rc, out = scall("report-check", "--run", str(run))
            self.assertEqual(rc, 0, out)
            self.assertTrue(review_path.is_file())
            sp = json.loads((run / "lane-spend.json").read_text())
            self.assertEqual(sp["checkpoints"][-1]["at"], "final")
            self.assertTrue(manifest)


if __name__ == "__main__":
    unittest.main()
