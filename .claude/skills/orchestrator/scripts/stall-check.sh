#!/usr/bin/env bash
# stall-check.sh — detect lane stall (N consecutive ticks with no material progress)
#
# Usage: stall-check.sh <sid> [branch] [pr-number]
#   sid       — the session id (matches last-state.json key)
#   branch    — git branch to fingerprint HEAD of (default: HEAD)
#   pr-number — open PR number to fingerprint mergeStateStatus + mergedAt of (default: empty)
#
# Behavior:
#   Builds a fingerprint of the current tick state (HEAD sha, PR state, wakeup file hash),
#   appends to ~/.claude/projects/<slug>/orchestrator-runs/tick-fingerprints/<sid>.jsonl,
#   compares the last STALL_THRESHOLD entries (default 3) — if all identical, the lane is
#   stalled and the loop should cancel.
#
# Exit codes:
#   0 — not stalled (continue loop)
#   1 — STALLED (cancel loop, surface single-line summary)
#   2 — bad args / missing dependencies (jq, gh)
#
# Material progress invalidates a stall, defined as ANY of:
#   - HEAD sha advanced
#   - PR mergeStateStatus changed (CLEAN → MERGED, BLOCKED → CLEAN, etc.)
#   - PR mergedAt flipped from null → non-null
#   - Wakeup file hash changed (new wakeup written)

set -euo pipefail

STALL_THRESHOLD=${STALL_THRESHOLD:-3}

if [ $# -lt 1 ]; then
  echo "usage: stall-check.sh <sid> [branch] [pr-number]" >&2
  exit 2
fi

SID="$1"
BRANCH="${2:-HEAD}"
PR="${3:-}"

if ! command -v jq >/dev/null 2>&1; then
  echo "stall-check: jq required" >&2
  exit 2
fi

PROJECT_RUNS=$(ls -td "$HOME"/.claude/projects/*/orchestrator-runs 2>/dev/null | head -1 || true)
if [ -z "$PROJECT_RUNS" ]; then
  echo "stall-check: no orchestrator-runs dir found; skipping (exit 0)" >&2
  exit 0
fi

LOG_DIR="$PROJECT_RUNS/tick-fingerprints"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/$SID.jsonl"
WAKEUP_DIR="$PROJECT_RUNS/wakeups"

# --- build fingerprint ---
HEAD_SHA=""
if [ -d .git ] || git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  HEAD_SHA=$(git rev-parse "$BRANCH" 2>/dev/null || echo "")
fi

PR_STATE="null"
if [ -n "$PR" ] && command -v gh >/dev/null 2>&1; then
  PR_RAW=$(gh pr view "$PR" --json mergeStateStatus,mergedAt,state 2>/dev/null || echo "{}")
  PR_STATE=$(echo "$PR_RAW" | jq -c '.' 2>/dev/null || echo "null")
fi

WAKEUP_HASH=""
if [ -f "$WAKEUP_DIR/$SID.json" ]; then
  WAKEUP_HASH=$(shasum "$WAKEUP_DIR/$SID.json" 2>/dev/null | awk '{print $1}')
fi

NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
FP=$(jq -nc \
  --arg ts "$NOW" \
  --arg head "$HEAD_SHA" \
  --argjson pr "$PR_STATE" \
  --arg wakeup "$WAKEUP_HASH" \
  '{ts:$ts, head:$head, pr:$pr, wakeup:$wakeup}')

echo "$FP" >> "$LOG"

# --- compare last STALL_THRESHOLD entries (excluding ts) ---
TOTAL=$(wc -l < "$LOG" | tr -d ' ')
if [ "$TOTAL" -lt "$STALL_THRESHOLD" ]; then
  echo "stall-check: only $TOTAL fingerprint(s) so far, threshold=$STALL_THRESHOLD — not stalled"
  exit 0
fi

# Strip ts from each, compare
LAST_N_NO_TS=$(tail -n "$STALL_THRESHOLD" "$LOG" | jq -c 'del(.ts)')
UNIQ_COUNT=$(echo "$LAST_N_NO_TS" | sort -u | wc -l | tr -d ' ')

if [ "$UNIQ_COUNT" -eq 1 ]; then
  STALLED_FP=$(echo "$LAST_N_NO_TS" | head -1)
  FIRST_TS=$(tail -n "$STALL_THRESHOLD" "$LOG" | head -1 | jq -r '.ts')
  echo "stall-check: STALLED — $STALL_THRESHOLD consecutive identical fingerprints since $FIRST_TS"
  echo "stall-check: fingerprint = $STALLED_FP"
  echo "stall-check: cancel the loop and surface a single-line stall summary to operator"
  exit 1
fi

echo "stall-check: $UNIQ_COUNT distinct fingerprint(s) in last $STALL_THRESHOLD ticks — not stalled"
exit 0
