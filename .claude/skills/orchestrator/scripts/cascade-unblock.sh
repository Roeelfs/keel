#!/usr/bin/env bash
# cascade-unblock.sh — wake sessions waiting on a merged issue
#
# Usage: cascade-unblock.sh <merged-issue-number>
#
# Scans the most recent last-state.json across all projects, finds sessions
# whose `depends_on_issues` contains the merged issue and whose `last_status`
# is in {WAITING_FOR_MERGE, PAUSED}, and writes wakeup files at:
#   ~/.claude/projects/<slug>/orchestrator-runs/wakeups/<sid>.json
#
# Sessions consult this file in their next /loop tick (BEFORE-tick check #1
# already cats last-state.json — we add a sibling wakeups dir read).
#
# Exit codes:
#   0 — script ran (zero or more wakeups written)
#   1 — bad args / missing dependencies (jq, gh)
#   2 — no last-state.json found

set -euo pipefail

if [ $# -ne 1 ]; then
  echo "usage: cascade-unblock.sh <merged-issue-number>" >&2
  exit 1
fi

ISSUE="$1"

if ! command -v jq >/dev/null 2>&1; then
  echo "cascade-unblock: jq required" >&2
  exit 1
fi

LATEST_STATE=$(ls -t "$HOME"/.claude/projects/*/orchestrator-runs/last-state.json 2>/dev/null | head -1 || true)
if [ -z "$LATEST_STATE" ]; then
  echo "cascade-unblock: no last-state.json found across ~/.claude/projects/" >&2
  exit 2
fi

PROJECT_DIR=$(dirname "$(dirname "$LATEST_STATE")")
WAKEUP_DIR="$PROJECT_DIR/orchestrator-runs/wakeups"
mkdir -p "$WAKEUP_DIR"

CANDIDATES=$(jq -r --argjson n "$ISSUE" '
  .sessions
  | to_entries
  | map(select(
      (.value.depends_on_issues // []) as $deps
      | ($deps | index($n)) != null
      and (.value.last_status != "IDLE_POST_COMPLETE")
      and (.value.last_status != "RETIRED")
    ))
  | .[]
  | "\(.key)|\(.value.name)|\(.value.lifecycle_step // "?")"
' "$LATEST_STATE")

if [ -z "$CANDIDATES" ]; then
  echo "cascade-unblock: no sessions waiting on #$ISSUE"
  exit 0
fi

NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
COUNT=0

while IFS='|' read -r SID NAME STEP; do
  [ -z "$SID" ] && continue
  WAKEUP_FILE="$WAKEUP_DIR/$SID.json"
  cat > "$WAKEUP_FILE" <<EOF
{
  "wakeup_ts": "$NOW",
  "trigger": "merged_issue",
  "merged_issue": $ISSUE,
  "session_name": "$NAME",
  "lifecycle_step_at_wakeup": "$STEP",
  "message": "PR closing #$ISSUE merged. Your lane was paused on this dependency. Pull origin/main, rebase your feature branch, resume the next /loop tick by re-checking depends_on state and continuing the lifecycle. If your impl plan had a #$ISSUE preflight gate, it is now satisfied — proceed to the gated phase."
}
EOF
  echo "cascade-unblock: wrote $WAKEUP_FILE ($NAME @ step $STEP)"
  COUNT=$((COUNT + 1))
done <<< "$CANDIDATES"

echo "cascade-unblock: $COUNT session(s) woken for #$ISSUE"
exit 0
