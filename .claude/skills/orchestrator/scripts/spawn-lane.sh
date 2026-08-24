#!/bin/bash
# spawn-lane.sh — launch a headless lane (the orchestrator's lane verb), on either runtime.
#
# The operator allowlists THIS path once; an orchestrator session may not invoke
# --permission-mode bypassPermissions or write its own allow rules directly.
#
# Usage:
#   spawn-lane.sh --mission <file|-> [--cwd <worktree>] [--worktree <name>]
#                 [--runtime claude|codex] [--model <alias>] [--mode <permission-mode>]
#                 [--mcp-config <file>]
#
#   --runtime codex   Spawn the lane on Codex instead of Claude. Separate billing pool.
#                     Defaults to claude, so every existing call site is unchanged.
#
# WHY A CODEX LANE COULD NOT SHIP UNTIL NOW, and what changed (probed 2026-08-24):
#   The Codex-first rule kept failing its metric because no Codex route could COMMIT, so
#   every shippable lane correctly fell to Claude. Two separate blockers, often conflated:
#     1. `codex-dispatch.sh` isolates $HOME to strip the preamble (~30% off input). That
#        also strips git identity and ssh keys — right for a read-only document lane,
#        disqualifying for anything that ships. This script does NOT use that wrapper.
#     2. Raw `codex exec -s workspace-write` still cannot commit: the sandbox excludes
#        `.git`, and the lane dies on
#          `fatal: Unable to create .../.git/index.lock: Operation not permitted`
#        Git IDENTITY was never the binding constraint; write access to `.git` was.
#   Granting `.git` as an explicit writable root fixes it. Verified both directions: with
#   the grant, commit `d79c968` was authored `Roee Alfasi <roie.lfs@gmail.com>` — the host
#   identity, unchanged; without it, the same prompt produced only the seed commit and the
#   `index.lock` error above.
#
#   The grant permits history rewriting inside that worktree. That is bounded by the
#   one-lane-one-worktree rule and is the price of a lane that can ship; do not widen it to
#   a repo root shared with other lanes.
#
#   --worktree  ONLY on the first spawn. Every continuation uses --cwd <existing>;
#               a second --worktree collides with the locked worktree.
#
# Repo-specific setup (static-credential MCP servers, secrets, env) is NOT in this
# script. A repo supplies it as an executable hook at <lane-cwd>/.claude/lane-env.sh,
# sourced below; it may export LANE_MCP_CONFIG=<path to an mcp-config json>.
# Interactive-OAuth MCPs do not load in -p mode — only static-credential ones work.
set -euo pipefail

MISSION_SRC="" ; WORKTREE="" ; MODEL="" ; MODE="bypassPermissions" ; LANE_CWD="" ; MCP_CFG=""
RUNTIME="claude"
while [ $# -gt 0 ]; do
  case "$1" in
    --mission)    MISSION_SRC="$2"; shift 2 ;;
    --cwd)        LANE_CWD="$2"; shift 2 ;;
    --worktree)   WORKTREE="$2"; shift 2 ;;
    --model)      MODEL="$2"; shift 2 ;;
    --runtime)    RUNTIME="$2"; shift 2 ;;
    --mode)       MODE="$2"; shift 2 ;;
    --mcp-config) MCP_CFG="$2"; shift 2 ;;
    *) echo "spawn-lane.sh: unknown arg $1" >&2; exit 2 ;;
  esac
done

[ -n "$MISSION_SRC" ] || { echo "spawn-lane.sh: --mission <file|-> required" >&2; exit 2; }
case "$RUNTIME" in
  claude) : "${MODEL:=sonnet}" ;;
  codex)  : "${MODEL:=gpt-5.6-terra}" ;;
  *) echo "spawn-lane.sh: --runtime must be claude|codex (got '$RUNTIME')" >&2; exit 2 ;;
esac
[ -n "$LANE_CWD" ] && cd "$LANE_CWD"

if [ "$MISSION_SRC" = "-" ]; then MISSION="$(cat)"; else MISSION="$(cat "$MISSION_SRC")"; fi
[ -n "$MISSION" ] || { echo "spawn-lane.sh: empty mission" >&2; exit 2; }

