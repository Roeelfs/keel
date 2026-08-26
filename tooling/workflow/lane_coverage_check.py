#!/usr/bin/env python3
"""Assert a consolidated program actually cites every investigation lane it dispatched.

Two failures motivated this, both from the 2026-08-26 /improve-harness cynap-latency run:

  1. SILENT TRUNCATION. The orchestrator's synthesis prompt sliced lane findings at
     `.slice(0, 60000)`. The synthesis agent saw 4 of 7 lanes and said so in passing;
     nothing failed.
  2. A RECOVERY CLAIMED BUT NOT PERFORMED — the worse one, and the one with no prior rule.
     The program then asserted "All 7 lanes were recovered from journal.jsonl". The lanes
     were read. The define-phase lane's numbers were dropped from the program anyway, and
     those numbers were the answer to the question the run existed to ask.

Prose already forbade (1) ("No silent caps", WORKFLOW.md). Nothing could catch (2), because
a claim of coverage is indistinguishable from coverage without comparing the two artifacts.
This does that comparison.

A lane counts as CITED if any of its distinctive tokens — decimals, multi-digit counts,
`file:line` anchors, CYN-keys, PR numbers, SHAs — appears anywhere in the program, including
inside a DID_NOT_SURVIVE entry. Refuted lanes still have to be mentioned.

Exit 0 = every dispatched lane completed and is cited. Exit 1 = otherwise, naming which.
Exit 2 = the inputs could not be read (never confuse this with a pass).
"""

from __future__ import annotations

import argparse
import json
import re
import sys

# Tokens distinctive enough that their presence in the program is real evidence of citation.
# Bare small integers are excluded deliberately: "3" appears in every document ever written.
TOKEN_PATTERNS = [
    r"\d+\.\d+",           # 36.55, 127.1, 0.4988
    r"\d{3,}",             # 8536, 262, 155
    r"[A-Z]{2,}-\d+",      # CYN-1164
    r"#\d{3,}",            # #2331
    r"[0-9a-f]{7,40}",     # SHAs
    r"[\w./-]+\.(?:ts|py|sh|md|yml|yaml|json|js|mjs|tsx):\d+",  # file:line
]
_TOKEN_RE = re.compile("|".join(f"(?:{p})" for p in TOKEN_PATTERNS))

# Numbers so generic that matching them proves nothing about this particular lane.
_STOPWORDS = {"100", "200", "404", "500", "1000", "2026", "2025", "0.0", "1.0"}


# Fields a lane uses to state its own load-bearing claim. Coverage is judged against THESE,
# not the whole payload. Judging the whole payload is false security: a lane's `commands_run`
# and `probe` fields are full of paths, dates and ids that incidentally appear in any program,
# so one accidental match certified a lane whose actual finding had been dropped. Measured
# 2026-08-26 — the first version of this checker PASSED its own negative control.
HEADLINE_FIELDS = ("headline", "corrected_claim", "corrected_item", "reason", "summary", "verdict")


def claim_text(payload: object) -> str:
    """The lane's load-bearing statement, preferred over its full return value."""
    if isinstance(payload, dict):
        parts = [str(payload[f]) for f in HEADLINE_FIELDS if payload.get(f)]
        if parts:
            return "\n".join(parts)
    return payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)


def distinctive_tokens(payload: object) -> set[str]:
    """Pull citation-worthy tokens out of a lane's load-bearing claim."""
    text = claim_text(payload)
    return {t for t in _TOKEN_RE.findall(text) if t not in _STOPWORDS and len(t) >= 3}


def load_journal(path: str) -> tuple[list[dict], int, int]:
    """Return (result rows, started count, malformed line count)."""
    results: list[dict] = []
    started = 0
    malformed = 0
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue
            kind = obj.get("type")
            if kind == "result":
                results.append(obj)
            elif kind in ("started", "start", "dispatch"):
                started += 1
    return results, started, malformed


def lane_identity(row: dict, index: int) -> str:
    for key in ("label", "agentLabel", "name", "agentId", "id"):
        value = row.get(key)
        if isinstance(value, str) and value:
            return value
    return f"lane[{index}]"


def lane_payload(row: dict) -> object:
    for key in ("value", "result", "output"):
        if key in row:
            value = row[key]
            if isinstance(value, str):
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    return value
            return value
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--journal", required=True, help="Workflow journal.jsonl")
    ap.add_argument("--program", required=True, help="The consolidated program markdown")
    ap.add_argument("--min-tokens", type=int, default=2,
                    help="Distinctive tokens from the lane's CLAIM that must appear for it to count as cited (default 2; 1 incidental match is not citation)")
    args = ap.parse_args()

    try:
        results, started, malformed = load_journal(args.journal)
        program = open(args.program, encoding="utf-8").read()
    except OSError as exc:
        print(f"lane-coverage: CANNOT READ INPUT — {exc}", file=sys.stderr)
        print("lane-coverage: this is NOT a pass.", file=sys.stderr)
        return 2

    if not results:
        print(f"lane-coverage: journal {args.journal} has zero result rows — nothing to check.", file=sys.stderr)
        print("lane-coverage: this is NOT a pass.", file=sys.stderr)
        return 2

    uncited: list[tuple[str, int]] = []
    cited: list[str] = []
    tokenless: list[str] = []

    for index, row in enumerate(results):
        name = lane_identity(row, index)
        tokens = distinctive_tokens(lane_payload(row))
        if not tokens:
            tokenless.append(name)
            continue
        hits = sum(1 for token in tokens if token in program)
        if hits >= args.min_tokens:
            cited.append(name)
        else:
            uncited.append((name, len(tokens)))

    died = max(0, started - len(results)) if started else 0

    print(f"lane-coverage: dispatched={started or 'unknown'} completed={len(results)} "
          f"cited={len(cited)} uncited={len(uncited)} tokenless={len(tokenless)} died={died}")
    if malformed:
        print(f"lane-coverage: {malformed} malformed journal line(s) skipped")

    ok = True
    if died:
        print(f"lane-coverage: FAIL — {died} lane(s) dispatched but never returned. "
              f"A lane death is not a clean verdict; say so in the program.")
        ok = False
    for name, count in uncited:
        print(f"lane-coverage: FAIL — lane '{name}' is not cited anywhere in the program "
              f"({count} distinctive tokens, none present). Either carry its finding or "
              f"record why it was dropped.")
        ok = False
    for name in tokenless:
        print(f"lane-coverage: WARN — lane '{name}' returned no distinctive tokens; "
              f"coverage cannot be judged mechanically. Check it by hand.")

    if ok:
        print("lane-coverage: PASS — every completed lane is cited in the program.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
