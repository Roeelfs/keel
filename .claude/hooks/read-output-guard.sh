#!/usr/bin/env bash
# H7 (improve-harness 2026-07-06): task .output files are routinely >256KB; a full
# Read gets rejected and wastes a call (3 oversized-read rejections in one session).
# Deny Read of tasks/*.output without limit/offset. Fail-open on parse problems.
# H10 (2026-07-16): widened — bare Reads of session-transcript .jsonl and /tmp/codex-*.txt
# also hit the 25k-token/256KB ceiling (8 rejections / 3 sessions). SIZE-VERIFIED
# (os.path.getsize > 256KB), never a blanket pattern block.
set -uo pipefail
HOOK_INPUT="$(cat 2>/dev/null || true)"; [ -z "$HOOK_INPUT" ] && exit 0
export HOOK_INPUT
python3 -c '
import sys, json, os
try:
    d = json.loads(os.environ["HOOK_INPUT"])
    ti = d.get("tool_input", {}) or {}
    fp = ti.get("file_path", "") or ""
    if ti.get("limit") or ti.get("offset"):
        sys.exit(0)
    if "/tasks/" in fp and fp.endswith(".output"):
        print("🚦 Task .output files are routinely >256KB — a bare Read will be rejected. "
              "RUN EXACTLY: jq -r .result <file> | head -c 20000   (or Read with offset/limit).",
              file=sys.stderr)
        sys.exit(2)
    big = False
    try:
        big = os.path.getsize(fp) > 256_000
    except Exception:
        big = False
    if big and ((fp.endswith(".jsonl") and "/.claude/projects/" in fp) or
                ("/tmp/codex-" in fp and fp.endswith(".txt"))):
        print("🚦 This file is >256KB — a bare Read will be rejected at the 25k-token ceiling. "
              "Transcript .jsonl: extract with jq/python (never read raw). Otherwise Read with offset/limit.",
              file=sys.stderr)
        sys.exit(2)
except SystemExit:
    raise
except Exception:
    pass
sys.exit(0)
'
