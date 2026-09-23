#!/usr/bin/env python3
"""SR1/SR4: validate a spec-review `.review.md` report against the pipeline's
hard rules (SKILL.md Step 5c).

Usage:
    python3 validate_review_report.py <report.md>

Exit 0 on pass, 1 on any failure. Prints one line per failure plus a
per-lane verdict-count summary.
"""
import re
import sys

VERDICT_WORDS = ("REFUTED", "SURVIVES", "DOWNGRADED")
VERDICT_RE = re.compile(r"\b(?:" + "|".join(VERDICT_WORDS) + r")\b", re.IGNORECASE)

# The ONE canonical falsifier-wave line format (SKILL.md Step 5c):
#   ### Falsifier wave: <N> dispatched over <M> CRITICAL/MAJOR — <R> REFUTED, <S> SURVIVES.
# Tolerates optional `#`/`**` wrapping and a short parenthetical aside before
# the dash (e.g. "(+2 factual splits)"), and either an em-dash or a hyphen.
FALSIFIER_LINE_RE = re.compile(
    r"falsifier wave:\**\s*"
    r"(?P<n>\d+)\s+dispatched\s+over\s+"
    r"(?P<m>\d+)\s+critical/major"
    r"(?:\s*\([^)\n]{0,80}\))?"
    r"\s*[—-]\s*"
    r"(?P<r>\d+)\s+refuted,\s*"
    r"(?P<s>\d+)\s+survives\b",
    re.IGNORECASE,
)

# Family ID tables: `| EC-3 | ... | CRITICAL | ... |` (any column order/count;
# severity is whatever cell is an exact CRITICAL/MAJOR/MINOR token).
TABLE_ROW_ID_RE = re.compile(r"\b(EC|Sec|Obs|LE)-(\d+)\b")
# F-N numbered-list style: "1. [F-3] [CRITICAL] <issue>"
F_ID_LIST_RE = re.compile(r"\[F-(\d+)\]\s*\[(CRITICAL|MAJOR|MINOR)\]", re.IGNORECASE)

SEVERITY_CELL_RE = re.compile(r"^(CRITICAL|MAJOR|MINOR)$", re.IGNORECASE)


def find_critical_major_ids(text):
    """Return {family_id_string: severity} for every EC-/Sec-/Obs-/LE-/F- row
    that carries an exact CRITICAL or MAJOR severity somewhere in its row."""
    out = {}

    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        ids_in_row = TABLE_ROW_ID_RE.findall(line)
        if not ids_in_row:
            continue
        cells = [c.strip().strip("*").strip("`") for c in line.strip().strip("|").split("|")]
        severities = [c.upper() for c in cells if SEVERITY_CELL_RE.match(c)]
        if not severities:
            continue
        # A row may report more than one severity token only in the template
        # placeholder ("CRITICAL / MAJOR / MINOR"); a real filled row has one.
        sev = severities[0]
        if sev not in ("CRITICAL", "MAJOR"):
            continue
        for family, num in ids_in_row:
            out[f"{family}-{num}"] = sev

    for m in F_ID_LIST_RE.finditer(text):
        sev = m.group(2).upper()
        if sev in ("CRITICAL", "MAJOR"):
            out[f"F-{m.group(1)}"] = sev

    return out


def id_has_verdict_elsewhere(report_id, text):
    """True if `report_id` co-occurs with a verdict word on some line."""
    escaped = re.escape(report_id)
    id_re = re.compile(r"\b" + escaped + r"\b")
    for line in text.splitlines():
        if id_re.search(line) and VERDICT_RE.search(line):
            return True
    return False


def extract_carried_obligations_ids(text):
    """IDs listed under the '## Carried obligations' section, if present."""
    m = re.search(r"^#+\s*Carried obligations\s*$", text, re.MULTILINE)
    if not m:
        return None, False
    start = m.end()
    next_heading = re.search(r"^#+\s+\S", text[start:], re.MULTILINE)
    body = text[start : start + next_heading.start()] if next_heading else text[start:]
    ids = set(re.findall(r"\b(?:Obs|Sec|LE)-\d+\b", body))
    return ids, True


