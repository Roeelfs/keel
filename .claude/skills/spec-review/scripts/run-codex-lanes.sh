#!/usr/bin/env bash
# run-codex-lanes.sh <run-dir> <profile>
#
# Starts every Codex lane the prepare stage materialized (<run-dir>/codex/plan.tsv: lane, class,
# prompt file, outfile) in PARALLEL through ~/.claude/scripts/codex-dispatch.sh, waits for all of
# them INSIDE this script, then exits once with one status line per lane.
#
# HOW TO LAUNCH: the MAIN loop runs this with the Bash tool's run_in_background: true -- one
# harness-tracked task, one completion notification. Do NOT launch it from inside a Workflow agent
# (spike wf_2163ac0b-17b: an agent is killed at its final answer and takes the child with it), and
# never wrap it in nohup or a trailing `&` at the tool level (the harness reaps the process group).
# The `&` below is fine: it is waited on by this same tracked process before it exits.
#
# Output: <run-dir>/codex/status.tsv  (lane, status, bytes, rc)  and the status lines on stdout.
#   status = OK | REFUSED (headroom gate) | SUSPECT (under the artifact floor) | QUOTA | DEAD | MISSING
# Grade a lane by this ARTIFACT status, never by an exit code (docs/codex-lane-contract.md).
set -uo pipefail

RUN="${1:?usage: run-codex-lanes.sh <run-dir> <profile>}"
PROFILE="${2:?missing profile (full|focused|hotfix)}"
DISPATCH="${CODEX_DISPATCH:-$HOME/.claude/scripts/codex-dispatch.sh}"
PLAN="$RUN/codex/plan.tsv"
STATUS="$RUN/codex/status.tsv"
FLOOR="${CODEX_MIN_ARTIFACT:-400}"

case "$RUN" in /*) ;; *) echo "run-codex-lanes: run-dir must be absolute" >&2; exit 1 ;; esac
[ -f "$PLAN" ] || { echo "run-codex-lanes: no $PLAN -- run the prepare stage first" >&2; exit 1; }
[ -x "$DISPATCH" ] || [ -f "$DISPATCH" ] || { echo "run-codex-lanes: no dispatcher at $DISPATCH" >&2; exit 1; }
ROOT="$(cat "$RUN/inputs/root.txt" 2>/dev/null)"
[ -d "$ROOT" ] || { echo "run-codex-lanes: no repo root in $RUN/inputs/root.txt" >&2; exit 1; }

: > "$STATUS"
lanes=()
while IFS=$'\t' read -r lane class prompt out; do
  [ -n "$lane" ] || continue
  lanes+=("$lane")
  if [ ! -f "$prompt" ]; then echo 1 > "$out.rc"; continue; fi
  rm -f "$out" "$out.rc"
  (
    CODEX_NETWORK=1 CODEX_SERVICE_TIER=fast bash "$DISPATCH" "$class" "$prompt" "$out" "$ROOT" > "$out.dispatch.log" 2>&1
    echo $? > "$out.rc"
  ) &
done < "$PLAN"
wait

n=0
while IFS=$'\t' read -r lane class prompt out; do
  [ -n "$lane" ] || continue
  n=$((n + 1))
  rc="$(cat "$out.rc" 2>/dev/null || echo '?')"
  bytes=0; [ -f "$out" ] && bytes="$(wc -c < "$out" | tr -d ' ')"
  if [ ! -f "$prompt" ]; then status=MISSING
  elif [ "$rc" = "2" ]; then status=REFUSED
  elif [ "$rc" = "0" ] && [ "$bytes" -ge "$FLOOR" ]; then status=OK
  elif [ "$rc" = "6" ]; then status=SUSPECT
  elif [ "$rc" = "0" ]; then status=SUSPECT
  else status=DEAD; fi
  if [ "$status" != "OK" ] && grep -qiE 'hit your usage limit|try again at' "$out.log" "$out.dispatch.log" 2>/dev/null; then status=QUOTA; fi
  printf '%s\t%s\t%s\t%s\n' "$lane" "$status" "$bytes" "$rc" >> "$STATUS"
  echo "LANE $lane status=$status rc=$rc bytes=$bytes"
done < "$PLAN"
echo "DONE $n codex lane(s), profile=$PROFILE, status file $STATUS"
