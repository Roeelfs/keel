#!/usr/bin/env python3
"""spec-review run-dir helper: the deterministic half of the Workflow pipeline.

A Workflow script has no filesystem access, so every file-shaped job it needs
(fill a prompt template, validate an envelope, check the report) is a
subcommand here, run by a tiny script-runner agent. Static lane data
(agent type, id prefix, question tags, prompt file) is read from the MANIFEST
literal inside spec-review.workflow.js -- the one place it is declared.

Run-dir contract (all paths under <run>):
  inputs/      context.md gates.json root.txt learnings.txt prefilter.md
               session-decisions.raw.json (best effort)
  dossier.md questions.json decisions.json   written ONCE by the miners
  prompts/     FILLED prompt copies -- lanes read these, never prompts/<x>.md
  codex/       <lane>.prompt.md plan.tsv <lane>.out.md status.tsv
  lanes/       <lane>.md          full findings, written by the lane
  envelopes/   <lane>.json        {lane, answered_questions, findings[]}
  falsifiers/  <id>.md <id>.json
  report.md

Every subcommand prints ONE JSON object on stdout; exit 1 means the stage must
fail (the JSON carries `errors`).
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
WORKFLOW_JS = SKILL_DIR / "scripts" / "spec-review.workflow.js"
PROMPTS_DIR = SKILL_DIR / "prompts"

SEVERITIES = ("CRITICAL", "MAJOR", "MINOR", "ELEVATE", "CAUTION")
FALSIFIED = ("CRITICAL", "MAJOR")
# An unfilled placeholder is any of: {{NAME}}, <FOCUS...>, <ALL_CAPS_NAME>.
PLACEHOLDER_RES = (
    re.compile(r"\{\{[^}\n]*\}\}"),
    re.compile(r"<FOCUS[^>\n]*>"),
    re.compile(r"<[A-Z][A-Z0-9_]{3,}>"),
)


class StageError(Exception):
    pass


# --------------------------------------------------------------------------
# manifest + templates
# --------------------------------------------------------------------------
def load_manifest(js_path=WORKFLOW_JS):
    text = Path(js_path).read_text(encoding="utf-8")
    m = re.search(r"// MANIFEST:BEGIN\s*\nconst MANIFEST = (.*?);?\s*\n// MANIFEST:END", text, re.S)
    if not m:
        raise StageError(f"no MANIFEST block in {js_path}")
    return json.loads(m.group(1))


def all_entries(manifest):
    return list(manifest["lanes"]) + list(manifest["support"])


INVESTIGATOR = "spec-drift-investigator"


def base_label(label):
    """spec-drift-investigator-DRIFT-1 -> spec-drift-investigator."""
    return INVESTIGATOR if label.startswith(INVESTIGATOR + "-") else label


def expand_labels(run, labels):
    """Add the second-wave drift investigators that actually wrote an envelope."""
    extra = sorted(p.stem for p in (Path(run) / "envelopes").glob(INVESTIGATOR + "-*.json"))
    return list(labels) + [x for x in extra if x not in labels]


def entry_by_label(manifest, label):
    label = base_label(label)
    for e in all_entries(manifest):
        if e["label"] == label:
            return e
    raise StageError(f"unknown lane label: {label}")


def extract_body(template_text):
    """Body of the first fenced `prompt: |` block, dedented two spaces."""
    lines = template_text.splitlines()
    start = next((i for i, l in enumerate(lines) if l.strip() == "prompt: |"), None)
    if start is None:
        raise StageError("template has no `prompt: |` block")
    body = []
    for l in lines[start + 1:]:
        if l == "```":
            break
        body.append(l[2:] if l.startswith("  ") else l)
    return "\n".join(body).strip("\n")


def find_placeholders(text):
    found = []
    for rx in PLACEHOLDER_RES:
        found.extend(rx.findall(text))
    return found


def fill(body, values):
    out = body
    for key, val in values.items():
        out = out.replace("{{" + key + "}}", val)
    return out


def role_line(template_text, label):
    first = template_text.splitlines()[0] if template_text else ""
    if first.strip() != f"ROLE: {label}":
        raise StageError(f"template for {label} must start with 'ROLE: {label}' (got {first!r})")


# --------------------------------------------------------------------------
# small io helpers
# --------------------------------------------------------------------------
def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write(path, text):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def emit(obj, ok=True):
    print(json.dumps(obj, separators=(",", ":")))
    return 0 if ok else 1


def run_cmd(cmd, cwd=None, timeout=60):
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, "", str(e)


def csv(value):
    return [x for x in (value or "").split(",") if x]


def lane_file(manifest, run, label):
    e = entry_by_label(manifest, label)
    if e.get("kind") == "codex":
        return Path(run) / "codex" / f"{label}.out.md"
    return Path(run) / "lanes" / f"{label}.md"


# --------------------------------------------------------------------------
# run contract appended to every filled lane prompt
# --------------------------------------------------------------------------
def learnings_paths(skill_dir=SKILL_DIR, home=None):
    home = Path(home or os.path.expanduser("~"))
    out = []
    committed = Path(skill_dir) / "LEARNINGS.md"
    if committed.is_file():
        out.append(str(committed))
    overlay = home / ".claude" / "skills-overlay" / "spec-review" / "LEARNINGS.md"
    if overlay.is_file():
        out.append(str(overlay))
    return out


def run_contract(run, entry, questions, label=None, ids_note=None):
    run = str(run)
    qlines = "\n".join(f"  - {q['id']} [{q.get('lane', '')}]: {q['text']}" for q in questions) or "  (none assigned)"
    prefix = entry.get("idPrefix", "F")
    label = label or entry["label"]
    ids_note = ids_note or (f"Use the ids your format defines (EC-N, Sec-N, Obs-N, LE-N, DRIFT-N); otherwise {prefix}-1, {prefix}-2, ... in file order.")
    return f"""

