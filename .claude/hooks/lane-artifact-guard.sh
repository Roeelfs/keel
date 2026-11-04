#!/usr/bin/env bash
# Thin shim. The logic lives in lane-artifact-guard.py — a real .py file, deliberately not
# an embedded `python3 -c '...'` block, because one apostrophe in a comment terminates the
# shell string and silently turns the guard into a no-op (three occurrences in one session).
# Stderr is NOT suppressed here: swallowing it is what let a broken guard read as working.
set -uo pipefail
py="${HOME}/.claude/hooks/lane-artifact-guard.py"
# A MISSING .py must fall OPEN, never masquerade as a deny. `python3 <missing>` exits 2,
# byte-identical to an intentional PreToolUse block, so a vanished logic file would deny
# every matching call machine-wide rather than degrade quietly. Verified 2026-08-03.
[ -r "$py" ] || exit 0
exec python3 "$py"
