# Session prompt template

Two paste actions to spawn a lane: the initial prompt (goal + setup), then `/loop ...` to start the harness-driven lifecycle.

---

## Paste 1 — initial prompt

```
You are starting a new worktree on the [PROJECT_NAME] repo. Goal: [GOAL_ONE_LINER]. Issue #[N].

Setup:
- `cd [REPO_ROOT] && git fetch origin && git worktree add ../[WORKTREE_SLUG] -b [BRANCH_NAME] origin/main`
- `cd ../[WORKTREE_SLUG]` and install deps if prompted
- Lifecycle: [spec is finalized at vX.X, light plan + implementation in place | spec needs writing, start at docs/specs/active/<date>-<slug>.md]

Background — read these first to skip rediscovery:
- [memory ref 1, e.g. ~/.claude/projects/<slug>/memory/project_X.md]
- [memory ref 2]
- Issue #[N] — `gh issue view [N]`

Scope (and owned paths the orchestrator will register in the program manifest):
- [BULLET 1] — [path/glob]
- [BULLET 2] — [path/glob]
- [BULLET 3] — [path/glob]

Hard constraints:
- DO NOT touch [PATH_OWNED_BY_OTHER_SESSION_1] — [SESSION_NAME_1] owns it
- DO NOT touch [PATH_OWNED_BY_OTHER_SESSION_2] — [SESSION_NAME_2] owns it
- DO NOT bump `package-lock.json` (or your lockfile) unless required for this fix; lockfile churn serializes lanes
- Conventional commits with `Session-Id: $CLAUDE_SESSION_ID` (UNQUOTED `<<EOF` heredoc so the SID expands — single-quoted `<<'EOF'` captures the literal placeholder)
- Run `[PROJECT_VERIFY_COMMAND]` before pushing. A docs-only diff *may* be skipped by the pre-push hook — **do not rely on it, and never assume a docs-only change can bypass the PR flow entirely** (branch protection is a separate gate from the verify hook and will still refuse a direct push to the base branch). **Rebase onto the base branch before pushing:** a docs-only classifier that diffs `<base>..HEAD` rather than the merge-base inherits *other* lanes' non-docs files, so a branch that is merely BEHIND is misclassified as a code push and the gate fires with a message about your own change. If a push is refused, print the hook's own file list and compare it to your diff before theorising — twice-measured, the refusal was about a sibling lane's file, not yours.
- PR title: `[PR_TITLE]`
- PR body MUST include `Closes #[N]`, tick the relevant issue checkbox, and document the test-spec decision (run or skip + reason). If your work depends on another lane's PR landing first, add `Depends on #[M]` to the body.
- **Expected merge tier:** `[A | B]` per the orchestrator skill's `references/merge-and-retire.md` — declared upfront so post-PR behavior is unambiguous. Tier A (docs-only, CLEAN, CI green or skipped, no review comments, no Depends-on pending) → this session runs `gh pr merge --squash --delete-branch` itself and continues the post-merge chain. Tier B (everything else) → STOP after PR-open with `gh pr checks <N>` quoted back; the orchestrator's review-merge agent takes it. If the diff outgrows the declared tier mid-implementation, STOP and re-classify.
- **The artifact this lane is graded on:** `[branch + PR | the named file | the migrated rows]`. A completion claim without it is not done.
- **Completion discipline (no stall — MANDATORY):** After pushing, open the PR and STOP immediately. Do NOT poll CI (`gh pr checks`, `gh run watch`, `Monitor`, `sleep`-then-check). The orchestrator watches CI — you do not need to. If your verify gate times out (e.g. on a machine-global build lock — prints "LOCK TIMEOUT" and exits 1), push your committed work, open the PR (mark `[WIP]` in the title if verify is incomplete), and report completion immediately. Your final message must include: PR URL, branch, changed files, what you verified and how, what (if anything) you could not verify and why.

State-aware lifecycle: the /loop directive (Paste 2) runs state-aware checks before every tick — reading the program state file `~/.claude/orchestrator/programs/[PROGRAM_SLUG].state.md` for sibling lanes, polling depends-on PRs via `gh pr view`, and surfacing collisions to the orchestrator instead of editing files a sibling just touched. `git push` after every commit so the orchestrator's surveys catch your state.