## Run contract (added by the pipeline script -- binding, overrides any conflicting instruction above)

- Run dir: {run}
- Shared inputs, mined once, READ-ONLY (never edit): {run}/dossier.md (ground-truth dossier),
  {run}/decisions.json (design decisions, if the file exists), {run}/inputs/context.md (the "why" block),
  {run}/inputs/prefilter.md (merge-base pin + open PRs). Read the dossier before you start; it replaces any
  "dossier content" placeholder above.
- Assigned review questions -- answer EVERY one, citing its Q-id in your findings file:
{qlines}
- Independence: you read no other lane's output. You are a leaf agent -- spawn no sub-agents or Workflows.
- Delivery:
  1. Write your COMPLETE output, in the format your brief above specifies, to {run}/lanes/{label}.md.
  2. Write {run}/envelopes/{label}.json: {{"lane": "{label}", "verdict": "<one word or ''>",
     "answered_questions": ["Q1", ...], "findings": [{{"id": "...", "severity": "CRITICAL|MAJOR|MINOR", "title": "<one line>"}}]}}.
     One entry per finding in your file -- including every CRITICAL and MAJOR. {ids_note}
  3. Your final reply is that same envelope via StructuredOutput (ids, severities, one-line titles; no finding bodies).
"""


# --------------------------------------------------------------------------
# questions
# --------------------------------------------------------------------------
def load_questions(run):
    qs = read_json(Path(run) / "questions.json")
    if not isinstance(qs, list) or not qs:
        raise StageError("questions.json missing, unparsable or empty")
    seen = set()
    for q in qs:
        if not isinstance(q, dict) or not q.get("id") or not q.get("text"):
            raise StageError(f"malformed question entry: {q!r}")
        if q["id"] in seen:
            raise StageError(f"duplicate question id {q['id']}")
        seen.add(q["id"])
    return qs


def assign_questions(questions, lane_entries):
    """{label: [question]} -- a question goes to every running lane whose tags
    include its tag; with none, to every running fallback lane."""
    out = {e["label"]: [] for e in lane_entries}
    fallbacks = [e for e in lane_entries if e.get("fallback")]
    for q in questions:
        owners = [e for e in lane_entries if q.get("lane") in e.get("tags", [])] or fallbacks
        if not owners:
            raise StageError(f"question {q['id']} [{q.get('lane')}] has no owning or fallback lane in the run set")
        for e in owners:
            out[e["label"]].append(q)
    return out


def focus_text(questions):
    if not questions:
        return ""
    body = " ".join(f"{q['id']}: {q['text']}" for q in questions)
    return ("Concerns to weigh, each with its id -- answer every one explicitly, beginning its answer with the id: "
            + body)


# --------------------------------------------------------------------------
# subcommands
# --------------------------------------------------------------------------
def cmd_init(a):
    run = Path(a.run)
    errors = []
    for d in ("lanes", "prompts", "envelopes", "falsifiers", "codex", "inputs"):
        (run / d).mkdir(parents=True, exist_ok=True)
    ctx = run / "inputs" / "context.md"
    if not ctx.is_file() or not ctx.read_text(encoding="utf-8").strip():
        errors.append("inputs/context.md missing or empty")
    gates = read_json(run / "inputs" / "gates.json")
    if not isinstance(gates, dict):
        errors.append("inputs/gates.json missing or not an object")
    if errors:
        return emit({"ok": False, "errors": errors}, False)

    write(run / "inputs" / "root.txt", a.root)
    learnings = learnings_paths(a.skill_dir)
    write(run / "inputs" / "learnings.txt", "\n".join(learnings))

    decisions_ok = False
    note = "skipped (no sid)"
    if a.sid:
        sessions = [Path(a.root) / ".claude/skills/claude-sessions/sessions.py",
                    Path(os.path.expanduser("~/.claude/skills/claude-sessions/sessions.py"))]
        script = next((p for p in sessions if p.is_file()), None)
        raw = run / "inputs" / "session-decisions.raw.json"
        if script is not None:
            rc, _, err = run_cmd(["python3", str(script), "extract-decisions", "--sid", a.sid, "--output", str(raw)], cwd=a.root, timeout=120)
            decisions_ok = rc == 0 and raw.is_file() and raw.stat().st_size > 2
            note = "ok" if decisions_ok else f"skipped (extract-decisions rc={rc}: {err[:120]})"
        else:
            note = "skipped (claude-sessions skill not found)"

    pre = ["# Mechanical pre-filter (script, inline, cheap)"]
    rc, out, err = run_cmd(["git", "-C", a.root, "fetch", "origin"], timeout=90)
    pre.append(f"- git fetch origin: {'ok' if rc == 0 else 'FAILED: ' + err[:120]}")
    rc, out, _ = run_cmd(["git", "-C", a.root, "merge-base", "origin/main", "HEAD"])
    pre.append(f"- merge-base origin/main HEAD: {out if rc == 0 else 'unavailable'}")
    rc, out, err = run_cmd(["gh", "pr", "list", "--state", "open", "--limit", "30", "--json", "number,title,headRefName"], cwd=a.root, timeout=60)
    pre.append(f"- open PRs (<=30): {out[:3000] if rc == 0 else 'unavailable: ' + err[:100]}")
    write(run / "inputs" / "prefilter.md", "\n".join(pre) + "\n")

    manifest = load_manifest()
    context = ctx.read_text(encoding="utf-8").strip()
    miners = ["context-dossier-miner"] + (["design-decisions-extractor"] if decisions_ok else [])
    for label in miners:
        e = entry_by_label(manifest, label)
        tpl = (PROMPTS_DIR / e["prompt"]).read_text(encoding="utf-8")
        role_line(tpl, label)
        values = {"SPEC_PATH": a.spec, "PROJECT_ROOT": a.root, "CONTEXT_BLOCK": context,
                  "DECISIONS_JSON_PATH": str(run / "inputs" / "session-decisions.raw.json"), "RUNTIME": a.runtime}
        body = fill(extract_body(tpl), values)
        if label == "context-dossier-miner":
            contract = f"""

