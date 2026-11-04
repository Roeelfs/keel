#!/usr/bin/env bash
# zsh-pipestatus-guard.sh — PreToolUse (Bash). Shim only; logic lives in
# zsh-pipestatus-guard.py — an embedded `python3 -c` block is silently darkened by a
# single apostrophe in a comment, so it does not live here. See that file's docstring
# for the WHY / FALSE-POSITIVE-CONTROL rationale.
#
# Escape: PIPESTATUS_OK=1. FAILS OPEN on any parse error.
set -uo pipefail
input=$(cat 2>/dev/null || echo '{}')

[ "${PIPESTATUS_OK:-0}" = "1" ] && exit 0

/usr/bin/python3 "$(dirname "${BASH_SOURCE[0]}")/zsh-pipestatus-guard.py" <<< "$input" 2>/dev/null || exit 0

exit 0
