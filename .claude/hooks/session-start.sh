#!/usr/bin/env bash
# .claude/hooks/session-start.sh
# SessionStart hook — writes session metadata to the shared workflow state dir.
#
# Behavior contract:
#   - Reads stdin JSON from Claude Code (contains "cwd" and "session_id" fields)
#   - Resolves GIT_COMMON_DIR for shared-across-worktrees state (NOT --show-toplevel)
#   - Writes sessions/<sid>.json with metadata + initial heartbeat
#   - Appends a telemetry event to telemetry.jsonl
#   - EXIT 0 UNCONDITIONALLY — Claude Code can't block SessionStart; explicit fail-open
#
# Does NOT claim scope — that is done explicitly via:
#   tooling/workflow/workflow claim-scope <globs>
# after the operator cd's into the target worktree.

set +e  # fail-open — errors must not reach Claude Code as non-zero exits

# ---------------------------------------------------------------------------
# Read and parse stdin JSON (all of it; Claude Code closes stdin after writing)
# ---------------------------------------------------------------------------
INPUT="$(cat)"

CWD=""
if command -v jq >/dev/null 2>&1; then
  CWD="$(printf '%s' "$INPUT" | jq -r '.cwd // ""' 2>/dev/null)"
else
  CWD="$(printf '%s' "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('cwd',''))" 2>/dev/null)"
fi

# Require a session ID from environment (capture-session-id.sh sets this first)
SID="${CLAUDE_SESSION_ID:-}"

# If we can't identify a session or a cwd, nothing to do
[ -z "$CWD" ] && exit 0
[ -z "$SID" ] && exit 0

# Guard against path-traversal or injection in SID before using it in file paths
case "$SID" in
  ''|*[!a-zA-Z0-9_-]*) exit 0 ;;
esac

# ---------------------------------------------------------------------------
# Resolve shared state dir via --git-common-dir
# CRITICAL: use --git-common-dir, NOT --show-toplevel.
# --show-toplevel returns each linked worktree's own path (per-worktree-invisible).
# --git-common-dir returns the shared .git/ of the main repo for all worktrees.
# ---------------------------------------------------------------------------
GIT_COMMON=""
GIT_COMMON="$(git -C "$CWD" rev-parse --git-common-dir 2>/dev/null)" || true

# If cwd is not inside a git repo, exit silently (don't crash on non-git projects)
[ -z "$GIT_COMMON" ] && exit 0

# --git-common-dir may return a path relative to the repo root (e.g. ".git").
# Resolve to absolute before using as a directory anchor.
case "$GIT_COMMON" in
  /*) ;;  # already absolute
  *)  GIT_COMMON="${CWD}/${GIT_COMMON}" ;;
esac

STATE_DIR="${GIT_COMMON}/claude-workflow"
mkdir -p "${STATE_DIR}/sessions" "${STATE_DIR}/owned-paths" 2>/dev/null || true

# ---------------------------------------------------------------------------
# Write sessions/<sid>.json — atomic mktemp + mv pattern
# ---------------------------------------------------------------------------
NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null)" || NOW=""
[ -z "$NOW" ] && exit 0

SESSION_FILE="${STATE_DIR}/sessions/${SID}.json"
LOCK_FILE="${STATE_DIR}/WORKING.lock"

SESSION_JSON="$(jq -n \
  --arg sid  "$SID" \
  --arg cwd  "$CWD" \
  --arg now  "$NOW" \
  '{
    sessionId:   $sid,
    launchCwd:   $cwd,
    startedAt:   $now,
    heartbeatAt: $now,
    scopeClaimed: false
  }' 2>/dev/null)" || SESSION_JSON=""

[ -z "$SESSION_JSON" ] && exit 0

# Write with flock for atomicity (handles parallel SessionStart from multiple windows)
TMP_SESSION="$(mktemp "${STATE_DIR}/sessions/.tmp.XXXXXX" 2>/dev/null)" || exit 0
printf '%s\n' "$SESSION_JSON" > "$TMP_SESSION" 2>/dev/null || { rm -f "$TMP_SESSION"; exit 0; }

if command -v flock >/dev/null 2>&1; then
  flock --exclusive --timeout 5 "$LOCK_FILE" mv "$TMP_SESSION" "$SESSION_FILE" 2>/dev/null \
    || { mv "$TMP_SESSION" "$SESSION_FILE" 2>/dev/null || rm -f "$TMP_SESSION"; }
else
  # flock not available (brew install flock on macOS) — best-effort atomic mv
  mv "$TMP_SESSION" "$SESSION_FILE" 2>/dev/null || rm -f "$TMP_SESSION"
fi

# ---------------------------------------------------------------------------
# Telemetry — append event line to telemetry.jsonl (fail-open)
# ---------------------------------------------------------------------------
TEL_LINE="$(jq -nc \
  --arg event "session_start" \
  --arg sid   "$SID" \
  --arg ts    "$NOW" \
  '{event:$event,sid:$sid,ts:$ts}' 2>/dev/null)" || TEL_LINE=""

if [ -n "$TEL_LINE" ]; then
  if command -v flock >/dev/null 2>&1; then
    # shellcheck disable=SC2016  # single quotes intentional: vars expand via env, not shell
    flock --exclusive --timeout 5 "$LOCK_FILE" \
      env TEL_LINE="$TEL_LINE" STATE_DIR="$STATE_DIR" \
      sh -c 'printf "%s\n" "$TEL_LINE" >> "$STATE_DIR/telemetry.jsonl"' 2>/dev/null || true
  else
    printf '%s\n' "$TEL_LINE" >> "${STATE_DIR}/telemetry.jsonl" 2>/dev/null || true
  fi
fi

exit 0
