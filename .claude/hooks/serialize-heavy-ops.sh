#!/usr/bin/env bash
# serialize-heavy-ops.sh — PreToolUse(Bash) guard.
#
# THE PROBLEM: when several Claude Code sessions run in parallel (one per
# worktree), each happily kicks off a full test suite or build at the same time.
# N concurrent `vitest run` / `next build` invocations drive load average through
# the roof and the machine grinds — or worse, the agent gives up on local tests
# and pushes to CI just to get a green check, burning CI minutes.
#
# THE FIX: a real machine-global lock (tooling/sandbox/with-heavy-lock) serializes
# heavy ops by QUEUING — they wait, then run LOCALLY, one at a time. A hook can't
# hold a lock across a command's lifetime, so this hook's only job is to ENFORCE
# that heavy ops acquire the lock: allow anything already lock-aware (wrapped in
# `with-heavy-lock`), refuse heavy ops that aren't, and tell the caller to prefix
# the wrapper. No racy `ps` detection, no "push to CI" escape hatch.
#
# FAIL-OPEN: any parse error / missing python / non-match -> exit 0 (allow).
# Deny == exit 2 (Claude Code blocks the call, stderr shown to the model).
set -uo pipefail

input="$(cat 2>/dev/null || true)"; [ -z "$input" ] && exit 0
cmd="$(printf '%s' "$input" | python3 -c 'import sys,json
try: print(json.load(sys.stdin).get("tool_input",{}).get("command",""))
except Exception: print("")' 2>/dev/null || true)"
[ -z "$cmd" ] && exit 0

m() { printf '%s' "$cmd" | grep -Eq "$1"; }

# --- Lock-aware? Then it already serializes via flock — always allow. ---
if m '(^|[[:space:];&|(/])with-heavy-lock([[:space:]]|$)'; then exit 0; fi

# --- Does the INCOMING command START a heavy op? (anchored; mentions ignored) ---
heavy_kind=""
if   m '(^|[;&|(])[[:space:]]*((npx|pnpm|npm|yarn)[[:space:]]+(exec[[:space:]]+|run[[:space:]]+|dlx[[:space:]]+)?)?(vitest|jest)([[:space:]]|$)'; then heavy_kind="unit-tests"
elif m '(^|[;&|(])[[:space:]]*(pnpm|npm|yarn)([[:space:]]+run)?[[:space:]]+test([[:space:]:]|$)';                                              then heavy_kind="test-script"
elif m '(^|[;&|(])[[:space:]]*((npx|pnpm|npm|yarn|turbo)[[:space:]]+(exec[[:space:]]+|run[[:space:]]+)?)?next[[:space:]]+build([[:space:]]|$)'; then heavy_kind="next-build"
elif m '(^|[;&|(])[[:space:]]*(pnpm|npm|yarn|turbo)([[:space:]]+run)?[[:space:]]+build([[:space:]:]|$)';                                       then heavy_kind="build"
elif m '(^|[;&|(])[[:space:]]*turbo[[:space:]]+(run[[:space:]]+)?[[:alnum:]_-]*build';                                                         then heavy_kind="turbo-build"
elif m '(^|[;&|(])[[:space:]]*(pnpm[[:space:]]+(install|i)|npm[[:space:]]+(install|ci)|yarn([[:space:]]+install)?)([[:space:]]|$)';            then heavy_kind="install"
fi
[ -z "$heavy_kind" ] && exit 0

# Rollout safety: only ENFORCE the wrapper once it's installed (on PATH). Until
# then, refusing would hard-break a setup that hasn't run install.sh yet, so
# degrade to ALLOW in that window (lock-aware commands still queue). Install with:
#   cp tooling/sandbox/with-heavy-lock /usr/local/bin/ && chmod +x /usr/local/bin/with-heavy-lock
command -v with-heavy-lock >/dev/null 2>&1 || exit 0

# Heavy + not lock-aware + wrapper available → refuse, point at the wrapper.
echo "🚦 Heavy op (${heavy_kind}) must run under the machine-global lock so parallel agent sessions don't melt the machine." >&2
echo "It will QUEUE (wait-then-run locally), not be refused. Prefix it with the wrapper:" >&2
echo "" >&2
echo "    with-heavy-lock ${cmd}" >&2
echo "" >&2
echo "Light ops stay parallel and need no wrapper: reads, grep, edits, git/gh, typecheck, lint." >&2
exit 2
