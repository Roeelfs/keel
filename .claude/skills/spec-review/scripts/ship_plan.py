#!/usr/bin/env python3
"""Validate a spec's `## Ships` table: a typed dependency plan with gate splits pre-declared.

Usage:
    python3 ship_plan.py <spec.md> [--rules <split-rules.json>]

The table (one row per ship, plus `DEFER` rows for scope that leaves this spec):

    | Ship | Scope items | Files and contracts | blockedBy | Dependency |
    | 1 schema | 1, 2 | `db/migrations/0042_x.sql` | - | none |
    | 2 caller | 3-5 | `src/api/x.ts` | 1 schema | gate-rule:schema-before-caller |
    | DEFER | 6 | - | TKT-12 | none |

Dependency is `none`, `data`, `contract`, `gate-rule:<name>` or `bake-carve-out`. Checks:
- every blockedBy names a ship in the table, and a serial edge is never typed `none`
  (a `none` ship has an empty blockedBy and dispatches concurrently);
- a typed dependency has a blockedBy edge; a `gate-rule:<name>` names a loaded rule;
- split rules: a ship whose files hit both sides of a rule is refused, and a ship holding a rule's
  `after` side must be blockedBy the ship holding its `before` side;
- a DEFER row names a tracker id in blockedBy;
- every numbered item under `## Scope` (else `## User Stories`) maps to a ship or a DEFER row.

Split rules are per repo: `--rules`, else `<git root>/.claude/split-rules.json`, shaped
`{"splitRules": [{"name": "...", "before": ["<glob>"], "after": ["<glob>"]}]}`. The receipt always prints
how many rules and scope items were checked, so a check that examined nothing is never silent.
Exit 0 on pass, 1 on any failure.
"""
import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path

DEPENDENCIES = ("none", "data", "contract", "bake-carve-out")
EMPTY = ("", "-", "—", "none", "n/a")
COLUMNS = ("ship", "scope", "files", "blockedby", "dependency")


def section(text, *titles):
    for title in titles:
        m = re.search(r"^#+\s*" + re.escape(title) + r"\s*$", text, re.MULTILINE | re.IGNORECASE)
        if m:
            nxt = re.search(r"^#{1,2}\s+\S", text[m.end():], re.MULTILINE)
            return title, text[m.end(): m.end() + nxt.start()] if nxt else text[m.end():]
    return None, None


def table(body):
    lines = [l.strip() for l in body.splitlines() if l.strip().startswith("|")]
    cells = [[c.strip().strip("*`").strip() for c in l.strip("|").split("|")] for l in lines]
    rows = [c for c in cells if not all(re.fullmatch(r":?-{3,}:?", x) for x in c if x)]
    if not rows:
        return None, []
    head = [h.lower().replace(" ", "") for h in rows[0]]
    col = {n: next((i for i, h in enumerate(head) if h.startswith(n)), None) for n in COLUMNS}
    get = lambda r, n: r[col[n]] if col[n] is not None and col[n] < len(r) else ""
    return col, [{n: get(r, n) for n in COLUMNS} for r in rows[1:]]


def numbers(cell):
    out = set()
    for a, b in re.findall(r"(\d+)\s*(?:[-–]\s*(\d+))?", cell):
        out |= set(range(int(a), int(b or a) + 1))
    return out


def paths(cell):
    return [p.strip("`") for p in re.split(r"[,\s]+", cell) if p.strip("`")]


def hits(files, globs):
    return any(fnmatch.fnmatch(f, g) for f in files for g in globs)


def load_rules(spec, rules_path):
    if not rules_path:
        try:
            root = subprocess.run(["git", "-C", str(Path(spec).resolve().parent), "rev-parse", "--show-toplevel"],
                                  capture_output=True, text=True, timeout=5).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            root = ""
        rules_path = Path(root) / ".claude" / "split-rules.json" if root else None
    if not rules_path or not Path(rules_path).is_file():
        return [], "no split-rules file"
    data = json.loads(Path(rules_path).read_text())
    return data.get("splitRules") or [], str(rules_path)


