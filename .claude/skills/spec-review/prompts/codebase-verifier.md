# Codebase Verifier

Checks the spec against the actual codebase: do referenced files exist? Are there duplicate implementations? Stale code? Repeat-fix hotspots?

**Agent type:** `Explore` (read-only, codebase search)
**Model:** default (sonnet — search-heavy, not reasoning-heavy)

```
description: "Verify spec against codebase: references, duplicates, stale code"
prompt: |
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
  - **PHANTOM**: Spec references a file/function that doesn't exist.
  - **ORPHAN**: Spec adds new code but old code doing the same thing would remain.

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

  ### Summary
  Phantoms: N | Duplicates: N | Stale: N | Hotspots: N | Orphans: N
  ```
```

**Leaf-agent scope:** you are a leaf agent — do NOT spawn sub-agents or Workflows; do the work inline and return.