def validate(text):
    """Return (ok: bool, failures: list[str], summary_lines: list[str])."""
    failures = []
    summary = []

    m = FALSIFIER_LINE_RE.search(text)
    if not m:
        failures.append(
            "Missing/malformed canonical falsifier-wave line: expected "
            "'### Falsifier wave: <N> dispatched over <M> CRITICAL/MAJOR — "
            "<R> REFUTED, <S> SURVIVES.'"
        )
        n = m_val = None
    else:
        n, m_val = int(m.group("n")), int(m.group("m"))
        if n == 0 and m_val > 0:
            failures.append(
                f"Falsifier wave dispatched N=0 while M={m_val} CRITICAL/MAJOR "
                "findings exist -- the wave was skipped (SKILL.md Step 5a: "
                "'stop and run the wave, do not write the report')."
            )

    ids = find_critical_major_ids(text)
    by_family = {}
    for rid, sev in ids.items():
        family = rid.split("-", 1)[0]
        by_family.setdefault(family, []).append((rid, sev))

    missing_verdict = []
    for rid in sorted(ids):
        if not id_has_verdict_elsewhere(rid, text):
            missing_verdict.append(rid)
    if missing_verdict:
        failures.append(
            "CRITICAL/MAJOR finding(s) with no verdict (REFUTED/SURVIVES/DOWNGRADED) "
            "anywhere in the report: " + ", ".join(missing_verdict)
        )

    # SR4: surviving Obs-/Sec-/LE- CRITICAL/MAJOR findings need a
    # '## Carried obligations' block listing each such ID.
    surviving_carry_families = ("Obs", "Sec", "LE")
    surviving_ids = sorted(
        rid
        for rid in ids
        if rid.split("-", 1)[0] in surviving_carry_families
        and id_has_verdict_elsewhere(rid, text)
        and not _id_verdict_is(rid, text, ("REFUTED",))
    )
    if surviving_ids:
        carried_ids, block_present = extract_carried_obligations_ids(text)
        if not block_present:
            failures.append(
                "SURVIVING CRITICAL/MAJOR Obs-/Sec-/LE- finding(s) present "
                f"({', '.join(surviving_ids)}) but no '## Carried obligations' "
                "section exists."
            )
        else:
            missing_from_block = [i for i in surviving_ids if i not in carried_ids]
            if missing_from_block:
                failures.append(
                    "'## Carried obligations' section exists but is missing: "
                    + ", ".join(missing_from_block)
                    + " (a bare heading with no matching row is a fail)."
                )

    for family in ("EC", "Sec", "Obs", "LE", "F"):
        rows = by_family.get(family, [])
        total = len(rows)
        with_verdict = sum(1 for rid, _ in rows if rid not in missing_verdict)
        summary.append(f"  {family}-N: {total} CRITICAL/MAJOR, {with_verdict} with a verdict")

    return (len(failures) == 0), failures, summary


def _id_verdict_is(report_id, text, words):
    escaped = re.escape(report_id)
    id_re = re.compile(r"\b" + escaped + r"\b")
    words_re = re.compile(r"\b(?:" + "|".join(words) + r")\b", re.IGNORECASE)
    for line in text.splitlines():
        if id_re.search(line) and words_re.search(line):
            return True
    return False


def main(argv):
    if len(argv) != 2:
        print("usage: validate_review_report.py <report.md>", file=sys.stderr)
        return 1
    path = argv[1]
    try:
        text = open(path, encoding="utf-8").read()
    except OSError as e:
        print(f"FAIL: cannot read {path}: {e}")
        return 1

    ok, failures, summary = validate(text)

    print(f"Report: {path}")
    print("Per-lane verdict counts:")
    print("\n".join(summary))
    if ok:
        print("PASS")
        return 0
    print("FAIL")
    for f in failures:
        print(f"  - {f}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
