#!/bin/bash
# lane_probe.sh — one-token check that a HEADLESS claude lane can run at all, before dispatching one.
# Headless `claude -p` lanes use the CLI login, which can be a different (capped) account from the
# desktop sessions that look healthy. A dead lane exits 0 with 0 tokens: grade the artifact, and
# probe BEFORE dispatch. Exit 0 = usable, 1 = refused (reason on stdout), 2 = probe itself failed.
# Usage: lane_probe.sh [model-alias]   (default: haiku, the cheapest; pass opus to probe that pool)
set -u
MODEL="${1:-haiku}"
OUT="$(claude -p "reply with the single word ok" --model "$MODEL" --output-format json 2>/dev/null)" || true
[ -n "$OUT" ] || { echo "probe: no output from claude -p (CLI missing or crashed)"; exit 2; }
printf '%s' "$OUT" | python3 -I -c '
import sys, json
for line in sys.stdin.read().splitlines():
    try: d = json.loads(line)
    except Exception: continue
    if d.get("is_error"):
        print("probe: REFUSED api_error_status=%s: %s" % (d.get("api_error_status"), str(d.get("result"))[:200])); sys.exit(1)
    if "result" in d:
        print("probe: ok"); sys.exit(0)
print("probe: unparseable output"); sys.exit(2)
'
