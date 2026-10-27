#!/usr/bin/env python3
"""spec-review run-dir helper: the deterministic half of the Workflow pipeline.

A Workflow script has no filesystem access and no shell, so every file-shaped job (fill a prompt
template, validate an envelope, check the report) is a subcommand here, run by the MAIN loop with the
Bash tool between Workflow stages. No LLM agent exists just to run a command. Static lane data
(agent type, id prefix, question tags, prompt file) is read from lanes.json (plus the
optional per-repo override), resolved once by `plan` into <run>/manifest.json -- the one manifest.

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
import copy
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
LANES_JSON = SKILL_DIR / "lanes.json"
OVERRIDE_REL = ".claude/spec-review.lanes.json"
RETUNABLE = ("model", "profiles", "codexClass")
PROMPTS_DIR = SKILL_DIR / "prompts"

SEVERITIES = ("CRITICAL", "MAJOR", "MINOR", "ELEVATE", "CAUTION")
FALSIFIED = ("CRITICAL", "MAJOR")
# Per-tier falsifier scope (budget.falsifier): which severities get a falsifier verdict.
# "uncorroborated": every CRITICAL, plus each MAJOR unit that only ONE lane raised (a MAJOR a second
# lane also raised is corroborated and skips the falsifier). "all" is every CRITICAL/MAJOR.
FALSIFIER_MODES = {"all": FALSIFIED, "uncorroborated": FALSIFIED, "critical": ("CRITICAL",), "off": ()}
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
def load_manifest(run=None):
    """The run's resolved manifest (written by `plan`), else the shipped default lanes.json."""
    if run and (Path(run) / "manifest.json").is_file():
        return json.loads((Path(run) / "manifest.json").read_text(encoding="utf-8"))
    return json.loads(LANES_JSON.read_text(encoding="utf-8"))


def validate_manifest(m, prompts_dir=PROMPTS_DIR):
    """One schema for the shipped manifest and the override-merged one."""
    errors = []
    profiles, gates = m.get("profiles", []), m.get("gates", [])
    labels = [e.get("label") for e in m.get("lanes", [])]
    if len(labels) != len(set(labels)):
        errors.append("duplicate lane labels")
    prefixes = [e.get("idPrefix") for e in m.get("lanes", []) if not e.get("substituteFor")]
    for e in m.get("lanes", []):
        who = e.get("label", "?")
        if e.get("kind") not in ("claude", "codex", "critic"):
            errors.append(f"{who}: kind must be claude|codex|critic")
        if not e.get("agentType") or not e.get("idPrefix"):
            errors.append(f"{who}: agentType and idPrefix are required")
        if not set(e.get("profiles", [])) <= set(profiles):
            errors.append(f"{who}: profiles must be a subset of {profiles}")
        if e.get("gate") is not None and e["gate"] not in gates:
            errors.append(f"{who}: unknown gate {e['gate']}")
        if e.get("prompt"):
            if not (Path(prompts_dir) / e["prompt"]).is_file():
                errors.append(f"{who}: prompt file {e['prompt']} not found")
        elif not e.get("brief"):
            errors.append(f"{who}: needs a prompt file or an inline brief")
    if len(prefixes) != len(set(prefixes)):
        errors.append("duplicate idPrefix")
    for name, t in m.get("tiers", {}).items():
        if t.get("profile") not in profiles:
            errors.append(f"tier {name}: profile {t.get('profile')} is not declared")
        b = t.get("budget", {})
        if b.get("falsifier") not in FALSIFIER_MODES:
            errors.append(f"tier {name}: budget.falsifier must be one of {sorted(FALSIFIER_MODES)}")
        for k in ("maxLanes", "maxCodexLanes", "tokenCeiling"):
            if not isinstance(b.get(k), int) or b[k] < 0:
                errors.append(f"tier {name}: budget.{k} must be a non-negative integer")
    for e in (x for x in m.get("lanes", []) if x.get("floor")):
        missing = [p for p in profiles if p not in e.get("profiles", [])]
        if missing:
            errors.append(f"{e['label']}: floor lane must run in every profile (missing {missing})")
    return errors


