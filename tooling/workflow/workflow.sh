#!/usr/bin/env bash
# tooling/workflow/workflow.sh
# Workflow CLI — manage per-session path ownership, heartbeats, and telemetry.
# Usage: tooling/workflow/workflow <subcommand> [args...]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/state.sh"
source "$SCRIPT_DIR/lib/glob.sh"
source "$SCRIPT_DIR/lib/cmds.sh"
source "$SCRIPT_DIR/lib/telemetry.sh"

# ===========================================================================
# _claim_scope_locked — runs inside flock; env vars carry context.
# Env: _WF_STATE, _WF_SID, _WF_GLOBS_JSON, _WF_NOW, _WF_EXPIRES,
#      _WF_WORKTREE, _WF_SCRIPT_DIR
# ===========================================================================
_claim_scope_locked() {
  local state="$_WF_STATE"
  local sid="$_WF_SID"
  local globs_json="$_WF_GLOBS_JSON"
  local now="$_WF_NOW"
  local expires_at="$_WF_EXPIRES"
  local worktree="$_WF_WORKTREE"

  source "$_WF_SCRIPT_DIR/lib/glob.sh"

  # Check collisions against other sessions' owned-paths
  for f in "$state/owned-paths/"*.json; do
    [[ -f "$f" ]] || continue
    local other_sid other_globs
    other_sid="$(jq -r '.sessionId // "unknown"' "$f")"
    [[ "$other_sid" == "$sid" ]] && continue
    other_globs="$(jq '.ownedPaths // []' "$f")"
    local a_len b_len
    a_len="$(jq 'length' <<<"$globs_json")"
    b_len="$(jq 'length' <<<"$other_globs")"
    if [[ "$a_len" -gt 0 && "$b_len" -gt 0 ]]; then
      if globs_overlap "$globs_json" "$other_globs" 2>/dev/null; then
        local other_paths
        other_paths="$(jq -r '.ownedPaths | join(", ")' "$f")"
        echo "claim-scope: collision with session $other_sid (paths: $other_paths)" >&2
        exit 2
      fi
    fi
  done

  # Write owned-paths/<sid>.json (atomic)
  local tmp
  tmp="$(mktemp "$state/owned-paths/.tmp.XXXXXX")"
  jq -n \
    --arg sid "$sid" \
    --arg now "$now" \
    --arg expires "$expires_at" \
    --arg wt "$worktree" \
    --argjson paths "$globs_json" \
    '{sessionId: $sid, claimedAt: $now, expiresAt: $expires, worktree: $wt, ownedPaths: $paths}' > "$tmp"
  mv "$tmp" "$state/owned-paths/$sid.json"

  # Write sessions/<sid>.json (atomic, seeds heartbeatAt)
  tmp="$(mktemp "$state/sessions/.tmp.XXXXXX")"
  jq -n \
    --arg sid "$sid" \
    --arg now "$now" \
    '{sessionId: $sid, claimedAt: $now, heartbeatAt: $now}' > "$tmp"
  mv "$tmp" "$state/sessions/$sid.json"

  # Refresh WORKING.md inside the lock — all mutations must be atomic.
  update_working_md refresh "$sid"
}

