#!/usr/bin/env bash
# tooling/workflow/lib/telemetry.sh
# Stats / telemetry subcommand implementation.

set -euo pipefail

# ---------------------------------------------------------------------------
# resolve_since <since_string> → echoes ISO-8601 timestamp or exits 2
# ---------------------------------------------------------------------------
resolve_since() {
  local since="$1"
  local git_ts

  # Try as a git ref first
  if git_ts="$(git log -1 --format=%cI "$since" 2>/dev/null)" && [[ -n "$git_ts" ]]; then
    echo "$git_ts"
    return 0
  fi

  # Try date parsing
  if command -v gdate &>/dev/null; then
    local iso
    iso="$(gdate -u -d "$since" -Iseconds 2>/dev/null)" || {
      echo "stats: cannot parse --since value: $since" >&2; exit 2
    }
    echo "$iso"
  else
    # BSD date: fall back to treating the string as ISO-8601 directly
    echo "$since"
  fi
}

# ---------------------------------------------------------------------------
# workflow_stats [--since <date-or-ref>]
# ---------------------------------------------------------------------------
workflow_stats() {
  local since=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --since) since="${2:?--since requires a value}"; shift 2 ;;
      --since=*) since="${1#*=}"; shift ;;
      *) echo "stats: unknown option: $1" >&2; exit 2 ;;
    esac
  done

  local state
  state="$(state_dir)"
  local tel="$state/telemetry.jsonl"

  if [[ ! -f "$tel" ]] || [[ ! -s "$tel" ]]; then
    echo "(no telemetry events in window)"
    return 0
  fi

  # Resolve --since to an ISO-8601 timestamp
  local since_iso=""
  [[ -n "$since" ]] && since_iso="$(resolve_since "$since")"

  # Filter telemetry by since_iso
  local filtered_tel
  if [[ -n "$since_iso" ]]; then
    filtered_tel="$(jq -R 'try fromjson catch null | select(. != null) | select(.ts >= "'"$since_iso"'")' "$tel")"
  else
    filtered_tel="$(jq -R 'try fromjson catch null | select(. != null)' "$tel")"
  fi

  if [[ -z "$filtered_tel" ]]; then
    echo "(no telemetry events in window)"
    return 0
  fi

  # Count events by type (single jq pass for efficiency)
  local counts_json
  counts_json="$(echo "$filtered_tel" | jq -s '{
    total: length,
    claim:          ([.[] | select(.event=="claim")]           | length),
    renew:          ([.[] | select(.event=="renew")]           | length),
    claim_add:      ([.[] | select(.event=="claim_add")]       | length),
    cross_cutting:  ([.[] | select(.event=="cross_cutting")]   | length),
    expired:        ([.[] | select(.event=="expired_rejected")]| length)
  }')"

  local total claim_count cross_cutting_count expired_count
  total="$(             jq '.total'          <<<"$counts_json")"
  claim_count="$(       jq '.claim'          <<<"$counts_json")"
  cross_cutting_count="$(jq '.cross_cutting' <<<"$counts_json")"
  expired_count="$(     jq '.expired'        <<<"$counts_json")"

  echo "=== Workflow Stats ==="
  [[ -n "$since_iso" ]] && echo "  since:              $since_iso"
  echo "  total events:       $total"
  echo "  claims:             $claim_count"
  echo "  renewals:           $(jq '.renew'     <<<"$counts_json")"
  echo "  claim_add:          $(jq '.claim_add' <<<"$counts_json")"
  echo "  cross-cutting:      $cross_cutting_count"
  echo "  expired-rejected:   $expired_count"

  if [[ "$claim_count" -gt 0 && "$cross_cutting_count" -gt 0 ]]; then
    local ratio
    ratio="$(awk "BEGIN {printf \"%.2f\", $cross_cutting_count / $claim_count}")"
    echo "  cross-cutting ratio: $ratio"
  fi
}
