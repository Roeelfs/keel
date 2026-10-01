#!/bin/bash
# spawn-lane.sh — launch a headless lane (the orchestrator's lane verb), on either runtime.
#
# The operator allowlists THIS path once; an orchestrator session may not invoke
# --permission-mode bypassPermissions or write its own allow rules directly.
#
# Usage:
#   spawn-lane.sh --mission <file|-> [--cwd <worktree>] [--worktree <name>]
#                 [--runtime claude|codex] [--model <alias>] [--class <task-class>] [--mode <permission-mode>]
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
RUNTIME="claude" ; ALLOW_NETWORK=0 ; CLASS="standard" ; CLASS_SET=0
while [ $# -gt 0 ]; do
  case "$1" in
    --mission)    MISSION_SRC="$2"; shift 2 ;;
    --cwd)        LANE_CWD="$2"; shift 2 ;;
    --worktree)   WORKTREE="$2"; shift 2 ;;
    --model)      MODEL="$2"; shift 2 ;;
    --runtime)    RUNTIME="$2"; shift 2 ;;
    --class)      CLASS="$2"; CLASS_SET=1; shift 2 ;;
    --allow-network) ALLOW_NETWORK=1; shift 1 ;;
    --mode)       MODE="$2"; shift 2 ;;
    --mcp-config) MCP_CFG="$2"; shift 2 ;;
    *) echo "spawn-lane.sh: unknown arg $1" >&2; exit 2 ;;
  esac
done

[ -n "$MISSION_SRC" ] || { echo "spawn-lane.sh: --mission <file|-> required" >&2; exit 2; }
case "$RUNTIME" in
  claude)
    [ "$CLASS_SET" = 0 ] || { echo "spawn-lane.sh: --class is codex-only" >&2; exit 2; }
    : "${MODEL:=sonnet}" ;;
  codex) : ;;
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
  # ---- parity: refuse options this path cannot honor, never accept-and-drop -------------
  # Accepting a capability-bearing option and then omitting the capability is a dead-lane
  # defect: a caller asking for a restrictive --mode would get Codex's unrelated defaults,
  # and LANE_MCP_CONFIG (the documented product of .claude/lane-env.sh, SKILL.md "Repo lane hook") would
  # become dead data while the skill still promises the lane gets those MCPs.
  [ -n "$WORKTREE" ] && { echo "spawn-lane.sh: --worktree is claude-only; create it first and pass --cwd" >&2; exit 2; }
  [ -n "$MCP_CFG" ] && { echo "spawn-lane.sh: --mcp-config is claude-only; supplied MCP config is unsupported on codex. Keep this lane on claude." >&2; exit 2; }
  [ "$MODE" != bypassPermissions ] && { echo "spawn-lane.sh: --mode is claude-only; codex sandboxing is set by this script. Keep this lane on claude." >&2; exit 2; }

  # All Codex launches, including explicit model overrides, consult the central cap gate.
  # Unknown-cap routes intentionally dispatch; missing or malformed gate responses do not.
  GATE="$HOME/.claude/scripts/codex-headroom.sh"
  [ -x "$GATE" ] || { echo "spawn-lane.sh: missing executable headroom gate" >&2; exit 2; }
  GATE_RC=0
  ROUTE="$("$GATE" --route "$CLASS")" || GATE_RC=$?
  case "$GATE_RC" in
    0|1) ;;
    *) echo "spawn-lane.sh: headroom gate refused or failed (rc=$GATE_RC); use Claude" >&2; exit 2 ;;
  esac
  read -r ROUTED_MODEL EFFORT EXTRA <<< "$ROUTE" || true
  case "$ROUTED_MODEL" in
    gpt-*) ;;
    *) echo "spawn-lane.sh: unusable headroom model; refusing" >&2; exit 2 ;;
  esac
  case "$EFFORT" in
    low|medium|high|xhigh|max) ;;
    *) echo "spawn-lane.sh: unusable headroom effort; refusing" >&2; exit 2 ;;
  esac
  [ -z "$EXTRA" ] && [ "$ROUTE" = "$ROUTED_MODEL $EFFORT" ] || {
    echo "spawn-lane.sh: malformed headroom route; refusing" >&2; exit 2;
  }
  : "${MODEL:=$ROUTED_MODEL}"

  # ---- writable roots: BOTH git dirs, and ENCODED, never interpolated -------------------
  # Both, because in a linked worktree --absolute-git-dir is .git/worktrees/<name> (HEAD,
  # index, per-worktree refs) while objects and refs/heads live in the COMMON dir, outside
  # the workspace. Granting only the first writes the file then dies on
  # `Operation not permitted` — the orchestrator's actual shape.
  #
  # THE COMMON GRANT IS A REAL WIDENING. Do not repeat the earlier claim that it is "bounded
  # by one-lane-one-worktree" — that was false. The common dir carries every local and
  # remote-tracking ref, the stash, the object database, shared config, and metadata for
  # EVERY linked worktree of this repo. It is also a persistence path: a lane can rewrite
  # `.git/config` to point core.hooksPath at a hook it placed there, so a later git command
  # in the parent or a sibling worktree would execute lane-authored code outside this
  # sandbox. What actually bounds the blast radius is that the lane CANNOT PUSH (below), so
  # damage stays local and is recoverable by discarding the worktree and resetting refs.
  #
  # The value is TOML, and it was previously built by pasting the path between literal
  # quotes. A `"` in a path then injects ADDITIONAL writable roots — demonstrated granting
  # ~/.ssh with exit 0 and no shell metacharacter. Encode with a real serializer.
  GIT_DIR_PATH="$(git rev-parse --path-format=absolute --absolute-git-dir 2>/dev/null || true)"
  GIT_COMMON_PATH="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
  [ -n "$GIT_DIR_PATH" ] || { echo "spawn-lane.sh: --runtime codex must run inside a git repo (--cwd)" >&2; exit 2; }
  ROOTS_JSON="$(GIT_DIR_PATH="$GIT_DIR_PATH" GIT_COMMON_PATH="$GIT_COMMON_PATH" /usr/bin/python3 -c '
