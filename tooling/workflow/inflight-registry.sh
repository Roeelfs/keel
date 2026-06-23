#!/usr/bin/env bash
# tooling/workflow/inflight-registry.sh
#
# Builds the IN-FLIGHT WORK REGISTRY: a single machine-joined view of every
# worktree, branch, open PR, the issue each maps to, and how stale each base
# is. Two modes:
#
#   --hook   Emit SessionStart JSON ({hookSpecificOutput.additionalContext})
#            so the registry is injected into every new session's context.
#   (none)   Print the registry as plain markdown to stdout (human / on-demand).
#
# WHY THIS EXISTS: parallel agent sessions kept doing double work — rebuilding
# code that already lived on a branch, branching off stale bases, opening a
# 2nd/3rd branch per issue — because no session could see what the others held.
# The raw data always existed (git worktrees + gh PRs); it was just never joined
# and shown at session start. This is that join.
#
# CONFIG (env, all optional):
#   ISSUE_KEY_RE   Regex (grep -E, case-insensitive) matching your tracker's
#                  issue keys so each branch can be joined to its ticket.
#                  Default: '[A-Z]+-[0-9]+' (matches JIRA/Linear-style keys like
#                  ACME-123). Set to '' to disable the Issue column entirely.
#   DEFAULT_BRANCH The trunk to measure staleness against. Default: 'main'.
#
# Contract: fail-open. Never block a session. Never exit non-zero in --hook mode.

set +e

MODE="${1:-print}"
ISSUE_KEY_RE="${ISSUE_KEY_RE-[A-Z]+-[0-9]+}"
DEFAULT_BRANCH="${DEFAULT_BRANCH:-main}"

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
# In a linked worktree, point at the main checkout so the view is repo-global.
COMMON_DIR="$(git rev-parse --git-common-dir 2>/dev/null)"
if [ -z "$REPO_ROOT" ]; then
  [ "$MODE" = "--hook" ] || echo "not a git repo"
  exit 0
fi

# Resolve the main worktree root (the one whose .git is a dir, not a file).
MAIN_ROOT="$REPO_ROOT"
case "$COMMON_DIR" in
  /*) MAIN_ROOT="$(dirname "$COMMON_DIR")" ;;
esac
cd "$MAIN_ROOT" 2>/dev/null || cd "$REPO_ROOT" 2>/dev/null || exit 0

# Extract the issue key from a branch name, or "—" if none / disabled.
issue_id() {
  [ -z "$ISSUE_KEY_RE" ] && { printf '—'; return; }
  local id
  id="$(printf '%s' "$1" | grep -oiE "$ISSUE_KEY_RE" | head -1 | tr '[:lower:]' '[:upper:]')"
  [ -z "$id" ] && id="—"
  printf '%s' "$id"
}

# ---- open PRs (best-effort; gh may be absent / unauthenticated) -------------
PR_TSV=""
if command -v gh >/dev/null 2>&1; then
  PR_TSV="$(gh pr list --state open --limit 200 --json number,headRefName,title \
            --jq '.[] | "\(.headRefName)\t\(.number)\t\(.title)"' 2>/dev/null)"
fi
pr_for() { printf '%s\n' "$PR_TSV" | awk -F'\t' -v b="$1" '$1==b{print "#"$2; exit}'; }

# ---- behind-count vs the trunk (no fetch — uses last-known ref) -------------
behind() {
  local n
  n="$(git rev-list --count "$1..origin/$DEFAULT_BRANCH" 2>/dev/null)"
  [ -z "$n" ] && n="?"
  printf '%s' "$n"
}

# ---- assemble worktree rows -------------------------------------------------
WT_ROWS=""
while IFS= read -r line; do
  case "$line" in
    worktree\ *) WT_PATH="${line#worktree }" ;;
    branch\ *)   WT_BR="${line#branch refs/heads/}"
                 short="${WT_PATH##*/}"
                 iid="$(issue_id "$WT_BR")"
                 pr="$(pr_for "$WT_BR")"; [ -z "$pr" ] && pr="—"
                 b="$(behind "$WT_BR")"
                 WT_ROWS="${WT_ROWS}| ${iid} | \`${WT_BR}\` | ${pr} | ${b} | ${short} |
" ;;
    detached)    short="${WT_PATH##*/}"
                 WT_ROWS="${WT_ROWS}| — | _(detached)_ | — | — | ${short} |
" ;;
  esac
done < <(git worktree list --porcelain 2>/dev/null)

# ---- open PRs that are NOT checked out in any worktree ----------------------
WT_BRANCHES="$(git worktree list --porcelain 2>/dev/null | awk '/^branch /{sub("refs/heads/","",$2); print $2}')"
ORPHAN_PR_ROWS=""
if [ -n "$PR_TSV" ]; then
  while IFS=$'\t' read -r br num title; do
    [ -z "$br" ] && continue
    printf '%s\n' "$WT_BRANCHES" | grep -qx "$br" && continue
    iid="$(issue_id "$br")"
    ORPHAN_PR_ROWS="${ORPHAN_PR_ROWS}| ${iid} | \`${br}\` | #${num} | ${title} |
"
  done <<EOF
$PR_TSV
EOF
fi

LOCAL_N="$(git branch 2>/dev/null | wc -l | tr -d ' ')"
REMOTE_N="$(git branch -r 2>/dev/null | grep -vc HEAD)"
WT_N="$(git worktree list 2>/dev/null | wc -l | tr -d ' ')"

read -r -d '' BODY <<EOF
## 🗂️ In-flight work registry (repo-global)

Counts: ${WT_N} worktrees · ${LOCAL_N} local / ${REMOTE_N} remote branches. \
Behind = commits on \`origin/${DEFAULT_BRANCH}\` missing from that branch (staleness of its base; from last fetch).

### Worktrees → branch → issue → PR
| Issue | Branch | PR | Behind | Worktree |
|-------|--------|----|-------:|----------|
${WT_ROWS}
### Open PRs not in a worktree
| Issue | Branch | PR | Title |
|-------|--------|----|-------|
${ORPHAN_PR_ROWS}
**Before starting work:** (1) find your issue ID above — if a branch/worktree already exists for it, **continue that one, do not open a new branch**. (2) New branches: \`git fetch origin\` then base off fresh \`origin/${DEFAULT_BRANCH}\` (a high "Behind" means a stale base — the #1 divergence cause). (3) Name branches so the issue key appears (e.g. \`feat/ACME-123-slug\`) so this join works. (4) Run \`git fetch origin --prune\` if counts look stale.
EOF

if [ "$MODE" = "--hook" ]; then
  if command -v jq >/dev/null 2>&1; then
    jq -nc --arg ctx "$BODY" \
      '{hookSpecificOutput:{hookEventName:"SessionStart",additionalContext:$ctx}}' 2>/dev/null
  fi
  exit 0
fi

printf '%s\n' "$BODY"
exit 0
