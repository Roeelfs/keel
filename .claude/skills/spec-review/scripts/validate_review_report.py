#!/usr/bin/env python3
"""SR1/SR4: validate a spec-review `.review.md` report against the pipeline's
hard rules (report-template.md + SKILL.md Step 5c), including the follow-on
dispositions, unknowns and founder-decisions tables.

Usage:
    python3 validate_review_report.py [--final] <report.md>

--final (Step 9, before the review is committed): a follow-on Tracker cell
still reading `to-file` is refused; report-check accepts it because the main
loop files those tickets in Step 5c.

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


def section_block(text, title):
    """The body of the '#… <title>' section, or None."""
    m = re.search(r"^#+\s*" + re.escape(title) + r"\s*$", text, re.MULTILINE | re.IGNORECASE)
    if not m:
        return None
    start = m.end()
    next_heading = re.search(r"^#+\s+\S", text[start:], re.MULTILINE)
    return text[start : start + next_heading.start()] if next_heading else text[start:]


def carried_block(text):
    """The body of the '## Carried obligations' section, or None."""
    return section_block(text, "Carried obligations")


def carried_rows(body):
    """(header cells, data rows as cell lists) of the first table in a section body."""
    lines = [l.strip() for l in body.splitlines() if l.strip().startswith("|")]
    cells = [[c.strip().strip("*`").strip() for c in l.strip("|").split("|")] for l in lines]
    rows = [c for c in cells if not all(re.fullmatch(r":?-{3,}:?", x) for x in c if x)]
    return (rows[0], rows[1:]) if rows else ([], [])


def carried_errors(text, surviving_ids):
    """P1/P3: every surviving CRITICAL/MAJOR id sits in a carried row with a named proof; a drive, bake or
    owed proof names an owner and a close-by date; a critical-tier report carries both boundary rows."""
    critical = re.search(r"\(tier critical\)", text, re.IGNORECASE) is not None
    rt = re.search(r"\(tier standard\)[^\n]*?runtime path:\s*([^\n;—]+)", text, re.IGNORECASE)
    standard_runtime = rt is not None and rt.group(1).strip().strip("`<>").lower() not in ("", "none", "n/a")
    if not surviving_ids and not critical and not standard_runtime:
        return []
    body = carried_block(text)
    if body is None:
        what = f"SURVIVING CRITICAL/MAJOR finding(s) present ({', '.join(surviving_ids)})" if surviving_ids else "tier critical or a standard-tier runtime path"
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
    if standard_runtime and not any(DRIVE in " | ".join(r).upper() for r in rows):
        errors.append(f"tier standard with a runtime path: '## Carried obligations' needs a '{DRIVE}' row with owner and close-by date")
    return errors


DISPOSITIONS = ("IN", "PARALLEL-TICKET", "PROBE", "DEFER", "OUT")
NO_CANDIDATES_RE = re.compile(r"\bno candidates\b", re.IGNORECASE)
TO_FILE = "to-file"


def table(body, *names):
    """(rows, column index per name or None) of the first table in a section body."""
    header, rows = carried_rows(body)
    return rows, {n: next((i for i, h in enumerate(header) if n in h.lower()), None) for n in names}


def cell_of(row, col, name):
    i = col[name]
    return row[i] if i is not None and i < len(row) else ""


def follow_on_required(text):
    """F1: completeness-reviewer runs (and owns the census) at standard and critical, and at light with a
    runtime path, so those reports carry the dispositions table."""
    if re.search(r"\(tier (?:standard|critical)\)", text, re.IGNORECASE):
        return True
    rt = re.search(r"\(tier light\)[^\n]*?runtime path:\s*([^\n;—]+)", text, re.IGNORECASE)
    return rt is not None and rt.group(1).strip().strip("`<>").lower() not in ("", "none", "n/a")


def follow_on_errors(text, final=False):
    """F1: every follow-on candidate has evidence and one disposition; PARALLEL-TICKET and DEFER name a tracker
    id; DEFER names its trigger; any PROBE row needs an Unknowns table. Returns (errors, has_probe)."""
    body = section_block(text, "Follow-on dispositions")
    if body is None:
        return (["tier runs the follow-on census but no '### Follow-on dispositions' section exists."]
                if follow_on_required(text) else []), False
    rows, col = table(body, "candidate", "evidence", "disposition", "tracker", "trigger")
    if col["disposition"] is None:
        return ["'### Follow-on dispositions' needs a table with a Disposition column "
                "(| # | Candidate | Class | Evidence | Disposition | Tracker | Trigger |)."], False
    if not rows and not NO_CANDIDATES_RE.search(body):
        return ["'### Follow-on dispositions' has no rows; write 'no candidates: <classes checked>' as the receipt."], False
    errors, has_probe = [], False
    for r in rows:
        name = cell_of(r, col, "candidate") or r[0]
        lead = re.match(r"[A-Za-z-]+", cell_of(r, col, "disposition").strip())
        disp = lead.group(0).upper() if lead else ""
        if disp not in DISPOSITIONS:
            errors.append(f"follow-on row '{name}' needs one disposition of {'/'.join(DISPOSITIONS)}, got {cell_of(r, col, 'disposition')!r}")
            continue
        has_probe |= disp == "PROBE"
        if cell_of(r, col, "evidence").lower() in EMPTY_CELLS:
            errors.append(f"follow-on row '{name}' cites no evidence (spec line, file:line, PR or ledger row); drop it or cite one")
        tracker = cell_of(r, col, "tracker").lower()
        if disp in ("PARALLEL-TICKET", "DEFER") and (tracker in EMPTY_CELLS or (final and tracker == TO_FILE)):
            errors.append(f"follow-on row '{name}' is {disp} with no tracker id (file the ticket, then write its id)")
        if disp == "DEFER" and cell_of(r, col, "trigger").lower() in EMPTY_CELLS:
            errors.append(f"follow-on row '{name}' is DEFER with no trigger event")
    return errors, has_probe


PROBE_CAP = 3
PROBE_CAP_OVERRIDE_RE = re.compile(r"probe cap override:\s*\S", re.IGNORECASE)


def unknowns_errors(text, has_probe):
    """F3: each unknown names a runnable probe (command, target, expected), a time-box and what ship it blocks;
    at most PROBE_CAP probes per spec unless the section states `probe cap override: <reason>`."""
    body = section_block(text, "Unknowns")
    if body is None:
        return ["a follow-on row is PROBE but no '### Unknowns' section exists."] if has_probe else []
    rows, col = table(body, "claim", "probe", "time-box", "blocks")
    missing = [n for n in ("claim", "probe", "time-box", "blocks") if col[n] is None]
    if missing:
        return ["'### Unknowns' needs columns | U-ID | Claim | Why unproven | Probe | Time-box | Blocks ship | (missing: "
                + ", ".join(missing) + ")."]
    if has_probe and not rows:
        return ["a follow-on row is PROBE but '### Unknowns' has no rows."]
    errors = []
    if len(rows) > PROBE_CAP and not PROBE_CAP_OVERRIDE_RE.search(body):
        errors.append(f"'### Unknowns' has {len(rows)} probes, over the cap of {PROBE_CAP}: merge probes on one seam, "
                      "or state 'probe cap override: <reason>' under the table")
    for r in rows:
        for n in ("probe", "time-box", "blocks"):
            if cell_of(r, col, n).lower() in EMPTY_CELLS:
                errors.append(f"unknown '{r[0]}' has an empty {n} cell")
    return errors


def decisions_errors(text):
    """F7: every founder decision owed carries a recommended answer, so one grill round settles it."""
    body = section_block(text, "Founder decisions owed")
    if body is None:
        return []
    rows, col = table(body, "decision", "recommended")
    if col["recommended"] is None:
        return ["'### Founder decisions owed' needs a Recommended answer column."]
    return [f"founder decision '{r[0]}' has no recommended answer" for r in rows
            if cell_of(r, col, "recommended").lower() in EMPTY_CELLS]


def validate(text, final=False):
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

    # F1/F3/F7: follow-on dispositions, unknowns with probes, founder decisions with a recommended answer.
    fo_errors, has_probe = follow_on_errors(text, final)
    failures += fo_errors + unknowns_errors(text, has_probe) + decisions_errors(text)

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
    final = "--final" in argv[1:]
    args = [a for a in argv[1:] if a != "--final"]
    if len(args) != 1:
        print("usage: validate_review_report.py [--final] <report.md>", file=sys.stderr)
        return 1
    path = args[0]
    try:
        text = open(path, encoding="utf-8").read()
    except OSError as e:
        print(f"FAIL: cannot read {path}: {e}")
        return 1

    ok, failures, summary = validate(text, final)

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