def merge_override(base, ov):
    """Apply <root>/.claude/spec-review.lanes.json over the default: add / disable / retune lanes,
    budget dials per tier. Returns (manifest, errors)."""
    m, errors = copy.deepcopy(base), []
    if not isinstance(ov, dict) or set(ov) - {"lanes", "tiers"}:
        return m, ["override must be an object with only 'lanes' and 'tiers'"]
    lanes, by = ov.get("lanes", {}), {e["label"]: e for e in m["lanes"]}
    if set(lanes) - {"add", "disable", "retune"}:
        errors.append("override.lanes accepts only add, disable, retune")
    for label in lanes.get("disable", []):
        e = by.get(label)
        if not e:
            errors.append(f"disable: unknown lane {label}")
        elif e.get("floor") or e.get("gate") or e.get("substituteFor"):
            errors.append(f"disable: {label} is non-droppable (floor, domain-gate or substitute lane)")
    m["lanes"] = [e for e in m["lanes"] if e["label"] not in lanes.get("disable", [])]
    for label, changes in lanes.get("retune", {}).items():
        e = by.get(label)
        if not e or label in lanes.get("disable", []):
            errors.append(f"retune: unknown or disabled lane {label}")
        elif set(changes) - set(RETUNABLE):
            errors.append(f"retune {label}: only {list(RETUNABLE)} may change")
        else:
            e.update(changes)
    for e in lanes.get("add", []):
        if e.get("label") in by:
            errors.append(f"add: lane {e.get('label')} already exists (use retune)")
        elif e.get("kind") != "claude" or e.get("prompt") or e.get("substituteFor") or e.get("floor"):
            errors.append(f"add {e.get('label')}: only kind=claude lanes with an inline brief may be added")
        else:
            m["lanes"].append(e)
            by[e["label"]] = e
    for name, t in ov.get("tiers", {}).items():
        if name not in m["tiers"] or set(t) - {"budget"}:
            errors.append(f"tiers.{name}: unknown tier or non-budget key")
        else:
            m["tiers"][name]["budget"].update(t["budget"])
    return m, errors


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
    severities = entry.get("severities", "CRITICAL|MAJOR|MINOR")
    handoffs = (', "research_handoffs": [{"id": "' + prefix + '-H1", "question": "<one narrow question for the investigation lane>"}]'
                if entry.get("researchHandoffs") else "")
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
     "answered_questions": ["Q1", ...], "findings": [{{"id": "...", "severity": "{severities}", "title": "<one line>", "cites": ["<path:line>", ...]}}]{handoffs}}}.
     One entry per finding in your file -- including every CRITICAL and MAJOR. {ids_note}
  3. Your final reply is that same envelope via StructuredOutput (ids, severities, one-line titles; no finding bodies).
"""


# --------------------------------------------------------------------------
# questions
# --------------------------------------------------------------------------
def lane_values(run, spec, root):
    """Placeholder values every lane brief may use, whichever runtime executes it."""
    return {
        "SPEC_PATH": spec, "PROJECT_ROOT": root,
        "ARCH_LENS_PATH": str(SKILL_DIR.parent / "improve-codebase-architecture" / "SKILL.md"),
        "LEARNINGS_LIST": f"{run}/inputs/learnings.txt",
        "DOSSIER_CONTENT": f"(shared file -- read {run}/dossier.md in full; design decisions in {run}/decisions.json if present)",
        "CONTEXT_BLOCK": (Path(run) / "inputs" / "context.md").read_text(encoding="utf-8").strip(),
        "GOAL": f"see the Goal line of {run}/inputs/context.md", "TRIGGER": f"see the Trigger line of {run}/inputs/context.md",
        "TARGET_OUTCOME": f"see the Target outcome line of {run}/inputs/context.md",
        "OUT_OF_SCOPE": f"see the Scope boundaries line of {run}/inputs/context.md",
    }


def codex_contract(run, entry, questions, spec):
    """Delivery contract for a brief authored for a Claude lane but executed by Codex: Codex
    cannot write the run dir, so its final message is the deliverable and an extractor builds
    the envelope from it."""
    qlines = "\n".join(f"  - {q['id']}: {q['text']}" for q in questions) or "  (none assigned)"
    return f"""
## Run contract (added by the pipeline script -- binding; it overrides any delivery or tool instructions above)
- You run as a Codex lane, read-only. Ignore instructions above about agent types, sub-agents, or writing files: your FINAL MESSAGE is the complete deliverable, in the output format the brief specifies.
- The spec is {spec} (relative paths resolve from the repository root, your working directory). Read it, the shared dossier {run}/dossier.md and the design decisions {run}/decisions.json (if present). Inspect the repository with shell reads only.
- Number your findings {entry.get('idPrefix', 'F')}-1, {entry.get('idPrefix', 'F')}-2, ... and give each a severity CRITICAL, MAJOR or MINOR and a file:line citation.
- Assigned review questions -- answer EVERY one, citing its Q-id:
{qlines}
"""


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
DOSSIER_QUESTION_TAGS = ("completeness", "codebase", "architecture", "provider-fit", "edge-case", "security",
                         "observability", "drift", "live-evidence", "codex-adversarial", "system1")
DECISION_KEYS = ("decisions", "rejected_alternatives", "corrections", "scope_boundaries", "open_concerns", "requirements", "gaps")
QUESTIONS_MARK = "===QUESTIONS_JSON==="
MIN_CODEX_DOSSIER = 1500

CODEX_DOSSIER_CONTRACT = """

## Run contract (added by the pipeline script -- binding; it overrides any delivery or tool instructions above)
- You run as a Codex lane, read-only: you cannot write files, and your FINAL MESSAGE is the deliverable. The spec is {spec} (relative paths resolve from the repository root, your working directory). Also read {run}/inputs/prefilter.md (merge-base pin + open PRs) as resolved ground truth.
- No MCP tools exist for you. Reach the tracker through the shell route docs/agents/issue-tracker.md names (CLI or GraphQL), plus the version-control CLI and gh. If the tracker cannot be reached, write "Tracker lineage: UNREACHABLE (<why>)" in the dossier; never guess a ticket body.
- FINAL MESSAGE layout: the complete dossier (the "Output format" section above, including its generated questions), then one line containing exactly {mark}, then ONE JSON array of 8-15 objects {{"id": "Q1", "lane": "<tag>", "text": "<question>"}} where <tag> is exactly one of {tags}. Nothing after the JSON array.
"""

CODEX_DECISIONS_CONTRACT = """

