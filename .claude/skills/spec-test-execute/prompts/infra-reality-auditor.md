# Infra Reality Auditor (spec-test-execute)

Runs BEFORE the prerequisite gate. Surveys the TRUE state of existing test infra and recent test-plan output across the repo — including sibling worktrees — so execution extends what exists instead of duplicating it.

**Default stance: extend and re-run what already exists. Only scaffold new infra when the audit confirms a real gap.**

## How to dispatch

Agent type: `Explore` (read-only). Model: sonnet. Budget: ~5 minutes.

Pass the agent:
- Plan path (absolute)
- Spec path (absolute, from the plan's header)
- Project root (absolute)
- Surface-area keywords extracted from the plan's tier tables
- Sibling worktrees: `ls <project_root>/.worktrees/ 2>/dev/null`

## What the agent does

1. **Existing tests for every tier row.** For each row in the plan's Tier 1–3 tables, search the repo for a matching test. Report: which test rows already have an implementation file, which don't.
2. **Existing fixtures/factories/helpers** that the plan's prerequisites list (or should list). Cite file paths.
3. **Existing flow registry entries** matching the plan's surface. Extract relevant `gotchas`, `requires`, and step `notes`.
4. **Existing staging probes / canary automations** in `testing/config.md` that the plan can reuse verbatim.
5. **Existing CI coverage.** Which `.github/workflows/` jobs already run tests for this surface?
6. **Cross-worktree in-flight test work.** For each dir in `.worktrees/`: list new/modified test files, new fixtures, new helpers (use `git -C <worktree> status --short` and `git -C <worktree> diff --name-only main`). Flag tests that are relevant to this plan and NOT visible in the current view.
7. **Recent main-branch test changes** (last 30 days) that touch this surface: `git log --since="30 days ago" --name-only -- <glob>`. Catch tests added between plan generation and execution.

## Output (max 400 words)

### ALREADY IMPLEMENTED — re-run, don't rewrite
- Plan rows that map to existing test files. Cite plan row id + actual test file path.

### FIXTURES/HELPERS — reuse these
- With path citations.

### FLOW REGISTRY — gotchas that apply
- Flow id + gotcha text + where in execution it kicks in.

### CI — already covered jobs
- Which workflow jobs already exercise this surface.

### STAGING/DEPLOY — reusable probes
- Probe names + what they verify.

### CROSS-WORKTREE — in-flight work not in this view
- Worktree path + test files modified + one-line summary. FLAG PROMINENTLY — the coordinator must decide whether to wait for / rebase / coordinate before executing.

### RECENT MAIN — changed since plan was written
- Test files touched in the last 30 days that affect this plan.

### GAPS — genuinely new infra needed
- Short list. These are the only places execution should author new tests.

## Rules

- Read-only. No edits. No writes.
- Every EXISTING claim cites a file path.
- If cross-worktree work exists, the coordinator must gate execution on a human decision — do NOT proceed silently.
- Do not propose new tests. Step 3 handles that.
- If nothing exists in a category, say so in one line. Don't pad.
