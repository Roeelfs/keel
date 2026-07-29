#!/bin/bash
# spawn-lane.sh — launch a headless Claude Code lane (the orchestrator's lane verb).
#
# The operator allowlists THIS path once; an orchestrator session may not invoke
# --permission-mode bypassPermissions or write its own allow rules directly.
#
# Usage:
#   spawn-lane.sh --mission <file|-> [--cwd <worktree>] [--worktree <name>]
#                 [--model <alias>] [--mode <permission-mode>] [--mcp-config <file>]
#
#   --worktree  ONLY on the first spawn. Every continuation uses --cwd <existing>;
#               a second --worktree collides with the locked worktree.
#
# Repo-specific setup (static-credential MCP servers, secrets, env) is NOT in this
# script. A repo supplies it as an executable hook at <lane-cwd>/.claude/lane-env.sh,
# sourced below; it may export LANE_MCP_CONFIG=<path to an mcp-config json>.
# Interactive-OAuth MCPs do not load in -p mode — only static-credential ones work.
set -euo pipefail

MISSION_SRC="" ; WORKTREE="" ; MODEL="sonnet" ; MODE="bypassPermissions" ; LANE_CWD="" ; MCP_CFG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --mission)    MISSION_SRC="$2"; shift 2 ;;
    --cwd)        LANE_CWD="$2"; shift 2 ;;
    --worktree)   WORKTREE="$2"; shift 2 ;;
    --model)      MODEL="$2"; shift 2 ;;
    --mode)       MODE="$2"; shift 2 ;;
    --mcp-config) MCP_CFG="$2"; shift 2 ;;
    *) echo "spawn-lane.sh: unknown arg $1" >&2; exit 2 ;;
  esac
done

[ -n "$MISSION_SRC" ] || { echo "spawn-lane.sh: --mission <file|-> required" >&2; exit 2; }
[ -n "$LANE_CWD" ] && cd "$LANE_CWD"

if [ "$MISSION_SRC" = "-" ]; then MISSION="$(cat)"; else MISSION="$(cat "$MISSION_SRC")"; fi
[ -n "$MISSION" ] || { echo "spawn-lane.sh: empty mission" >&2; exit 2; }

# Repo-supplied hook: may export LANE_MCP_CONFIG (and any lane-only env).
LANE_HOOK="${LANE_CWD:-$PWD}/.claude/lane-env.sh"
if [ -r "$LANE_HOOK" ]; then . "$LANE_HOOK"; fi
[ -z "$MCP_CFG" ] && MCP_CFG="${LANE_MCP_CONFIG:-}"

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