## Run contract (added by the pipeline script -- binding; it overrides any delivery or tool instructions above)
- You run as a Codex lane, read-only: your FINAL MESSAGE is the deliverable. Read {run}/inputs/session-decisions.raw.json.
- FINAL MESSAGE: ONE JSON object and nothing else, with array-valued keys decisions, rejected_alternatives, corrections, scope_boundaries, open_concerns, requirements, gaps; each item {{"text": "...", "evidence": "..."}}. This replaces the markdown output format above; the content rules are unchanged.
"""


def last_json(text, want=dict):
    """The last parseable JSON value of type `want` in a free-text message (fenced, bare or multi-line)."""
    t = re.sub(r"```(?:json)?", "", text or "")
    best, pos = None, 0
    dec = json.JSONDecoder()
    while True:
        m = re.compile(r"[\[{]").search(t, pos)
        if not m:
            return best
        try:
            v, end = dec.raw_decode(t[m.start():])
        except ValueError:
            pos = m.start() + 1
            continue
        if isinstance(v, want):
            best = v
        pos = m.start() + end


def validate_codex_questions(qs):
    if not isinstance(qs, list) or not 8 <= len(qs) <= 15:
        return "questions must be a JSON array of 8-15 objects"
    seen = set()
    for q in qs:
        if not isinstance(q, dict) or not q.get("id") or not q.get("text") or q.get("lane") not in DOSSIER_QUESTION_TAGS:
            return f"malformed question {q!r}"
        if q["id"] in seen:
            return f"duplicate question id {q['id']}"
        seen.add(q["id"])
    return None


def cmd_extract_finish(a):
    """Parse the Codex dossier + decisions outputs into dossier.md, questions.json, decisions.json.
    A lane that is not OK by artifact, or whose output fails validation, is listed in `fallback`:
    those (and only those) rerun as the Claude lane."""
    run = Path(a.run)
    status = {}
    sp = run / "codex" / "extract-status.tsv"
    if sp.is_file():
        for line in sp.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                status[parts[0]] = parts[1]
    wanted = [l for l in ("context-dossier-miner", "design-decisions-extractor")
              if (run / "codex" / f"{l}.prompt.md").is_file()]
    fallback, reasons, used = [], {}, []
    for label in wanted:
        out = run / "codex" / f"{label}.out.md"
        why = None
        if status.get(label) != "OK" or not out.is_file():
            why = f"codex status {status.get(label, 'NO-STATUS')}"
        else:
            text = out.read_text(encoding="utf-8", errors="replace")
            if label == "context-dossier-miner":
                head, sep, tail = text.partition(QUESTIONS_MARK)
                qs = last_json(tail, list) if sep else None
                why = None if sep else f"no {QUESTIONS_MARK} line"
                if not why and len(head.strip()) < MIN_CODEX_DOSSIER:
                    why = f"dossier under {MIN_CODEX_DOSSIER} bytes"
                if not why:
                    why = validate_codex_questions(qs)
                if not why:
                    write(run / "dossier.md", head.strip() + "\n")
                    write(run / "questions.json", json.dumps(qs, indent=1))
            else:
                obj = last_json(text, dict)
                if not obj or not any(isinstance(obj.get(k), list) for k in DECISION_KEYS):
                    why = "no decisions JSON object"
                else:
                    write(run / "decisions.json", json.dumps({k: obj.get(k) if isinstance(obj.get(k), list) else [] for k in DECISION_KEYS}, indent=1))
        if why:
            fallback.append(label)
            reasons[label] = why
        else:
            used.append(label)
    return emit({"ok": True, "codex": used, "fallback": fallback, "reasons": reasons})


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
        plan_gates = (read_json(run / "plan.json") or {}).get("gates")
        if isinstance(plan_gates, dict):
            gates = plan_gates
            write(run / "inputs" / "gates.json", json.dumps(gates))
        else:
            errors.append("inputs/gates.json missing and no plan.json to take the gates from")
    if errors:
        return emit({"ok": False, "errors": errors}, False)

    write(run / "inputs" / "root.txt", a.root)
    write(run / "inputs" / "sid.txt", a.sid or "")
    spec_abs = Path(a.spec) if os.path.isabs(a.spec) else Path(a.root) / a.spec
    write(run / "inputs" / "spec.snapshot.md", spec_abs.read_text(encoding="utf-8") if spec_abs.is_file() else "")
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

    manifest = load_manifest(a.run)
    context = ctx.read_text(encoding="utf-8").strip()
    miners = ["context-dossier-miner"] + (["design-decisions-extractor"] if decisions_ok else [])
    codex_rows = []
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
        if label == "context-dossier-miner":
            codex_contract_text = CODEX_DOSSIER_CONTRACT.format(run=run, spec=a.spec, mark=QUESTIONS_MARK, tags=", ".join(DOSSIER_QUESTION_TAGS))
            codex_class = "verify"
        else:
            codex_contract_text = CODEX_DECISIONS_CONTRACT.format(run=run)
            codex_class = "luna"
        write(run / "codex" / f"{label}.prompt.md", f"ROLE: {label}\n{body}{codex_contract_text}")
        codex_rows.append((label, codex_class, run / "codex" / f"{label}.prompt.md", run / "codex" / f"{label}.out.md"))
    if errors:
        return emit({"ok": False, "errors": errors}, False)
    write(run / "codex" / "extract.tsv", "".join(f"{l}\t{c}\t{pp}\t{o}\n" for l, c, pp, o in codex_rows))
    return emit({"ok": True, "decisions": decisions_ok, "decisionsNote": note, "miners": miners, "learnings": learnings})


def delta_block(run, label):
    """On a delta re-review, inputs/delta.md names the changed spec sections; each re-run lane's brief gets it."""
    p = Path(run) / "inputs" / "delta.md"
    if not p.is_file():
        return ""
    extra = Path(run) / "inputs" / "delta-lanes" / f"{label}.md"
    own = extra.read_text(encoding="utf-8") if extra.is_file() else ""
    return "\n" + p.read_text(encoding="utf-8").rstrip() + "\n" + (own.rstrip() + "\n" if own else "")


