#!/usr/bin/env bash
# tooling/workflow/lib/glob.sh
# Glob comparison helpers for workflow CLI.

set -euo pipefail

# ---------------------------------------------------------------------------
# is_broad_glob <glob>
# Returns exit 0 if the glob is considered "too broad" and requires
# --allow-broad. Broad patterns: apps/**, packages/**, **, ., *, **/*
# ---------------------------------------------------------------------------
is_broad_glob() {
  local glob="$1"
  case "$glob" in
    "apps/**"|"packages/**"|"src/**"|"**"|"."|"*"|"**/*")
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

# ---------------------------------------------------------------------------
# globs_overlap <globs_a_json> <globs_b_json>
# globs_a_json and globs_b_json are JSON arrays of glob strings.
# Returns exit 0 if any pair of globs from A and B have overlapping paths.
# Implementation: enumerate up to 100 representative paths per glob via
# git ls-files and check for non-empty intersection.
# Falls back to string prefix overlap if git ls-files yields nothing.
# ---------------------------------------------------------------------------
globs_overlap() {
  local globs_a_json="$1"
  local globs_b_json="$2"

  # Build arrays from JSON (portable — mapfile is Bash 4+ only)
  local -a globs_a=() globs_b=()
  while IFS= read -r line; do globs_a+=("$line"); done < <(echo "$globs_a_json" | jq -r '.[]')
  while IFS= read -r line; do globs_b+=("$line"); done < <(echo "$globs_b_json" | jq -r '.[]')

  # Collect paths for each set (up to 100 per glob)
  local -a paths_a=() paths_b=()

  for g in "${globs_a[@]}"; do
    while IFS= read -r p; do
      paths_a+=("$p")
    done < <(git ls-files "$g" 2>/dev/null | head -100)
  done

  for g in "${globs_b[@]}"; do
    while IFS= read -r p; do
      paths_b+=("$p")
    done < <(git ls-files "$g" 2>/dev/null | head -100)
  done

  # If we got paths from both sides, check intersection
  if [[ ${#paths_a[@]} -gt 0 && ${#paths_b[@]} -gt 0 ]]; then
    # Sort + comm approach for intersection
    local tmp_a tmp_b
    tmp_a="$(mktemp)"
    tmp_b="$(mktemp)"
    printf '%s\n' "${paths_a[@]}" | sort -u > "$tmp_a"
    printf '%s\n' "${paths_b[@]}" | sort -u > "$tmp_b"
    local common
    common="$(comm -12 "$tmp_a" "$tmp_b")"
    rm -f "$tmp_a" "$tmp_b"
    [[ -n "$common" ]] && return 0
    # No file-level overlap found — also check prefix overlap
  fi

  # Fallback: prefix/string overlap check.
  # If one glob is a prefix of the other (after stripping /**), they overlap.
  for ga in "${globs_a[@]}"; do
    for gb in "${globs_b[@]}"; do
      local pa pb
      pa="${ga%%\*\*}"   # strip trailing **
      pa="${pa%%\*}"     # strip trailing *
      pa="${pa%/}"       # strip trailing /
      pb="${gb%%\*\*}"
      pb="${pb%%\*}"
      pb="${pb%/}"
      # Check if either is a prefix of the other
      if [[ -z "$pa" || -z "$pb" || "$pa" == "$pb"* || "$pb" == "$pa"* ]]; then
        return 0
      fi
    done
  done

  return 1
}

# ---------------------------------------------------------------------------
# path_in_globs <path> <glob1> [<glob2> ...]
# Returns exit 0 if <path> matches any of the supplied globs.
# Uses git ls-files (which natively handles **) with a prefix-strip fallback
# for untracked paths. Avoids shopt globstar (Bash 4+ only).
# ---------------------------------------------------------------------------
path_in_globs() {
  local path="$1"
  shift
  local glob

  for glob in "$@"; do
    # Exact case match (handles literal globs without **)
    case "$path" in
      "$glob") return 0 ;;
    esac

    # git ls-files handles ** correctly across all git versions
    if git ls-files --error-unmatch -- "$glob" 2>/dev/null | grep -qFx -- "$path"; then
      return 0
    fi

    # Fallback: strip trailing /** and check if path starts with prefix
    # (handles paths not yet tracked by git)
    # Use literal /\*\* in the pattern so bash does not treat * as a wildcard
    # and over-strip globs like "apps/foo.ts" → "apps".
    local stripped
    case "$glob" in
      */'**') stripped="${glob%/\*\*}" ;;
      *)      stripped="$glob" ;;
    esac
    if [[ "$stripped" != "$glob" ]] && [[ "$path" == "$stripped"/* ]]; then
      return 0
    fi
  done

  return 1
}
