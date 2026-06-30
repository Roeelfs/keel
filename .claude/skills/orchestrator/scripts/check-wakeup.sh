#!/usr/bin/env bash
# Mailbox check for /loop sessions.
#
# Sessions invoke this FIRST every tick. If the orchestrator wrote a fresh
# wakeup file (mtime > the .last-seen marker), the script:
#   - prints "FRESH_WAKEUP" on stdout
#   - prints the wakeup JSON on stderr (so the model sees it without piping)
#   - touches the .last-seen marker to mark this wakeup as consumed
#
# The session then treats the wakeup's `message` field as the highest-priority
# instruction for the current tick, dropping whatever else was planned.
#
# Usage:
#   ~/.claude/skills/orchestrator/scripts/check-wakeup.sh <SESSION_ID>
#
# Exit codes:
#   0 — completed (whether wakeup was found or not — check stdout for FRESH_WAKEUP)
#   1 — usage error (missing SESSION_ID)
#
# The script is read-only against the wakeup file itself; it only writes to the
# .last-seen marker. Multiple sessions calling this concurrently are safe (each
# writes a SID-scoped marker file).

set -euo pipefail

SID="${1:?usage: $0 <session-id>}"

# Find the wakeup file under any project slug. Sessions don't necessarily know
# their own project slug at script-call time, so we search.
WAKEUP_FILE=$(find "$HOME/.claude/projects/" -maxdepth 4 -name "${SID}*.json" \
  -path "*/wakeups/*" -type f 2>/dev/null | head -1)

if [ -z "$WAKEUP_FILE" ]; then
  # No wakeup file for this session — normal case, exit silently.
  exit 0
fi

WAKEUP_DIR=$(dirname "$WAKEUP_FILE")
LAST_SEEN_FILE="$WAKEUP_DIR/.last-seen-${SID}"

# If the wakeup is older than (or equal to) the last-seen marker, it's been
# consumed already. Exit silently.
if [ -f "$LAST_SEEN_FILE" ] && [ ! "$WAKEUP_FILE" -nt "$LAST_SEEN_FILE" ]; then
  exit 0
fi

# Fresh wakeup — surface it.
echo "FRESH_WAKEUP"
echo "wakeup_file=$WAKEUP_FILE"
echo "---" >&2
cat "$WAKEUP_FILE" >&2
echo "---" >&2

# Mark consumed.
touch "$LAST_SEEN_FILE"
