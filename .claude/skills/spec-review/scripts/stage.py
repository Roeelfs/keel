#!/usr/bin/env python3
"""spec-review stage gates: the Bash steps the MAIN loop runs between Workflow stages.

A Workflow script has no shell, so nothing in it can run a command; before this file a haiku
"script-runner" agent ran each one. Now each gate here is ONE composite, idempotent command that does
the deterministic work (init, lane prompts, envelope checks, merge validation, falsifier plan, spend
ceiling, report brief) and prints ONE JSON object with the exact args of the next Workflow stage.

  prepare        init the run dir (+ delta re-review setup when --prior)
  finish-prepare lane prompts for the lanes that run this wave
  post-review    drift briefs, question coverage, spend gate -> review2 args
  synth-prep     Codex status, substitute critics, envelope check, merge check
  falsify-prep   merge validation, spend gate, falsifier plan -> batches
  falsify-check  verdict coverage, then writes the synthesis-writer brief
  report-check   mechanical report check; publishes it; writes lane-spend.json
  mark-applied   record which merged findings the fixing step applied
  extract-plan   list the OK Codex lanes whose prose output needs an envelope (luna extraction)
  extract-envelopes   validate and write the envelopes the luna extraction produced
  spend          write lane-spend.json now

Run state lives in <run>/state.json (no other store). Exit 1 means the stage must fail.
"""
import argparse
import contextlib
import difflib
import io
import json
import re
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import lane_spend  # noqa: E402
import run_dir as rd  # noqa: E402

SEV_MAP = "Codex severity words map: critical -> CRITICAL; high -> MAJOR; medium -> MAJOR if user-facing else MINOR; low -> MINOR."
HARD = {
    "adr": "the adr-auditor found the spec changes an Accepted ADR/invariant with no founder-approval marker",
    "legal": "the legal-auditor found the spec breaches an in-force legal commitment with no founder-approval marker",
}


# ---------------------------------------------------------------------------
# state + small helpers
# ---------------------------------------------------------------------------
def load_state(run):
    return rd.read_json(Path(run) / "state.json", {}) or {}


def save_state(run, st):
    rd.write(Path(run) / "state.json", json.dumps(st, indent=1))


def load_plan(run):
    plan = rd.read_json(Path(run) / "plan.json")
    if not isinstance(plan, dict):
        raise rd.StageError("plan.json missing: run `run_dir.py plan` first")
    return plan


