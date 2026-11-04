#!/usr/bin/env python3
"""PostToolUse(Agent): refuse to let a dead lane read as a result.

Lives in a real .py file, NOT inside a `python3 -c '...'` block in a shell script.
That embedding is a live footgun: a single apostrophe in a comment terminates the
single-quoted shell string and turns the hook into a syntax error. It happened three
times in one session while writing these guards, and with `2>/dev/null` on the caller
it fails SILENTLY — the guard reads as working while checking nothing.

THE DEFECT THIS CATCHES: a dispatched lane can terminate with a success-shaped envelope
whose entire payload is a quota banner. Measured over ~1,750 lane transcripts: 41 lanes
across 10 parent sessions, worst cluster 13 concurrent spec-review lanes inside 92
seconds, all counted by the orchestrator as reviewers. No `is_error` is set on this class.

CALIBRATION (the first version of this guard was 86% firing / 0% precision):
Over 900 real agent envelopes on this machine the shape census is exactly
  status="async_launched", no content  -> 787   (a HEALTHY backgrounded lane; reports later)
  status="completed",      has content -> 113
An earlier whitelist of ("success","completed","ok","done") — three of which occur in
ZERO real envelopes — fired on the async_launched arm and told the orchestrator "DO NOT
COUNT IT" about lanes still in flight, which makes it re-dispatch live work: duplicated
cost, colliding worktrees, loudest during a wave. Gate on the real shape first.
"""
import sys
import json
import re

QUOTA = re.compile(
    r"hit your (session|usage) limit"
    r"|Your organization has disabled"
    r"|usage limit.*try again"
    r"|Transport channel closed"
    r"|MCP error -32600",
    re.I,
)

# A real quota payload is tiny: largest measured 144 chars. The smallest FALSE positive
# was 5,041 — an 89k-char mining report that merely QUOTES a banner. 400 sits in an empty
# ~35x gap between the two populations.
MAX_BANNER_CHARS = 400


def main() -> int:
    try:
        d = json.load(sys.stdin)
    except Exception:
        return 0

    resp = d.get("tool_response")
    if not isinstance(resp, dict):
        return 0                      # unknown shape -> stay silent, never guess

    # Gate on the real envelope shape BEFORE looking at content.
    status = str(resp.get("status") or "")
    if "content" not in resp or (status and status.lower() != "completed"):
        return 0

    parts = []
    c = resp.get("content")
    if isinstance(c, list):
        for b in c:
            if isinstance(b, dict) and isinstance(b.get("text"), str):
                parts.append(b["text"])
            elif isinstance(b, str):
                parts.append(b)
    elif isinstance(c, str):
        parts.append(c)
    text = "\n".join(parts).strip()

    # Detect on SHAPE (a short payload that is entirely a banner), never on the presence
    # of banner text anywhere — the reset-time suffix varies ("11pm", "8:20pm", "4am"),
    # and a long report discussing quota walls is not a dead lane.
    if not (len(text) <= MAX_BANNER_CHARS and QUOTA.search(text)):
        return 0

    # NO bare length arms. "80-char return after 139 tool calls" was a real lane correctly
    # handing off to a background task; short returns are correct answers to short prompts.
    # Both arms measured zero true positives across 777 envelopes and were deleted.

    atype = resp.get("agentType") or (d.get("tool_input") or {}).get("subagent_type") or "agent"
    msg = (
        "[dead-lane] The `%s` lane returned a SUCCESS-SHAPED envelope whose entire "
        "%d-char payload is a quota/transport banner, not an answer. No `is_error` is set "
        "on this class, which is why it reads as a result.\n"
        "DO NOT COUNT IT as a completed lane, and do not fold its (absent) findings into a "
        "report or a completion claim.\n"
        "Next: (1) check the reset clock ONCE and batch re-dispatch every lane that died on "
        "the same wall - never one at a time, never blind; (2) if the lane owned a worktree, "
        "run `git -C <wt> status --porcelain` BEFORE re-dispatching - 4 of 6 zero-commit "
        "lanes left real recoverable work behind; (3) re-dispatch as a CONTINUATION mission, "
        "not a replay of the original prompt." % (atype, len(text))
    )

    # BOTH channels. Two binary probes this session disagreed on whether `systemMessage`
    # reaches the MODEL (one found it carried on every event; the other found the
    # attachment->content map returns `hook_system_message:()=>[]` while
    # `hook_additional_context` builds content). The reading that fits both: systemMessage
    # renders in the human TUI, additionalContext reaches the model. This guard exists for
    # headless lanes where no human is watching, so bet on neither - send both.
    print(json.dumps({
        "systemMessage": msg,
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": msg,
        },
    }))
    return 0


sys.exit(main())