# ===========================================================================
# Subcommand: claim-scope
# ===========================================================================
workflow_claim_scope() {
  local -a globs=()
  local allow_broad_reason=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --allow-broad)
        allow_broad_reason="${2:?--allow-broad requires a reason argument}"
        shift 2
        ;;
      --allow-broad=*)
        allow_broad_reason="${1#*=}"
        shift
        ;;
      -*)
        echo "claim-scope: unknown option: $1" >&2; exit 2
        ;;
      *)
        globs+=("$1")
        shift
        ;;
    esac
  done

  if [[ ${#globs[@]} -eq 0 ]]; then
    echo "claim-scope: at least one glob is required" >&2; exit 2
  fi
  if [[ -z "${CLAUDE_SESSION_ID:-}" ]]; then
    echo "claim-scope: CLAUDE_SESSION_ID is not set." >&2
    echo "  This var is auto-populated by Claude Code at session launch." >&2
    echo "  If running manually, export CLAUDE_SESSION_ID=\$(uuidgen)" >&2
    exit 1
  fi
  local sid="$CLAUDE_SESSION_ID"

  for g in "${globs[@]}"; do
    if is_broad_glob "$g" && [[ -z "$allow_broad_reason" ]]; then
      echo "claim-scope: glob '$g' is too broad. Use --allow-broad <reason> to override." >&2
      exit 2
    fi
  done

  local state now expires_at worktree globs_json
  state="$(state_dir)"
  now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  if command -v gdate &>/dev/null; then
    expires_at="$(gdate -u -d '+48 hours' +%Y-%m-%dT%H:%M:%SZ)"
  else
    expires_at="$(date -u -v+48H +%Y-%m-%dT%H:%M:%SZ)"
  fi
  worktree="$(basename "$(git rev-parse --show-toplevel)")"
  globs_json="$(printf '%s\n' "${globs[@]}" | jq -R . | jq -s .)"

  export _WF_STATE="$state" _WF_SID="$sid" _WF_GLOBS_JSON="$globs_json" \
         _WF_NOW="$now" _WF_EXPIRES="$expires_at" _WF_WORKTREE="$worktree" \
         _WF_SCRIPT_DIR="$SCRIPT_DIR"

  lock bash -c "source '$SCRIPT_DIR/workflow.sh' && _claim_scope_locked"

  local tel_line
  tel_line="$(jq -nc \
    --arg sid "$sid" \
    --arg ts "$now" \
    --argjson globs "$globs_json" \
    '{event:"claim",sid:$sid,ts:$ts,globs:$globs}')"
  echo "$tel_line" >> "$state/telemetry.jsonl"

  echo "claimed: ${globs[*]}" >&2
}

# ===========================================================================
# Subcommand: claim (--renew | --add | --cross-cutting)
# ===========================================================================
workflow_claim() {
  if [[ -z "${CLAUDE_SESSION_ID:-}" ]]; then
    echo "claim: CLAUDE_SESSION_ID is not set." >&2
    echo "  This var is auto-populated by Claude Code at session launch." >&2
    echo "  If running manually, export CLAUDE_SESSION_ID=\$(uuidgen)" >&2
    exit 1
  fi
  local sid="$CLAUDE_SESSION_ID"
  local state
  state="$(state_dir)"

  local mode="" glob_arg="" reason="" ttl=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --renew)         mode="renew"; shift ;;
      --add)           mode="add"; glob_arg="${2:?--add requires a glob}"; shift 2 ;;
      --cross-cutting) mode="cross-cutting"; glob_arg="${2:?--cross-cutting requires a glob}"; shift 2 ;;
      --reason)        reason="${2:?--reason requires a value}"; shift 2 ;;
      --reason=*)      reason="${1#*=}"; shift ;;
      --ttl)           ttl="${2:?--ttl requires a value}"; shift 2 ;;
      --ttl=*)         ttl="${1#*=}"; shift ;;
      *)               echo "claim: unknown option: $1" >&2; exit 2 ;;
    esac
  done

  if [[ ! -f "$state/owned-paths/$sid.json" ]]; then
    echo "claim: no existing manifest for session $sid — run claim-scope first" >&2; exit 1
  fi

  local now
  now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  case "$mode" in
    renew)
      local ttl_h="${ttl:-48h}"; ttl_h="${ttl_h%h}"
      local new_expires
      if command -v gdate &>/dev/null; then
        new_expires="$(gdate -u -d "+${ttl_h} hours" +%Y-%m-%dT%H:%M:%SZ)"
      else
        new_expires="$(date -u -v+${ttl_h}H +%Y-%m-%dT%H:%M:%SZ)"
      fi
      write_owned_paths "$sid" ".expiresAt = \"$new_expires\""
      update_working_md refresh "$sid"
      echo "$(jq -nc --arg sid "$sid" --arg ts "$now" '{event:"renew",sid:$sid,ts:$ts}')" \
        >> "$state/telemetry.jsonl"
      echo "renewed: expires $new_expires" >&2
      ;;

    add)
      [[ -n "$glob_arg" ]] || { echo "claim --add: glob is required" >&2; exit 2; }
      export _WF_CLAIM_SID="$sid" _WF_CLAIM_GLOB="$glob_arg" _WF_SCRIPT_DIR="$SCRIPT_DIR"
      lock bash -c "
        source '$SCRIPT_DIR/lib/state.sh'
        write_owned_paths \"\$_WF_CLAIM_SID\" \".ownedPaths += [\\\"\$_WF_CLAIM_GLOB\\\"]\"
        update_working_md refresh \"\$_WF_CLAIM_SID\"
      "
      echo "$(jq -nc --arg sid "$sid" --arg ts "$now" --arg g "$glob_arg" \
        '{event:"claim_add",sid:$sid,ts:$ts,glob:$g}')" >> "$state/telemetry.jsonl"
      echo "added: $glob_arg" >&2
      ;;

    cross-cutting)
      [[ -n "$reason" ]] || { echo "claim --cross-cutting: --reason is required" >&2; exit 2; }
      local ttl_h="${ttl:-4h}"; ttl_h="${ttl_h%h}"
      local cc_expires
      if command -v gdate &>/dev/null; then
        cc_expires="$(gdate -u -d "+${ttl_h} hours" +%Y-%m-%dT%H:%M:%SZ)"
      else
        cc_expires="$(date -u -v+${ttl_h}H +%Y-%m-%dT%H:%M:%SZ)"
      fi
      local cc_json
      cc_json="$(jq -nc --arg g "$glob_arg" --arg r "$reason" --arg e "$cc_expires" \
        '{globs:[$g],reason:$r,expiresAt:$e}')"
      export _WF_CLAIM_SID="$sid" _WF_CLAIM_CC_JSON="$cc_json" _WF_SCRIPT_DIR="$SCRIPT_DIR"
      lock bash -c "
        source '$SCRIPT_DIR/lib/state.sh'
        write_owned_paths \"\$_WF_CLAIM_SID\" \".crossCutting = \$_WF_CLAIM_CC_JSON\"
        update_working_md refresh \"\$_WF_CLAIM_SID\"
      "
      echo "$(jq -nc --arg sid "$sid" --arg ts "$now" --arg g "$glob_arg" --arg r "$reason" \
        '{event:"cross_cutting",sid:$sid,ts:$ts,glob:$g,reason:$r}')" \
        >> "$state/telemetry.jsonl"
      echo "cross-cutting claimed: $glob_arg (expires $cc_expires)" >&2
      ;;

    *)
      echo "claim: one of --renew, --add, or --cross-cutting is required" >&2; exit 2
      ;;
  esac
}

# ===========================================================================
# Main dispatch — must be after all function definitions.
# Guard: only run when executed directly, not when sourced (e.g. by lock re-entry).
# ===========================================================================
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  cmd="${1:-help}"; shift || true

  case "$cmd" in
    claim-scope)  workflow_claim_scope "$@" ;;
    claim)        workflow_claim "$@" ;;
    release)      workflow_release "$@" ;;
    status)       workflow_status "$@" ;;
    stats)        workflow_stats "$@" ;;
    heartbeat)    workflow_heartbeat "$@" ;;
    help|--help)  workflow_help ;;
    *)            echo "unknown subcommand: $cmd" >&2; workflow_help; exit 2 ;;
  esac
fi