def sub(fn, **kw):
    """Run a run_dir subcommand in-process and return (rc, its JSON object)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn(SimpleNamespace(**kw))
    line = [l for l in buf.getvalue().splitlines() if l.strip().startswith("{")]
    return rc, (json.loads(line[-1]) if line else {})


def hard_text(reasons):
    return "; ".join(HARD.get(r, f"gate lane defect ({r}): relaunch that lane, its verdict is not usable") for r in reasons)


def protected(entry, plan):
    """Lanes a spend stop never drops: floor lanes and lanes whose gate fired."""
    gate = entry.get("gate")
    return bool(entry.get("floor") or (gate and plan["gates"].get(gate, {}).get("run")))


def lane_meta(e, wiring_type=None):
    meta = {"label": e["label"], "agentType": wiring_type if (wiring_type and e["label"] == "runtime-wiring") else e["agentType"]}
    if e.get("model"):
        meta["model"] = e["model"]
    return meta


def has_envelope(run, label):
    return (Path(run) / "envelopes" / f"{label}.json").is_file()


# ---------------------------------------------------------------------------
# spend: log every run, warn at the ceiling, stop launching optional work at 1.5x
# ---------------------------------------------------------------------------
def spend_gate(run, checkpoint, sid=None, wf_dirs=None):
    plan = load_plan(run)
    sid_file = Path(run) / "inputs" / "sid.txt"
    if not sid and sid_file.is_file():
        sid = sid_file.read_text(encoding="utf-8").strip()
    ceiling = plan["budget"]["tokenCeiling"]
    sp = lane_spend.run_spend(str(run), sid, ceiling, wf_dirs=wf_dirs)
    prior = rd.read_json(Path(run) / "lane-spend.json", {}) or {}
    sp["checkpoints"] = (prior.get("checkpoints") or []) + [{"at": checkpoint, "total": sp["total"], "ratio": sp["ratio"]}]
    sp["stoppedLanes"] = prior.get("stoppedLanes", [])
    rd.write(Path(run) / "lane-spend.json", json.dumps(sp, indent=1))
    return sp


def note_stopped(run, labels):
    p = Path(run) / "lane-spend.json"
    sp = rd.read_json(p, {}) or {}
    sp["stoppedLanes"] = sorted(set(sp.get("stoppedLanes", [])) | set(labels))
    rd.write(p, json.dumps(sp, indent=1))


def spend_brief(sp):
    return {"total": sp["total"], "ceiling": sp["tokenCeiling"], "ratio": sp["ratio"], "warn": sp["warn"], "stop": sp["stop"]}


def spend_note(sp, at):
    if sp["stop"]:
        return f"SPEND STOP at {at}: {sp['total']} tokens = {sp['ratio']}x the {sp['tokenCeiling']} ceiling (>= {lane_spend.STOP_RATIO}x): optional lanes are not launched"
    if sp["warn"]:
        return f"SPEND WARNING at {at}: {sp['total']} tokens = {sp['ratio']}x the {sp['tokenCeiling']} ceiling"
    return None


def cmd_spend(a):
    sp = spend_gate(a.run, a.checkpoint or "manual", a.sid or None, [d for d in rd.csv(a.wf_dirs)] or None)
    return rd.emit({"ok": True, "spend": spend_brief(sp), "path": str(Path(a.run) / "lane-spend.json")})


# ---------------------------------------------------------------------------
# delta re-review: reuse the prior dossier, re-run only the lanes whose inputs changed
# ---------------------------------------------------------------------------
def spec_sections(text):
    """[(heading, start_line, sha)] for each markdown section; text before the first heading is section ''."""
    import hashlib
    lines = text.splitlines()
    marks = [i for i, l in enumerate(lines) if re.match(r"^#{1,6}\s", l)]
    spans = [(0, "")] if (not marks or marks[0] > 0) else []
    spans += [(i, lines[i].lstrip("#").strip()) for i in marks]
    out = []
    for n, (start, title) in enumerate(spans):
        end = spans[n + 1][0] if n + 1 < len(spans) else len(lines)
        out.append((title, start + 1, hashlib.sha256("\n".join(lines[start:end]).encode()).hexdigest()))
    return out


def changed_sections(old_text, new_text):
    old = {}
    for title, _, sha in spec_sections(old_text):
        old.setdefault(title, []).append(sha)
    seen, changed = {}, []
    for title, line, sha in spec_sections(new_text):
        n = seen.get(title, 0)
        seen[title] = n + 1
        if n >= len(old.get(title, [])) or old[title][n] != sha:
            changed.append({"heading": title, "line": line})
    gone = [t for t in old if t not in {c for c, _, _ in spec_sections(new_text)}]
    return changed, gone


def section_number(title):
    m = re.match(r"^(\d+(?:\.\d+)*)[.)\s]", title + " ")
    return m.group(1) if m else None


def mentions_changed(text, changed):
    low = text.lower()
    for c in changed:
        t = c["heading"]
        if len(t) >= 4 and t.lower() in low:
            return True
        num = section_number(t)
        if num and re.search(r"(?:§|section\s+)" + re.escape(num) + r"(?![\d.]*\d)", low):
            return True
    return False


def build_delta(run, prior, plan):
    """Copy the prior dossier, decide per planned lane re-run vs carry-forward, copy the carried
    lanes' envelopes (minus REFUTED and applied findings). Returns the state fields and a report."""
    run, prior = Path(run), Path(prior)
    need = ["dossier.md", "questions.json", "plan.json", "inputs/spec.snapshot.md"]
    gone = [n for n in need if not (prior / n).is_file()]
    if gone:
        raise rd.StageError(f"prior run {prior} cannot seed a delta re-review (missing {gone}); run a full review")
    for n in ("dossier.md", "questions.json", "decisions.json"):
        if (prior / n).is_file():
            shutil.copyfile(prior / n, run / n)
    old = (prior / "inputs" / "spec.snapshot.md").read_text(encoding="utf-8")
    new = (run / "inputs" / "spec.snapshot.md").read_text(encoding="utf-8")
    changed, removed = changed_sections(old, new)
    diff = "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), "prior", "current", n=2))
    rd.write(run / "inputs" / "spec.delta.diff", diff)

    prior_units = (rd.read_json(prior / "merged.json", {}) or {}).get("units") or []
    verdicts = {}
    if prior_units and (prior / "falsifiers").is_dir():
        ids = [m for u in prior_units for m in u["members"]]
        verdicts, _, _ = rd.falsifier_counts(prior, ids)
    refuted = {i for i, v in verdicts.items() if v == "REFUTED"}
    applied_ids = {m for u in prior_units if u.get("applied") is True for m in u["members"]}
    manifest = rd.load_manifest(str(run))
    assignments_prior = rd.read_json(prior / "assignments.json", {}) or {}
    rerun, carried, why = [], [], {}
    own_extra = {}
    for e in plan["run"]:
        label = e["label"]
        env, _ = rd.read_envelope(prior, label)
        reason = None
        if e.get("floor"):
            reason = "tier floor lane"
        elif protected(e, plan):
            reason = "fired-gate lane"
        elif env is None:
            reason = "no usable prior result"
        else:
            mine = [f["id"] for f in env["findings"] if f["id"] in applied_ids]
            lane_path = rd.lane_file(manifest, prior, label)
            text = lane_path.read_text(encoding="utf-8", errors="replace") if lane_path.is_file() else ""
            if mine:
                reason = f"raised finding(s) {', '.join(mine)} that the spec fix touched"
                own_extra[label] = "### Prior findings the spec fix addressed (verify each fix is correct and complete)\n" + "\n".join(f"- {i}" for i in mine)
            elif mentions_changed(text, changed):
                reason = "its prior findings reference a changed section"
        if reason:
            rerun.append(label)
            why[label] = f"re-run: {reason}"
        else:
            carried.append(label)
            why[label] = "carried forward: its inputs are unchanged"
    for label in carried:
        env, _ = rd.read_envelope(prior, label)
        keep = [f for f in env["findings"] if f["id"] not in refuted and f["id"] not in applied_ids]
        rd.write(run / "envelopes" / f"{label}.json", json.dumps({**env, "findings": keep, "carried_from": str(prior)}, indent=1))
        src = rd.lane_file(manifest, prior, label)
        dst = rd.lane_file(manifest, run, label)
        if src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
    assignments = rd.read_json(run / "assignments.json", {}) or {}
    assignments.update({l: assignments_prior[l] for l in carried if l in assignments_prior})
    rd.write(run / "assignments.json", json.dumps(assignments, indent=1))
    heads = "\n".join(f"- {c['heading'] or '(preamble)'} (line {c['line']})" for c in changed) or "- (no section text changed)"
    rd.write(run / "inputs" / "delta.md", (
        "\n## Delta re-review (added by the pipeline script -- binding)\n"
        f"This spec was already reviewed (prior run {prior}). The shared dossier is the prior one. Your prior-round findings for UNCHANGED sections are carried forward and are NOT to be re-raised.\n"
        f"Review ONLY the changed sections below, plus any unchanged text a change newly depends on. The unified diff is {run}/inputs/spec.delta.diff.\n"
        f"Changed or new sections:\n{heads}\n"
        + (f"Removed sections: {', '.join(removed)}\n" if removed else "")))
    for label, text in own_extra.items():
        rd.write(run / "inputs" / "delta-lanes" / f"{label}.md", text + "\n")
    return {"rerun": rerun, "carried": carried, "why": why, "changed": changed, "removed": removed, "refutedDropped": sorted(refuted), "appliedDropped": sorted(applied_ids)}


