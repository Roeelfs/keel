#!/usr/bin/env python3
"""PreToolUse(Agent|Task|Workflow): an opus implementation lane goes to Codex unless it says why not.

WHY A HOOK. "Codex first for qualifying lanes" was a prose rule for weeks and stayed one: in one
measured window most opus `Role: implementation` dispatch prompts never mentioned Codex at all,
and about half of the sampled ones qualified for it (self-contained, a document or one-worktree
deliverable, no harness state). A rule that is only remembered at dispatch time is not weighed at
dispatch time, so this hook asks the question at that moment.

WHAT IS GATED. A dispatch that sends an IMPLEMENTATION lane to Claude at the opus tier:
  * Agent/Task: the prompt declares `Role: implementation`, and the effective model is opus.
    Effective model = the explicit `model`; else a named agent's frontmatter pin; else (an
    untyped dispatch with no model) the main loop's model, treated as opus.
  * Workflow: the script (inline `script`, the file at `scriptPath`, and `args`) declares
    `Role: implementation`, and at least one agent() model is opus or unset.
NOT gated: sonnet/haiku lanes, `Role: spec` lanes, lanes with no `Role: implementation` line, and
headless lanes (`spawn-lane.sh` enforces the same rule itself, so this hook does not parse Bash).

THE ESCAPE. One line `Codex-no: <reason>` (10+ chars) in the prompt or script: which of the three
offload tests fails (not self-contained / not a document or one-worktree deliverable / it edits
harness state). A quota wall is never a reason; a Codex lane at the wall reports BLOCKED-ON-QUOTA.

KILL SWITCH. `~/.claude/run/codex-first-gate.off` exists -> the hook allows everything.

FAIL-OPEN BY CONSTRUCTION: any error returns 0 with no stdout, so the dispatch proceeds.
Every gated decision (deny, or allow on a stated reason) is logged to
`~/.claude/analytics/codex-first-gate.jsonl`, which the share measurement reads.
"""
import datetime
import json
import os
import re
import sys

HOME = os.path.expanduser("~")
KILL_SWITCH = os.path.join(HOME, ".claude/run/codex-first-gate.off")
LOG = os.path.join(HOME, ".claude/analytics/codex-first-gate.jsonl")
LOG_MAX_BYTES = 2 * 1024 * 1024
AGENTS_DIR = os.path.join(HOME, ".claude/agents")

ROLE_IMPL_RE = re.compile(r"(?i)\bRole:[ \t]*implementation\b")
# A reason must be real text on the same line: `Codex-no:` followed by 10+ non-quote chars.
REASON_RE = re.compile(r"(?i)\bCodex-no:[ \t]*([^\n\r\"'`]{10,})")
FRONTMATTER_MODEL_RE = re.compile(r"(?m)^model:[ \t]*([A-Za-z0-9_.-]+)")
WF_MODEL_RE = re.compile(r"""\bmodel["']?\s*:\s*["'`]([A-Za-z0-9_.-]+)["'`]""")
WF_AGENT_RE = re.compile(r"\bagent\s*\(")
SCRIPT_MAX_BYTES = 512 * 1024

CODEX_COMMANDS = (
    "  document or report:  ~/.claude/scripts/codex-dispatch.sh standard <promptfile> <outfile> [workdir]\n"
    "  commits in ONE worktree:  ~/.claude/scripts/spawn-lane.sh --mission <promptfile> --cwd <worktree> "
    "--class implementation\n"
    "(class `standard` routes to sol through codex-headroom.sh; spawn-lane.sh runs Codex by default.)"
)


def is_deep(model):
    m = (model or "").strip().lower()
    return m == "opus" or m.startswith("claude-opus") or m == "fable" or m.startswith("claude-fable")