# Repo-supplied hook: may export LANE_MCP_CONFIG (and any lane-only env).
LANE_HOOK="${LANE_CWD:-$PWD}/.claude/lane-env.sh"
if [ -r "$LANE_HOOK" ]; then . "$LANE_HOOK"; fi
[ -z "$MCP_CFG" ] && MCP_CFG="${LANE_MCP_CONFIG:-}"

if [ "$RUNTIME" = codex ]; then
  # The worktree must already exist: Codex has no --worktree equivalent, so the caller
  # creates it and passes --cwd. Failing loudly beats spawning into the wrong directory.
  [ -n "$WORKTREE" ] && { echo "spawn-lane.sh: --worktree is claude-only; create it first and pass --cwd" >&2; exit 2; }
  # BOTH git dirs, or a lane in a linked worktree cannot commit. In a linked worktree
  # --absolute-git-dir is .git/worktrees/<name> (HEAD, index, per-worktree refs) while
  # objects and refs/heads live in the COMMON dir — and the common dir is outside the
  # workspace. Granting only the first writes the file and then dies on
  # `Operation not permitted`, which is the orchestrator's actual shape.
  #
  # This nearly shipped: the first end-to-end test passed because the scratch repo sat
  # under /tmp, which `workspace-write` grants by DEFAULT (the banner reads
  # `[workdir, /tmp, $TMPDIR, ...]`). Re-run outside /tmp it failed immediately. Any probe
  # of this sandbox must live outside /tmp or it proves nothing.
  GIT_DIR_PATH="$(git rev-parse --path-format=absolute --absolute-git-dir 2>/dev/null || true)"
  GIT_COMMON_PATH="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
  [ -n "$GIT_DIR_PATH" ] || { echo "spawn-lane.sh: --runtime codex must run inside a git repo (--cwd)" >&2; exit 2; }
  ROOTS="\"$GIT_DIR_PATH\""
  [ -n "$GIT_COMMON_PATH" ] && [ "$GIT_COMMON_PATH" != "$GIT_DIR_PATH" ] && ROOTS="$ROOTS,\"$GIT_COMMON_PATH\""
  CARGS=( --skip-git-repo-check -m "$MODEL" -s workspace-write
          -c "sandbox_workspace_write.writable_roots=[$ROOTS]" )
  # Same stdin discipline as the claude path, and for the same reason: `codex exec` with an
  # inherited pipe hangs on "Reading additional input from stdin" and never runs the mission.
  if [ "$MISSION_SRC" = "-" ]; then
    exec env -u CLAUDE_SESSION_ID -u CLAUDE_CODE_ENTRYPOINT -u CLAUDECODE \
      codex exec "${CARGS[@]}" "$MISSION"
  else
    exec env -u CLAUDE_SESSION_ID -u CLAUDE_CODE_ENTRYPOINT -u CLAUDECODE \
      codex exec "${CARGS[@]}" "$MISSION" < /dev/null
  fi
fi

ARGS=( --permission-mode "$MODE" --session-id "$(uuidgen | tr 'A-Z' 'a-z')" --model "$MODEL" )
[ -n "$WORKTREE" ] && ARGS+=( --worktree "$WORKTREE" )
[ -n "$MCP_CFG" ] && ARGS+=( --mcp-config "$MCP_CFG" )
ARGS+=( -p --output-format json )

# Stdin discipline: an inherited pipe or tty makes `claude -p` wait on stdin and can
# silently no-op the run (observed: exit 0, 0 bytes, zero work, locked empty worktree).
# Unless the mission itself came from stdin, hard-detach stdin from /dev/null.
# Identity scrub: the child must not masquerade as the parent session.
if [ "$MISSION_SRC" = "-" ]; then
  exec env -u CLAUDE_SESSION_ID -u CLAUDE_CODE_ENTRYPOINT -u CLAUDECODE \
    claude "${ARGS[@]}" "$MISSION"
else
  exec env -u CLAUDE_SESSION_ID -u CLAUDE_CODE_ENTRYPOINT -u CLAUDECODE \
    claude "${ARGS[@]}" "$MISSION" < /dev/null
fi