# ---------------------------------------------------------------------------
# prepare / finish-prepare
# ---------------------------------------------------------------------------
def cmd_prepare(a):
    a.skill_dir = a.skill_dir or str(rd.SKILL_DIR)
    a.runtime = a.runtime or "claude"
    plan = load_plan(a.run)
    rc, init = sub(rd.cmd_init, run=a.run, spec=a.spec, root=a.root, sid=a.sid, runtime=a.runtime, skill_dir=a.skill_dir)
    if rc:
        return rd.emit(init, False)
    st = {"claude": [], "codex": [], "carried": [], "prior": a.prior or None, "reviewPath": None}
    notes = [f"decisions mining: {init['decisionsNote']}",
             f"lane plan: tier {plan['tier']}, {plan['planned']} lanes ({plan['plannedCodex']} Codex) from {', '.join(plan['files'])}"
             + (f"; over budget (advisory): {'; '.join(plan['overBudget'])}" if plan["overBudget"] else "")]
    out = {"ok": True, "decisions": init["decisions"], "notes": notes}
    if a.prior:
        d = build_delta(a.run, a.prior, plan)
        st.update({"rerun": d["rerun"], "carried": d["carried"], "why": d["why"]})
        notes.append(f"delta re-review of {a.prior}: re-run {len(d['rerun'])} lane(s), carried {len(d['carried'])}; changed sections: {len(d['changed'])}")
        out.update({"next": "finish-prepare", "delta": {k: d[k] for k in ("rerun", "carried", "why")}})
    else:
        out.update({"next": "extract", "extractCommand": f"bash {a.skill_dir}/scripts/run-codex-lanes.sh {a.run} extract"})
    save_state(a.run, st)
    return rd.emit(out)


def cmd_finish_prepare(a):
    run = Path(a.run)
    plan, st = load_plan(run), load_state(run)
    labels = st.get("rerun") or [e["label"] for e in plan["run"]]
    rc, lanes = sub(rd.cmd_lanes, run=a.run, spec=a.spec, lanes=",".join(labels))
    if rc:
        return rd.emit(lanes, False)
    st["claude"], st["codex"] = lanes["claude"], lanes["codex"]
    save_state(run, st)
    by = {e["label"]: e for e in plan["run"]}
    notes = [f"{s['label']}: SKIPPED (gate: {s['reason'].replace('gate: ', '', 1)})" for s in plan["skipped"]]
    notes += [f"{l}: {st['why'][l]}" for l in st.get("carried", []) if l in st.get("why", {})]
    return rd.emit({"ok": True, "claudeLanes": lanes["claude"], "codexLanes": lanes["codex"], "carried": st.get("carried", []),
                    "reviewLanes": [lane_meta(by[l], a.wiring_type) for l in lanes["claude"]],
                    "codexCommand": f"bash {rd.SKILL_DIR}/scripts/run-codex-lanes.sh {run} {plan['profile']}",
                    "skipped": plan["skipped"], "notes": notes})