def cmd_lanes(a):
    run = Path(a.run)
    manifest = load_manifest(a.run)
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
                values = {"SPEC_PATH_REL": spec_rel, "DOSSIER_PATH": str(dossier), "FOCUS_TEXT": focus_text(qs), **lane_values(run, spec, root)}
                text = f"ROLE: {label}\n" + fill(extract_body(tpl), values) + "\n"
                if e.get("codexContract"):
                    text += codex_contract(run, e, qs, spec_rel)
                text += delta_block(run, label)
                left = find_placeholders(text)
                if left:
                    errors.append(f"{label}: unfilled placeholders {sorted(set(left))}")
                write(run / "codex" / f"{label}.prompt.md", text)
                codex_rows.append((label, e["codexClass"], run / "codex" / f"{label}.prompt.md", run / "codex" / f"{label}.out.md"))
                continue
            if e.get("prompt"):
                tpl = (PROMPTS_DIR / e["prompt"]).read_text(encoding="utf-8")
                role_line(tpl, label)
                body = fill(extract_body(tpl), lane_values(run, spec, root))
            else:
                body = (e["brief"].replace("{{SPEC_PATH}}", spec).replace("{{PROJECT_ROOT}}", root))
            text = f"ROLE: {label}\n{body}" + run_contract(run, e, qs) + delta_block(run, label)
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
    manifest = load_manifest(a.run)
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


def envelope_error(env):
    if not isinstance(env, dict):
        return "missing or unparsable"
    if not isinstance(env.get("answered_questions"), list) or not isinstance(env.get("findings"), list):
        return "answered_questions/findings missing"
    for f in env["findings"]:
        if not isinstance(f, dict) or not f.get("id") or f.get("severity") not in SEVERITIES or not f.get("title"):
            return f"malformed finding {f!r}"
    return None


def read_envelope(run, label):
    env = read_json(Path(run) / "envelopes" / f"{label}.json")
    err = envelope_error(env)
    return (None, err) if err else (env, None)


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


def codex_status_rows(run, name="status.tsv"):
    """{lane: {status, bytes}} from a run-codex-lanes.sh status file (graded by artifact, never exit code)."""
    rows = {}
    p = Path(run) / "codex" / name
    if p.is_file():
        for line in p.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t")
            if len(parts) >= 3:
                rows[parts[0]] = {"status": parts[1], "bytes": int(parts[2]) if parts[2].isdigit() else 0}
    return rows


def falsifier_severities(run):
    """Severities the run's tier sends to the falsifier wave (plan.json budget.falsifier)."""
    plan = read_json(Path(run) / "plan.json")
    return FALSIFIER_MODES[plan["budget"]["falsifier"]] if isinstance(plan, dict) else FALSIFIED


def all_critical_major(run, labels, scoped=False):
    """Every CRITICAL/MAJOR envelope finding; scoped=True keeps only the tier's falsifier scope."""
    severities = falsifier_severities(run) if scoped else FALSIFIED
    out = []
    for label in labels:
        env, _ = read_envelope(run, label)
        if env:
            out += [{"lane": label, **f} for f in env["findings"] if f["severity"] in severities]
    return out


SEV_RANK = {"CRITICAL": 2, "MAJOR": 1}


def finding_index(findings):
    """Compact id list handed to the finding-merger (ids, lanes, severities, titles)."""
    return [{"id": f["id"], "lane": f["lane"], "severity": f["severity"], "title": f["title"],
             **({"cites": f["cites"]} if f.get("cites") else {})} for f in findings]


def validate_merged(merged, findings):
    """Normalize the merger's clusters into F-1..F-N units. Every CRITICAL/MAJOR id must be a
    member of exactly one cluster; severity is the max of the members'. Returns (units, errors)."""
    want = {f["id"]: f for f in findings}
    if not isinstance(merged, list) or not merged:
        return [], ["merged.json must be a non-empty JSON list of clusters"]
    seen, units, errors = {}, [], []
    for n, c in enumerate(merged, 1):
        uid = f"F-{n}"
        members = c.get("members") if isinstance(c, dict) else None
        if not isinstance(members, list) or not members:
            errors.append(f"{uid}: members must be a non-empty list of envelope ids")
            continue
        valid = []
        for m in members:
            m = str(m)
            if m not in want:
                errors.append(f"{uid}: member {m} is not a CRITICAL/MAJOR envelope id")
            elif m in seen:
                errors.append(f"{uid}: member {m} is already in {seen[m]}")
            else:
                seen[m] = uid
                valid.append(m)
        if not valid:
            continue
        units.append({"id": uid,
                      "severity": max((want[m]["severity"] for m in valid), key=SEV_RANK.get),
                      "title": str(c.get("title") or want[valid[0]]["title"]),
                      "seam": str(c.get("seam") or ""),
                      "members": valid,
                      "lanes": sorted({want[m]["lane"] for m in valid}),
                      # null until the fixing step records whether the finding changed the spec (mark-applied)
                      "applied": None,
                      "cites": [str(x) for x in (c.get("cites") or [])]})
    missing = [i for i in want if i not in seen]
    if missing:
        errors.append(f"CRITICAL/MAJOR ids in no cluster: {missing}")
    return units, errors


