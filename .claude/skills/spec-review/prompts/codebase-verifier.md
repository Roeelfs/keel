# Codebase Verifier

Checks the spec against the actual codebase: do referenced files exist? Are there duplicate implementations? Stale code? Repeat-fix hotspots? What is the FULL blast radius of every seam the spec changes?

**Agent type:** `general-purpose` (standing default — the `Explore` type false-stopped/refused tools in 6+ documented runs; do not use it here)
**Model:** default (sonnet — search-heavy, not reasoning-heavy)

```
description: "Verify spec against codebase: references, duplicates, stale code, blast radius"
prompt: |
  EXECUTE THE TOOLS. Do not ask for permission, do not summarize instead of
  searching, do not wait on any other agent — read ONLY the spec and the repo,
  run the checks, return the report.

  You are verifying a spec against the actual codebase. The spec claims certain
  things about the current state — you check whether those claims are true.

  ## Spec File
  Read: {{SPEC_PATH}}

  ## Project Root
  {{PROJECT_ROOT}}

  ## Your Checks

  ### D. Codebase Cross-Reference
  For each system/module the spec touches:
  1. Do the files the spec references actually exist at the stated paths?
  2. Do the functions/classes the spec mentions exist with the described signatures?
  3. Are there callers or dependents the spec doesn't mention that would break?
  4. Does the spec's description of "current state" match what's actually in the code?

  Search broadly — use Glob for file patterns, Grep for function/class names.

  ### E. Single Source of Truth
  For each new thing the spec introduces:
  1. Search for existing implementations of similar functionality.
     Use: Grep for key function names, class names, route patterns from the spec.
  2. Search for stale/dead code doing something similar:
     Grep for TODO, FIXME, HACK, DEPRECATED in files the spec touches.
  3. Check git blame on files the spec modifies:
     ```bash
     git log --oneline --since="2 months ago" -- <file> | wc -l
     ```
     Files with 10+ commits in 2 months are repeat-fix hotspots.

  Flag:
  - **DUPLICATE**: Existing code does the same thing, spec doesn't mention deletion.
  - **STALE**: Dead code in the spec's files that should be cleaned up.
  - **HOTSPOT**: File edited 10+ times in 2 months — might need redesign, not another patch.
    Join the commits to their tickets (grep commit subjects for ticket ids): ≥3 FIX
    commits in the same subsystem = the spec may be adding the Nth patch to a seam
    that needs a premise re-audit — say so explicitly.
  - **PHANTOM**: Spec references a file/function that doesn't exist.
  - **ORPHAN**: Spec adds new code but old code doing the same thing would remain.

  ### F. Blast Radius — consumer census (mandatory for every changed seam)
  The self-reported inventory in a spec ALWAYS runs low. For every seam the spec
  changes, deletes, or renames (a field, column, enum value, tool, table, module,
  event name, env var):
  1. Enumerate ALL readers AND writers repo-wide — use several search strategies
     (exact symbol, string literal, semantic variants), not one grep.
  2. **Deletion completeness:** for anything removed, grep for count/list/snapshot/
     parity/allowlist TESTS asserting the current inventory — each un-updated one
     is a guaranteed CI-red the spec must name.
  3. **Registry fan-out:** a new tool/enum/permission usually must land in MORE
     registries than the spec lists (allowlists, schemas, parity tests, portal
     mirrors). Grep for where EXISTING peers of the new thing are registered and
     diff that set against the spec's list.
  4. **CI-glob conformance:** do the spec's new file paths fall inside the globs
     the CI gates actually run? A test outside every gated glob does not exist.
  5. **Deploy-reachability:** trace how the new surface actually REACHES its
     consumer end-to-end (what populates the row/catalog/config the UI or
     dispatcher reads from — is that step automated, or a manual script no
     workflow runs?).

  ### G. "Reuse shipped primitive X unchanged" — verify at the CODE's granularity
  The most repeated load-bearing miss class. For every claim that the spec will
  reuse/extend/consume an existing primitive unchanged:
  1. Grep X's POLICY/REGISTRY file for an empty/`v1:`-stub default — a primitive
     can be "implemented" yet inert or blocked behind a deferred resolver.
  2. If X's scope/name was recently SPLIT (git log the resolver/guard), verify the
     spec names the RIGHT member of the family; read the guard's own
     "must never share/reach" comments.
  3. Verify the lane/runtime that would ENFORCE or READ X on the spec's path
     actually does (a value can be wired for audit yet ignored at the seam that
     matters).
  4. Open every "per ADR N" / "mirrors <file>:<lines>" citation and READ the
     target — a spec citing an authority that says the OPPOSITE is CRITICAL.
  5. For any `CREATE OR REPLACE` / wrapper over an existing function: resolve the
     LIVE signature (latest baseline + the actual caller's arg list), never the
     historical migration.
  6. For any "set field=X to change behavior" mechanism: verify (a) no
     heal/normalize/reconcile wrapper reverts the field, (b) an op/effector exists
     to REALIZE the new value, (c) the sibling modules that act on the entity
     actually READ the changed field.

  ## Output Format

  ```
  ## Codebase Verification Report

  ### References: [N VALID / N PHANTOM]
  - ✓ path/to/file.ts:functionName — exists
  - ✗ path/to/missing.ts — PHANTOM (spec section 4.2 references this)
  ...

  ### Duplicates & Stale Code: [CLEAN / N ISSUES]
  - [DUPLICATE] spec adds X, but Y already does this at path/to/existing.ts:42
  - [STALE] path/to/file.ts has TODO on line 15: "remove after migration"
  - [HOTSPOT] path/to/views.py — 14 commits in 2 months, last 5 are bug fixes
  - [ORPHAN] spec creates new_handler.ts but old_handler.ts still exists with no deletion plan
  ...

  ### Dependency Impact: [SAFE / N RISKS]
  - Changing X would affect [list of callers found via grep]
  ...

  ### Blast Radius: [COMPLETE / N UNDER-SCOPED SEAMS]
  - <seam>: spec names N consumers, census found M — missing: [list]
  - Deletion completeness: [list of inventory tests that must change]
  - Registry fan-out: [registries missing from the spec's list]
  - CI-glob / deploy-reachability: [findings]
  ...

  ### Reuse-Claim Verification: [ALL HOLD / N BROKEN]
  - <claim>: [HOLDS / BROKEN — stub default / wrong scope member /
    enforcement lane doesn't read it / citation says the opposite / dead
    overload / inert desired-state] with file:line evidence
  ...

  ### Summary
  Phantoms: N | Duplicates: N | Stale: N | Hotspots: N | Orphans: N |
  Under-scoped seams: N | Broken reuse claims: N
  ```
```

**Leaf-agent scope:** you are a leaf agent — do NOT spawn sub-agents or Workflows; do the work inline and return.
