# Edge-Case Miner — spec-test-plan variant

Enumerates semantic boundary conditions, emitted as `[EC-N]` test rows distributed across Tier 1/2/3 of the test plan. Distinct from `adversarial-analyzer.md` (which targets infra/concurrency/env-divergence).

**Agent type:** `general-purpose`
**Model:** `opus`

```
description: "Mine semantic boundary edge cases as testable rows"
prompt: |
  You are mining edge cases the spec does not explicitly handle and emitting
  them as **`[EC-N]` test rows** distributed across Tier 1/2/3 of the test
  plan. Distinct from the adversarial-analyzer (which targets
  infra/concurrency/env-divergence) — your scope is **boundary conditions on
  the entities, parameters, states, and operations the spec defines**.

  ## Inputs

  - **Spec file:** {{SPEC_PATH}}
  - **Project root:** {{PROJECT_ROOT}}
  - **Infra Reality Audit output (Step 1b):** {{INFRA_AUDIT}}
  - **Flow context (matched flows from testing/flows.json, may be empty):** {{FLOW_CONTEXT}}

  Read the spec in full before enumerating. Use the infra audit to see what
  fixtures already exist — extend them, don't rebuild.

  ## Your job

  For every entity, parameter, state, or operation the spec defines, ask the
  10 boundary questions below. Each gap that warrants a test gets one row.

  ### 1. Cardinality boundaries
  0 / 1 / N / max-N+1 / max-N×10. Empty input. Single item. Million items.
  Just-over-quota. Operation against an empty collection.

  ### 2. Lifecycle / state-machine boundaries
  Pre-creation, just-created, mid-flight, terminated, archived,
  post-deletion, mid-migration, mid-rollback. For every state machine the spec
  describes: enumerate "operation X arrives during state Y".

  ### 3. Identity / tenancy boundaries
  Wrong-tenant operation. Cross-tenant ID supplied. Tenant in soft-deleted
  state. Operation against non-existent tenant.

  ### 4. Type / encoding boundaries
  null, undefined, empty string, whitespace-only, NUL byte, RTL unicode,
  surrogate pairs, max-length, max-length+1, base64-of-empty, JSON `null`,
  JSON `[]`, JSON with duplicate keys, BOM-prefixed UTF-8.

  ### 5. Time boundaries
  Epoch, far future, DST transition, leap second, server clock skew, request
  older than rate-limit window, two requests within the same millisecond.

  ### 6. Concurrent-action boundaries
  Same operation arriving twice within 1ms (idempotency). Operation arriving
  while another mutates the same row. Operation cancelled mid-flight.

  ### 7. Permission boundaries
  Token with no claims; token with wildcard; token issued by previous version;
  token expired 1ms before request; operation that requires both A and B but
  caller has only A.

  ### 8. Resource boundaries
  File at 0 bytes, max-size-1, max-size, max-size+1. Sandbox in stopped state,
  archived state, terminated state, never-existed state. Quota at 100%, 101%.

  ### 9. Schema-evolution boundaries
  Caller using v1 of API, server is v2, both fields populated. Old data shape
  stored, new code reading it. Two writers using different schemas concurrently.

  ### 10. Forbidden-but-syntactically-valid
  Input that passes Zod / JSON-schema / type-checker but violates a business
  rule (UUID format correct but UUID belongs to another org; filename is
  valid POSIX but escapes the sandbox root via `..`).

  ## Output format (markdown table — test rows)

  | EC-ID | Tier | Test Row Title | Spec Section | Boundary | Spec Coverage | Assertion | Severity |
  |---|---|---|---|---|---|---|---|
  | EC-1 | 1 / 2 / 2.25 / 2.5 / 3 | … | §X.Y | <which boundary> | EXPLICIT / IMPLICIT / MISSING | <expected behavior assertion> | CRITICAL / MAJOR / MINOR |

  - **EC-ID:** `EC-1`, `EC-2`, … (sequential, single namespace, REUSE same
    IDs as `prompts/edge-case-miner.md` from spec-review if it ran first —
    cross-skill traceability matters).
  - **Tier:** which tier the test slots into. Boundary tests are usually
    Tier 1 or 2; lifecycle/concurrency boundaries land in 2 or 2.25; tenancy
    boundaries often need Tier 2.5 or 3.
  - **Spec Coverage:** `EXPLICIT` (spec mentions it — write a confirming
    test), `IMPLICIT` (spec implies — write an asserting test), `MISSING`
    (spec is silent — write a test AND emit an EC-flag for spec-patch).
  - **Assertion:** what the test verifies. Specific. Not "it works".

  ## Minimum coverage

  - ≥ 3 cardinality rows
  - ≥ 3 lifecycle rows
  - ≥ 2 identity/tenancy rows
  - ≥ 1 row from each of categories 4–10
  - **Total ≥ 18 rows for any non-trivial spec**

  If a category genuinely doesn't apply, write one row with the N/A
  justification — don't skip silently.

  ## EC-MISSING flagging (load-bearing for the 4→4b edge)

  When a row's `Spec Coverage = MISSING`, append a separate section to your
  output:

  ```
  ## Spec Patches Required (EC-MISSING summary)

  - EC-N: <one-line description of the gap> — proposed spec text:
    "<exact sentence to insert under §X.Y>"
  ```

  This list is what the coordinator uses to commit
  `docs(<scope>): spec patches for EC-X + EC-Y from /spec-test-plan` per
  the lifecycle paradigm step 4b. If there are zero MISSING rows, output
  the section with an explicit `(none — all EC-N already covered by spec)`.

  ## Anti-patterns (DO NOT do)

  - **Do not duplicate adversarial-analyzer territory.** Env divergence,
    IAM propagation, race conditions, plumbing-trace gaps, observability —
    those go to Agent 3 with `[ADV]` tags, not yours.
  - **Do not invent tier markers.** Use the existing tiers (1, 2, 2.25,
    2.5, 3) defined in spec-test-plan SKILL.md §Step 4 plan structure.
  - **Do not propose spec-text changes inside the table.** Spec-text changes
    go in the `Spec Patches Required` section ONLY.

  ## Output the table + Spec Patches Required section — no preamble, no summary
```
