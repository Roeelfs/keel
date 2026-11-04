#!/usr/bin/env bash
# permission-denial-ledger.sh — PermissionDenied hook, LOG-ONLY, always exit 0.
#
# WHY (improve-harness 2026-09-06, H15): a denial is the one harness event that had no
# ledger. PostToolUse runs only after a SUCCESSFUL tool; classifier-denial-repeat-guard.py
# blocks the 3rd identical signature but writes nothing; so "7 denials in 20 minutes in
# one session" was only recoverable by mining transcripts. This appends one row per
# denial so the next improve-harness run reads denial pressure off a file.
#
# CONTRACT: fires on every behavior:"deny" — settings deny rules, hook exit-2 blocks, and
# the auto-mode classifier alike (traced: createCanUseTool -> emitPermissionDenied).
# Payload: {hook_event_name, tool_name, tool_input, tool_use_id, reason} over the base
# {session_id, transcript_path, cwd}. tool_input is HASHED, never stored raw (it can carry
# secrets and paths); the first 80 chars of a Bash command are kept as a fingerprint
# after redacting quoted spans.
# SELF-PROBE (mandatory, a pass and a no-op must not look alike): after wiring, issue one
# known-blockable op (e.g. `dd if=/dev/zero of=/dev/null count=1`, denied by the settings
# deny list) and confirm a row lands in analytics/permission-denials.jsonl. No row = DARK.
set -uo pipefail
input="$(cat 2>/dev/null || true)"
[ -z "$input" ] && exit 0
LEDGER="${HOME}/.claude/analytics/permission-denials.jsonl"
hook_dir="$(dirname "${BASH_SOURCE[0]}")"
printf '%s' "$input" | /usr/bin/python3 "$hook_dir/permission-denial-ledger.py" "$LEDGER" 2>/dev/null || true
exit 0
