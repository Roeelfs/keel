#!/bin/sh
# SessionStart hook: Capture Claude Code session ID as an env var.
# Reads session_id from stdin JSON and persists it via CLAUDE_ENV_FILE
# so it's available as $CLAUDE_SESSION_ID for the entire session.
#
# Everything downstream that ties work back to a session — the workflow
# path-ownership CLI, the `Session-Id:` commit trailer, the session miner —
# depends on this one var being set. Keep this hook first.

INPUT=$(cat)

SESSION_ID=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('session_id',''))" 2>/dev/null)

if [ -n "$SESSION_ID" ] && [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "export CLAUDE_SESSION_ID=$SESSION_ID" >> "$CLAUDE_ENV_FILE"
fi

# Linked worktree only: state the id literally. The native guard in a worktree-isolated
# session refuses any `$...` in a git command, so the `$CLAUDE_SESSION_ID` trailer form is
# denied while the literal id succeeds. Measured 2026-11-03: every denied commit came from
# a session started in a linked worktree, and all 7 denied literal-id commits carried
# another `$` such as `$?`. Silent elsewhere, because this text is paid on every turn.
CWD=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('cwd',''))" 2>/dev/null)
if [ -n "$SESSION_ID" ] && [ -n "$CWD" ]; then
  WT_GIT_DIR=$(git -C "$CWD" rev-parse --path-format=absolute --git-dir 2>/dev/null)
  WT_COMMON_DIR=$(git -C "$CWD" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)
  if [ -n "$WT_GIT_DIR" ] && [ "$WT_GIT_DIR" != "$WT_COMMON_DIR" ]; then
    printf 'This session id is %s. In a linked worktree the git guard can refuse any `$...` in a git command, including `$CLAUDE_SESSION_ID`, so here use the literal id in a plain, separate command with no `$`, `&&`, `;` or pipe: git commit -F <file> --trailer "Session-Id: %s"\n' "$SESSION_ID" "$SESSION_ID"
  fi
fi
