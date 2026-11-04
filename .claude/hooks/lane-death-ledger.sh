#!/usr/bin/env bash
# lane-death-ledger.sh — StopFailure → append-only forensic ledger.
#
# StopFailure fires INSTEAD OF Stop when an API error ends a turn, for main sessions and
# subagent lanes alike. Its output is discarded by design — the binary's own doc string:
# "Fire-and-forget — hook output and exit codes are ignored." So this hook cannot speak;
# it can only leave evidence. That is exactly what was missing: measured 2026-08-03, 41
# lanes across 10 sessions ended with a terminal `apiErrorStatus:429` that NOTHING read,
# and recovery took a human typing "re-run all agents that failed" ~2.5h later.
#
# Read it with:  jq -s 'group_by(.error)|map({error:.[0].error,n:length})' ~/.claude/analytics/lane-deaths.jsonl
set -uo pipefail
input="$(cat 2>/dev/null || true)"; [ -z "$input" ] && exit 0

LEDGER="${HOME}/.claude/analytics/lane-deaths.jsonl"
mkdir -p "$(dirname "$LEDGER")" 2>/dev/null || exit 0

printf '%s' "$input" | python3 -c '
import sys, json, os, datetime

try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)

# agent_id is present ONLY when the failure came from inside a subagent — that is the
# single most useful field here, because a dead LANE is invisible to the orchestrator
# while a dead main turn is not.
row = {
    "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "event": d.get("hook_event_name"),
    "error": d.get("error"),
    "error_details": (d.get("error_details") or "")[:300],
    "is_subagent": bool(d.get("agent_id")),
    "agent_id": d.get("agent_id"),
    "agent_type": d.get("agent_type"),
    "session_id": d.get("session_id"),
    "transcript": d.get("transcript_path"),
    "cwd": d.get("cwd"),
    "last_message": (d.get("last_assistant_message") or "")[:300],
}
try:
    with open(os.path.expanduser("~/.claude/analytics/lane-deaths.jsonl"), "a") as f:
        f.write(json.dumps(row) + "\n")
except OSError:
    pass
' 2>/dev/null

exit 0
