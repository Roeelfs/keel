#!/usr/bin/env bash
# codex-first-gate.sh — PreToolUse (Agent|Task|Workflow). Shim only; logic lives in
# codex-first-gate.py (an embedded `python3 -c` block is silently darkened by one apostrophe).
# See that file's docstring for what is gated, the `Codex-no:` escape and the kill switch.
# FAILS OPEN: a missing .py or any python error lets the dispatch through.
set -uo pipefail
py="$(dirname "${BASH_SOURCE[0]}")/codex-first-gate.py"
[ -r "$py" ] || exit 0
input=$(cat 2>/dev/null || echo '{}')
/usr/bin/python3 "$py" <<< "$input" 2>/dev/null || exit 0
exit 0
