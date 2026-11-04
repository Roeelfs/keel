#!/usr/bin/env bash
# _run.sh — fail-OPEN wrapper for PreToolUse guards.
#
# WHY: a PreToolUse hook that exits non-zero BLOCKS the tool call. bash exits 2 on a
# parse error — the same code as an intentional block — so a single typo in any guard
# wedges EVERY Bash call in EVERY session on this machine, while the guard's own header
# claims it fails open. Observed live 2026-08-03: one apostrophe inside an embedded
# `python3 -c '...'` block terminated the shell string and broke the session until fixed.
#
# The trade: a broken guard goes silent instead of taking the machine down — an outage
# becomes a coverage hole, which is only the right trade if the hole is LOUD. Two things
# make it loud, and neither is automatic-by-wishing:
#   - PostToolUse(Edit|Write) runs `hook-syntax-sentinel.sh`, which reports the break in
#     the same turn that caused it. This is the one that actually fires on its own.
#   - `~/.claude/scripts/replay-hook.sh syntax` sweeps every hook — but it is a MANUAL
#     command. Nothing invokes it; do not read it as a gate.
# The wrapper also says the guard is dark via systemMessage.
# CAVEAT: on PreToolUse an exit-0 hook has NO verified model-facing channel — this
# notice reaches the human's TUI, and may not reach the model at all. Accepted trade:
# the alternative is exit 2, which would BLOCK the call the wrapper exists to let through.
#
# Usage in settings.json:  bash ~/.claude/hooks/_run.sh <hook-file.sh>
set -uo pipefail
HOOK_DIR="${HOME}/.claude/hooks"
hook="${1:-}"
[ -n "$hook" ] || exit 0
path="$HOOK_DIR/$hook"
[ -f "$path" ] || exit 0        # a removed hook must never block a tool call

if ! err="$(bash -n "$path" 2>&1)"; then
  # Broken guard: report it loudly, but ALLOW the call through.
  python3 -c '
import sys, json
print(json.dumps({"systemMessage":
  "[hook] "+sys.argv[1]+" FAILED TO PARSE and is currently DARK — every check it owns "
  "is silently disabled. Fix it, then run ~/.claude/scripts/replay-hook.sh syntax.\n"
  +sys.argv[2][:400]}))' "$hook" "$err" 2>/dev/null
  exit 0
fi

# Record silent hook runs too; analytics must never interfere with the guard or its stdin.
(
  ts="${EPOCHSECONDS:-$(date +%s)}" || exit 0
  name="${hook//\\/\\\\}"
  name="${name//\"/\\\"}"
  name="${name//$'\n'/\\n}"
  name="${name//$'\r'/\\r}"
  name="${name//$'\t'/\\t}"
  printf '{"ts":%s,"hook":"%s"}\n' "$ts" "$name" >> "${HOME}/.claude/analytics/hook-runs.jsonl"
) </dev/null 2>/dev/null || :

exec bash "$path"
