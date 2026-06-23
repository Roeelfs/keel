#!/usr/bin/env bash
# tooling/workflow/lib/state.sh
# State directory helpers for workflow CLI.
# All shared-state mutations go through lock() for atomicity.

set -euo pipefail

# ---------------------------------------------------------------------------
# state_dir — resolves (and creates) the canonical state directory.
# Uses --git-common-dir so all worktrees of a repo share one state store.
# ---------------------------------------------------------------------------
state_dir() {
  local git_common_dir
  git_common_dir="$(git rev-parse --git-common-dir)"
  local dir="$git_common_dir/claude-workflow"
  mkdir -p "$dir/sessions" "$dir/owned-paths"
  echo "$dir"
}

# ---------------------------------------------------------------------------
# lock <body_command...>
# Wraps the supplied command inside an exclusive flock on WORKING.lock.
# Timeout: 5 seconds.
# ---------------------------------------------------------------------------
lock() {
  local state="$(state_dir)"
  flock --exclusive --timeout 5 "$state/WORKING.lock" "$@"
}

# ---------------------------------------------------------------------------
# read_session <sid>
# Echoes the JSON content of sessions/<sid>.json, or "{}" if missing.
# ---------------------------------------------------------------------------
read_session() {
  local sid="$1"
  local state
  state="$(state_dir)"
  local f="$state/sessions/$sid.json"
  if [[ -f "$f" ]]; then
    jq '.' "$f"
  else
    echo "{}"
  fi
}

# ---------------------------------------------------------------------------
# write_session <sid> <jq_filter>
# Atomically applies <jq_filter> to the existing session file (or {}) and
# writes the result back via tmp + mv.
# ---------------------------------------------------------------------------
write_session() {
  local sid="$1"
  local filter="$2"
  local state
  state="$(state_dir)"
  local f="$state/sessions/$sid.json"
  local tmp
  tmp="$(mktemp "$state/sessions/.tmp.XXXXXX")"
  local existing="{}"
  [[ -f "$f" ]] && existing="$(cat "$f")"
  echo "$existing" | jq "$filter" > "$tmp"
  mv "$tmp" "$f"
}

# ---------------------------------------------------------------------------
# write_owned_paths <sid> <jq_filter>
# Atomically applies <jq_filter> to owned-paths/<sid>.json and writes back.
# ---------------------------------------------------------------------------
write_owned_paths() {
  local sid="$1"
  local filter="$2"
  local state
  state="$(state_dir)"
  local f="$state/owned-paths/$sid.json"
  local tmp
  tmp="$(mktemp "$state/owned-paths/.tmp.XXXXXX")"
  local existing="{}"
  [[ -f "$f" ]] && existing="$(cat "$f")"
  echo "$existing" | jq "$filter" > "$tmp"
  mv "$tmp" "$f"
}

# ---------------------------------------------------------------------------
# update_working_md <action> <sid> [...]
# action: append | remove | refresh
# WORKING.md is a derived view rebuilt from all owned-paths/*.json files.
# We always do a full refresh regardless of action for simplicity + correctness.
# ---------------------------------------------------------------------------
update_working_md() {
  local action="$1"  # kept for future use / telemetry; currently always refresh
  local sid="${2:-}"
  local state
  state="$(state_dir)"
  local md="$state/WORKING.md"
  local tmp
  tmp="$(mktemp "$state/.working_md.XXXXXX")"

  {
    echo "# WORKING.md — Active workflow claims"
    echo "# Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo ""

    local found=0
    for f in "$state/owned-paths/"*.json; do
      [[ -f "$f" ]] || continue
      found=1
      local fsid worktree globs claimed expires cross_cutting
      fsid="$(jq -r '.sessionId // "unknown"' "$f")"
      worktree="$(jq -r '.worktree // "unknown"' "$f")"
      claimed="$(jq -r '.claimedAt // "unknown"' "$f")"
      expires="$(jq -r '.expiresAt // "unknown"' "$f")"
      globs="$(jq -r '.ownedPaths // [] | join(", ")' "$f")"
      cross_cutting="$(jq -r 'if .crossCutting then "  cross-cutting: " + (.crossCutting.globs | join(", ")) + " (expires " + .crossCutting.expiresAt + ")" else "" end' "$f")"

      echo "## Session: $fsid"
      echo "  worktree:  $worktree"
      echo "  claimed:   $claimed"
      echo "  expires:   $expires"
      echo "  paths:     $globs"
      [[ -n "$cross_cutting" ]] && echo "$cross_cutting"
      echo ""
    done

    if [[ "$found" -eq 0 ]]; then
      echo "(no active claims)"
    fi
  } > "$tmp"

  mv "$tmp" "$md"
}