import json, os, sys
roots = [os.environ["GIT_DIR_PATH"]]
common = os.environ.get("GIT_COMMON_PATH") or ""
if common and common != roots[0]:
    roots.append(common)
for r in roots:
    # A control character cannot appear in a path we are willing to grant; refuse rather
    # than emit an escape whose handling in the TOML reader we have not verified.
    if any(ord(c) < 0x20 for c in r):
        sys.exit("spawn-lane.sh: refusing a git dir containing a control character")
print(json.dumps(roots))')" || exit 2

  # ---- no push authority ---------------------------------------------------------------
  # workspace-write is network-DENIED by default and STAYS that way. With HOME preserved,
  # shared git config granted and network open, a lane would hold the operator's full push
  # authority with no ref-level restriction — `git push origin HEAD:main` as spellable as
  # its own branch, gated only by prompt text, against a machine contract that names that
  # exact command a production verb needing in-session approval. Denying egress removes the
  # question instead of guarding it.
  #
  # THE SEAM: the lane commits; the ORCHESTRATOR pushes after grading the artifact. That is
  # the same division the advance tick already uses for deploys.
  #
  # --allow-network re-opens egress for a lane that genuinely needs it (a package install,
  # a vendor API). It confers push authority as a side effect. Do not use it to make a lane
  # "ship by itself"; use it when the WORK needs the network, and grade what it pushed.
  CARGS=( --skip-git-repo-check -m "$MODEL" -s workspace-write
          -c "model_reasoning_effort=$EFFORT"
          -c "sandbox_workspace_write.writable_roots=$ROOTS_JSON" )
  if [ "$ALLOW_NETWORK" = 1 ]; then
    CARGS+=( -c "sandbox_workspace_write.network_access=true" )
  else
    CARGS+=( -c "sandbox_workspace_write.network_access=false" )
  fi

  # ---- dead-lane signal ----------------------------------------------------------------
  # The claude path gets --output-format json, so empty stdout + exit 0 proves it never ran.
  # Codex has no equivalent unless asked: docs/codex-lane-contract.md requires -o <outfile>
  # and grades THAT to separate DEAD from BLOCKED-ON-QUOTA. Without it a caller has no
  # runtime-health signal at all.
  LANE_OUT="${LANE_OUT:-${TMPDIR:-/tmp}/codex-lane-$(uuidgen | tr 'A-Z' 'a-z').json}"
  CARGS+=( -o "$LANE_OUT" )
  echo "spawn-lane.sh: codex lane output -> $LANE_OUT" >&2

  # ---- Session-Id trailer --------------------------------------------------------------
  # ~/.codex/AGENTS.md requires every Codex commit to carry a Session-Id trailer, and no
  # commit-msg hook exists here to add one. The launcher cannot force the model's git
  # invocation, so it does the two things it CAN do deterministically: mint a stable lane
  # key, and state the requirement in the mission every single time.
  LANE_KEY="codex-lane-$(uuidgen | tr 'A-Z' 'a-z')"
  # The lane never pushes; the session that spawned it does, and owns the resulting PR. Record
  # lane -> parent session BEFORE the identity scrub below, so a PR whose commits carry only lane
  # keys still resolves to a session a peer can message. Best-effort: a write failure never
  # blocks the lane.
  if [ -n "${CLAUDE_SESSION_ID:-}" ]; then
    mkdir -p "$HOME/.claude/state" 2>/dev/null &&
      printf '{"lane":"%s","parent":"%s","ts":"%s"}\n' "$LANE_KEY" "$CLAUDE_SESSION_ID" \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$HOME/.claude/state/lane-parents.jsonl" 2>/dev/null || true
  fi
  MISSION="$MISSION

