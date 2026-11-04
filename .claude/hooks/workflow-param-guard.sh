#!/usr/bin/env bash
# workflow-param-guard.sh — PreToolUse(Workflow) guard (improve-harness 2026-07-16, H8).
#
# WHY: the Workflow tool is inherently detached (background; completion re-invokes the
# session) and REJECTS a run_in_background parameter with an InputValidationError —
# but the mistake recurred in >=5 sessions, each burning a validator round-trip.
# Convert it into an immediate, self-explaining deny. FAIL-OPEN on any parse error.
set -uo pipefail

input="$(cat 2>/dev/null || true)"; [ -z "$input" ] && exit 0

hit="$(printf '%s' "$input" | python3 -c '
import sys, json
try:
    d = json.load(sys.stdin)
    ti = d.get("tool_input", {}) or {}
    print("DENY" if "run_in_background" in ti else "ALLOW")
except Exception:
    print("ALLOW")
' 2>/dev/null || echo ALLOW)"

[ "$hit" = "DENY" ] || exit 0

echo "🚦 Workflow does not accept run_in_background — it ALWAYS runs detached and re-invokes you via <task-notification> on completion. Remove the parameter and re-send the identical call." >&2
exit 2
