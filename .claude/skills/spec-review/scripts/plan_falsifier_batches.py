#!/usr/bin/env python3
"""SR2: plan_falsifier_batches — group the Step 5a falsifier wave into a
bounded number of seam-cohesive batches instead of one lane per finding.

Root failure this fixes: session 0b284639 (2026-09-05) lost 11 falsifier
lanes to a single session limit because Step 5a dispatched one lane per
CRITICAL/MAJOR finding with no cap. This script reads the FINISHED review
report (the `[F-N] [SEVERITY] ... File: <path>:<line>` findings SR1 made
stable and parseable) and packs the CRITICAL/MAJOR ones into at most
--max-batches batches, grouped by seam (the finding's cited file) so a
falsifier lane reads one file's context once. If a batch's lane dies, the
report can name that ONE batch's F-N ids for re-dispatch -- the whole wave
never needs replaying.

Usage:
    python3 plan_falsifier_batches.py <report.md> [--max-batches 4]

Prints a JSON plan to stdout. Never edits the report.
"""
import argparse
import json
import re
import sys
from pathlib import Path

# Matches "1. [F-3] [CRITICAL] <issue> ..." (Consensus Issues / Codex-Only
# Findings numbered-list style; the same shape validate_review_report.py's
# F_ID_LIST_RE targets). EC-/Sec-/Obs-/LE- rows use a different ID prefix
# and a markdown-table shape, so this pattern never matches them.
FINDING_RE = re.compile(r"^\s*\d+\.\s*\[F-(\d+)\]\s*\[(CRITICAL|MAJOR|MINOR)\]", re.IGNORECASE)
FILE_FIELD_RE = re.compile(r"File:\s*([^\s|]+)")
LINE_SUFFIX_RE = re.compile(r":\d")


def parse_findings(text):
    """Return a list of {id, severity, seam, file_field} dicts, one per
    [F-N] [SEVERITY] finding in the report, in document order.

    `seam` is the file path lifted from that finding's `File: <path>:<line>`
    field (the only per-finding location field the report format carries),
    with the trailing `:<line>` or `:<start>-<end>` stripped. `seam` is None
    when the finding block carries no File: field at all.
    """
    lines = text.splitlines()
    n = len(lines)
    findings = []
    i = 0
    while i < n:
        m = FINDING_RE.match(lines[i])
        if not m:
            i += 1
            continue
        fid = f"F-{m.group(1)}"
        severity = m.group(2).upper()
        seam = None
        file_field = None
        j = i + 1
        while j < n:
            line = lines[j]
            if FINDING_RE.match(line):
                break
            if line.strip() == "":
                nxt = lines[j + 1] if j + 1 < n else ""
                if nxt.startswith(" ") or nxt.startswith("\t"):
                    j += 1
                    continue
                break
            fm = FILE_FIELD_RE.search(line)
            if fm and file_field is None:
                file_field = fm.group(1)
                seam = (
                    file_field.rsplit(":", 1)[0]
                    if LINE_SUFFIX_RE.search(file_field)
                    else file_field
                )
            j += 1
        findings.append({"id": fid, "severity": severity, "seam": seam, "file_field": file_field})
        i = j
    return findings


def plan_batches(findings, max_batches=4):
    """Bin-pack findings into <= max_batches batches, grouped by seam.

    A seam's findings NEVER split across batches -- that is the whole point
    (one lane death costs one batch, and a lane that reads a seam reads it
    once). A finding with no seam gets a synthetic singleton seam so it is
    never silently dropped and never falsely merged with an unrelated one.
    Seam-groups are assigned largest-first to the currently least-loaded
    batch (greedy LPT) so batch sizes stay balanced.
    """
    if max_batches < 1:
        max_batches = 1
    groups = {}
    unseamed_ids = []
    for f in findings:
        seam = f["seam"]
        if seam is None:
            unseamed_ids.append(f["id"])
            seam = f"__unseamed__:{f['id']}"
        groups.setdefault(seam, []).append(f)

    items = sorted(groups.items(), key=lambda kv: -len(kv[1]))
    num_batches = min(max_batches, len(items)) if items else 0
    bucket_findings = [[] for _ in range(num_batches)]
    bucket_seams = [[] for _ in range(num_batches)]
    for seam, group in items:
        idx = min(range(num_batches), key=lambda k: len(bucket_findings[k]))
        bucket_findings[idx].extend(group)
        bucket_seams[idx].append(seam)

    batches = []
    for bi in range(num_batches):
        batches.append(
            {
                "batch_id": bi + 1,
                "seams": bucket_seams[bi],
                "finding_ids": [f["id"] for f in bucket_findings[bi]],
                "findings": bucket_findings[bi],
            }
        )
    return batches, unseamed_ids


def assert_seam_cohesion(batches):
    """Raise AssertionError if any seam's findings are split across more
    than one batch. Exported so the test suite can also run it against a
    deliberately-broken plan as a negative control (proving this assertion
    actually fires on broken grouping, not just on the happy path)."""
    seam_to_batch = {}
    for b in batches:
        for seam in b["seams"]:
            if seam in seam_to_batch and seam_to_batch[seam] != b["batch_id"]:
                raise AssertionError(
                    f"seam {seam!r} split across batches "
                    f"{seam_to_batch[seam]} and {b['batch_id']} -- grouping is broken"
                )
            seam_to_batch[seam] = b["batch_id"]


def build_plan(report_text, report_path, max_batches):
    findings = parse_findings(report_text)
    critical_major = [f for f in findings if f["severity"] in ("CRITICAL", "MAJOR")]
    batches, unseamed_ids = plan_batches(critical_major, max_batches)
    assert_seam_cohesion(batches)
    return {
        "report": report_path,
        "max_batches": max_batches,
        "total_findings_parsed": len(findings),
        "critical_major_count": len(critical_major),
        "findings_missing_seam": unseamed_ids,
        "batches": batches,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("report", help="Path to the written spec-review .review.md report")
    ap.add_argument("--max-batches", type=int, default=4)
    args = ap.parse_args()

    path = Path(args.report)
    if not path.is_file():
        print(f"error: report not found: {path}", file=sys.stderr)
        return 2
    text = path.read_text(encoding="utf-8")
    plan = build_plan(text, str(path), args.max_batches)
    print(json.dumps(plan, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
