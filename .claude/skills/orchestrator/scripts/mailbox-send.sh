#!/usr/bin/env bash
# Orchestrator-side mailbox sender.
#
# The orchestrator calls this to drop a message for a lane session running
# wakeup-wait.sh in mailbox mode. Atomic write (temp+mv) so the watcher's
# mtime check never sees a half-written file.
#
# Usage:
#   mailbox-send.sh <SESSION_ID> <JSON_PAYLOAD>
#   mailbox-send.sh <SESSION_ID> --file <path-to-json>
#   mailbox-send.sh <SESSION_ID> --stdin    # read JSON from stdin
#
# The mailbox lives at:
#   ~/.claude/projects/<slug>/orchestrator-runs/wakeups/<SID>.json
#
# If the slug dir doesn't exist (e.g. lane is in a different project), the
# script searches all projects for an existing wakeup-dir keyed to this SID.
# If none exists, it defaults to the orchestrator's current cwd-derived slug.
#
# Exit codes:
#   0 — wrote successfully
#   1 — usage error or write failure

set -euo pipefail

SID="${1:?usage: $0 <session-id> '<json>' | $0 <session-id> --file <path> | $0 <session-id> --stdin}"
shift

MODE="inline"
PAYLOAD=""
SRC_FILE=""

case "${1:-}" in
  --file)
    MODE="file"
    SRC_FILE="${2:?--file requires a path}"
    ;;
  --stdin)
    MODE="stdin"
    ;;
  "")
    echo "missing payload" >&2; exit 1
    ;;
  *)
    PAYLOAD="$1"
    ;;
esac

# Resolve target directory. Order:
#   1. Existing wakeups dir already used by this SID (find one)
#   2. Slug derived from current cwd
TARGET_DIR=""
EXISTING=$(find "$HOME/.claude/projects/" -maxdepth 4 -name "${SID}*.json" \
  -path "*/wakeups/*" -type f 2>/dev/null | head -1)
if [ -n "$EXISTING" ]; then
  TARGET_DIR=$(dirname "$EXISTING")
else
  SLUG=$(pwd | sed 's|/|-|g')
  TARGET_DIR="$HOME/.claude/projects/$SLUG/orchestrator-runs/wakeups"
fi

mkdir -p "$TARGET_DIR"
TARGET_FILE="$TARGET_DIR/${SID}.json"
TMP_FILE="${TARGET_FILE}.tmp.$$"

case "$MODE" in
  inline) printf '%s' "$PAYLOAD" > "$TMP_FILE" ;;
  file)   cp "$SRC_FILE" "$TMP_FILE" ;;
  stdin)  cat > "$TMP_FILE" ;;
esac

# Validate JSON before atomic move so we never leave junk in the mailbox.
if ! python3 -c "import json,sys; json.load(open('$TMP_FILE'))" 2>/dev/null; then
  rm -f "$TMP_FILE"
  echo "ERROR: payload is not valid JSON" >&2
  exit 1
fi

mv "$TMP_FILE" "$TARGET_FILE"

# Print confirmation: target + size + new mtime.
M=$(stat -f %m "$TARGET_FILE" 2>/dev/null || stat -c %Y "$TARGET_FILE")
S=$(wc -c < "$TARGET_FILE" | tr -d ' ')
echo "WROTE $TARGET_FILE (size=$S bytes, mtime=$M)"
