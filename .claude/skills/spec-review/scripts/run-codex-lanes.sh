#!/usr/bin/env bash
# run-codex-lanes.sh <run-dir> <profile|extract>
#
# Two modes, one wrapper, both started by the MAIN loop with the Bash tool's run_in_background: true
# (one harness-tracked task, one completion notification; never wrap it in nohup or a tool-level `&`,
# never launch it from a Workflow agent: an agent is killed at its final answer and takes the child
# with it, spike wf_2163ac0b-17b). The `&` below is fine: this same process waits on it.
#
#   extract   dossier + design-decisions mining. Dispatches <run-dir>/codex/extract.tsv (lane, class,
#             prompt file, outfile) in parallel, grades each lane by ARTIFACT, writes
#             codex/extract-status.tsv, then runs `run_dir.py extract-finish` and prints its JSON line
#             (`fallback` names the miners that must rerun as Claude lanes: DEAD / QUOTA / invalid).
#   <profile> the review wave. Dispatches <run-dir>/codex/plan.tsv in parallel, grades them into
#             codex/status.tsv, then turns each OK lane's prose output into an envelope with a luna
#             extraction dispatch (`stage.py extract-plan` / `extract-envelopes`); a lane whose
#             extraction fails is picked up by the critics stage as a Claude extractor.
#
# status = OK | REFUSED (headroom gate) | SUSPECT (under the artifact floor) | QUOTA | DEAD | MISSING
# Grade a lane by this ARTIFACT status, never by an exit code (docs/codex-lane-contract.md).
set -uo pipefail

RUN="${1:?usage: run-codex-lanes.sh <run-dir> <profile|extract>}"
PROFILE="${2:?missing profile (full|standard|light|hotfix) or 'extract'}"
DISPATCH="${CODEX_DISPATCH:-$HOME/.claude/scripts/codex-dispatch.sh}"
HERE="$(cd "$(dirname "$0")" && pwd)"
FLOOR="${CODEX_MIN_ARTIFACT:-400}"

case "$RUN" in /*) ;; *) echo "run-codex-lanes: run-dir must be absolute" >&2; exit 1 ;; esac
[ -x "$DISPATCH" ] || [ -f "$DISPATCH" ] || { echo "run-codex-lanes: no dispatcher at $DISPATCH" >&2; exit 1; }
ROOT="$(cat "$RUN/inputs/root.txt" 2>/dev/null)"
[ -d "$ROOT" ] || { echo "run-codex-lanes: no repo root in $RUN/inputs/root.txt" >&2; exit 1; }

# dispatch_all <plan.tsv>: every row in parallel, then wait.
dispatch_all() {
  local plan="$1" lane class prompt out
  while IFS=$'\t' read -r lane class prompt out; do
    [ -n "$lane" ] || continue
    if [ ! -f "$prompt" ]; then echo 1 > "$out.rc"; continue; fi
    rm -f "$out" "$out.rc"
    (
      CODEX_NETWORK=1 CODEX_SERVICE_TIER=fast bash "$DISPATCH" "$class" "$prompt" "$out" "$ROOT" > "$out.dispatch.log" 2>&1
      echo $? > "$out.rc"
    ) &
  done < "$plan"
  wait
}

# grade_all <plan.tsv> <status.tsv> <floor>: one status line per lane.
grade_all() {
  local plan="$1" status="$2" floor="$3" lane class prompt out rc bytes st n=0
  : > "$status"
  while IFS=$'\t' read -r lane class prompt out; do
    [ -n "$lane" ] || continue
    n=$((n + 1))
    rc="$(cat "$out.rc" 2>/dev/null || echo '?')"
    bytes=0; [ -f "$out" ] && bytes="$(wc -c < "$out" | tr -d ' ')"
    if [ ! -f "$prompt" ]; then st=MISSING
    elif [ "$rc" = "2" ]; then st=REFUSED
    elif [ "$rc" = "0" ] && [ "$bytes" -ge "$floor" ]; then st=OK
    elif [ "$rc" = "6" ]; then st=SUSPECT
    elif [ "$rc" = "0" ]; then st=SUSPECT
    else st=DEAD; fi
    if [ "$st" != "OK" ] && grep -qiE 'hit your usage limit|try again at' "$out.log" "$out.dispatch.log" 2>/dev/null; then st=QUOTA; fi
    printf '%s\t%s\t%s\t%s\n' "$lane" "$st" "$bytes" "$rc" >> "$status"
    echo "LANE $lane status=$st rc=$rc bytes=$bytes"
  done < "$plan"
  echo "DONE $n codex lane(s), status file $status"
}

if [ "$PROFILE" = "extract" ]; then
  PLAN="$RUN/codex/extract.tsv"
  [ -f "$PLAN" ] || { echo "run-codex-lanes: no $PLAN -- run stage.py prepare first" >&2; exit 1; }
  dispatch_all "$PLAN"
  grade_all "$PLAN" "$RUN/codex/extract-status.tsv" 200
  python3 "$HERE/run_dir.py" extract-finish --run "$RUN"
  exit 0
fi

PLAN="$RUN/codex/plan.tsv"
[ -f "$PLAN" ] || { echo "run-codex-lanes: no $PLAN -- run stage.py finish-prepare first" >&2; exit 1; }
dispatch_all "$PLAN"
grade_all "$PLAN" "$RUN/codex/status.tsv" "$FLOOR"
echo "profile=$PROFILE"

# Envelope extraction of the OK lanes' prose, on the cheap Codex class (luna), in parallel.
python3 "$HERE/stage.py" extract-plan --run "$RUN"
if [ -s "$RUN/codex/extract-env.tsv" ]; then
  dispatch_all "$RUN/codex/extract-env.tsv"
  python3 "$HERE/stage.py" extract-envelopes --run "$RUN"
fi