# ---------------------------------------------------------------------------
# post-review
# ---------------------------------------------------------------------------
def cmd_post_review(a):
    run = Path(a.run)
    plan, st = load_plan(run), load_state(run)
    by = {e["label"]: e for e in plan["run"]}
    present = [l for l in st["claude"] if has_envelope(run, l)]
    notes = [f"{l}: FAILED (no envelope written)" for l in st["claude"] if l not in present]
    if "spec-drift-scout" in present and "driftBriefs" not in st:
        rc, d = sub(rd.cmd_drift_briefs, run=a.run, spec=a.spec)
        if rc:
            return rd.emit(d, False)
        st["driftBriefs"], st["driftDropped"] = d["briefs"], d["dropped"]
        if d["dropped"]:
            notes.append(f"drift investigators: {d['dropped']} candidate(s) beyond the cap of 5 were not investigated (user decision needed)")
    briefs = st.get("driftBriefs", [])
    carried_claude = [l for l in st["carried"] if by.get(l, {}).get("kind") != "codex"]
    lanes = present + carried_claude + [b for b in briefs if has_envelope(run, b)]
    rc, chk = sub(rd.cmd_check_envelopes, run=a.run, lanes=",".join(lanes), codex="")
    unanswered, invalid = chk.get("unanswered", {}), chk.get("invalid", [])
    sp = spend_gate(run, "post-review")
    note = spend_note(sp, "post-review")
    if note:
        notes.append(note)
    todo_briefs = [b for b in briefs if not has_envelope(run, b)]
    dropped = []
    if sp["stop"]:
        dropped = [b for b in todo_briefs]
        todo_briefs = []
        for l in list(unanswered):
            if not protected(by[l], plan):
                dropped.append(l)
        notes.append("not launched at the ceiling stop: " + (", ".join(dropped) or "nothing pending"))
        note_stopped(run, dropped)
    repair = [{**lane_meta(by[l]), "questions": qs} for l, qs in unanswered.items() if l not in dropped]
    pending = bool(todo_briefs or repair)
    if a.final and (invalid or [l for l in unanswered if l not in dropped]):
        return rd.emit({"ok": False, "errors": chk.get("errors", []), "notes": notes}, False)
    save_state(run, st)
    out = {"ok": True, "needReview2": pending and not a.final, "briefs": todo_briefs, "repair": repair, "dropped": dropped,
           "notes": notes + [f"envelope missing: {m}" for m in chk.get("missing", [])], "spend": spend_brief(sp)}
    if repair or todo_briefs:
        out["review2Args"] = {"stage": "review2", "briefs": [{"label": b} for b in todo_briefs], "repair": repair}
    if not pending or a.final:
        rc, s = sub(rd.cmd_summary, run=a.run, lanes=",".join(lanes), planned=",".join(by))
        out.update({"counts": s.get("raw"), "hardStop": s.get("hardStop", False), "hardStopReasons": s.get("hardStopReasons", [])})
        if s.get("hardStop"):
            out["notes"].append(f"HARD STOP: {hard_text(s['hardStopReasons'])}; no fixes may be applied until the founder decides")
    return rd.emit(out)


# ---------------------------------------------------------------------------
# Codex envelope extraction (luna) -- the prose output of a Codex lane becomes an envelope
# ---------------------------------------------------------------------------
def extractor_prompt(run, e):
    label = e["label"]
    extra = ""
    if label == "codex-research":
        extra = " Research items use severity ELEVATE or CAUTION, never CRITICAL/MAJOR/MINOR."
    if label == "codex-frontier":
        extra = (" Frontier: each of its items (1) most-likely-wrong decision, (2) the cross-cutting risks, (3) best-in-class delta becomes a finding;"
                 " use its stated severity, else MAJOR (CRITICAL when its verdict is redesign for item 1).")
    return (f"ROLE: codex-envelope-extractor\nRead the Codex lane output {run}/codex/{label}.out.md (the lane's full findings; do not edit it). "
            f"List EVERY finding in it and build this envelope object: {{\"lane\": \"{label}\", \"verdict\": \"<the lane's verdict word, or ''>\", "
            f"\"answered_questions\": [<the Q-ids the lane answered; assigned ids are in {run}/assignments.json under \"{label}\">], "
            f"\"findings\": [{{\"id\": \"{e['idPrefix']}-1\", \"severity\": \"...\", \"title\": \"<one line>\"}}, ...]}} with ids {e['idPrefix']}-1.. in file order. "
            f"{SEV_MAP}{extra} Never drop a finding to keep the envelope short. "
            f"Your FINAL MESSAGE is that one JSON object and nothing else (no fence, no prose); write no file.\n")


def cmd_extract_plan(a):
    run = Path(a.run)
    plan, st = load_plan(run), load_state(run)
    status = rd.codex_status_rows(run)
    rows = []
    for e in plan["run"]:
        if e["kind"] != "codex" or e["label"] not in st.get("codex", []):
            continue
        s = status.get(e["label"])
        if not (s and s["status"] == "OK" and s["bytes"] >= 400):
            continue
        prompt = run / "codex" / f"{e['label']}.extract.prompt.md"
        rd.write(prompt, extractor_prompt(str(run), e))
        rows.append((e["label"], "luna", prompt, run / "codex" / f"{e['label']}.extract.out.md"))
    rd.write(run / "codex" / "extract-env.tsv", "".join(f"{l}\t{c}\t{p}\t{o}\n" for l, c, p, o in rows))
    return rd.emit({"ok": True, "lanes": [r[0] for r in rows]})


def cmd_extract_envelopes(a):
    run = Path(a.run)
    written, failed = [], {}
    tsv = run / "codex" / "extract-env.tsv"
    for line in (tsv.read_text(encoding="utf-8").splitlines() if tsv.is_file() else []):
        label = line.split("\t")[0]
        out = run / "codex" / f"{label}.extract.out.md"
        env = rd.last_json(out.read_text(encoding="utf-8", errors="replace"), dict) if out.is_file() else None
        err = rd.envelope_error(env)
        if not err and env.get("lane") != label:
            env["lane"] = label
        if err:
            failed[label] = err
            continue
        rd.write(run / "envelopes" / f"{label}.json", json.dumps(env, indent=1))
        written.append(label)
    return rd.emit({"ok": True, "written": written, "failed": failed})


