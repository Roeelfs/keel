#!/usr/bin/env python3
"""PreToolUse(Agent|Task|Workflow): delegated lanes run headless on Claude, not native.

Headless-first: a lane goes to `spawn-lane.sh` (Claude by default); Codex only when the lane
must (spawn-lane.sh owns that rule and its --codex-reason). This hook gates only the native
surfaces. Native dispatch defaults to deny, regardless of role or model inheritance. Preserve
the spec-author and sonnet/haiku mechanical exceptions, unless the prompt describes a large
research/review pass (scope-wide or document-shaped). This is a conservative text heuristic,
not a semantic proof of eligibility. A non-qualifying lane states one Native-why: reason
(10+ trimmed characters): harness state, MCP servers, conversation context, interactive
work, or a sub-minute lookup. Named/pinned agents use the same reason, never a name bypass.

The filename predates headless-first; it is kept because the hook is registered by path.
Workflow reads inline script, scriptPath and string args; only agent() scripts are native.
Kill switch: ~/.claude/run/codex-first-gate.off. Any error fails open (0, no stdout).
Decisions, including mechanical/spec allowances, go to the existing analytics JSONL with
dispatch_runtime=native and native_why. Logging failures never block a dispatch.
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

ROLE_SPEC_RE = re.compile(r"(?i)\bRole:[ \t]*spec\b")
REASON_RE = re.compile(r"(?im)^[ \t]*(?://[ \t]*)?Native-why:[ \t]*([^\n\r\"'`]+)")
PASS_RE = re.compile(r"(?i)\b(research|review|audit|investigat\w*|survey|census|falsif\w*)\b")
DOCUMENT_RE = re.compile(r"(?i)\b(report|document|findings|verdict|dossier|memo)\b|\.md\b")
SCOPE_RE = re.compile(r"(?i)\b(entire|all|across|comprehensive|large|deep|repository|codebase)\b")
FRONTMATTER_MODEL_RE = re.compile(r"(?m)^model:[ \t]*([A-Za-z0-9_.-]+)")
WF_MODEL_RE = re.compile(r"""\bmodel["']?\s*:\s*["'`]([A-Za-z0-9_.-]+)["'`]""")
WF_AGENT_RE = re.compile(r"\bagent\s*\(")
SCRIPT_MAX_BYTES = 512 * 1024

HEADLESS_COMMANDS = (
    "  ~/.claude/scripts/spawn-lane.sh --runtime claude --model opus --mission <promptfile> "
    "--cwd <worktree> --class implementation\n"
    "  (a report or other read-only lane: same command with --class research; mechanical: --model sonnet)"
)


def is_mechanical(model):
    m = (model or "").strip().lower()
    return any(m == family or m.startswith("claude-" + family) for family in ("sonnet", "haiku"))


def document_pass(text):
    return bool(PASS_RE.search(text) and (DOCUMENT_RE.search(text) or SCOPE_RE.search(text)))


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
            parts.extend(string_args(ti.get("args")))
        except (TypeError, ValueError):
            pass
    return "\n".join(parts).replace("\\n", "\n").replace("\\r", "\r")


def string_args(value):
    """Read decoded argument strings, preserving reason-line boundaries."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in string_args(v)]
    if isinstance(value, list):
        return [s for v in value for s in string_args(v)]
    return []


def decide(d):
    """-> (verdict, detail); None means this is not a native lane dispatch."""
    tool, ti = d.get("tool_name"), d.get("tool_input")
    if not isinstance(ti, dict):
        return None, {}
    if tool in ("Agent", "Task"):
        text = ti.get("prompt")
        if not isinstance(text, str):
            return None, {}
        model = agent_effective_model(ti)
        mechanical = is_mechanical(model) and ti.get("subagent_type") not in (
            "critic", "verifier", "security-reviewer")
        detail = {"surface": "agent", "model": model, "subagent_type": ti.get("subagent_type")}
    elif tool == "Workflow":
        # Args may contain a mission, but cannot turn a non-agent script into a dispatch.
        script = workflow_text({k: v for k, v in ti.items() if k != "args"})
        calls = len(WF_AGENT_RE.findall(script))
        if not calls:
            return None, {}
        text = workflow_text(ti)
        models = WF_MODEL_RE.findall(script)
        mechanical = len(models) == calls and all(is_mechanical(m) for m in models)
        detail = {"surface": "workflow", "script": os.path.basename(str(ti.get("scriptPath") or "inline"))}
    else:
        return None, {}
    reason = next((m.group(1).strip() for m in REASON_RE.finditer(text)
                   if len(m.group(1).strip()) >= 10), None)
    # A spec tag in one Workflow lane must not exempt unrelated siblings.
    spec = bool(ROLE_SPEC_RE.search(text)) and (tool != "Workflow" or calls == 1)
    exempt = (mechanical or spec) and not document_pass(text)
    detail = dict(detail, dispatch_runtime="native", native_why=reason[:300] if reason else None,
                  eligibility="exception" if exempt else "headless")
    return ("allow" if reason or exempt else "deny"), detail


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
    return (
        "BLOCKED (native-dispatch gate): native %s dispatch requires a reason. Delegated lanes run "
        "as headless Claude lanes, including large read-only research/review passes. Run:\n%s\n"
        "For a native exception, add ONE line `Native-why: <reason>` (10+ characters) to the prompt. "
        "Reasons: needs harness state, MCP servers or conversation context; interactive work; "
        "a sub-minute lookup. Named agents (critic, verifier, security-reviewer) also need this line. "
        "Spec authors and sonnet/haiku mechanical lanes remain exempt unless doing a large "
        "document-shaped research/review pass. Codex only if the lane must (Claude cannot do it, or "
        "Claude is at a quota wall): spawn-lane.sh --runtime codex --codex-reason \"<why>\"."
        % (detail.get("surface"), HEADLESS_COMMANDS)
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
