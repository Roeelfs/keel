#!/usr/bin/env bash
# serialize-heavy-ops.sh — PreToolUse(Bash) guard; logic lives in the sibling .py
# (no embedded python block, per the repo's own hook convention). Fails OPEN.
exec python3 "$(dirname "$0")/serialize-heavy-ops.py"