Post-merge phase chain (sessions don't retire at merge): staging deploy poll (`gh run list --branch main --workflow <name> --limit 1`) → staging E2E (Tier 3a marker with PASS + evidence URL) → stage-aware env-var marker if applicable → soak issue if observation-warranted → final summary + retire. The /loop drives these as subsequent ticks.

Begin by reading the background. The lifecycle continuation fires via /loop after this prompt — see Paste 2.
```

## Paste 2 — start the loop

After Paste 1 is accepted, paste the `/loop` directive **verbatim from `prompts/loop-directive.md` §Paste 2** — that file is the single source of truth for the directive text; never re-type it here, the two copies drift. Default cadence `5m`; tuning notes are in the same file.

---

## Filling guide

### `[GOAL_ONE_LINER]`

Critical for the `claude-sessions` skill PURPOSE extraction. Lead with `ship X` / `implement X` / `fix X` / `build X` so the regex captures cleanly. Examples:
- `ship Spec D Stage 5 — drill-down + StatGroup + motion lib swap`
- `implement observability Phase 1 P0 wire — hotfix-style standalone PR`
- `fix data-path restoration — restore page cards seed, dedupe filter bar, diagnose aggregate 403s`

### Background — read first

Always include 2-4 memory references the session should read before any work. This skips ~80% of exploration. Look in `~/.claude/projects/<slug>/memory/` for the relevant `project_*` and `reference_*` files. Also link the issue (`gh issue view <N>`).

### `[WORKTREE_SLUG]` / `[BRANCH_NAME]`

Match the goal: `<proj>-spec-d-stage-5` / `feat/spec-d-stage-5-drilldown-statgroup-motion`, `<proj>-data-restoration` / `fix/data-restoration`.

### Hard constraints — DO-NOT-TOUCH list

Before generating, run the conflict-map analysis from the orchestrator SKILL.md §"Before spawning: conflict map". List every active session and its surface; explicitly forbid those paths in the new prompt. Example for a front-end lane while backend lanes run:

```
- DO NOT touch `<backend dir>/*`, `<customers/config dir>/*` — backend cleanup / observability sessions own those
- DO NOT touch `<front-end dir>/.stylelintrc*` — a sibling lane sealed it
- DO NOT touch [other Stage]'s files — sister front-end lane
```

### `[PROJECT_VERIFY_COMMAND]`

Your project's verify gate — the command your project documents (the full lint + typecheck/compile + test + migration/schema-check pipeline, e.g. whatever your repo's CLAUDE.md/AGENTS.md specifies, sometimes with a `--full` flavor for lockfile/multi-workspace changes). For other projects, the project's CLAUDE.md should specify.

### Loop cadence

Default `5m` (minimizes stale time when an agent finishes mid-step). `10m` for steady-state with longer per-iteration work (slow Codex turnarounds, large-task implementation). `15m` for long-running implementation phases where each tick is a meaningful small commit. Avoid `<3m` — fires while tools are running, creates noise.

### Owned paths declaration

Paste 1's "Scope" bullets should include the file paths/globs the lane will write to. After acknowledging Paste 1, the orchestrator registers those paths on this lane's entry in the program manifest (`claims.paths`). Sibling lanes consulting state see this lane's claimed surface and can avoid collisions. Two patterns:

- **Owned**: `<dir>/src/lib/feature-module.ts` — full ownership, the lane will edit
- **Read-only ref**: `<dir>/src/lib/authorization.ts` — the lane consumes this surface but does not edit it (note in Hard constraints with the lane that owns it)

If a session can't enumerate paths upfront (e.g. exploratory spec phase), put `["docs/specs/active/<date>-<slug>-design.md"]` initially and update after the spec lands.

### Depends-on registration

If your lane consumes a primitive from another lane's pending PR, add `Depends on #[M]` to the PR body (and the issue body). The /loop directive's BEFORE-tick check polls `gh pr view <M> --json mergedAt` and pauses your lane if M is unmerged — prevents rebase-on-stale-state. Multiple deps: `Depends on #126, #128`.