## Run contract (added by the pipeline script -- binding)
- Also read {run}/inputs/prefilter.md (merge-base pin + open PRs) and treat it as resolved ground truth.
- Write your full dossier (the "Output format" section above, including its generated questions) to {run}/dossier.md.
- Write {run}/questions.json: a JSON array of 8-15 objects {{"id": "Q1", "lane": "<tag>", "text": "<question>"}}, where <tag> is exactly one of
  completeness, codebase, architecture, provider-fit, edge-case, security, observability, drift, live-evidence, codex-adversarial.
- Final reply: StructuredOutput with ok and the question count. You are a leaf agent -- spawn no sub-agents or Workflows.
"""
        else:
            contract = f"""

## Run contract (added by the pipeline script -- binding)
- Write your result to {run}/decisions.json as ONE JSON object with array-valued keys decisions, rejected_alternatives,
  corrections, scope_boundaries, open_concerns, requirements, gaps; each item {{"text": "...", "evidence": "..."}}.
  This replaces the markdown output format above; the content rules are unchanged.
- Final reply: StructuredOutput with ok. You are a leaf agent -- spawn no sub-agents or Workflows.
"""
        text = f"ROLE: {label}\n{body}{contract}"
        left = find_placeholders(text)
        if left:
            errors.append(f"{label}: unfilled placeholders {sorted(set(left))}")
        write(run / "prompts" / f"{label}.md", text)
    if errors:
        return emit({"ok": False, "errors": errors}, False)
    return emit({"ok": True, "decisions": decisions_ok, "decisionsNote": note, "miners": miners, "learnings": learnings})


def cmd_lanes(a):
    run = Path(a.run)
    manifest = load_manifest()
    errors = []
    try:
        dossier = run / "dossier.md"
        if not dossier.is_file() or dossier.stat().st_size < 200:
            raise StageError("dossier.md missing or under 200 bytes -- the miner did not deliver")
        questions = load_questions(run)
        labels = csv(a.lanes)
        entries = [entry_by_label(manifest, l) for l in labels]
        subs = [e for e in entries if e.get("substituteFor")]
        regular = [e for e in entries if not e.get("substituteFor")]
        assign_path = run / "assignments.json"
        assignments = read_json(assign_path, {}) if assign_path.is_file() else {}
        if regular:
            fresh = assign_questions(questions, regular)
            assignments.update({k: [q["id"] for q in v] for k, v in fresh.items()})
        for e in subs:
            assignments[e["label"]] = list(assignments.get(e["substituteFor"], []))
        write(assign_path, json.dumps(assignments, indent=1))
        by_id = {q["id"]: q for q in questions}
        root = (run / "inputs" / "root.txt").read_text(encoding="utf-8").strip()
        spec = a.spec
        spec_rel = os.path.relpath(spec, root) if os.path.isabs(spec) else spec
        claude, codex_rows = [], []
        for e in entries:
            label = e["label"]
            qs = [by_id[i] for i in assignments.get(label, []) if i in by_id]
            if e["kind"] == "codex":
                tpl = (PROMPTS_DIR / e["prompt"]).read_text(encoding="utf-8")
                role_line(tpl, label)
                values = {"SPEC_PATH_REL": spec_rel, "DOSSIER_PATH": str(dossier), "FOCUS_TEXT": focus_text(qs)}
                text = f"ROLE: {label}\n" + fill(extract_body(tpl), values) + "\n"
                left = find_placeholders(text)
                if left:
                    errors.append(f"{label}: unfilled placeholders {sorted(set(left))}")
                write(run / "codex" / f"{label}.prompt.md", text)
                codex_rows.append((label, e["codexClass"], run / "codex" / f"{label}.prompt.md", run / "codex" / f"{label}.out.md"))
                continue
            if e.get("prompt"):
                tpl = (PROMPTS_DIR / e["prompt"]).read_text(encoding="utf-8")
                role_line(tpl, label)
                values = {
                    "SPEC_PATH": spec, "PROJECT_ROOT": root,
                    "DOSSIER_CONTENT": f"(shared file -- read {run}/dossier.md in full; design decisions in {run}/decisions.json if present)",
                    "CONTEXT_BLOCK": (run / "inputs" / "context.md").read_text(encoding="utf-8").strip(),
                    "GOAL": f"see the Goal line of {run}/inputs/context.md", "TRIGGER": f"see the Trigger line of {run}/inputs/context.md",
                    "TARGET_OUTCOME": f"see the Target outcome line of {run}/inputs/context.md",
                    "OUT_OF_SCOPE": f"see the Scope boundaries line of {run}/inputs/context.md",
                }
                body = fill(extract_body(tpl), values)
            else:
                body = (e["brief"].replace("{{SPEC_PATH}}", spec).replace("{{PROJECT_ROOT}}", root))
            text = f"ROLE: {label}\n{body}" + run_contract(run, e, qs)
            left = find_placeholders(text)
            if left:
                errors.append(f"{label}: unfilled placeholders {sorted(set(left))}")
            write(run / "prompts" / f"{label}.md", text)
            claude.append(label)
        if codex_rows:
            write(run / "codex" / "plan.tsv", "".join(f"{l}\t{c}\t{p}\t{o}\n" for l, c, p, o in codex_rows))
    except StageError as e:
        errors.append(str(e))
        return emit({"ok": False, "errors": errors}, False)
    if errors:
        return emit({"ok": False, "errors": errors}, False)
    return emit({"ok": True, "claude": claude, "codex": [r[0] for r in codex_rows],
                 "assignments": {k: v for k, v in assignments.items() if k in labels}})


def cmd_drift_briefs(a):
    run = Path(a.run)
    manifest = load_manifest()
    scout = read_json(run / "envelopes" / "spec-drift-scout.json", {})
    items = scout.get("drift_investigations") or []
    if not items:
        return emit({"ok": True, "briefs": [], "dropped": 0})
    e = entry_by_label(manifest, INVESTIGATOR)
    tpl = (PROMPTS_DIR / e["prompt"]).read_text(encoding="utf-8")
    role_line(tpl, INVESTIGATOR)
    body = extract_body(tpl)
    root = (run / "inputs" / "root.txt").read_text(encoding="utf-8").strip()
    briefs, errors = [], []
    for it in items[:5]:
        did = str(it.get("drift_id", "")).strip()
        if not did:
            errors.append(f"drift_investigations entry without drift_id: {it!r}")
            continue
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", did)
        label = f"{INVESTIGATOR}-{safe}"
        scout_file = run / "lanes" / "spec-drift-scout.md"
        values = {"SPEC_PATH": a.spec, "PROJECT_ROOT": root, "DRIFT_ID": did,
                  "SCOUT_FINDING": f"the {did} row in {scout_file} (read that row only)",
                  "TARGETED_PATHS": f"the paths/worktrees/specs named in the {did} row of {scout_file}",
                  "NARROW_QUESTION": str(it.get("narrow_question") or f"resolve {did} as the scout's row asks")}
        note = f"Use ids DI-1, DI-2, ... in file order (the scout already owns the {did} id)."
        text = f"ROLE: {INVESTIGATOR}\n" + fill(body, values) + run_contract(run, e, [], label=label, ids_note=note)
        left = find_placeholders(text)
        if left:
            errors.append(f"{label}: unfilled placeholders {sorted(set(left))}")
        write(run / "prompts" / f"{label}.md", text)
        briefs.append(label)
    if errors:
        return emit({"ok": False, "errors": errors}, False)
    return emit({"ok": True, "briefs": briefs, "dropped": max(0, len(items) - 5)})


def read_envelope(run, label):
    env = read_json(Path(run) / "envelopes" / f"{label}.json")
    if not isinstance(env, dict):
        return None, "missing or unparsable"
    if not isinstance(env.get("answered_questions"), list) or not isinstance(env.get("findings"), list):
        return None, "answered_questions/findings missing"
    for f in env["findings"]:
        if not isinstance(f, dict) or not f.get("id") or f.get("severity") not in SEVERITIES or not f.get("title"):
            return None, f"malformed finding {f!r}"
    return env, None


def cmd_check_envelopes(a):
    run = Path(a.run)
    assignments = read_json(run / "assignments.json", {})
    codex = set(csv(a.codex))
    missing, invalid, unanswered, warn, ids = [], [], {}, {}, {}
    findings = {}
    for label in expand_labels(run, csv(a.lanes)):
        env, err = read_envelope(run, label)
        if env is None:
            (missing if err.startswith("missing or") else invalid).append(f"{label}: {err}")
            continue
        for f in env["findings"]:
            if f["id"] in ids:
                invalid.append(f"{label}: finding id {f['id']} already used by {ids[f['id']]}")
            ids[f["id"]] = label
        findings[label] = [{"id": f["id"], "severity": f["severity"]} for f in env["findings"]]
        gap = [q for q in assignments.get(label, []) if q not in env["answered_questions"]]
        if gap:
            (warn if label in codex else unanswered)[label] = gap
    ok = not (invalid or unanswered)
    return emit({"ok": ok, "missing": missing, "invalid": invalid, "unanswered": unanswered,
                 "codexUnanswered": warn, "errors": invalid + [f"{k}: unanswered {v}" for k, v in unanswered.items()],
                 "criticalMajor": {l: [f["id"] for f in fs if f["severity"] in FALSIFIED] for l, fs in findings.items()}}, ok)


def cmd_codex_status(a):
    rows = {}
    p = Path(a.run) / "codex" / "status.tsv"
    if p.is_file():
        for line in p.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t")
            if len(parts) >= 3:
                rows[parts[0]] = {"status": parts[1], "bytes": int(parts[2]) if parts[2].isdigit() else 0}
    return emit({"ok": True, "lanes": rows})


def all_critical_major(run, labels):
    out = []
    for label in labels:
        env, _ = read_envelope(run, label)
        if env:
            out += [{"lane": label, **f} for f in env["findings"] if f["severity"] in FALSIFIED]
    return out


STOP = set("the a an and or of to in on for with is are be by at as it its this that not no from into than then when what which does do did has have had can will would should must may via per vs all any each only one two new old own more less over under".split())
STRONG_RE = re.compile(r"^(?:[a-z]+-\d+|[\w.-]*[_/][\w./-]*|[\w-]+\.[a-z]{1,4})$", re.I)


def title_tokens(title):
    toks = [t.strip(".,;:()[]'\"`") for t in re.split(r"\s+", title.lower())]
    toks = [t for t in toks if len(t) >= 3 and t not in STOP]
    return set(toks), {t for t in toks if STRONG_RE.match(t)}


def cluster_findings(findings):
    """Union near-duplicate findings across lanes (overlapping title tokens or shared
    identifiers/paths). Every original id stays in its cluster -- nothing is dropped."""
    toks = [title_tokens(f["title"]) for f in findings]
    parent = list(range(len(findings)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(findings)):
        for j in range(i + 1, len(findings)):
            (ai, si), (aj, sj) = toks[i], toks[j]
            union = len(ai | aj) or 1
            jac = len(ai & aj) / union
            if jac >= 0.5 or (len(si & sj) >= 3 and jac >= 0.25):
                parent[find(j)] = find(i)
    groups = {}
    for i, f in enumerate(findings):
        groups.setdefault(find(i), []).append(i)
    clusters = []
    for idxs in groups.values():
        members = [findings[i] for i in idxs]
        counts = {}
        for i in idxs:
            for t in toks[i][1]:
                counts[t] = counts.get(t, 0) + 1
        paths = sorted(((c, t) for t, c in counts.items() if "/" in t or re.search(r"\.[a-z]{1,4}$", t)), reverse=True)
        strong = sorted(((c, t) for t, c in counts.items()), reverse=True)
        seam = (paths or strong or [(0, members[0]["lane"])])[0][1]
        clusters.append({"seam": seam, "ids": [m["id"] for m in members], "members": members})
    clusters.sort(key=lambda c: (-len(c["ids"]), c["ids"][0]))
    return clusters


def plan_batches(findings, max_batches=6):
    """Pack clusters into <= max_batches batches, keeping a seam together while it fits.
    Every id lands in exactly one batch."""
    if max_batches < 1:
        raise StageError("max-batches must be >= 1")
    clusters = cluster_findings(findings)
    total = sum(len(c["ids"]) for c in clusters)
    cap = -(-total // max_batches)
    batches = [{"ids": [], "clusters": [], "seams": []} for _ in range(max_batches)]
    for c in clusters:
        home = next((b for b in batches if c["seam"] in b["seams"] and len(b["ids"]) + len(c["ids"]) <= cap * 3 // 2), None)
        target = home or min(batches, key=lambda b: (len(b["ids"]), batches.index(b)))
        target["ids"] += c["ids"]
        target["clusters"].append(c["ids"])
        if c["seam"] not in target["seams"]:
            target["seams"].append(c["seam"])
    out = [b for b in batches if b["ids"]]
    flat = [i for b in out for i in b["ids"]]
    if sorted(flat) != sorted(f["id"] for f in findings):
        raise StageError("batch plan does not cover every id exactly once")
    return out


def cmd_falsify_plan(a):
    run = Path(a.run)
    a.lanes = ",".join(expand_labels(run, csv(a.lanes)))
    manifest = load_manifest()
    root = (run / "inputs" / "root.txt").read_text(encoding="utf-8").strip()
    e = entry_by_label(manifest, "finding-falsifier")
    tpl = (PROMPTS_DIR / e["prompt"]).read_text(encoding="utf-8")
    role_line(tpl, "finding-falsifier")
    body = extract_body(tpl)
    findings = all_critical_major(run, csv(a.lanes))
    batches = plan_batches(findings, int(a.max_batches or 6))
    by_id = {f["id"]: f for f in findings}
    plan, errors = [], []
    for n, b in enumerate(batches, 1):
        items = "\n".join(
            f"    - {i} [{by_id[i]['lane']}, {by_id[i]['severity']}] {by_id[i]['title']}  (full finding: {lane_file(manifest, run, by_id[i]['lane'])}, find it by its id)"
            for i in b["ids"])
        dupes = "\n".join("    - " + ", ".join(c) for c in b["clusters"] if len(c) > 1) or "    (none)"
        values = {"LANE": "several -- see the batch list", "SEVERITY": "per item below",
                  "FINDING_TEXT": f"a BATCH of {len(b['ids'])} findings, each judged separately:\n{items}",
                  "CITED_EVIDENCE": "as cited in each finding inside its lane file",
                  "PROPOSED_FIX": "as proposed in each finding inside its lane file",
                  "SPEC_PATH": a.spec, "PROJECT_ROOT": root}
        text = "ROLE: finding-falsifier\n" + fill(body, values) + f"""

