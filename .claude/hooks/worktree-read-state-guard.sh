#!/usr/bin/env bash
# Shim only. Logic lives in worktree-read-state-guard.py — an embedded `python3 -c` block
# is silently darkened by a single apostrophe in a comment, so it does not live here.
set -uo pipefail
py="$(dirname "${BASH_SOURCE[0]}")/worktree-read-state-guard.py"
# A MISSING .py must fall OPEN, never masquerade as a deny. `python3 <missing>` exits 2,
# byte-identical to an intentional PreToolUse block, so a vanished logic file would deny
# every matching call machine-wide rather than degrade quietly. Verified 2026-08-03.
[ -r "$py" ] || exit 0
exec /usr/bin/python3 "$py"
