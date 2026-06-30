#!/usr/bin/env bash
# Blocking mailbox watcher for mailbox-mode lane sessions.
#
# Lanes invoke this via run_in_background:true. The script polls the mailbox
# file's mtime against the per-session .last-seen marker every $POLL_INTERVAL
# seconds, and exits 0 when fresh content arrives — Claude Code then notifies
# the lane model on completion (zero tokens consumed during the wait).
#
# Cross-platform: portable stat (BSD on macOS, GNU on Linux). No fswatch /
# inotifywait dependency.
#
# Usage:
#   ~/.claude/skills/orchestrator/scripts/wakeup-wait.sh <SESSION_ID> [--max-wait-sec N]
#
# Exit codes:
#   0  — fresh wakeup found (payload printed on stdout, marker touched)
#   2  — soft timeout reached (--max-wait-sec, default 86400 = 24h)
#   1  — usage error
#
# Output:
#   stdout: WAKEUP_FOUND\n<wakeup_file_path>\n---\n<json payload>\n---
#           or TIMEOUT\n on soft timeout
#   stderr: progress trace (one line every TRACE_EVERY iterations, optional)

set -euo pipefail

SID="${1:?usage: $0 <session-id> [--max-wait-sec N]}"
shift || true

MAX_WAIT_SEC=86400  # 24h default — can be overridden
while [ $# -gt 0 ]; do
  case "$1" in
    --max-wait-sec) MAX_WAIT_SEC="$2"; shift 2 ;;
    *) echo "unknown flag: $1" >&2; exit 1 ;;
  esac
done

POLL_INTERVAL="${POLL_INTERVAL:-2}"

# Portable mtime fetch (epoch seconds).
mtime() {
  if stat -f %m "$1" 2>/dev/null; then return; fi  # BSD/macOS
  stat -c %Y "$1" 2>/dev/null                       # GNU/Linux
}

# Find the wakeup file. The orchestrator writes to
# ~/.claude/projects/<slug>/orchestrator-runs/wakeups/<SID>.json — but the slug
# isn't known to lanes at runtime, so search.
find_wakeup() {
  find "$HOME/.claude/projects/" -maxdepth 4 -name "${SID}*.json" \
    -path "*/wakeups/*" -type f 2>/dev/null | head -1
}

# Start: snapshot the last-seen mtime so we only wake on NEW writes.
WAKEUP_FILE="$(find_wakeup)"
WAKEUP_DIR=""
LAST_SEEN_FILE=""
START_MTIME=0

if [ -n "$WAKEUP_FILE" ]; then
  WAKEUP_DIR=$(dirname "$WAKEUP_FILE")
  LAST_SEEN_FILE="$WAKEUP_DIR/.last-seen-${SID}"
  if [ -f "$LAST_SEEN_FILE" ]; then
    START_MTIME=$(mtime "$LAST_SEEN_FILE" || echo 0)
  fi
fi

DEADLINE=$(( $(date +%s) + MAX_WAIT_SEC ))

while [ "$(date +%s)" -lt "$DEADLINE" ]; do
  # Re-discover wakeup file each iteration in case it was just created.
  if [ -z "$WAKEUP_FILE" ] || [ ! -f "$WAKEUP_FILE" ]; then
    WAKEUP_FILE="$(find_wakeup)"
    if [ -n "$WAKEUP_FILE" ]; then
      WAKEUP_DIR=$(dirname "$WAKEUP_FILE")
      LAST_SEEN_FILE="$WAKEUP_DIR/.last-seen-${SID}"
    fi
  fi

  if [ -n "$WAKEUP_FILE" ] && [ -f "$WAKEUP_FILE" ]; then
    M=$(mtime "$WAKEUP_FILE" || echo 0)
    L=0
    [ -f "$LAST_SEEN_FILE" ] && L=$(mtime "$LAST_SEEN_FILE" || echo 0)
    # Wake if mailbox is strictly newer than last-seen marker AND newer than
    # our snapshot (so a stale leftover from a previous turn doesn't refire).
    if [ "$M" -gt "$L" ] && [ "$M" -gt "$START_MTIME" ]; then
      echo "WAKEUP_FOUND"
      echo "wakeup_file=$WAKEUP_FILE"
      echo "---"
      cat "$WAKEUP_FILE"
      echo
      echo "---"
      # Mark consumed by touching the last-seen marker to current time.
      touch "$LAST_SEEN_FILE"
      exit 0
    fi
  fi

  sleep "$POLL_INTERVAL"
done

echo "TIMEOUT"
exit 2