## Run contract (added by the pipeline script -- binding)
- This is batch {n} of {len(batches)}: {len(b['ids'])} findings grouped by seam. Try to defeat EACH id separately and give EACH its own verdict; never merge or skip an id.
  Near-duplicate clusters inside the batch (same seam; you may share evidence, not verdicts):
{dupes}
- Read ONLY the listed findings in their lane files, never another lane's output.
- Write your full reasoning to {run}/falsifiers/batch-{n}.md, and ONE file per id, {run}/falsifiers/<id with any char outside A-Za-z0-9_.- replaced by _>.json:
  {{"id": "<id>", "verdict": "REFUTED|SURVIVES|SURVIVES-BUT-FIX-REJECTED|NEEDS-LIVE-EVIDENCE", "evidence": "<one line>"}}.
- Final reply: {{"verdicts": [that object for every id in the batch]}} via StructuredOutput. You are a leaf agent -- spawn no sub-agents or Workflows.
"""
        left = find_placeholders(text)
        if left:
            errors.append(f"batch {n}: unfilled placeholders {sorted(set(left))}")
        path = run / "prompts" / f"falsifier-batch-{n}.md"
        if not a.dry:
            write(path, text)
        plan.append({"batch": n, "ids": b["ids"], "clusters": b["clusters"], "seams": b["seams"], "prompt": str(path)})
    if errors:
        return emit({"ok": False, "errors": errors}, False)
    return emit({"ok": True, "totalIds": len(findings), "plan": plan})


def falsifier_counts(run, expected_ids):
    verdicts = {}
    for i in expected_ids:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", i)
        v = read_json(Path(run) / "falsifiers" / f"{safe}.json")
        verdicts[i] = (v or {}).get("verdict", "MISSING")
    refuted = sum(1 for v in verdicts.values() if v == "REFUTED")
    return verdicts, refuted


def cmd_summary(a):
    run = Path(a.run)
    labels = expand_labels(run, csv(a.lanes))
    cm = all_critical_major(run, labels)
    verdicts, refuted = falsifier_counts(run, [f["id"] for f in cm])
    raw = {"CRITICAL": 0, "MAJOR": 0, "MINOR": 0}
    surviving = {"CRITICAL": 0, "MAJOR": 0}
    for label in labels:
        env, _ = read_envelope(run, label)
        for f in (env or {"findings": []})["findings"]:
            if f["severity"] in raw:
                raw[f["severity"]] += 1
    for f in cm:
        if verdicts.get(f["id"]) != "REFUTED":
            surviving[f["severity"]] += 1
    adr, _ = read_envelope(run, "adr-auditor")
    hard = False
    if adr is not None:
        data = read_json(Path(run) / "envelopes" / "adr-auditor.json", {})
        hard = bool(data.get("founder_approval_needed")) and not bool(data.get("founder_approval_marker_present"))
    missing = [i for i, v in verdicts.items() if v == "MISSING"]
    return emit({"ok": True, "raw": raw, "surviving": surviving, "falsifierDispatched": sum(1 for v in verdicts.values() if v != "MISSING"),
                 "refuted": refuted, "missingVerdicts": missing, "hardStop": hard})


def cmd_check_report(a):
    run = Path(a.run)
    sys.path.insert(0, str(SKILL_DIR / "scripts"))
    import validate_review_report as vrr

    report = run / "report.md"
    errors = []
    if not report.is_file():
        return emit({"ok": False, "errors": ["report.md missing"]}, False)
    text = report.read_text(encoding="utf-8")
    if len(text) < 500:
        errors.append("report.md is under 500 chars -- synthesis did not write the report")
    ok, failures, _ = vrr.validate(text)
    errors += [f"validator: {f}" for f in failures]
    labels = expand_labels(run, csv(a.lanes))
    cm = all_critical_major(run, labels)
    for f in cm:
        if not re.search(r"(?<![A-Za-z0-9-])" + re.escape(f["id"]) + r"(?![A-Za-z0-9])", text):
            errors.append(f"envelope {f['severity']} id {f['id']} (lane {f['lane']}) is missing from report.md")
    leftovers = find_placeholders(text)
    if leftovers:
        errors.append(f"report.md has unfilled placeholders {sorted(set(leftovers))}")
    for label in csv(a.manifest):
        lines = [l for l in text.splitlines() if re.search(r"(?<![A-Za-z0-9-])" + re.escape(label) + r"(?![A-Za-z0-9-])", l)]
        if not lines:
            errors.append(f"lane manifest: {label} is not listed in report.md")
    for label in csv(a.skipped):
        if not any("SKIPPED (gate:" in l for l in text.splitlines() if label in l):
            errors.append(f"lane manifest: {label} must appear as 'SKIPPED (gate: <reason>)'")
    frontier = [l for l in ("codex-frontier", "critic-frontier") if (run / "envelopes" / f"{l}.json").is_file()]
    if not frontier:
        errors.append("Astra frontier lane: neither codex-frontier nor critic-frontier produced an envelope")
    verdicts, refuted = falsifier_counts(run, [f["id"] for f in cm])
    n, m = len(cm), len(cm)
    line = f"{n} dispatched over {m} CRITICAL/MAJOR"
    if not re.search(re.escape(line) + r"[^\n]*?\b" + str(refuted) + r"\s+REFUTED,\s*" + str(n - refuted) + r"\s+SURVIVES", text, re.I):
        errors.append(f"falsifier line must read '{line} — {refuted} REFUTED, {n - refuted} SURVIVES.'")
    miss = [i for i, v in verdicts.items() if v == "MISSING"]
    if miss:
        errors.append(f"falsifier verdict files missing for {miss}")
    if not errors and a.publish:
        write(a.publish, text)
    return emit({"ok": not errors, "errors": errors, "falsifierLine": f"{n} dispatched over {m} CRITICAL/MAJOR — {refuted} REFUTED, {n - refuted} SURVIVES."}, not errors)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, *flags):
        p = sub.add_parser(name)
        p.add_argument("--run", required=True)
        for f in flags:
            p.add_argument(f"--{f}", default="")
        p.set_defaults(fn=fn)
        return p

    add("init", cmd_init, "spec", "root", "sid", "runtime", "skill-dir")
    add("lanes", cmd_lanes, "spec", "lanes")
    add("check-envelopes", cmd_check_envelopes, "lanes", "codex")
    add("codex-status", cmd_codex_status)
    add("drift-briefs", cmd_drift_briefs, "spec")
    p = add("falsify-plan", cmd_falsify_plan, "lanes", "spec", "max-batches")
    p.add_argument("--dry", action="store_true", help="print the plan without writing prompts")
    add("summary", cmd_summary, "lanes")
    add("check-report", cmd_check_report, "lanes", "manifest", "skipped", "publish")
    a = ap.parse_args(argv)
    a.skill_dir = getattr(a, "skill_dir", "") or str(SKILL_DIR)
    a.runtime = getattr(a, "runtime", "") or "claude"
    try:
        return a.fn(a)
    except StageError as e:
        return emit({"ok": False, "errors": [str(e)]}, False)


if __name__ == "__main__":
    sys.exit(main())