# ---------------------------------------------------------------------------
# synth-prep: Codex status, critics, envelope check, merge check (rerun after the critics workflow)
# ---------------------------------------------------------------------------
def cmd_synth_prep(a):
    run = Path(a.run)
    plan, st = load_plan(run), load_state(run)
    manifest = rd.load_manifest(str(run))
    status = rd.codex_status_rows(run)
    notes, live, dead = [], [], []
    for e in [x for x in plan["run"] if x["kind"] == "codex" and x["label"] in st["codex"]]:
        s = status.get(e["label"])
        if s and s["status"] == "OK" and s["bytes"] >= 400:
            live.append(e["label"])
        else:
            dead.append(e["label"])
            sub_word = "backfilled by critic (opus)" if e["label"] in ("codex-adversarial", "codex-frontier") else "no substitute (investigation / dossier carry it)"
            notes.append(f"{e['label']}: timed-out/{s['status'] if s else 'NO-STATUS'} -- {sub_word}; cross-examination unavailable for it")
    sp = spend_gate(run, "synth-prep")
    sn = spend_note(sp, "synth-prep")
    if sn:
        notes.append(sn)
    subs = [e for e in plan["substitutes"] if e.get("substituteFor") in dead]
    stopped = [e["label"] for e in subs if sp["stop"] and e["label"] != "critic-frontier"]
    if stopped:
        subs = [e for e in subs if e["label"] not in stopped]
        note_stopped(run, stopped)
        notes.append("critic substitute(s) not launched at the ceiling stop: " + ", ".join(stopped))
    for e in plan["substitutes"]:
        if e.get("substituteFor") and e not in subs and e["label"] not in stopped:
            notes.append(f"{e['label']}: SKIPPED (gate: {e['substituteFor']} produced its artifact)")
    if subs:
        rc, o = sub(rd.cmd_lanes, run=a.run, spec=a.spec, lanes=",".join(e["label"] for e in subs))
        if rc:
            return rd.emit(o, False)
    by = {e["label"]: e for e in plan["run"]}
    need_extract = [l for l in live if rd.read_envelope(run, l)[0] is None]
    pending = {"critics": [lane_meta(e) for e in subs if not has_envelope(run, e["label"])],
               "extractors": [{"label": l, "promptPath": str(run / "codex" / f"{l}.extract.prompt.md")} for l in need_extract]}
    for x in pending["extractors"]:
        if not Path(x["promptPath"]).is_file():
            rd.write(x["promptPath"], extractor_prompt(str(run), by[x["label"]]))
    if pending["critics"] or pending["extractors"]:
        return rd.emit({"ok": True, "pending": True, "criticsArgs": {"stage": "critics", **pending}, "notes": notes, "spend": spend_brief(sp)})

    planned = [e["label"] for e in plan["run"]] + [e["label"] for e in subs]
    codex_labels = [e["label"] for e in plan["run"] if e["kind"] == "codex"]
    rc, chk = sub(rd.cmd_check_envelopes, run=a.run, lanes=",".join(planned), codex=",".join(codex_labels))
    if chk.get("invalid") or chk.get("unanswered"):
        return rd.emit({"ok": False, "errors": [f"envelope contract failed: {'; '.join(chk.get('errors', []))}"], "notes": notes}, False)
    failed = [m.split(":")[0] for m in chk.get("missing", [])]
    notes += [f"{l}: FAILED (no envelope)" for l in failed]
    notes += [f"{l}: Codex lane left assigned question(s) unanswered: {', '.join(qs)}" for l, qs in (chk.get("codexUnanswered") or {}).items()]
    has_sub = any(e["label"] == "critic-frontier" for e in subs)
    if "codex-frontier" in failed and not has_sub:
        return rd.emit({"ok": False, "errors": ["Astra frontier lane has no envelope and no substitute"], "notes": notes}, False)
    ok = [l for l in planned if l not in failed]
    if "codex-frontier" not in ok and "critic-frontier" not in ok:
        return rd.emit({"ok": False, "errors": ["no Astra frontier result (lane and critic fallback both failed)"], "notes": notes}, False)
    st["synth"] = {"ok": ok, "failed": failed, "dead": dead, "subs": [e["label"] for e in subs], "notes": notes}
    save_state(run, st)
    rc, mc = sub(rd.cmd_merge_check, run=a.run, lanes=",".join(ok))
    out = {"ok": True, "pending": False, "lanesOk": ok, "failedLanes": failed, "notes": notes, "spend": spend_brief(sp), "mergeNeeded": not mc.get("ok"),
           "mergeArgs": {"stage": "merge", "ok": ok, "indexPath": mc.get("indexPath") or str(run / "merge-index.txt"), "totalIds": mc.get("totalIds", 0)}}
    if mc.get("ok"):
        out["notes"].append(f"merge: {mc['totalIds']} CRITICAL/MAJOR ids -> {mc['clusters']} F-N units")
    return rd.emit(out)


