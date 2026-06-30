#!/bin/sh
# cleanup-tmp.sh — prune stale Codex worktree fallbacks under /private/tmp.
#
# Codex sandbox_mode=workspace-write blocks writes outside the lane's
# writable root, so workers occasionally fall back to a /private/tmp/<prefix>-*
# directory (observed in a past incident). Those dirs accumulate fast and are
# never cleaned.
#
# Set CODEX_TMP_PREFIX to the prefix your workers use (default: "codex").
#
# Usage:
#   tools/codex-sessions/scripts/cleanup-tmp.sh           # dry-run, lists candidates
#   tools/codex-sessions/scripts/cleanup-tmp.sh --apply   # actually delete
#   tools/codex-sessions/scripts/cleanup-tmp.sh --age 48  # 48h cutoff (default 24)

set -e

AGE_HOURS=24
APPLY=0
PREFIX="${CODEX_TMP_PREFIX:-codex}"

while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --age)   AGE_HOURS="$2"; shift ;;
    -h|--help)
      sed -n '2,16p' "$0"; exit 0 ;;
    *)
      echo "unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done

# Refuse to operate outside /private/tmp/<prefix>-* — this is the only safe glob.
# Use -mmin for sub-day granularity (-mtime +0 excludes today's dirs).
candidates=$(find /private/tmp -maxdepth 1 -type d -name "${PREFIX}-*" \
             -mmin +$((AGE_HOURS * 60)) 2>/dev/null || true)

if [ -z "$candidates" ]; then
  echo "no stale /private/tmp/${PREFIX}-* dirs older than ${AGE_HOURS}h"
  exit 0
fi

echo "stale dirs older than ${AGE_HOURS}h:"
echo "$candidates" | sed 's/^/  /'

if [ "$APPLY" = "0" ]; then
  echo
  echo "(dry-run — re-run with --apply to delete)"
  exit 0
fi

echo
echo "$candidates" | while IFS= read -r dir; do
  # Belt-and-suspenders: never rm anything not literally under /private/tmp/<prefix>-
  case "$dir" in
    /private/tmp/"${PREFIX}"-*) rm -rf "$dir" && echo "  rm $dir" ;;
    *) echo "  REFUSED $dir (path mismatch)" >&2 ;;
  esac
done

echo
echo "now run: cd $(git -C "$(dirname "$0")" rev-parse --show-toplevel 2>/dev/null || echo .) && git worktree prune"
echo "(some pruned dirs may be registered worktrees; prune drops their .git/worktrees/ refs)"
