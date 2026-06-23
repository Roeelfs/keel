#!/usr/bin/env bash
# .claude/hooks/heartbeat-reaper.sh
# Periodic reaper for ungracefully-killed sessions.
#
# Invoked by a periodic timer (launchd plist on macOS, systemd timer on Linux —
# see tooling/workflow/install/). Runs OUTSIDE any Claude Code session context —
# cwd and CLAUDE_SESSION_ID are NOT set by the harness here, so the repo must be
# supplied explicitly.
#
# Behavior:
#   1. Discover the repo from $REPO (env), $1 (arg), or fall back to cwd
#   2. Resolve STATE_DIR via --git-common-dir
#   3. For each sessions/*.json:
#      - Parse heartbeatAt; compute age in hours
#      - If age > 4h: cross-check whether the worktree still exists in git
#      - If worktree gone OR age > 24h: run `tooling/workflow/workflow release --session <sid>`
#   4. Append telemetry for each purge
#   5. EXIT 0 ON ANY ERROR — best-effort periodic task
#
# CONFIG: set REPO to the absolute path of the repo to reap. The install plist /
# systemd unit passes it in. SessionStart/SessionEnd hooks handle the happy path;
# this reaper only cleans up sessions that were killed without firing SessionEnd.

set +e  # fail-open throughout

# ---------------------------------------------------------------------------
# Repo discovery — the timer has no session context, so REPO must be explicit.
# Precedence: $REPO env  >  first arg  >  current working directory.
# ---------------------------------------------------------------------------
REPO="${REPO:-${1:-$PWD}}"

# If repo doesn't exist (e.g. first-time setup or a different machine), do nothing
[ -d "$REPO" ] || exit 0

# ---------------------------------------------------------------------------
# Resolve STATE_DIR — CRITICAL: --git-common-dir, NOT --show-toplevel
# ---------------------------------------------------------------------------
GIT_COMMON=""
GIT_COMMON="$(git -C "$REPO" rev-parse --git-common-dir 2>/dev/null)" || true
[ -z "$GIT_COMMON" ] && exit 0

case "$GIT_COMMON" in
  /*) ;;  # already absolute
  *)  GIT_COMMON="${REPO}/${GIT_COMMON}" ;;
esac

STATE_DIR="${GIT_COMMON}/claude-workflow"
[ -d "${STATE_DIR}/sessions" ] || exit 0

WORKFLOW_CLI="${REPO}/tooling/workflow/workflow"
LOCK_FILE="${STATE_DIR}/WORKING.lock"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# iso_to_epoch <iso8601_utc> — echoes seconds since epoch, or "" on failure
iso_to_epoch() {
  local ts="$1"
  if command -v gdate >/dev/null 2>&1; then
    gdate -u -d "$ts" +%s 2>/dev/null || true
  else
    # BSD date (macOS default): -j -f format -u
    date -u -j -f '%Y-%m-%dT%H:%M:%SZ' "$ts" +%s 2>/dev/null || true
  fi
}

# worktree_exists <worktree_name> — exit 0 if name still appears in worktree list
worktree_exists() {
  local name="$1"
  git -C "$REPO" worktree list --porcelain 2>/dev/null \
    | grep -q "^worktree .*/${name}$" 2>/dev/null
}

# ---------------------------------------------------------------------------
# Reaper loop — iterate over all session files
# Bash 3.2 compatible: no mapfile, no shopt globstar
# ---------------------------------------------------------------------------
NOW_EPOCH="$(date -u +%s 2>/dev/null)" || exit 0
NOW_ISO="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null)" || exit 0

FOUR_H_SECS=14400   # 4 * 3600
DAY_SECS=86400      # 24 * 3600

for session_file in "${STATE_DIR}/sessions/"*.json; do
  [ -f "$session_file" ] || continue

  SID="$(jq -r '.sessionId // ""' "$session_file" 2>/dev/null)" || continue
  HEARTBEAT="$(jq -r '.heartbeatAt // ""' "$session_file" 2>/dev/null)" || continue
  WORKTREE="$(jq -r '.worktree // ""' "$session_file" 2>/dev/null)" || continue

  # Also check owned-paths for worktree name (claim-scope writes it there)
  if [ -z "$WORKTREE" ]; then
    owned="${STATE_DIR}/owned-paths/${SID}.json"
    if [ -f "$owned" ]; then
      WORKTREE="$(jq -r '.worktree // ""' "$owned" 2>/dev/null)" || true
    fi
  fi

  [ -z "$SID" ] && continue

  case "$SID" in
    ''|*[!a-zA-Z0-9_-]*) continue ;;
  esac

  [ -z "$HEARTBEAT" ] && continue

  HEARTBEAT_EPOCH="$(iso_to_epoch "$HEARTBEAT")"
  [ -z "$HEARTBEAT_EPOCH" ] && continue

  AGE_SECS="$(( NOW_EPOCH - HEARTBEAT_EPOCH ))" || continue

  # Skip fresh sessions
  [ "$AGE_SECS" -le "$FOUR_H_SECS" ] && continue

  # -------------------------------------------------------------------------
  # Age > 4h: determine whether to purge
  # -------------------------------------------------------------------------
  REASON=""

  if [ "$AGE_SECS" -gt "$DAY_SECS" ]; then
    REASON="heartbeat_stale_24h"          # older than 24h — purge unconditionally
  elif [ -n "$WORKTREE" ] && ! worktree_exists "$WORKTREE"; then
    REASON="worktree_gone"                # worktree no longer present in git
  fi

  [ -z "$REASON" ] && continue

  # -------------------------------------------------------------------------
  # Purge via workflow CLI (manual fallback if the CLI is unavailable)
  # -------------------------------------------------------------------------
  if [ -x "$WORKFLOW_CLI" ]; then
    (cd "$REPO" && "$WORKFLOW_CLI" release --session "$SID" 2>/dev/null) || {
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
    }
  else
    rm -f "${STATE_DIR}/sessions/${SID}.json" 2>/dev/null || true
    rm -f "${STATE_DIR}/owned-paths/${SID}.json" 2>/dev/null || true
  fi

  # -------------------------------------------------------------------------
  # Telemetry for this purge
  # -------------------------------------------------------------------------
  if command -v jq >/dev/null 2>&1; then
    TEL_LINE="$(jq -nc \
      --arg event  "reaper_purge" \
      --arg sid    "$SID" \
      --arg ts     "$NOW_ISO" \
      --arg reason "$REASON" \
      '{event:$event,sid:$sid,ts:$ts,reason:$reason}' 2>/dev/null)" || TEL_LINE=""

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
  fi

done

exit 0