--- appended by spawn-lane.sh (non-negotiable) ---
Every commit you make MUST carry this git trailer, or it is invalid on this machine:
  --trailer \"Session-Id: $LANE_KEY\"
Do NOT push, open a PR, or touch a remote. Commit locally and report your branch and SHAs;
the orchestrator pushes after grading. If you find yourself wanting to push, you are done."

  # Same stdin discipline as the claude path, and for the same reason: `codex exec` with an
  # inherited pipe hangs on "Reading additional input from stdin" and never runs the mission.
  # ---- zero-commit guard (implementation lanes only) -------------------------------------
  # An implementation lane exists to commit. A clean exit with HEAD unchanged is a dead lane
  # wearing a success code. Research lanes legitimately commit nothing, so they keep exec.
  if [ "$CLASS" != implementation ]; then
    if [ "$MISSION_SRC" = "-" ]; then
      exec env -u CLAUDE_SESSION_ID -u CLAUDE_CODE_ENTRYPOINT -u CLAUDECODE \
        codex exec "${CARGS[@]}" "$MISSION"
    else
      exec env -u CLAUDE_SESSION_ID -u CLAUDE_CODE_ENTRYPOINT -u CLAUDECODE \
        codex exec "${CARGS[@]}" "$MISSION" < /dev/null
    fi
  fi
  HEAD_BEFORE="$(git rev-parse HEAD 2>/dev/null || echo none)"
  CODEX_RC=0
  if [ "$MISSION_SRC" = "-" ]; then
    env -u CLAUDE_SESSION_ID -u CLAUDE_CODE_ENTRYPOINT -u CLAUDECODE \
      codex exec "${CARGS[@]}" "$MISSION" || CODEX_RC=$?
  else
    env -u CLAUDE_SESSION_ID -u CLAUDE_CODE_ENTRYPOINT -u CLAUDECODE \
      codex exec "${CARGS[@]}" "$MISSION" < /dev/null || CODEX_RC=$?
  fi
  [ "$CODEX_RC" -ne 0 ] && exit "$CODEX_RC"
  if [ "$(git rev-parse HEAD 2>/dev/null || echo none)" = "$HEAD_BEFORE" ]; then
    if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
      echo "spawn-lane.sh: DEAD LANE: codex exited 0 but committed nothing; uncommitted work is left in $(pwd), salvage before re-dispatch" >&2
    else
      echo "spawn-lane.sh: DEAD LANE: codex exited 0 but committed nothing and left a clean tree" >&2
    fi
    exit 3
  fi
  exit 0
fi

ARGS=( --permission-mode "$MODE" --session-id "$(uuidgen | tr 'A-Z' 'a-z')" --model "$MODEL" )
[ -n "$WORKTREE" ] && ARGS+=( --worktree "$WORKTREE" )
[ -n "$MCP_CFG" ] && ARGS+=( --mcp-config "$MCP_CFG" )
ARGS+=( -p --output-format json --permission-prompts none )

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
