---
license: MIT
name: spec-test-plan
description: Use when a spec needs an executable verification contract. Produces the smallest proof-obligation ledger that covers its acceptance criteria and real runtime risks.
---

# Spec Test Plan

Turn a spec into a compact, executable proof contract. The useful artifact is not a large catalogue of possible tests; it is a short ledger that a verifier will actually execute.

## Skill memory

Read `LEARNINGS.md` and the private overlay at `~/.claude/skills-overlay/spec-test-plan/LEARNINGS.md` when present. Route operator-private learning to the overlay, project facts to project memory, and universal craft to `/improve-harness`.

## Choose one mode

- `checklist`: trivial or docs-only behavior. Put the exact checks in the implementation/PR artifact; a separate plan file is optional.
- `moderate`: the default for a normal feature or changed customer/runtime behavior.
- `critical`: auth, money, deletion, migration, isolation, irreversible state, or another named trust boundary.

For `moderate` and `critical`, the provisional default is no more than 12 unique proof obligations and 2 customer journeys. These are compression defaults, not safety caps. Exceed either only when `budget_override_reason` names the uncovered acceptance criterion or risk that requires the additional row.

The root author writes the plan. Do not dispatch a mandatory child. A `critical` or genuinely ambiguous plan may receive one fresh Terra-medium, read-only coverage review using `prompts/critical-coverage-reviewer.md`. Use Sol only for one bounded unresolved security, irreversible-architecture, or trust-boundary dispute.

## Read context: index, then select

Read the spec fully. For large project test references, index, then select only the relevant sections and flow entries:

```bash
rg -n '^## ' testing/config.md
jq -r '.flows | to_entries[] | [.key, (.value.description // "")] | @tsv' testing/flows.json
```

Then extract the named section or keyed flow. For example:

```bash
awk '/^## <selected section>/{on=1; next} /^## /{on=0} on' testing/config.md
jq '.flows["<selected-flow-key>"]' testing/flows.json
```

Include the selected known limitations and operational gotchas in the plan. Read an entire large registry only when keyed selection cannot answer the question; record that reason under `## Context selection`.

## Build the proof-obligation ledger

Map every acceptance criterion and material runtime risk to one unique row. Prefer existing tests and the narrowest proof that can fail for the intended reason. Add a customer journey only when a local seam check cannot establish the customer-visible outcome. Add a deployed bake only when the merged/deployed substrate is itself part of the claim.

Use these kinds:

- `targeted`: focused local or component proof.
- `invariant`: cheap assertion at a boundary mocks cannot cover.
- `journey`: one customer-visible path across seams.
- `project-gate`: the project-authoritative verification command; exactly one row for `moderate`/`critical`.
- `deployed-bake`: changed runtime seam that requires a named deployed environment.

Do not duplicate the same source and proof in multiple rows. Do not enumerate permutations merely because they exist. Vary cases only when they exercise a distinct contract or failure mode.

## Output

Write `<spec-dir>/<spec-name>-test-plan.md`:

```markdown
---
mode: moderate
budget_override_reason:
---
# Test Plan: <title>

## What working means
<The customer/operator outcome in 2-4 lines.>

## Context selection
- `testing/config.md`: <named sections read>
- `testing/flows.json`: <keys read>
- Full-file exception: <reason, or none>

## Proof-obligation ledger
| ID | Kind | Source | Proof | Status | Evidence / deferred owner |
|---|---|---|---|---|---|
| PO-01 | targeted | AC-1 | `<exact command>` proves <strong assertion> | PENDING | |
| PO-02 | journey | RISK-auth-callback | <exact runner, safe identity, expected state/log/output> | PENDING | |
| PO-03 | project-gate | project test contract | `<project command>` once after targeted proofs | PENDING | |
```

Every row needs:

- a stable ID;
- a source reference to an acceptance criterion or named risk;
- an exact command/journey and a strong assertion;
- a status from `PENDING`, `PASS`, `FAIL`, `BLOCKED`, `SKIP`, or `DEFERRED`;
- for `DEFERRED`, `owner: <issue/person>` in the last column.

Escape a literal pipe in a proof command as `\|`; malformed table rows fail validation rather than disappearing from the budget.

Validate the artifact before handoff:

```bash
python3 ~/.claude/skills/spec-test-plan/scripts/validate_plan.py <test-plan.md>
```

Commit it with the rest of the define artifact. A separate plan-only commit is optional.

## Handoff

Return the plan path, mode, row count, journey count, selected context slices, and any budget override. A material planning finding may patch the spec before build. Zero findings require no stub or no-op commit.

## Do not use

- Do not create a second adversarial spec review disguised as a test plan.
- Do not load large registries repeatedly into agents.
- Do not deploy, poll, or execute the plan here.
- Do not require one test per consumer, permutation, or severity tier.
