#!/usr/bin/env bash
# .claude/hooks/session-end.sh
# SessionEnd hook — best-effort cleanup of session + owned-paths state.
#
# Behavior contract:
#   - Claude Code docs: "SessionEnd hooks cannot block session termination"
#   - Sessions killed by terminal close, Ctrl-C, or Ctrl-D may skip this entirely
#   - The heartbeat-reaper (heartbeat-reaper.sh + a periodic timer) is the safety net
#   - EXIT 0 UNCONDITIONALLY — never crash; cleanup is best-effort
#
# Implementation: shells out to tooling/workflow/workflow release to remove
# sessions/<sid>.json + owned-paths/<sid>.json and refresh WORKING.md. This
# keeps the hook tiny and delegates authoritative logic to the CLI.

set +e  # fail-open throughout

INPUT="$(cat)"

CWD=""
if command -v jq >/dev/null 2>&1; then
  CWD="$(printf '%s' "$INPUT" | jq -r '.cwd // ""' 2>/dev/null)"
else
  CWD="$(printf '%s' "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('cwd',''))" 2>/dev/null)"
fi

SID="${CLAUDE_SESSION_ID:-}"

[ -z "$CWD" ] && exit 0
[ -z "$SID" ] && exit 0

# Guard against path-traversal or injection in SID before using it in file paths
case "$SID" in
  ''|*[!a-zA-Z0-9_-]*) exit 0 ;;
esac

# ---------------------------------------------------------------------------
# Resolve shared state dir — CRITICAL: --git-common-dir, NOT --show-toplevel
# ---------------------------------------------------------------------------
GIT_COMMON=""
GIT_COMMON="$(git -C "$CWD" rev-parse --git-common-dir 2>/dev/null)" || true
[ -z "$GIT_COMMON" ] && exit 0

case "$GIT_COMMON" in
  /*) ;;  # already absolute
  *)  GIT_COMMON="${CWD}/${GIT_COMMON}" ;;
esac

STATE_DIR="${GIT_COMMON}/claude-workflow"
[ -d "$STATE_DIR" ] || exit 0

# ---------------------------------------------------------------------------
# Locate the workflow CLI relative to the repo root.
# Hook: <repo>/.claude/hooks/session-end.sh ; CLI: <repo>/tooling/workflow/workflow
# ---------------------------------------------------------------------------
REPO_ROOT=""
REPO_ROOT="$(git -C "$CWD" rev-parse --show-toplevel 2>/dev/null)" || true

WORKFLOW_CLI=""
if [ -n "$REPO_ROOT" ] && [ -x "${REPO_ROOT}/tooling/workflow/workflow" ]; then
  WORKFLOW_CLI="${REPO_ROOT}/tooling/workflow/workflow"
fi

# ---------------------------------------------------------------------------
# Run release via CLI; fall back to manual cleanup if CLI unavailable.
# ---------------------------------------------------------------------------
if [ -n "$WORKFLOW_CLI" ]; then
  (cd "$CWD" && "$WORKFLOW_CLI" release --session "$SID" 2>/dev/null) || true
else
  LOCK_FILE="${STATE_DIR}/WORKING.lock"
  SESSION_FILE="${STATE_DIR}/sessions/${SID}.json"
  OWNED_FILE="${STATE_DIR}/owned-paths/${SID}.json"
  if command -v flock >/dev/null 2>&1; then
    # shellcheck disable=SC2016  # single quotes intentional: vars expand via env, not shell
    flock --exclusive --timeout 5 "$LOCK_FILE" \
      env SESSION_FILE="$SESSION_FILE" OWNED_FILE="$OWNED_FILE" \
      sh -c 'rm -f "$SESSION_FILE" "$OWNED_FILE"' 2>/dev/null || true
  else
    rm -f "$SESSION_FILE" 2>/dev/null || true
    rm -f "$OWNED_FILE" 2>/dev/null || true
  fi
fi

# ---------------------------------------------------------------------------
# Telemetry — append session_end event (fail-open)
# ---------------------------------------------------------------------------
NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null)" || NOW=""
if [ -n "$NOW" ] && command -v jq >/dev/null 2>&1; then
  TEL_LINE="$(jq -nc \
    --arg event "session_end" \
    --arg sid   "$SID" \
    --arg ts    "$NOW" \
    '{event:$event,sid:$sid,ts:$ts}' 2>/dev/null)" || TEL_LINE=""

  if [ -n "$TEL_LINE" ]; then
    LOCK_FILE="${STATE_DIR}/WORKING.lock"
    if command -v flock >/dev/null 2>&1; then
      # shellcheck disable=SC2016  # single quotes intentional: vars expand via env, not shell
      flock --exclusive --timeout 5 "$LOCK_FILE" \
        env TEL_LINE="$TEL_LINE" STATE_DIR="$STATE_DIR" \
        sh -c 'printf "%s\n" "$TEL_LINE" >> "$STATE_DIR/telemetry.jsonl"' 2>/dev/null || true
    else
      printf '%s\n' "$TEL_LINE" >> "${STATE_DIR}/telemetry.jsonl" 2>/dev/null || true
    fi
  fi
fi

exit 0