# ---------------------------------------------------------------------------
# falsify-prep / falsify-check
# ---------------------------------------------------------------------------
def cmd_falsify_prep(a):
    run = Path(a.run)
    plan, st = load_plan(run), load_state(run)
    ok = st["synth"]["ok"]
    rc, mc = sub(rd.cmd_merge_check, run=a.run, lanes=",".join(ok))
    if not mc.get("ok"):
        st["mergeAttempts"] = st.get("mergeAttempts", 0) + 1
        save_state(run, st)
        if st["mergeAttempts"] > 2:
            return rd.emit({"ok": False, "errors": [f"finding merge failed validation after 2 repairs: {'; '.join(mc.get('errors', []))}"]}, False)
        return rd.emit({"ok": True, "mergeNeeded": True, "mergeArgs": {"stage": "merge", "ok": ok, "indexPath": mc.get("indexPath") or str(run / "merge-index.txt"),
                                                                       "totalIds": mc.get("totalIds", 0), "repairErrors": mc.get("errors", [])}})
    notes = [f"merge: {mc['totalIds']} CRITICAL/MAJOR ids -> {mc['clusters']} F-N units"]
    sp = spend_gate(run, "falsify-prep")
    sn = spend_note(sp, "falsify-prep")
    if sn:
        notes.append(sn)
    units = (rd.read_json(run / "merged.json", {}) or {}).get("units") or []
    skipped = []
    if sp["stop"]:
        for u in units:
            if u.get("falsify") and u["severity"] != "CRITICAL":
                u["falsify"], u["stopSkipped"] = False, True
                skipped.append(u["id"])
        if skipped:
            rd.write(run / "merged.json", json.dumps({"units": units}, indent=1))
            note_stopped(run, [f"falsify:{i}" for i in skipped])
            notes.append(f"MAJOR unit(s) {', '.join(skipped)} not falsified at the ceiling stop (CRITICAL falsification is exempt)")
    corroborated = [u["id"] for u in units if not u.get("falsify") and not u.get("stopSkipped")]
    if corroborated:
        notes.append(f"{len(corroborated)} MAJOR unit(s) corroborated by a second lane skip the falsifier: {', '.join(corroborated)}")
    rc, fp = sub(rd.cmd_falsify_plan, run=a.run, lanes=",".join(ok), spec=a.spec, max_batches=str(a.max_batches or 6), dry=False)
    if rc:
        return rd.emit(fp, False)
    notes.append(f"falsifier plan: {fp['totalUnits']} units ({fp['totalIds']} ids) in {len(fp['plan'])} batches")
    st["falsifyBatches"] = fp["plan"]
    st["falsifyIds"] = fp["totalIds"]
    save_state(run, st)
    return rd.emit({"ok": True, "mergeNeeded": False, "falsifyNeeded": bool(fp["plan"]), "notes": notes, "spend": spend_brief(sp),
                    "falsifyArgs": {"stage": "falsify", "batches": [{"batch": b["batch"], "prompt": b["prompt"]} for b in fp["plan"]]}})


