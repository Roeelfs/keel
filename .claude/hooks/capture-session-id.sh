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
