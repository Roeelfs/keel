#!/usr/bin/env bash
# tooling/workflow/lib/cmds.sh
# Simple subcommand implementations: help, status, release, heartbeat.

set -euo pipefail

# ---------------------------------------------------------------------------
# workflow_help
# ---------------------------------------------------------------------------
workflow_help() {
  cat >&2 <<'EOF'
workflow — per-session path ownership CLI

USAGE
  workflow <subcommand> [options]

SUBCOMMANDS
  claim-scope <glob>... [--allow-broad <reason>]
      Claim ownership of one or more path globs for the current session.
      Broad globs (apps/**, **, *, etc.) require --allow-broad <reason>.

  claim --renew [--ttl <48h>]
      Extend expiresAt on existing manifest.

  claim --add <glob> [--reason <r>]
      Append a new glob to the existing manifest.

  claim --cross-cutting <glob> --reason <r> [--ttl <4h>]
      Claim a cross-cutting glob with a shorter TTL.

  release [--session <sid>]
      Remove session + owned-paths manifests; refresh WORKING.md.
      Defaults to current $CLAUDE_SESSION_ID.

  status
      Print active claims from WORKING.md and stale session warnings.

  stats [--since <date-or-ref>]
      Parse telemetry.jsonl and output summary statistics.
      --since accepts "7 days ago", ISO-8601, or a git ref.

  heartbeat
      Bump heartbeatAt on sessions/<sid>.json.

  help | --help
      Show this message.

STATE
  All state is stored under $(git rev-parse --git-common-dir)/claude-workflow/
  so all worktrees of a repo share one state store.
EOF
}

# ---------------------------------------------------------------------------
# workflow_status
# ---------------------------------------------------------------------------
workflow_status() {
  local state
  state="$(state_dir)"
  local md="$state/WORKING.md"

  if [[ -f "$md" ]]; then
    cat "$md"
  else
    echo "(no WORKING.md — no claims recorded yet)"
  fi

  # Warn about stale sessions (expiresAt in the past)
  local now_epoch
  now_epoch="$(date -u +%s)"
  for f in "$state/owned-paths/"*.json; do
    [[ -f "$f" ]] || continue
    local fsid expires exp_epoch
    fsid="$(jq -r '.sessionId // "unknown"' "$f")"
    expires="$(jq -r '.expiresAt // ""' "$f")"
    [[ -z "$expires" ]] && continue
    if command -v gdate &>/dev/null; then
      exp_epoch="$(gdate -u -d "$expires" +%s 2>/dev/null)" || continue
    else
      exp_epoch="$(date -u -j -f '%Y-%m-%dT%H:%M:%SZ' "$expires" +%s 2>/dev/null)" || continue
    fi
    if [[ "$exp_epoch" -lt "$now_epoch" ]]; then
      echo "[STALE] session $fsid expired at $expires" >&2
    fi
  done
}

# ---------------------------------------------------------------------------
# workflow_release [--session <sid>]
# ---------------------------------------------------------------------------
workflow_release() {
  local sid="${CLAUDE_SESSION_ID:-}"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --session) sid="${2:?--session requires a value}"; shift 2 ;;
      --session=*) sid="${1#*=}"; shift ;;
      *) echo "release: unknown option: $1" >&2; exit 2 ;;
    esac
  done

  if [[ -z "$sid" ]]; then
    echo "release: CLAUDE_SESSION_ID is not set and --session not provided." >&2
    echo "  This var is auto-populated by Claude Code at session launch." >&2
    echo "  If running manually, export CLAUDE_SESSION_ID=\$(uuidgen) or pass --session <id>" >&2
    exit 1
  fi

  local state
  state="$(state_dir)"

  rm -f "$state/sessions/$sid.json"
  rm -f "$state/owned-paths/$sid.json"
  update_working_md refresh "$sid"

  echo "released: $sid" >&2
}

# ---------------------------------------------------------------------------
# workflow_heartbeat
# ---------------------------------------------------------------------------
workflow_heartbeat() {
  if [[ -z "${CLAUDE_SESSION_ID:-}" ]]; then
    echo "heartbeat: CLAUDE_SESSION_ID is not set." >&2
    echo "  This var is auto-populated by Claude Code at session launch." >&2
    echo "  If running manually, export CLAUDE_SESSION_ID=\$(uuidgen)" >&2
    exit 1
  fi
  local sid="$CLAUDE_SESSION_ID"
  local state
  state="$(state_dir)"
  local sess="$state/sessions/$sid.json"

  if [[ ! -f "$sess" ]]; then
    echo "heartbeat: no session file for $sid — run claim-scope first" >&2; exit 1
  fi

  local now
  now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  write_session "$sid" ".heartbeatAt = \"$now\""
}