def report_prompt(run, plan, st, sp, a):
    synth = st["synth"]
    P = plan
    skip_subs = [e for e in P["substitutes"] if e.get("substituteFor") and e["label"] not in synth["subs"]]
    carried = set(st.get("carried", []))
    gone = set(synth["dead"]) | set(synth["failed"])
    rows = []
    for e in P["run"]:
        status = ("DEAD: " + (rd.codex_status_rows(run).get(e["label"], {}).get("status", "NO-STATUS")) if e["label"] in synth["dead"]
                  else "FAILED (no output)" if e["label"] in synth["failed"]
                  else f"carried forward (inputs unchanged; prior run {st['prior']})" if e["label"] in carried else "run")
        rows.append(f"| {e['label']} | {status} | {e['agentType']}{' / ' + e['model'] if e.get('model') else ''} |")
    rows += [f"| {l} | run (substitute for {next(x['substituteFor'] for x in P['substitutes'] if x['label'] == l)}) | critic / opus |" for l in synth["subs"]]
    rows += [f"| {s['label']} | SKIPPED ({s['reason']}) | - |" for s in P["skipped"]]
    rows += [f"| {e['label']} | SKIPPED (gate: {e['substituteFor']} produced its artifact) | - |" for e in skip_subs]
    ran = [e for e in P["run"] if e["label"] not in gone]
    ran_codex = [e for e in ran if e["kind"] == "codex"]
    mode = P["budget"]["falsifier"]
    labels = [e["label"] for e in ran]
    spend_line = (f"- spend: {sp['total']} tokens (Claude {sp['claudeTotal']}, Codex {sp['codexTotal']}) = {sp['ratio']}x the {sp['tokenCeiling']} ceiling"
                  + ("; CEILING REACHED" if sp["warn"] else "") + ("; STOP LAUNCHING NEW LANES (>= 1.5x): not launched: " + (", ".join(rd.read_json(Path(run) / 'lane-spend.json', {}).get('stoppedLanes', [])) or "nothing pending") if sp["stop"] else ""))
    plan_block = [
        f"### Lane plan: tier {P['tier']} (profile {P['profile']}) — planned {P['planned']} lanes ({P['plannedCodex']} Codex), ran {len(ran)} ({len(ran_codex)} Codex); advisory budget: max {P['budget']['maxLanes']} lanes / {P['budget']['maxCodexLanes']} Codex, token ceiling {P['budget']['tokenCeiling']}, falsifier scope {mode}. Manifest files: {', '.join(P['files'])}.",
        *[f"- over budget (advisory): {w}" for w in P["overBudget"]],
        spend_line,
        *[f"- {e['label']}: {P['laneReasons'][e['label']]}" for e in P["run"]],
    ]
    scope = {"all": "every CRITICAL/MAJOR", "uncorroborated": "every CRITICAL plus each MAJOR unit only one lane raised (a MAJOR a second lane also raised is corroborated and skips the falsifier)",
             "critical": "CRITICAL only", "off": "none"}[mode]
    rc, summ = sub(rd.cmd_summary, run=str(run), lanes=",".join(synth["ok"]), planned=",".join(labels))
    universe = len(rd.all_critical_major(run, rd.expand_labels(run, synth["ok"]), scoped=True))
    n = summ["falsifierDispatched"]
    fals_line = f"{n} dispatched over {universe} CRITICAL/MAJOR — {summ['refuted']} REFUTED, {n - summ['refuted']} SURVIVES."
    manifest_labels = [e["label"] for e in P["run"]] + [s["label"] for s in P["skipped"]] + [e["label"] for e in P["substitutes"] if e.get("substituteFor")]
    skipped_labels = [s["label"] for s in P["skipped"]] + [e["label"] for e in skip_subs]
    st["manifestLabels"], st["skippedLabels"] = manifest_labels, skipped_labels
    lines = [
        "ROLE: synthesis-writer",
        f"You write the final spec-review report. Write it to {run}/report.md following the template {rd.SKILL_DIR}/report-template.md exactly (section order, one canonical Falsifier wave line, F-N ids assigned once). Do not read the spec's design discussion; read evidence only.",
        f"Spec: {a.spec}. Tier: {P['tier']} (profile {P['profile']}). Run dir: {run}. Investigation brief: {a.investigation or 'none (no investigation Workflow ran)'}.",
        f"Inputs: every {run}/envelopes/*.json (ids + severities per lane); full findings in {run}/lanes/*.md and {run}/codex/*.out.md; the merged units in {run}/merged.json (use its F-N ids and member lists as the report's F-N ids); falsifier verdicts per F-N in {run}/falsifiers/F-*.json (+ batch-*.md reasoning; a unit's verdict is every member's verdict); ground truth in {run}/dossier.md and {run}/decisions.json; LEARNINGS paths (read the parts that apply; never edit): {run}/inputs/learnings.txt lists them.",
        "Hard rules the pipeline checks mechanically after you finish:",
        f"- EVERY CRITICAL/MAJOR id in ANY envelope appears in report.md, each on a line carrying its verdict word (REFUTED or SURVIVES from its falsifier verdict; SURVIVES-BUT-FIX-REJECTED and NEEDS-LIVE-EVIDENCE count as SURVIVES with the note). Keep each lane's own ids (EC-N, Sec-N, Obs-N, LE-N, DRIFT-N, COMP-N ...). Consensus / Codex-only / Claude-only entries get an F-N id AND list the lane ids they merge.",
        "- Right after the Profile line reproduce this block VERBATIM (it carries the planned-vs-actual lane count, the spend against the ceiling and the per-lane reasons):", *plan_block,
        f"- Falsifier scope at this tier is {mode} ({scope}). A CRITICAL/MAJOR id outside that scope was not falsified: its report line carries the verdict word SURVIVES with the note \"(not falsified at tier {P['tier']}: <corroborated by lane X | outside scope | ceiling stop>)\".",
        f"- The falsifier line is exactly: ### Falsifier wave: {fals_line}",
        "- REFUTED findings go to the Resolved section with the refuting evidence; an unrefuted CRITICAL keeps its severity (no downgrade without a REFUTED verdict).",
        '- Surviving Obs-/Sec-/LE- CRITICAL/MAJOR not applied as spec prose go under "Carried obligations".',
        "- Lanes marked 'carried forward' were not re-run on this delta re-review: their envelopes come from the prior run (minus REFUTED and already-applied findings); say so in their lane lines.",
        '- The Lane manifest section reproduces this table verbatim (a lane with status FAILED or DEAD keeps that status; verdict lines say "timed-out/<status> -- backfilled by <substitute>" where a substitute ran):',
        "| Lane | Status | Agent / model |", "|---|---|---|", *rows,
    ]
    if summ["hardStop"]:
        lines.append(f"- HARD STOP: open the report with a bold HARD STOP banner: {hard_text(summ['hardStopReasons'])}; no fixes until the founder decides.")
    every = [e["label"] for e in P["run"] if e.get("reportEveryFinding")]
    if every:
        lines.append(f"- EVERY finding id of ANY severity and EVERY research_handoffs id in the envelopes of {', '.join(every)} appears in report.md, in that lane's own template section. Its ELEVATE items are a decision surface, never auto-applied; its hand-offs are listed for the main loop to send to the investigation skill.")
    lines += ["- No placeholder text may remain: no double-brace tokens, no angle-bracket FOCUS tokens, no ALL_CAPS angle-bracket tokens.", "Reply via StructuredOutput with the path only."]
    return "\n".join(lines), summ


