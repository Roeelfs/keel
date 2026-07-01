---
name: flows
description: Browse, inspect, and maintain the flow registry (testing/flows.json). Flows are non-code-documented E2E behaviors that compound across spec-test cycles.
---

# Flow Registry — Browse & Maintain

Standalone skill for browsing and maintaining the project's flow registry at `testing/flows.json`.

**Trigger:** "show flows", "flow registry", "what flows do we have", "stale flows", "flow dependencies"

## Skill Memory (LEARNINGS.md)

**Before starting:** Read `LEARNINGS.md` in this skill directory. Apply entries under **What Worked** and **Patterns**; use **Open Questions** to spot decisions that still need care. Also read the private overlay if present: `~/.claude/skills-overlay/flows/LEARNINGS.md` (adopter-private; never in this public repo) — it carries accumulated, project-specific findings layered on top of the portable patterns here.

**Before ending — route each learning by scope; NEVER append to this repo's committed `LEARNINGS.md` (a read-only curated seed):** operator-private skill craft → `~/.claude/skills-overlay/flows/LEARNINGS.md` (create if absent); project-specific facts → the project's `.claude/memory/`; universal craft worth publishing → note it for `/improve-harness` to promote (de-identified) into the seed via PR. Full routing: [`docs/skill-memory.md`](../../../docs/skill-memory.md).

---

## Flow

### Step 1: Load the Registry

Read `testing/flows.json` in the current project root. If it doesn't exist:

> "No flow registry found for this project. The registry is created automatically during spec-test-execute runs. To bootstrap an empty registry, create `testing/flows.json` with: `{"version": 1, "flows": {}}`"

Check the `version` field. If it's not `1`, warn:

> "flows.json has version N, but this skill expects version 1. Proceeding with best effort — some fields may be unexpected."

If the file is malformed JSON or contains merge conflict markers, warn:

> "flows.json is malformed (parse error / merge conflict markers). Please fix the file before using /flows."

### Step 2: Respond to the User's Request

The registry is a flat JSON file. Read it, reason about it, and respond. Common operations:

**Browse:** "show me flows related to X"
- Scan flow names, descriptions, and gotcha descriptions for keyword matches
- Present matching flows with their type, status, last run date, and gotcha count
- For flows with step `notes` or `requires`, show a summary: "N steps have operational notes, N steps have env var requirements, flow has N cross-cutting requirements"
- Show flow-level `requires` if present

**Inspect:** "what does X depend on?"
- Find the flow by ID
- Follow `ref` chains in its steps to find all referenced primitives
- For each referenced primitive, show its status, last run, and active gotchas
- Show step `notes` for any step that has them (these are the operational instructions)
- Show step `requires` for any step that has env var requirements
- **Compute effective requires:** Union of flow `requires` + all step `requires` + transitive requires from referenced primitives. Present as: "This flow requires: [list of all env vars/preconditions]"

**Reverse deps:** "what uses the login flow?"
- Scan ALL flows for steps with `ref: "login"`
- List every journey that references it

**Stale check:** "what needs re-verification?"
- Find flows where the most recent `run_at` is >14 days ago (or the user's threshold)
- Also flag flows with zero runs

**History:** "when was X last tested?"
- Find the flow, show its `runs` array (most recent first)
- Summarize: last N runs with status, runner, date

**Maintain — resolve gotcha:** "mark gotcha N as resolved"
- Read the flow, find the gotcha by index or description match
- Set `still_relevant: false`, update `updated_at` to current ISO 8601 UTC timestamp
- Edit the file using the Edit tool
- Re-read the file to verify valid JSON

**Maintain — deprecate flow:** "deprecate X, replaced by Y"
- Set `status: "deprecated"` and `replaced_by: "Y"` on the flow
- Scan all other flows for steps with `ref: "X"` — warn about each one
- Suggest updating those refs to point to "Y"
- Edit the file, re-read to verify

**Create flow:** "add a new flow for checkout"
- Ask the user for: ID (slug), name, type (primitive/journey), product, description, how_to_verify
- Enforce invariants: primitive must have `product: null`, journey must have non-null `product`
- Check the ID doesn't already exist
- Add the flow with empty steps, runs, gotchas, current timestamp for created_at/updated_at
- Steps can optionally include `notes` (string) and `requires` (string[]) — these are populated over time by spec-test-execute Step 5.5, not typically set at creation time
- Flows can optionally include `requires` (string[]) for cross-cutting env vars — also typically populated by Step 5.5
- Edit the file, re-read to verify

**Audit:** "check registry health"
- Verify all `ref` targets exist and are active
- Check for deprecated flows with active inbound refs
- Find flows with no runs (never verified)
- Flag any invariant violations (step XOR, product constraint, etc.)
- Check for flows with `requires` entries — verify the env var names are valid format (VAR_NAME=value or freeform string)
- Report flows with rich operational knowledge (steps with notes/requires) vs sparse flows (steps with only action/expected)

### Invariants (enforce on every write)

After every edit to `flows.json`, re-read the file and verify:
1. Valid JSON
2. Flow IDs unchanged (no renames)
3. Type unchanged for existing flows
4. Primitives have `product: null`, journeys have non-null `product`
5. Each step has exactly one of `ref` or `action`
6. All `ref` targets exist in `flows` and are active
7. No cycles in `ref` chains (trace transitively for <50 flows)
8. Runs are most-recent-first, max 20
9. `version` field is `1`

---

## Flow Variants (blast-radius extension)

A single flow name often hides multiple meaningful executions. The registry supports
this via `variants` — same flow, different tenant/fixture/env configuration.

**When to add variants:**

- Fallback branches: the happy-path flow hits integration A, but the spec has a
  fallback to B and C. Add variants that force each branch.
- Tenant config divergence: an org with `communication_channels` row vs one without;
  an org with OAuth configured vs one without.
- Fixture diversity: drivers with religious head coverings, single-name drivers,
  non-ASCII names — each forces a different code path in validation/matching.
- Runtime parity: local vs staging vs prod; FileSystem storage vs cloud object storage; with IAM
  propagation wait vs without.

**Shape (extend a flow object):**

```json
{
  "id": "invoice-dispatch",
  "type": "journey",
  "variants": [
    {
      "id": "happy-path",
      "preconditions": ["org=test-org", "communication_channels row present"],
      "forces_branch": "primary"
    },
    {
      "id": "fallback-customer-integrations",
      "preconditions": ["org=test-org-no-comms", "communication_channels row absent"],
      "forces_branch": "customer_integrations fallback"
    }
  ]
}
```

Each variant gets its own run history. A flow with ONE variant is brittle — it
passes in the happy-path org and ships bugs in all others. Surface this during
stale checks: "flow has N variants, only K have recent runs — untested variants:
V1, V2". A past incident hit exactly this: a `send_to_channel` fallback branch was
never exercised because all E2E runs used the one happy-path test org, which had the
primary-branch preconditions — so the fallback shipped broken.

## When NOT to Use

- To create/update flows during test execution — that's spec-test-execute Step 5.5
- To plan tests based on flows — that's spec-test-plan Step 1
- For unit-testable behavior — flows are for non-code-documented E2E behaviors only
