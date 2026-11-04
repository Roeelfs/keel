#!/usr/bin/env bash
# chrome-focus-guard.sh — PreToolUse guard on the Control_Chrome MCP tools. Shim only;
# logic lives in chrome-focus-guard.py — an embedded `python3 -c` block is silently
# darkened by a single apostrophe in a comment, so it does not live here. See that
# file's docstring for the WHY and the verbatim index.js line numbers it is grounded in.
#
# SAFETY: fail-open on any parse error / missing python. Deny == exit 2. `python3
# <missing-file>` itself exits 2 — the SAME code as an intentional deny — so this
# explicitly checks the target .py is present and readable before invoking; a missing
# or unreadable .py falls back to ALLOW rather than masquerading as a real deny.
set -uo pipefail
command -v python3 >/dev/null 2>&1 || exit 0
input="$(cat 2>/dev/null || true)"; [ -z "$input" ] && exit 0
py="$(dirname "${BASH_SOURCE[0]}")/chrome-focus-guard.py"
[ -r "$py" ] || exit 0
printf '%s' "$input" | python3 "$py"
exit $?
