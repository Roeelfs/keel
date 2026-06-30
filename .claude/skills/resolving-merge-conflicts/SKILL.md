---
name: resolving-merge-conflicts
description: "Use when you need to resolve an in-progress git merge/rebase conflict."
---

1. **See the current state** of the merge/rebase. Check git history, and the conflicting files.

2. **Find the primary sources** for each conflict. Understand deeply why each change was made, and what the original intent was. Read the commit messages, check the PRs, check original issues/tickets.

3. **Resolve each hunk.** Preserve both intents where possible. Where incompatible, pick the one matching the merge's stated goal and note the trade-off. Do **not** invent new behaviour. Always resolve; never `--abort`.

4. Run the project's **automated checks** — your project's verify gate (the command your project documents), NOT a bare `npx tsc`/`vitest` (those can bypass any locking wrapper and miss CI-only steps). Fix anything the merge broke.

5. **Finish the merge/rebase.** Stage everything and commit, following your project's commit-trailer conventions (if any). If rebasing, continue until all commits are rebased.

## Project guardrails (override the generic flow above)

- **NEVER rebase a stale branch onto a moved `origin/main`** — it manufactures N-way conflicts (a contamination class seen in a past incident). `git fetch origin` first.
- **A *contaminated* branch is not a conflict to resolve — it is closed.** If a scope audit (`git diff --name-status origin/main HEAD`) shows files you never touched, do NOT salvage by resolving conflicts (salvage failed every time it was attempted). Re-integrate ONLY by cherry-picking the one clean commit onto fresh `origin/main`.
- **To squash, reset to the merge-base** (`git reset --soft $(git merge-base origin/main HEAD)`), never to the `origin/main` tip (that collapses newer main work into your commit as deletions).
