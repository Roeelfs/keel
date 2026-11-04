#!/usr/bin/env bash
# replay-hook.sh — the standing regression gate for every hook edit.
#
# WHY THIS EXISTS: a synthetic dry-run proves only that a hook matches its author's
# model of the bug. Observed 2026-07-24: a guard passed 9/9 hand-written cases, shipped,
# and was a false negative on 3 of 3 REAL incidents while blocking live work. The only
# valid acceptance test is a replay against the transcripts that motivated the change.
#
# Two arms, always. A hook that fires on the NEGATIVE set is worse than no hook.
#
#   replay-hook.sh syntax                       — bash -n every hook (run this FIRST)
#   replay-hook.sh check                        — installed heavy-command hook == keel's, rewrite intact
#   replay-hook.sh probe   <hook> <cmd>         — one command through one hook, show verdict
#   replay-hook.sh corpus  <hook> [glob] [max]  — replay every Bash call in real transcripts
#
# Exit: 0 clean, 1 regression.
set -uo pipefail
HOOKS="$HOME/.claude/hooks"
PROJ="$HOME/.claude/projects"

die() { printf '%s\n' "$*" >&2; exit 1; }

# --- syntax: the 50ms gate that would have caught a live breakage ------------------
cmd_syntax() {
  local rc=0 f
  for f in "$HOOKS"/*.sh; do
    if bash -n "$f" 2>/dev/null; then
      printf '  ok    %s\n' "${f##*/}"
    else
      printf '  BROKE %s\n' "${f##*/}"; bash -n "$f" 2>&1 | sed 's/^/          /'; rc=1
    fi
  done
  # .py hooks too. Added after a guard whose logic was moved OUT of an embedded block into
  # a real .py file would have been invisible to a .sh-only gate.
  for f in "$HOOKS"/*.py; do
    [ -e "$f" ] || continue
    if python3 -m py_compile "$f" 2>/dev/null; then
      printf '  ok    %s\n' "${f##*/}"
    else
      printf '  BROKE %s\n' "${f##*/}"; python3 -m py_compile "$f" 2>&1 | sed 's/^/          /'; rc=1
    fi
  done
  # An embedded `python3 -c '...'` block sits inside a SINGLE-QUOTED shell string: one
  # apostrophe in a comment silently terminates it (three occurrences in one session).
  # bash -n catches the breakage; this flags the HAZARD. Only report blocks over ~40 lines
  # — nearly every hook here embeds a small block, and flagging all 19 is how a checker
  # teaches you to ignore it. Long blocks are where a prose comment (and its apostrophe)
  # actually gets written.
  python3 - "$HOOKS" <<'PYEOF'
import sys, glob, os, re
START = re.compile(r"python3 -c '")
# Find the block's closing quote by SCANNING FORWARD FROM THE OPENER, exactly as the
# shell does — never by looking for a line that starts with a quote. The line-based
# version could not see a block that opened and closed on ONE line: it set inblk and
# skipped to the next line, then counted every remaining line in the file. That printed
  # a phantom long embedded block for a hook whose blocks were all one-liners — and a
  # checker that cries wolf is how you learn to ignore its real notes
# (bash-git-guards.sh's 61-line block, sitting in the same output, is genuine).
#
# Scanning to the first `'` mirrors the shell's own parse, so a block already broken by
# a stray apostrophe measures short and goes unflagged here — that case is `bash -n`'s,
# and it is checked above.
for f in sorted(glob.glob(os.path.join(sys.argv[1], "*.sh"))):
    try:
        s = open(f, errors="ignore").read()
    except OSError:
        continue
    for m in START.finditer(s):
        end = s.find("'", m.end())
        if end < 0:
            continue
        n = s.count("\n", m.end(), end) + 1
        if n > 40:
            print(f"  note  {os.path.basename(f)} — {n}-line embedded python block; move it to a")
            print( "        sibling .py and `exec python3 <path>` (kills the apostrophe hazard).")
PYEOF
  return $rc
}

# --- envelope: reconstruct the real PreToolUse stdin -------------------------------
envelope() { # $1=command  $2=cwd
  python3 -c '
import json,sys
print(json.dumps({"session_id":"replay","transcript_path":"/dev/null","cwd":sys.argv[2],
  "hook_event_name":"PreToolUse","tool_name":"Bash",
  "tool_input":{"command":sys.argv[1],"description":"replay"}}))' "$1" "$2"
}

run_hook() { # $1=hook $2=command $3=cwd -> prints "<exit>|<stdout+stderr first line>"
  local out ec
  out="$(envelope "$2" "$3" | bash "$HOOKS/$1" 2>&1)"; ec=$?
  printf '%s|%s' "$ec" "$(printf '%s' "$out" | tr '\n' ' ' | cut -c1-160)"
}

cmd_probe() {
  local hook="$1" c="$2" cwd="${3:-$PWD}"
  [ -f "$HOOKS/$hook" ] || die "no such hook: $hook"
  printf 'cmd : %s\n' "$(printf '%s' "$c" | tr '\n' '⏎')"
  printf 'verdict: %s\n' "$(run_hook "$hook" "$c" "$cwd")"
}

# --- corpus: every Bash call in real transcripts, both arms ------------------------
cmd_corpus() {
  local hook="$1" glob="${2:-*}" max="${3:-4000}"
  [ -f "$HOOKS/$hook" ] || die "no such hook: $hook"
  exec python3 "$(dirname "$0")/replay-hook-corpus.py" \
    "$PROJ" "$HOOKS" "$hook" "$glob" "$max"
}

# --- check: the installed heavy-command hook is keel's, rewrite included ---------------
# WHY: install-resource-hooks.py once overwrote the installed serialize-heavy-ops.py with a
# keel copy that had lost the interactive rewrite (grep -c updatedInput was 0 on both while
# the harness HEAD held 2), and 383 denials followed with no signal. A green syntax gate
# cannot see that: both files compile. This compares the installed pair to keel's source and
# demands the rewrite marker, so a clobber in either direction fails loudly.
cmd_check() {
  local keel rc=0 f n
  keel="${KEEL_ROOT:-$(cd "$(dirname "$(readlink "$HOME/.claude/scripts/spawn-lane.sh")")/.." 2>/dev/null && pwd)}"
  [ -d "$keel/.claude/hooks" ] || die "cannot locate keel (set KEEL_ROOT)"
  for f in serialize-heavy-ops.py heavy_command.py; do
    if cmp -s "$HOOKS/$f" "$keel/.claude/hooks/$f"; then
      printf '  ok    %s matches keel
' "$f"
    else
      printf '  DRIFT %s differs from %s (reinstall: install-resource-hooks.py)
' "$f" "$keel/.claude/hooks/$f"; rc=1
    fi
  done
  n="$(grep -c updatedInput "$HOOKS/serialize-heavy-ops.py" 2>/dev/null)"
  if [ "${n:-0}" -ge 1 ]; then
    printf '  ok    installed serialize-heavy-ops.py carries the rewrite (updatedInput x%s)
' "$n"
  else
    printf '  LOST  installed serialize-heavy-ops.py has no updatedInput: the heavy-command rewrite is gone
'; rc=1
  fi
  return "$rc"
}

case "${1:-}" in
  syntax) cmd_syntax ;;
  check)  cmd_check ;;
  probe)  shift; cmd_probe "$@" ;;
  corpus) shift; cmd_corpus "$@" ;;
  *) die "usage: replay-hook.sh syntax | check | probe <hook> <cmd> [cwd] | corpus <hook> [glob] [max]" ;;
esac
