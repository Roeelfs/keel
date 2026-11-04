#!/usr/bin/env bash
# Thin shim — logic lives in hook-syntax-sentinel.py. See that file's docstring.
# Deliberately NOT an embedded python block: this hook exists to catch exactly that bug.
set -uo pipefail
py="${HOME}/.claude/hooks/hook-syntax-sentinel.py"
# A MISSING .py must fall OPEN, never masquerade as a deny. `python3 <missing>` exits 2,
# byte-identical to an intentional PreToolUse block, so a vanished logic file would deny
# every matching call machine-wide rather than degrade quietly. Verified 2026-08-03.
[ -r "$py" ] || exit 0
exec python3 "$py"
