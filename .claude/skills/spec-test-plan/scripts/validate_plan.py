#!/usr/bin/env python3
"""Validate the compact spec-test-plan Markdown contract."""

from __future__ import annotations

import re
import sys
from pathlib import Path


MODES = {"checklist", "moderate", "critical"}
KINDS = {"targeted", "invariant", "journey", "project-gate", "deployed-bake"}
STATUSES = {"PENDING", "PASS", "FAIL", "BLOCKED", "SKIP", "DEFERRED"}


def _frontmatter(text: str) -> dict[str, str]:
    match = re.match(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", text, re.S)
    if not match:
        return {}
    result: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            result[key.strip()] = value.strip()
    return result


def _rows(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [cell.replace(r"\|", "|").strip() for cell in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
        if len(cells) != 6 or cells[0] in {"ID", "---"} or set(cells[0]) == {"-"}:
            continue
        rows.append(dict(zip(("id", "kind", "source", "proof", "status", "evidence"), cells)))
    return rows


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def validate_text(text: str) -> list[str]:
    errors: list[str] = []
    meta = _frontmatter(text)
    mode = meta.get("mode", "")
    reason = meta.get("budget_override_reason", "")
    rows = _rows(text)

    in_ledger = False
    for line in text.splitlines():
        if re.match(r"^\s*\|\s*ID\s*\|\s*Kind\s*\|", line, re.I):
            in_ledger = True
            continue
        if not in_ledger:
            continue
        if not line.lstrip().startswith("|"):
            if line.strip():
                in_ledger = False
            continue
        cells = re.split(r"(?<!\\)\|", line.strip().strip("|"))
        if cells and set(cells[0].strip()) == {"-"}:
            continue
        if len(cells) != 6:
            errors.append("malformed proof row: escape literal pipes as \\|")

    if mode not in MODES:
        errors.append(f"mode must be one of {sorted(MODES)}")
    if mode != "checklist" and not rows:
        errors.append("moderate/critical plans need at least one proof obligation")

    seen_ids: set[str] = set()
    seen_proofs: set[tuple[str, str]] = set()
    for row in rows:
        if not row["id"]:
            errors.append("every row needs an ID")
        elif not re.fullmatch(r"[A-Za-z]+-\d+", row["id"]):
            errors.append(f"invalid stable ID: {row['id']}")
        elif row["id"] in seen_ids:
            errors.append(f"duplicate ID: {row['id']}")
        seen_ids.add(row["id"])

        if row["kind"] not in KINDS:
            errors.append(f"{row['id']}: unsupported kind {row['kind']!r}")
        if not row["source"]:
            errors.append(f"{row['id']}: source is required")
        if not row["proof"]:
            errors.append(f"{row['id']}: proof is required")
        signature = (_normalized(row["source"]), _normalized(row["proof"]))
        if signature in seen_proofs:
            errors.append(f"{row['id']}: duplicate source/proof")
        seen_proofs.add(signature)
        if row["status"] not in STATUSES:
            errors.append(f"{row['id']}: unsupported status {row['status']!r}")
        if row["status"] == "DEFERRED" and "owner:" not in row["evidence"].lower():
            errors.append(f"{row['id']}: DEFERRED requires owner:")

    gates = [row for row in rows if row["kind"] == "project-gate"]
    if mode in {"moderate", "critical"} and len(gates) != 1:
        errors.append("moderate/critical plans require exactly one project-gate")
    elif len(gates) > 1:
        errors.append("at most one project-gate is allowed")

    overflow_sources: list[str] = []
    substantive_rows = [row for row in rows if row["kind"] != "project-gate"]
    if mode in {"moderate", "critical"} and len(rows) > 12:
        overflow_sources.extend(row["source"] for row in substantive_rows[11:])
    journeys = [row for row in rows if row["kind"] == "journey"]
    if mode in {"moderate", "critical"} and len(journeys) > 2:
        overflow_sources.extend(row["source"] for row in journeys[2:])
    missing_override_sources = {
        source for source in overflow_sources if source and source.lower() not in reason.lower()
    }
    if missing_override_sources:
        errors.append(
            "budget_override_reason must name every overflow source: "
            + ", ".join(sorted(missing_override_sources))
        )

    return errors


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {Path(argv[0]).name} <test-plan.md>", file=sys.stderr)
        return 2
    path = Path(argv[1])
    errors = validate_text(path.read_text())
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"PASS: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
