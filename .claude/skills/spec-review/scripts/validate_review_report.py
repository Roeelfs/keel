#!/usr/bin/env python3
"""SR1/SR4: validate a spec-review `.review.md` report against the pipeline's
hard rules (report-template.md + SKILL.md Step 5c).

Usage:
    python3 validate_review_report.py <report.md>

Exit 0 on pass, 1 on any failure. Prints one line per failure plus a
per-lane verdict-count summary.
"""
import re
import sys

VERDICT_WORDS = ("REFUTED", "SURVIVES", "DOWNGRADED")
VERDICT_RE = re.compile(r"\b(?:" + "|".join(VERDICT_WORDS) + r")\b", re.IGNORECASE)

# The ONE canonical falsifier-wave line format (report-template.md + SKILL.md Step 5c):
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


CARRIED_ID_RE = re.compile(r"\b(?:EC|Sec|Obs|LE|F)-\d+\b")
EMPTY_CELLS = ("", "-", "—", "tbd", "todo", "none", "n/a", "na", "owed", "proof owed", "?")
DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
DRIVE, BAKE = "PRE-MERGE DRIVE", "POST-DEPLOY BAKE"


def carried_block(text):
    """The body of the '## Carried obligations' section, or None."""
    m = re.search(r"^#+\s*Carried obligations\s*$", text, re.MULTILINE)
    if not m:
        return None
    start = m.end()
    next_heading = re.search(r"^#+\s+\S", text[start:], re.MULTILINE)
    return text[start : start + next_heading.start()] if next_heading else text[start:]


def carried_rows(body):
    """(header cells, data rows as cell lists) of the first table in the carried block."""
    lines = [l.strip() for l in body.splitlines() if l.strip().startswith("|")]
    cells = [[c.strip().strip("*`").strip() for c in l.strip("|").split("|")] for l in lines]
    rows = [c for c in cells if not all(re.fullmatch(r":?-{3,}:?", x) for x in c if x)]
    return (rows[0], rows[1:]) if rows else ([], [])


def carried_errors(text, surviving_ids):
    """P1/P3: every surviving CRITICAL/MAJOR id sits in a carried row with a named proof; a drive, bake or
    owed proof names an owner and a close-by date; a critical-tier report carries both boundary rows."""
    critical = re.search(r"\(tier critical\)", text, re.IGNORECASE) is not None
    if not surviving_ids and not critical:
        return []
    body = carried_block(text)
    if body is None:
        what = f"SURVIVING CRITICAL/MAJOR finding(s) present ({', '.join(surviving_ids)})" if surviving_ids else "tier critical"
        return [f"{what} but no '## Carried obligations' section exists."]
    header, rows = carried_rows(body)
    col = {name: next((i for i, h in enumerate(header) if name in h.lower()), None) for name in ("proof", "owner", "close-by")}
    if col["proof"] is None:
        return ["'## Carried obligations' needs a table with a Proof column (| ID | Obligation | Proof | Owner | Close-by |)."]
    cell = lambda r, k: r[col[k]] if col[k] is not None and col[k] < len(r) else ""
    errors = []
    listed = set()
    for r in rows:
        row_text = " | ".join(r)
        listed |= set(CARRIED_ID_RE.findall(row_text))
        proof = cell(r, "proof")
        if proof.lower() in EMPTY_CELLS:
            errors.append(f"carried row '{r[0]}' has no named proof (test, probe, drive or bake): {proof!r}")
        boundary = DRIVE in row_text.upper() or BAKE in row_text.upper() or "owed" in proof.lower()
        if boundary and (cell(r, "owner").lower() in EMPTY_CELLS or not DATE_RE.search(cell(r, "close-by"))):
            errors.append(f"carried row '{r[0]}' is a drive, bake or owed proof without an owner and a close-by date (YYYY-MM-DD)")
    missing = [i for i in surviving_ids if i not in listed]
    if missing:
        errors.append("'## Carried obligations' is missing: " + ", ".join(missing) + " (each surviving CRITICAL/MAJOR id needs a table row).")
    if critical:
        for need in (DRIVE, BAKE):
            if not any(need in " | ".join(r).upper() for r in rows):
                errors.append(f"tier critical: '## Carried obligations' needs a '{need}' row with owner and close-by date")
    return errors


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
                "findings exist -- the wave was skipped (the synthesize stage "
                "must run it before the report is written)."
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

    # P1: every surviving CRITICAL/MAJOR finding, from any lane, is carried to the build with a named proof.
    surviving_ids = sorted(
        rid
        for rid in ids
        if id_has_verdict_elsewhere(rid, text)
        and not _id_verdict_is(rid, text, ("REFUTED",))
    )
    failures += carried_errors(text, surviving_ids)

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
