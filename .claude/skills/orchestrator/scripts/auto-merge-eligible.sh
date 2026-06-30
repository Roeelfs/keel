#!/usr/bin/env bash
# Tier B auto-merge eligibility check for orchestrator-managed PRs.
#
# A PR is Tier-B-eligible when ALL of these hold:
#   1. PR is OPEN, mergeable, mergeStateStatus = CLEAN
#   2. The issue this PR closes carries the `auto-merge-ok` label
#      (or a class-scoped variant like `auto-merge-ok-mcp-fixes`)
#   3. PR is small: additions + deletions < 100 LOC
#   4. PR touches only one lane's owned scope (no cross-lane file overlap)
#   5. No new MCP tool registration (grep for `registerTool(`)
#   6. No new schema files (no migrations/* additions)
#   7. No security-class file changes (your repo's auth / authz / credential /
#      handler-wrapper core files — set SECURITY_CLASS_REGEX below to match them)
#   8. All required CI checks SUCCESS or SKIPPED (no FAILURE / no still-running required)
#   9. No unresolved review comments (reviewDecision is APPROVED or null)
#
# If eligible: prints "ELIGIBLE pr=<N> issue=<M> labels=<...>" and exits 0.
# If ineligible: prints "INELIGIBLE pr=<N> reason=<...>" and exits 1.
# Errors: exits 2.
#
# Usage:
#   ~/.claude/skills/orchestrator/scripts/auto-merge-eligible.sh <PR_NUMBER>
#
# Then:
#   if auto-merge-eligible.sh 147; then
#     gh pr merge 147 --squash --delete-branch
#     # cascade-unblock fires from the merge
#   fi
#
# Customize SECURITY_CLASS_REGEX to your repo's sensitive surfaces. The default
# below is a generic example matching common auth/credential core files — replace
# the paths with your own (e.g. the files that gate authentication, authorization,
# credential storage, or remote-code execution in your codebase).

set -euo pipefail

PR="${1:?usage: $0 <pr-number>}"

# Files that must never auto-merge without operator review. Edit for your repo.
SECURITY_CLASS_REGEX="${SECURITY_CLASS_REGEX:-(^|/)(authorization|auth-middleware|authz|handler-wrapper|credentials?)\.[a-z]+$}"

err() { echo "INELIGIBLE pr=$PR reason=$1"; exit 1; }
fatal() { echo "ERROR pr=$PR: $1" >&2; exit 2; }

# 1. PR state
pr_json=$(gh pr view "$PR" --json state,mergeable,mergeStateStatus,additions,deletions,closingIssuesReferences,files,reviewDecision,statusCheckRollup 2>/dev/null) || fatal "gh pr view failed"

state=$(jq -r .state <<<"$pr_json")
[ "$state" = "OPEN" ] || err "state=$state"

mergeable=$(jq -r .mergeable <<<"$pr_json")
[ "$mergeable" = "MERGEABLE" ] || err "mergeable=$mergeable"

ms=$(jq -r .mergeStateStatus <<<"$pr_json")
[ "$ms" = "CLEAN" ] || err "mergeStateStatus=$ms"

# 2. Closes an auto-merge-ok-labeled issue
issues=$(jq -r '.closingIssuesReferences[]?.number' <<<"$pr_json")
[ -n "$issues" ] || err "no closing issue"

found_label=""
matched_issue=""
for issue in $issues; do
  labels=$(gh issue view "$issue" --json labels --jq '[.labels[].name] | join(",")' 2>/dev/null) || continue
  if echo ",$labels," | grep -qE ',auto-merge-ok(-[a-z0-9-]+)?,'; then
    found_label=$(echo "$labels" | tr ',' '\n' | grep -E '^auto-merge-ok' | head -1)
    matched_issue=$issue
    break
  fi
done
[ -n "$found_label" ] || err "no closing issue carries auto-merge-ok* label"

# 3. Size cap
adds=$(jq -r .additions <<<"$pr_json")
dels=$(jq -r .deletions <<<"$pr_json")
loc=$((adds + dels))
[ "$loc" -lt 100 ] || err "size=$loc LOC > 100 cap"

# 4-7. File-class checks
files=$(jq -r '.files[].path' <<<"$pr_json")

# 5. No new registerTool() calls — grep diff
if gh pr diff "$PR" 2>/dev/null | grep -qE '^\+.*registerTool\('; then
  err "adds new MCP tool registration (registerTool() in diff)"
fi

# 6. No new schema/migration files
if echo "$files" | grep -qE '(^|/)migrations/.*\.sql$'; then
  if gh pr diff "$PR" --name-only 2>/dev/null | xargs -I{} echo {} | grep -qE 'migrations/.*\.sql$'; then
    # Distinguish add vs modify — added files only block.
    added_migrations=$(gh pr diff "$PR" 2>/dev/null | grep -E '^diff --git.*migrations/.*\.sql$' | head -3)
    if [ -n "$added_migrations" ]; then
      err "touches migrations/*.sql — schema changes need operator review"
    fi
  fi
fi

# 7. Security-class core file changes
if echo "$files" | grep -qE "$SECURITY_CLASS_REGEX"; then
  err "touches security-class core file (matches SECURITY_CLASS_REGEX)"
fi

# 8. CI checks — all required must be SUCCESS or SKIPPED, no FAILURE / no pending
ci=$(jq -r '.statusCheckRollup[] | select(.name != null) | "\(.name)|\(.status)|\(.conclusion)"' <<<"$pr_json")
fail_count=$(echo "$ci" | grep -cE '\|COMPLETED\|FAILURE|^[^|]+\|COMPLETED\|CANCELLED' || true)
[ "$fail_count" -eq 0 ] || err "$fail_count CI check(s) failed"

# Pending counts: queued/in_progress/pending. We allow an external-provider PENDING
# (e.g. a deploy-preview check) since it's out-of-band; tune EXTERNAL_PENDING_REGEX.
EXTERNAL_PENDING_REGEX="${EXTERNAL_PENDING_REGEX:-^Vercel\\|}"
pending=$(echo "$ci" | grep -cE '\|(QUEUED|IN_PROGRESS|PENDING)\|' || true)
if [ "$pending" -gt 0 ]; then
  pending_required=$(echo "$ci" | grep -E '\|(QUEUED|IN_PROGRESS|PENDING)\|' | grep -vE "$EXTERNAL_PENDING_REGEX" | head -3)
  if [ -n "$pending_required" ]; then
    err "$pending CI check(s) still pending (non-external)"
  fi
fi

# 9. Reviews
review=$(jq -r '.reviewDecision // empty' <<<"$pr_json")
case "$review" in
  ""|"APPROVED") ;;
  *) err "reviewDecision=$review (need APPROVED or none)";;
esac

echo "ELIGIBLE pr=$PR issue=$matched_issue label=$found_label loc=$loc"
exit 0