def pinned_model(subagent_type):
    """Frontmatter model of a named agent, or None when unknown."""
    if not isinstance(subagent_type, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", subagent_type):
        return None
    try:
        with open(os.path.join(AGENTS_DIR, subagent_type + ".md"), encoding="utf-8") as fh:
            m = FRONTMATTER_MODEL_RE.search(fh.read(4096))
    except OSError:
        return None
    return m.group(1).lower() if m else None


def agent_effective_model(ti):
    model = ti.get("model")
    if isinstance(model, str) and model.strip():
        return model.strip().lower()
    sub = ti.get("subagent_type")
    if sub not in (None, "", "general-purpose"):
        pin = pinned_model(sub)
        if pin:
            return pin
        # A named agent with no readable pin: its own default, not ours to guess. Treat as
        # inherit, which is the main loop's model.
    return "inherit"


def workflow_text(ti):
    parts = []
    script = ti.get("script")
    if isinstance(script, str):
        parts.append(script)
    path = ti.get("scriptPath")
    if isinstance(path, str) and path:
        try:
            with open(os.path.expanduser(path), encoding="utf-8", errors="replace") as fh:
                parts.append(fh.read(SCRIPT_MAX_BYTES))
        except OSError:
            pass
    if "args" in ti:
        try:
            parts.append(json.dumps(ti.get("args")))
        except (TypeError, ValueError):
            pass
    return "\n".join(parts)


def workflow_sends_deep(text):
    """True when some agent() lane may run at opus: an explicit opus model, or an agent()
    call while the script names no sonnet/haiku-only model set."""
    models = [m.lower() for m in WF_MODEL_RE.findall(text)]
    if any(is_deep(m) for m in models):
        return True
    if not WF_AGENT_RE.search(text):
        return False
    # agent() calls with no model at all inherit the main loop (opus). A script whose every
    # stated model is sonnet/haiku is read as a mechanical script.
    return not models


def decide(d):
    """-> (verdict, detail) where verdict is None (not gated), 'allow' or 'deny'."""
    tool = d.get("tool_name")
    ti = d.get("tool_input")
    if not isinstance(ti, dict):
        return None, {}
    if tool in ("Agent", "Task"):
        text = ti.get("prompt")
        if not isinstance(text, str) or not ROLE_IMPL_RE.search(text):
            return None, {}
        model = agent_effective_model(ti)
        if not (is_deep(model) or model == "inherit"):
            return None, {}
        detail = {"surface": "agent", "model": model, "subagent_type": ti.get("subagent_type")}
    elif tool == "Workflow":
        text = workflow_text(ti)
        if not ROLE_IMPL_RE.search(text) or not workflow_sends_deep(text):
            return None, {}
        detail = {"surface": "workflow", "script": os.path.basename(str(ti.get("scriptPath") or "inline"))}
    else:
        return None, {}
    m = REASON_RE.search(text)
    if m:
        detail["reason"] = m.group(1).strip()[:300]
        return "allow", detail
    return "deny", detail


def log(d, verdict, detail):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        if os.path.exists(LOG) and os.path.getsize(LOG) > LOG_MAX_BYTES:
            os.replace(LOG, LOG + ".1")
        row = dict(detail, ts=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   session_id=d.get("session_id"), verdict=verdict,
                   synthetic=not d.get("transcript_path"))
        with open(LOG, "a") as fh:
            fh.write(json.dumps(row) + "\n")
    except OSError:
        pass


def deny_reason(detail):
    where = ("an Agent dispatch (model %s)" % detail.get("model")
             if detail.get("surface") == "agent" else "a Workflow whose agent() lanes run opus or inherit it")
    return (
        "BLOCKED (codex-first gate): %s sends a `Role: implementation` lane to Claude at the opus tier. "
        "Implementation goes to Codex whenever the lane qualifies (self-contained prompt; a document or "
        "one-worktree deliverable; no harness-state edit). Run it on Codex:\n%s\n"
        "Or keep it on Claude: add ONE line `Codex-no: <which test fails and why>` to the prompt, e.g. "
        "`Codex-no: edits harness hooks a cold Codex lane cannot reach`. A quota wall is never a reason: "
        "a Codex lane at the wall reports BLOCKED-ON-QUOTA. Mechanical work: use model sonnet or haiku."
        % (where, CODEX_COMMANDS)
    )


def main():
    try:
        if os.path.exists(KILL_SWITCH):
            return 0
        d = json.load(sys.stdin)
        verdict, detail = decide(d)
        if verdict is None:
            return 0
        log(d, verdict, detail)
        if verdict == "deny":
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": deny_reason(detail),
            }}))
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