def cmd_falsify_check(a):
    run = Path(a.run)
    plan, st = load_plan(run), load_state(run)
    ok = st["synth"]["ok"]
    rc, s = sub(rd.cmd_summary, run=a.run, lanes=",".join(ok), planned=",".join(e["label"] for e in plan["run"]))
    notes = []
    if s["missingVerdicts"]:
        if st.get("falsifyRetried"):
            return rd.emit({"ok": False, "errors": [f"falsifier verdict missing for {s['missingVerdicts']}"]}, False)
        st["falsifyRetried"] = True
        save_state(run, st)
        redo = [b for b in st["falsifyBatches"] if any(i in s["missingVerdicts"] for i in b["ids"])]
        return rd.emit({"ok": True, "redo": True, "falsifyArgs": {"stage": "falsify", "batches": [{"batch": b["batch"], "prompt": b["prompt"]} for b in redo]},
                        "notes": [f"falsifier retry for batch(es) {', '.join(str(b['batch']) for b in redo)}: missing {', '.join(s['missingVerdicts'])}"]})
    total = len(rd.falsified_ids(run, rd.expand_labels(run, ok)))
    if s["falsifierDispatched"] != total:
        return rd.emit({"ok": False, "errors": [f"verdicts-per-id mismatch ({s['falsifierDispatched']} ids with verdicts vs {total})"]}, False)
    notes.append(f"falsifier wave: {len(st.get('falsifyBatches', []))} batches, {total} ids, {s['refuted']} ids REFUTED")
    sp = spend_gate(run, "falsify-check")
    st["reviewPath"] = a.review_path or None
    brief, summ = report_prompt(run, plan, st, sp, a)
    brief_path = run / "prompts" / "synthesis-writer.md"
    rd.write(brief_path, brief + "\n")
    save_state(run, st)
    if summ["hardStop"]:
        notes.append(f"HARD STOP surfaced in report.md ({', '.join(summ['hardStopReasons'])})")
    return rd.emit({"ok": True, "redo": False, "reportArgs": {"stage": "report", "briefPath": str(brief_path)}, "counts": {"raw": s["raw"], "surviving": s["surviving"], "refuted": s["refuted"], "falsifierDispatched": total},
                    "hardStop": s["hardStop"], "hardStopReasons": s["hardStopReasons"], "notes": notes, "spend": spend_brief(sp)})


def cmd_report_check(a):
    run = Path(a.run)
    st = load_state(run)
    flags = SimpleNamespace(run=a.run, lanes=",".join(st["synth"]["ok"]), manifest=",".join(st["manifestLabels"]),
                            skipped=",".join(st["skippedLabels"]), publish=st.get("reviewPath") or "")
    rc, out = sub(rd.cmd_check_report, **vars(flags))
    if rc == 0:
        sp = spend_gate(run, "final")
        out["spend"] = spend_brief(sp)
        out["spendPath"] = str(run / "lane-spend.json")
        note = spend_note(sp, "final")
        if note:
            out["spendNote"] = note
    return rd.emit(out, rc == 0)


# ---------------------------------------------------------------------------
# mark-applied
# ---------------------------------------------------------------------------
def cmd_mark_applied(a):
    p = Path(a.run) / "merged.json"
    data = rd.read_json(p)
    if not isinstance(data, dict):
        return rd.emit({"ok": False, "errors": ["merged.json missing: no review has merged findings in this run dir"]}, False)
    want = set(rd.csv(a.ids))
    status = a.status.lower() not in ("false", "no", "0")
    known = {u["id"] for u in data["units"]}
    if want - known:
        return rd.emit({"ok": False, "errors": [f"unknown merged finding id(s) {sorted(want - known)}"]}, False)
    for u in data["units"]:
        if u["id"] in want:
            u["applied"] = status
    rd.write(p, json.dumps(data, indent=1))
    tally = {"applied": 0, "notApplied": 0, "unmarked": 0}
    for u in data["units"]:
        tally["unmarked" if u.get("applied") is None else "applied" if u["applied"] else "notApplied"] += 1
    return rd.emit({"ok": True, **tally})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub_ = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, *flags, **bools):
        p = sub_.add_parser(name)
        p.add_argument("--run", required=True)
        for f in flags:
            p.add_argument(f"--{f}", default="")
        for b in bools:
            p.add_argument(f"--{b}", action="store_true")
        p.set_defaults(fn=fn)

    add("prepare", cmd_prepare, "spec", "root", "sid", "runtime", "skill-dir", "prior")
    add("finish-prepare", cmd_finish_prepare, "spec", "wiring-type")
    add("post-review", cmd_post_review, "spec", final=True)
    add("extract-plan", cmd_extract_plan)
    add("extract-envelopes", cmd_extract_envelopes)
    add("synth-prep", cmd_synth_prep, "spec")
    add("falsify-prep", cmd_falsify_prep, "spec", "max-batches")
    add("falsify-check", cmd_falsify_check, "spec", "investigation", "review-path")
    add("report-check", cmd_report_check)
    add("mark-applied", cmd_mark_applied, "ids", "status")
    add("spend", cmd_spend, "checkpoint", "sid", "wf-dirs")
    a = ap.parse_args(argv)
    if hasattr(a, "status") and not a.status:
        a.status = "true"
    try:
        return a.fn(a)
    except rd.StageError as e:
        return rd.emit({"ok": False, "errors": [str(e)]}, False)


if __name__ == "__main__":
    sys.exit(main())
