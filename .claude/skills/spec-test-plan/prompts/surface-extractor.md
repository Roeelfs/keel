# Testable Surface Extractor

Reads the spec and extracts every testable surface with tier classification, prerequisites, AND downstream-consumer enumeration.

**Agent type:** `general-purpose` | **Model:** `opus`

```
description: "Extract testable surfaces from spec — including consumers, state transitions, and fixture dependencies"
prompt: |
  Read the spec at {{SPEC_PATH}} and extract EVERY testable surface. Be exhaustive.

  ## Extract:

  For each surface found, output a row:

  | ID | Surface | Spec Section | Tier(s) | Preconditions | Priority | Consumers |
  |----|---------|-------------|---------|---------------|----------|-----------|

  ### What counts as a testable surface:
  - Every new/modified function, endpoint, handler, component
  - Every user-facing flow or workflow
  - Every data mutation (DB writes, file creation, state changes)
  - Every integration point (external APIs, webhooks, auth flows)
  - Every error/edge case the spec explicitly mentions
  - Every UI change (new pages, modified layouts, interactive elements)
  - Every migration (schema changes, data transformations)
  - Every configuration change (env vars, feature flags, permissions)
  - Every callback or event hook registered by the spec (onSuccess, onFailure, completion callback, etc.)
  - Every stub / placeholder / `NotImplementedError` that the spec says will be replaced

  ### Tier classification:
  - **Unit**: isolated function/module, mockable boundaries
  - **Integration**: real DB/services, component interaction
  - **Chain**: multi-step sequence end-to-end (upload → serialize → render; acquire → use → release)
  - **Deploy**: env vars, build output, service health, IAM grants, runtime parity
  - **E2E**: full browser user journey

  A surface can belong to multiple tiers. For mutations with callbacks, the surface
  requires BOTH unit (callback wiring) AND integration (callback fires in all paths).

  ### Preconditions per surface:
  - Auth required? Which role?
  - Seed data required? What kind?
  - Services required? Which ones?
  - Env vars required? Which ones?
  - Test org/tenant variance required? (see "Tenant variance" below)
  - Runtime required? (local only / staging / serverless container / real object-store bucket / real function)

  ### Consumers (blast-radius column) — REQUIRED for every mutation

  For every surface that mutates state (DB row, file, cache, external call), enumerate
  EVERY downstream consumer of that mutation. A mutation with untested consumers is a
  plumbing bug waiting to happen.

  Consumer categories to probe:
  - **Callbacks**: Every terminal path that should fire onSuccess/onFailure/onCompletion hooks
  - **Serializers**: Every API response shape that reads the mutated field
  - **UI renderers**: Admin views, list views, detail views, mobile app screens
  - **Downstream jobs**: Crons, schedulers, webhooks, notification dispatchers
  - **Dependent queries**: Filters, joins, aggregations that read this field
  - **External APIs**: Webhook payloads, partner integrations, mobile decoders

  Example:
  - Surface: `Task.attachment_url` URLField → FileField migration
  - Consumers: (1) TaskSerializer → mobile app decoder, (2) AdminAttachmentFilter admin
    review queue, (3) /api/tasks detail view → React component, (4) signed-URL health
    probe, (5) object-store storage backend switch.
  - EACH consumer needs its own test row. The plan has FIVE tests, not one.

  Real bugs caught by consumer enumeration:
  - A completion callback: the spec defined ONE callback hook, but FOUR completion paths
    (a health-report path + several lifecycle-manager paths) should have invoked it. The plan
    had one test; the un-wired paths shipped broken.
  - An `os.path.exists` filter: the admin consumer of `attachment_url` was never tested
    against object-store storage; local FileSystem made all tests pass, prod hid every image.

  ### State mutations — enumerate each flag/status transition

  For every DB column, cache key, or in-memory flag that governs downstream behavior,
  produce a sub-table:

  | State Field | Valid Values | Write Triggers | Read Consumers | Ordering Constraint |
  |-------------|--------------|----------------|----------------|---------------------|
  | is_stale | bool | markStale before async worker invoke | background poller | WRITE must commit before invoke |
  | review_status | incomplete/pending/approved/rejected | item submission, admin action | commit guard, AuditTrailTest setUp | transition rules spec §X |

  - "Ordering Constraint" forces the spec author to make two-phase writes explicit.
  - Missing constraints become unit test rows: "write X before Y or poller misses it".

  ### Fixture dependencies — enumerate seed data per test

  For each Tier (unit / integration / chain / deploy / E2E), list the fixtures required.
  A missing fixture is a silent SKIP that becomes a prod bug.

  - Unit: factories needed, mock shapes, parameterized data
  - Integration: seed rows, test accounts, pre-created files
  - Chain/E2E: test org variants (see next), pre-authenticated sessions, pre-uploaded assets

  Real bug: a user-lookup fixture was missing → the dependent message-routing tests
  silently skipped → message routing shipped broken.

  ### Tenant / org variance — required for multi-integration specs

  If the spec touches a feature with fallback chains, optional integrations, or
  per-tenant config:

  - List at LEAST two test org variants:
    - Baseline: all integrations configured (happy path)
    - Missing-integration: at least one optional integration absent (forces fallback)
  - List fixture-diversity requirements:
    - Input diversity (multi-byte unicode names, single-token names, non-ASCII names)
    - Edge populations (zero-history accounts, suspended accounts, pending-approval accounts)

  Real bug: a `notify_destination` fallback shipped broken because all E2E tests used the one
  test org that had the primary destination-config row pre-seeded — the fallback path never ran.

  ## Output

  Produce:
  1. The complete surface table (with `Consumers` column populated).
  2. The state-mutation table.
  3. The fixture-dependency table per tier.
  4. The tenant-variance list (or "N/A — single tenant, no fallback" if genuinely absent).
  5. Summary:
     - Total surfaces: N
     - By tier: N unit, N integration, N chain, N deploy, N E2E
     - Mutations with untested consumers: N (MUST be 0 — every mutation needs every consumer covered)
     - Stubs / placeholders present: N (each must have a "stub replaced" test)
     - Blocking preconditions: list anything requiring human action

  Be exhaustive. A missing surface is a future bug. An untracked consumer is a
  future plumbing drop. An untested fallback is a future fallback-miss incident.
```