def falsifier_mode(run):
    plan = read_json(Path(run) / "plan.json")
    return plan["budget"]["falsifier"] if isinstance(plan, dict) else "all"


def unit_falsify(unit, mode):
    """Does this merged unit get a falsifier verdict? uncorroborated: every CRITICAL, and each MAJOR
    unit only ONE lane raised; a MAJOR a second lane also raised is corroborated and skips it."""
    if mode == "off":
        return False
    if mode == "uncorroborated":
        return unit["severity"] == "CRITICAL" or len(unit.get("lanes") or []) < 2
    return True


def falsified_ids(run, labels):
    """Envelope ids that get a falsifier verdict: the mode's universe, narrowed (after the merge) to
    the members of units with falsify true."""
    universe = all_critical_major(run, labels, scoped=True)
    units = load_units(run)
    if units is None:
        return [f["id"] for f in universe]
    keep = {m for u in units if u.get("falsify", True) for m in u["members"]}
    return [f["id"] for f in universe if f["id"] in keep]


def load_units(run):
    data = read_json(Path(run) / "merged.json")
    return data.get("units") if isinstance(data, dict) else None


def plan_batches(units, max_batches=6):
    """Pack merged units into <= max_batches batches, keeping a seam together while it fits.
    Every unit lands in exactly one batch."""
    if max_batches < 1:
        raise StageError("max-batches must be >= 1")
    cap = -(-len(units) // max_batches) if units else 0
    batches = [{"ids": [], "seams": []} for _ in range(max_batches)]
    for u in sorted(units, key=lambda u: (u["seam"], u["id"])):
        home = next((b for b in batches if u["seam"] and u["seam"] in b["seams"] and len(b["ids"]) < max(2, cap * 3 // 2)), None)
        target = home or min(batches, key=lambda b: (len(b["ids"]), batches.index(b)))
        target["ids"].append(u["id"])
        if u["seam"] and u["seam"] not in target["seams"]:
            target["seams"].append(u["seam"])
    out = [b for b in batches if b["ids"]]
    flat = [i for b in out for i in b["ids"]]
    if sorted(flat) != sorted(u["id"] for u in units):
        raise StageError("batch plan does not cover every unit exactly once")
    return out


def cmd_merge_check(a):
    run = Path(a.run)
    findings = all_critical_major(run, expand_labels(run, csv(a.lanes)), scoped=True)
    if not findings:
        write(run / "merged.json", json.dumps({"units": []}))
        return emit({"ok": True, "totalIds": 0, "clusters": 0})
    raw = read_json(run / "merged.raw.json")
    if raw is None:
        # The index goes to a file, never stdout: a 60+ id one-line JSON gets mangled when relayed
        # through a relay model, which made the whole stage fail (CYN-2850).
        idx = run / "merge-index.txt"
        write(idx, "\n".join(
            f"- {f['id']} [{f['lane']}, {f['severity']}] {f['title']}"
            + (f" (cites {', '.join(f['cites'])})" if f.get("cites") else "")
            for f in finding_index(findings)) + "\n")
        return emit({"ok": False, "errors": ["merged.raw.json missing"], "totalIds": len(findings), "indexPath": str(idx)}, False)
    units, errors = validate_merged(raw, findings)
    if errors:
        return emit({"ok": False, "errors": errors, "totalIds": len(findings)}, False)
    mode = falsifier_mode(run)
    for u in units:
        u["falsify"] = unit_falsify(u, mode)
    write(run / "merged.json", json.dumps({"units": units}, indent=1))
    return emit({"ok": True, "totalIds": len(findings), "clusters": len(units)})


def cmd_falsify_plan(a):
    run = Path(a.run)
    a.lanes = ",".join(expand_labels(run, csv(a.lanes)))
    manifest = load_manifest(a.run)
    root = (run / "inputs" / "root.txt").read_text(encoding="utf-8").strip()
    e = entry_by_label(manifest, "finding-falsifier")
    tpl = (PROMPTS_DIR / e["prompt"]).read_text(encoding="utf-8")
    role_line(tpl, "finding-falsifier")
    body = extract_body(tpl)
    findings = all_critical_major(run, csv(a.lanes), scoped=True)
    units = load_units(run)
    if units is None:
        raise StageError("merged.json missing: run merge-check before falsify-plan")
    lane_of = {f["id"]: f["lane"] for f in findings}
    units = [u for u in units if u.get("falsify", True)]
    by_unit = {u["id"]: u for u in units}
    batches = plan_batches(units, int(a.max_batches or 6))
    plan, errors = [], []
    for n, b in enumerate(batches, 1):
        items = []
        for uid in b["ids"]:
            u = by_unit[uid]
            where = "; ".join(f"{m} in {lane_file(manifest, run, lane_of[m])}" for m in u["members"])
            cites = f" cites: {', '.join(u['cites'])}." if u["cites"] else ""
            items.append(f"    - {uid} [{u['severity']}] {u['title']}  (merges {where}.{cites})")
        values = {"LANE": "several -- see the batch list", "SEVERITY": "per item below",
                  "FINDING_TEXT": f"a BATCH of {len(b['ids'])} merged findings, each judged separately:\n" + "\n".join(items),
                  "CITED_EVIDENCE": "as cited in each member finding inside its lane file",
                  "PROPOSED_FIX": "as proposed in each member finding inside its lane file",
                  "SPEC_PATH": a.spec, "PROJECT_ROOT": root}
        text = "ROLE: finding-falsifier\n" + fill(body, values) + f"""

## Run contract (added by the pipeline script -- binding)
- This is batch {n} of {len(batches)}: {len(b['ids'])} merged findings (F-N), grouped by seam. Each F-N merges one or more lane findings that describe the same defect. Try to defeat EACH F-N separately and give EACH its own verdict; never skip one.
- Read ONLY the member findings named above in their lane files, never another lane's output.
- Write your full reasoning to {run}/falsifiers/batch-{n}.md, and ONE file per F-N, {run}/falsifiers/<F-N>.json:
  {{"id": "<F-N>", "verdict": "REFUTED|SURVIVES|SURVIVES-BUT-FIX-REJECTED|NEEDS-LIVE-EVIDENCE", "evidence": "<one line>"}}.
- A unit's verdict applies to every member. When ONE member is wrong while the unit's defect stands (or the reverse), ALSO write {run}/falsifiers/<member id, any char outside A-Za-z0-9_.- replaced by _>.json with that member's own verdict; it overrides the unit for that member. Judge members separately whenever they make different claims.
- Final reply: {{"verdicts": [that object for every F-N in the batch, plus every member override]}} via StructuredOutput. You are a leaf agent -- spawn no sub-agents or Workflows.
"""
        left = find_placeholders(text)
        if left:
            errors.append(f"batch {n}: unfilled placeholders {sorted(set(left))}")
        path = run / "prompts" / f"falsifier-batch-{n}.md"
        if not a.dry:
            write(path, text)
        plan.append({"batch": n, "ids": b["ids"], "seams": b["seams"], "prompt": str(path)})
    if errors:
        return emit({"ok": False, "errors": errors}, False)
    return emit({"ok": True, "totalUnits": len(units), "totalIds": sum(len(u["members"]) for u in units), "plan": plan})


def falsifier_counts(run, expected_ids):
    """Verdict per original id, read from its merged unit's verdict file (F-N fans out to members)."""
    unit_of = {m: u["id"] for u in (load_units(run) or []) for m in u["members"]}
    safe = lambda x: re.sub(r"[^A-Za-z0-9_.-]", "_", x)
    verdicts = {}
    for i in expected_ids:
        # A member-level file overrides its unit's verdict, so one refutable member inside a
        # surviving unit is not masked by the fan-out.
        own = read_json(Path(run) / "falsifiers" / f"{safe(i)}.json") if i in unit_of else None
        v = own or read_json(Path(run) / "falsifiers" / f"{safe(unit_of.get(i, i))}.json")
        verdicts[i] = (v or {}).get("verdict", "MISSING")
    refuted = sum(1 for v in verdicts.values() if v == "REFUTED")
    return verdicts, refuted, unit_of


# Lanes whose verdict can stop the review: label -> (reason, envelope flag that fires it).
GATE_LANES = {"adr-auditor": ("adr", "founder_approval_needed"), "legal-auditor": ("legal", "legal_commitment_breach")}


def hard_stop_reasons(run, planned):
    """Why the review must stop. A planned gate lane with no usable envelope is a reason, never a silent pass."""
    reasons = []
    for label, (reason, flag) in GATE_LANES.items():
        if label not in planned:
            continue
        env, _ = read_envelope(run, label)
        if env is None:
            reasons.append(f"{label}-envelope-missing")
            continue
        if env.get(flag) and not env.get("founder_approval_marker_present"):
            reasons.append(reason)
        # A legal verdict that read no source bound nothing; only the no-register receipt may do that.
        if label == "legal-auditor" and env.get("register_found") is not False and not env.get("sources_read"):
            reasons.append(f"{label}-read-no-sources")
    return reasons


def cmd_summary(a):
    run = Path(a.run)
    labels = expand_labels(run, csv(a.lanes))
    cm = all_critical_major(run, labels)
    verdicts, refuted, unit_of = falsifier_counts(run, falsified_ids(run, labels))
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
    reasons = hard_stop_reasons(run, set(csv(a.planned)) or set(labels))
    missing = sorted({unit_of.get(i, i) for i, v in verdicts.items() if v == "MISSING"})
    return emit({"ok": True, "raw": raw, "surviving": surviving, "falsifierDispatched": sum(1 for v in verdicts.values() if v != "MISSING"),
                 "refuted": refuted, "missingVerdicts": missing, "hardStop": bool(reasons), "hardStopReasons": reasons})


LEDGER_ENV = "SPEC_REVIEW_LEDGER"


def cmd_ledger(a):
    """Append one per-run falsifier row (B10) to a persistent jsonl, so verdict counts outlive /tmp.

    The path is always the caller's: `--path`, else $SPEC_REVIEW_LEDGER. This script never names
    a machine location itself, because it ships in a public repo. Re-running a finished run
    appends nothing (an identical row is skipped), so a retried Synthesize stage cannot double-count.
    """
    path = a.path or os.environ.get(LEDGER_ENV, "")
    if not path:
        return emit({"ok": False, "errors": [f"no ledger path: pass --path or set ${LEDGER_ENV}"]}, False)
    run = Path(a.run)
    labels = expand_labels(run, csv(a.lanes))
    verdicts, _, _ = falsifier_counts(run, falsified_ids(run, labels))
    tally = lambda word: sum(1 for v in verdicts.values() if v == word)
    row = {"date": datetime.date.today().isoformat(), "spec": a.spec or run.name,
           "dispatched": sum(1 for v in verdicts.values() if v != "MISSING"),
           "refuted": tally("REFUTED"), "survives": tally("SURVIVES"),
           "fix_rejected": tally("SURVIVES-BUT-FIX-REJECTED"), "needs_live": tally("NEEDS-LIVE-EVIDENCE")}
    line = json.dumps(row, separators=(",", ":"), sort_keys=True)
    target = Path(path).expanduser()
    existing = target.read_text(encoding="utf-8").splitlines() if target.is_file() else []
    if line not in existing:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    return emit({"ok": True, "row": row, "path": str(target), "appended": line not in existing})


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
    manifest = load_manifest(a.run)
    for label in labels:
        if not entry_by_label(manifest, label).get("reportEveryFinding"):
            continue
        env, _ = read_envelope(run, label)
        ids = [f["id"] for f in (env or {}).get("findings", [])] + [h.get("id") for h in (env or {}).get("research_handoffs", []) if isinstance(h, dict)]
        for i in ids:
            if i and not re.search(r"(?<![A-Za-z0-9-])" + re.escape(i) + r"(?![A-Za-z0-9])", text):
                errors.append(f"lane {label} reports every finding and hand-off: id {i} is missing from report.md")
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
    universe = all_critical_major(run, labels, scoped=True)
    verdicts, refuted, _ = falsifier_counts(run, falsified_ids(run, labels))
    n, m = len(verdicts), len(universe)
    line = f"{n} dispatched over {m} CRITICAL/MAJOR"
    if not re.search(re.escape(line) + r"[^\n]*?\b" + str(refuted) + r"\s+REFUTED,\s*" + str(n - refuted) + r"\s+SURVIVES", text, re.I):
        errors.append(f"falsifier line must read '{line} — {refuted} REFUTED, {n - refuted} SURVIVES.'")
    miss = [i for i, v in verdicts.items() if v == "MISSING"]
    if miss:
        errors.append(f"falsifier verdict files missing for {miss}")
    if not errors and a.publish:
        write(a.publish, text)
    return emit({"ok": not errors, "errors": errors, "falsifierLine": f"{n} dispatched over {m} CRITICAL/MAJOR — {refuted} REFUTED, {n - refuted} SURVIVES."}, not errors)


# --------------------------------------------------------------------------
# plan: tier + gates + lanePlan -> the one resolved manifest and lane plan
# --------------------------------------------------------------------------
SLIM = ("label", "kind", "agentType", "model", "idPrefix", "reportEveryFinding", "substituteFor", "gate", "profiles")


FLOOR_GATES = ("security", "cutover")


def tier_rule_errors(m, tier, gates, scope, cynap):
    """Depth rules R2-R4: `critical` is for a spec in a cynap repo that touches a floor domain
    (security/money/tenancy/cutover/access/personal data/architecture). Everything else tops out at
    `standard`; a fired floor gate still adds its lane at any tier."""
    if tier != "critical":
        return []
    if scope.get("harnessOnly"):
        return ["tier critical refused (R2): a tooling/harness-only spec runs at standard; a fired gate still adds its lane"]
    floor = any(gates[g]["run"] for g in FLOOR_GATES if g in gates) or bool(scope.get("floorDomain")) \
        or (cynap and gates.get("legalSurface", {}).get("run"))
    if not floor:
        why = "R4" if cynap else "R3: not a cynap repo"
        return [f"tier critical refused ({why}): no security/money/tenancy/cutover floor domain (set frame.floorDomain, or fire a floor gate); use standard"]
    return []


def skip_reason(e, g, profile, tier):
    if g:
        r = (g.get("reason") or "").strip()
        return f"gate: {e['gate']} not fired" + (f" ({r})" if r.lower() not in ("", "none", "n/a", "na") else "")
    return f"gate: not in tier {tier} (profile {profile})"


def plan_lanes(m, tier, gates, lane_plan, scope=None):
    """The gate rule (a lane runs when its profile lists it OR its domain gate fired), then the
    LLM's lanePlan add/drop validated against the manifest. Returns (plan, errors)."""
    scope = scope or {}
    cynap = scope.get("repo", m["cynapRepos"][0]) in m["cynapRepos"]
    errors = []
    if tier not in m["tiers"]:
        return None, [f"lanePlan.tier must be one of {sorted(m['tiers'])}"]
    profile = m["tiers"][tier]["profile"]
    for g in m["gates"]:
        if not isinstance(gates.get(g), dict) or not isinstance(gates[g].get("run"), bool) or not gates[g].get("reason"):
            errors.append(f"gates.{g} must be {{run: boolean, reason: string}}")
    if errors:
        return None, errors
    errors += tier_rule_errors(m, tier, gates, scope, cynap)
    fired = [g for g in m["gates"] if gates[g]["run"]]
    if tier == "light" and fired:
        errors.append(f"tier light is below the floor: gate(s) {fired} fired (a fired gate forces standard or critical)")
    add, drop, why = lane_plan.get("add", []), lane_plan.get("drop", []), lane_plan.get("reasons", {})
    lanes = {e["label"]: e for e in m["lanes"] if not e.get("substituteFor")}
    gate_of = lambda e: gates[e["gate"]] if e.get("gate") else None
    for label in add + drop:
        if label not in lanes:
            errors.append(f"lanePlan: unknown lane label {label}")
        if not why.get(label):
            errors.append(f"lanePlan: {label} needs a reason in lanePlan.reasons")
    for label in why:
        if label not in lanes:
            errors.append(f"lanePlan.reasons: unknown lane label {label}")
    run, skipped, reasons = [], [], {}
    for e in lanes.values():
        g = gate_of(e)
        label = e["label"]
        if e.get("cynapOnly") and not cynap:
            skipped.append({"label": label, "reason": f"gate: cynap-only lane, repo {scope.get('repo')} is not a cynap repo"})
        elif label in drop:
            if tier == "critical":
                errors.append(f"lanePlan: {label} cannot be dropped at tier critical (only add)")
            elif e.get("floor") or (g and g["run"]):
                errors.append(f"lanePlan: {label} is non-droppable (floor lane or its gate fired)")
            elif not (profile in e["profiles"] or label in add):
                errors.append(f"lanePlan: drop {label} is not in tier {tier}'s set")
            skipped.append({"label": label, "reason": f"gate: lanePlan drop: {why.get(label, '')}"})
        elif profile in e["profiles"] or (g and g["run"]) or label in add:
            run.append(e)
            reasons[label] = why.get(label) or (f"gate {e['gate']} fired: {g['reason']}" if g and g["run"] and profile not in e["profiles"] else f"tier {tier} default set")
        else:
            skipped.append({"label": label, "reason": skip_reason(e, g, profile, tier)})
    if not errors and not any(e["label"] == "codex-frontier" for e in run):
        errors.append("the Astra frontier lane is non-droppable in every tier")
    if errors:
        return None, errors
    budget = m["tiers"][tier]["budget"]
    codex = [e for e in run if e["kind"] == "codex"]
    over = [f"{len(run)} lanes planned over maxLanes {budget['maxLanes']}"] if len(run) > budget["maxLanes"] else []
    over += [f"{len(codex)} Codex lanes planned over maxCodexLanes {budget['maxCodexLanes']}"] if len(codex) > budget["maxCodexLanes"] else []
    slim = lambda e: {k: e[k] for k in SLIM if k in e}
    return {"tier": tier, "profile": profile, "gates": gates, "budget": budget, "overBudget": over,
            "planned": len(run), "plannedCodex": len(codex), "laneReasons": reasons,
            "run": [slim(e) for e in run], "skipped": skipped,
            "substitutes": [slim(e) for e in m["lanes"] if e.get("substituteFor")]}, []


def cmd_plan(a):
    run, root = Path(a.run), Path(a.root)
    frame = read_json(Path(a.input))
    if not isinstance(frame, dict) or not isinstance(frame.get("lanePlan"), dict) or not isinstance(frame.get("gates"), dict):
        return emit({"ok": False, "errors": ["--input must be a JSON object with 'gates' and 'lanePlan'"]}, False)
    manifest, files, errors = load_manifest(), [str(LANES_JSON)], []
    override = root / OVERRIDE_REL
    if override.is_file():
        files.append(str(override))
        ov = read_json(override)
        manifest, errors = merge_override(manifest, ov)
    errors += validate_manifest(manifest)
    if errors:
        return emit({"ok": False, "errors": errors, "files": files}, False)
    if not isinstance(frame.get("repo"), str) or not frame["repo"]:
        return emit({"ok": False, "errors": ["frame.repo (the repo name the spec belongs to) is required"], "files": files}, False)
    scope = {"repo": frame["repo"], "harnessOnly": bool(frame.get("harnessOnly")), "floorDomain": str(frame.get("floorDomain") or "")}
    plan, errors = plan_lanes(manifest, frame["lanePlan"].get("tier"), frame["gates"], frame["lanePlan"], scope)
    if errors:
        return emit({"ok": False, "errors": errors, "files": files}, False)
    plan["files"], plan["scope"] = files, scope
    write(run / "manifest.json", json.dumps(manifest, indent=1))
    write(run / "plan.json", json.dumps(plan, indent=1))
    return emit({"ok": True, "tier": plan["tier"], "profile": plan["profile"], "files": files, "planned": plan["planned"],
                 "plannedCodex": plan["plannedCodex"], "budget": plan["budget"], "overBudget": plan["overBudget"],
                 "lanes": plan["laneReasons"], "skipped": plan["skipped"]})


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

    add("plan", cmd_plan, "root", "input")
    add("init", cmd_init, "spec", "root", "sid", "runtime", "skill-dir")
    add("extract-finish", cmd_extract_finish)
    add("lanes", cmd_lanes, "spec", "lanes")
    add("check-envelopes", cmd_check_envelopes, "lanes", "codex")
    add("drift-briefs", cmd_drift_briefs, "spec")
    add("merge-check", cmd_merge_check, "lanes")
    p = add("falsify-plan", cmd_falsify_plan, "lanes", "spec", "max-batches")
    p.add_argument("--dry", action="store_true", help="print the plan without writing prompts")
    add("summary", cmd_summary, "lanes", "planned")
    add("ledger", cmd_ledger, "lanes", "spec", "path")
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
