# Infra Reality Auditor (spec-test-plan & spec-test-execute)

Surveys the TRUE state of existing test infrastructure BEFORE any planning or execution. Addresses the parallel-worktree drift problem: a session in `.worktrees/<feature>` has a scoped view and will reinvent fixtures that already exist on main or in sibling worktrees.

**Default stance: extend what exists. Only build new when the audit shows a real gap.**

## How to dispatch

Agent type: `Explore` (read-only codebase search). Model: sonnet. Budget: ~5 minutes.

Pass the agent:
- Spec path (absolute)
- Project root (absolute)
- Spec's "surface area" — 3-6 module names, feature keywords, or file globs the spec touches
- Any sibling worktrees: `ls <project_root>/.worktrees/` if the dir exists

## What the agent does

1. **Existing test infra by surface area.** For each surface area the spec touches:
   - Glob for matching test files (`*.test.ts`, `*.integration.test.ts`, `*.e2e.ts`, `*.spec.ts`)
   - Grep for helpers, fixtures, factories referenced by those tests
   - Note naming conventions and directory structure actually in use
2. **Existing flow registry entries.** Read `testing/flows.json` if present. List flows whose `description`, `steps`, or `gotchas` mention the spec's keywords.
3. **Existing CI slots.** Read `.github/workflows/`. Note which jobs already run tests covering this surface (e.g. `test:integration`, `test:e2e`, deploy-validation).
4. **Existing deploy / staging probes.** Read `testing/config.md` if present. Note staging URL, probes, canary automations already defined.
5. **Cross-worktree check.** If `.worktrees/` exists, for each worktree dir: `ls <worktree>/testing/`, `ls <worktree>/__tests__/`, `git -C <worktree> log --oneline -10` to catch in-flight test infra that `main` hasn't absorbed yet. Flag any tests/fixtures in a worktree that are relevant to this spec and NOT in the current view.

## Output (max 300 words, prose only)

Produce 5 sections. Every claim cites a file path (with line number when relevant).

### EXISTING — use these, don't rebuild
- Helpers, fixtures, factories, test utilities by path.
- Similar tests to use as reference patterns.

### EXISTING — flow registry
- Matching flows by id, plus their `gotchas` and `requires`.

### EXISTING — CI coverage
- Jobs/workflows that already exercise this surface area.

### EXISTING — staging / deploy probes
- Relevant probes + canary automations from `testing/config.md`.

### CROSS-WORKTREE in-flight (if any)
- Test infra in `.worktrees/<name>/` that isn't in the current view. Include path + one-line summary.

### GAPS — what's genuinely missing
- Short list. Only include items the audit confirmed do NOT already exist. **This is the short list the plan should extend onto existing infra.**

## Rules

- Do NOT propose tests — that's the Surface Extractor's and Adversarial Analyzer's job.
- Do NOT speculate. Every EXISTING item must cite a file path.
- Do NOT read spec internals beyond its surface-area map. The agent's job is reality, not intent.
- If nothing exists for a surface area, say "NO EXISTING COVERAGE" under GAPS. Don't pad.
- Report is read-only. No writes. No edits.
