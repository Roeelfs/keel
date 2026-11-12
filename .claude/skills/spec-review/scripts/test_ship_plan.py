#!/usr/bin/env python3
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "ship_plan.py"
sys.path.insert(0, str(SCRIPT.parent))
import ship_plan as sp  # noqa: E402

RULES = [{"name": "schema-before-caller", "before": ["db/migrations/*"], "after": ["src/*"]}]

SPEC = """\
# Widget limits

## Scope
1. Add the limit column.
2. Backfill existing rows.
3. Enforce the limit in the API.
4. Show the limit in the UI.

## Ships
| Ship | Scope items | Files and contracts | blockedBy | Dependency |
|---|---|---|---|---|
| A schema | 1, 2 | `db/migrations/0042_limit.sql` | - | none |
| B api | 3 | `src/api/limit.ts` | A schema | gate-rule:schema-before-caller |
| C docs | - | `docs/limits.md` | - | none |
| DEFER | 4 | - | TKT-12 | none |

## Out of Scope
- nothing
"""


def errs(text, rules=RULES):
    return sp.check(text, rules)[0]


class ShipPlanTests(unittest.TestCase):
    def test_valid_plan_passes_with_a_receipt(self):
        errors, receipt = sp.check(SPEC, RULES)
        self.assertEqual(errors, [])
        self.assertIn("split rules checked: 1", receipt)
        self.assertIn("scope items checked: 4", receipt)

    def test_missing_section_or_columns(self):
        self.assertTrue(any("no '## Ships'" in e for e in errs("# x\n")))
        self.assertTrue(any("needs columns" in e for e in errs("## Ships\n| Ship | Files |\n|---|---|\n| A | x |\n")))

    def test_serial_edge_typed_none_and_typed_dep_without_edge(self):
        none_edge = SPEC.replace("| A schema | gate-rule:schema-before-caller |", "| A schema | none |")
        self.assertTrue(any("serial edge typed none" in e for e in errs(none_edge, [])))
        no_edge = SPEC.replace("| `docs/limits.md` | - | none |", "| `docs/limits.md` | - | contract |")
        self.assertTrue(any("no blockedBy edge" in e for e in errs(no_edge)))
        bad_kind = SPEC.replace("| `docs/limits.md` | - | none |", "| `docs/limits.md` | - | maybe |")
        self.assertTrue(any("use none, data" in e for e in errs(bad_kind)))

    def test_unknown_ship_and_unknown_rule(self):
        self.assertTrue(any("not a ship in the table" in e for e in errs(SPEC.replace("| A schema | gate", "| Z | gate"))))
        self.assertTrue(any("not a loaded split rule" in e for e in errs(SPEC, [])))

    def test_split_rule_both_sides_and_order(self):
        both = SPEC.replace("`db/migrations/0042_limit.sql`", "`db/migrations/0042_limit.sql`, `src/api/limit.ts`")
        self.assertTrue(any("holds both sides" in e for e in errs(both)))
        unordered = SPEC.replace("| A schema | gate-rule:schema-before-caller |", "| C docs | data |")
        self.assertTrue(any("not blockedBy A schema" in e for e in errs(unordered)))

    def test_defer_row_needs_a_tracker_and_scope_must_be_covered(self):
        self.assertTrue(any("names no tracker id" in e for e in errs(SPEC.replace("| TKT-12 |", "| - |"))))
        dropped = SPEC.replace("| DEFER | 4 | - | TKT-12 | none |\n", "")
        self.assertTrue(any("not mapped to a ship or DEFER row: 4" in e for e in errs(dropped)))

    def test_no_scope_list_is_named_in_the_receipt(self):
        text = SPEC.split("## Ships")[1]
        errors, receipt = sp.check("## Ships" + text, RULES)
        self.assertEqual(errors, [])
        self.assertTrue(any("no numbered Scope" in r for r in receipt))

    def test_cli_reads_rules_file(self):
        with tempfile.TemporaryDirectory() as d:
            spec, rules = Path(d) / "spec.md", Path(d) / "rules.json"
            spec.write_text(SPEC)
            rules.write_text(json.dumps({"splitRules": RULES}))
            ok = subprocess.run([sys.executable, str(SCRIPT), str(spec), "--rules", str(rules)], capture_output=True, text=True)
            self.assertEqual(ok.returncode, 0, ok.stdout)
            self.assertIn("split rules checked: 1", ok.stdout)
            norules = subprocess.run([sys.executable, str(SCRIPT), str(spec), "--rules", str(Path(d) / "absent.json")],
                                     capture_output=True, text=True)
            self.assertEqual(norules.returncode, 1, norules.stdout)
            self.assertIn("not a loaded split rule", norules.stdout)


if __name__ == "__main__":
    unittest.main()