def check(text, rules):
    """-> (errors, receipt lines)."""
    _, body = section(text, "Ships")
    if body is None:
        return ["no '## Ships' section: add | Ship | Scope items | Files and contracts | blockedBy | Dependency |"], []
    col, rows = table(body)
    if not col or any(col[n] is None for n in COLUMNS):
        return ["'## Ships' needs columns | Ship | Scope items | Files and contracts | blockedBy | Dependency |"], []
    errors = []
    ships = {r["ship"]: r for r in rows if r["ship"].upper() != "DEFER"}
    rule_names = {r["name"]: r for r in rules}
    for name, r in ships.items():
        dep, blocked = r["dependency"].strip(), r["blockedby"].strip()
        edges = [] if blocked.lower() in EMPTY else [e.strip() for e in blocked.split(",")]
        r["edges"] = edges
        for e in edges:
            if e not in ships:
                errors.append(f"ship '{name}' is blockedBy '{e}', which is not a ship in the table")
        kind = dep.split(":", 1)[0].lower()
        if kind not in DEPENDENCIES and kind != "gate-rule":
            errors.append(f"ship '{name}' has dependency {dep!r}; use none, data, contract, gate-rule:<name> or bake-carve-out")
        elif kind == "none" and edges:
            errors.append(f"ship '{name}' has a serial edge typed none: name the data, contract or gate rule, or drop the edge")
        elif kind != "none" and not edges:
            errors.append(f"ship '{name}' declares dependency {dep!r} but no blockedBy edge")
        if kind == "gate-rule" and dep.split(":", 1)[-1] not in rule_names:
            errors.append(f"ship '{name}' cites {dep!r}, which is not a loaded split rule")
    for rule in rules:
        before = [n for n, r in ships.items() if hits(paths(r["files"]), rule.get("before") or [])]
        after = [n for n, r in ships.items() if hits(paths(r["files"]), rule.get("after") or [])]
        for n in sorted(set(before) & set(after)):
            errors.append(f"ship '{n}' holds both sides of split rule '{rule['name']}'; split it in the declared order")
        for n in sorted(set(after) - set(before)):
            if before and not set(ships[n]["edges"]) & set(before):
                errors.append(f"ship '{n}' holds the after side of split rule '{rule['name']}' but is not blockedBy "
                              f"{', '.join(sorted(before))}")
    for r in rows:
        if r["ship"].upper() == "DEFER" and r["blockedby"].strip().lower() in EMPTY:
            errors.append(f"DEFER row for scope '{r['scope']}' names no tracker id in blockedBy")
    title, scope_body = section(text, "Scope", "User Stories")
    items = {int(n) for n in re.findall(r"^\s*(\d+)\.\s", scope_body or "", re.MULTILINE)}
    covered = set().union(*(numbers(r["scope"]) for r in rows)) if rows else set()
    missing = sorted(items - covered)
    if missing:
        errors.append(f"'## {title}' items not mapped to a ship or DEFER row: {', '.join(map(str, missing))}")
    receipt = [f"ships: {len(ships)}, DEFER rows: {len(rows) - len(ships)}",
               f"split rules checked: {len(rules)}",
               f"scope items checked: {len(items)}" + ("" if items else " (no numbered Scope or User Stories list)")]
    return errors, receipt


def main(argv):
    args = argv[1:]
    rules_path = None
    if "--rules" in args:
        i = args.index("--rules")
        rules_path = args[i + 1] if i + 1 < len(args) else ""
        args = args[:i] + args[i + 2:]
    if len(args) != 1:
        print("usage: ship_plan.py <spec.md> [--rules <split-rules.json>]", file=sys.stderr)
        return 1
    try:
        text = Path(args[0]).read_text(encoding="utf-8")
        rules, source = load_rules(args[0], rules_path)
    except (OSError, ValueError) as e:
        print(f"FAIL: {e}")
        return 1
    errors, receipt = check(text, rules)
    print(f"Ship plan: {args[0]} (rules: {source})")
    print("\n".join("  " + r for r in receipt))
    if not errors:
        print("PASS")
        return 0
    print("FAIL")
    print("\n".join(f"  - {e}" for e in errors))
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
