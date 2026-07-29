# Loop directive — harness-managed via `/loop`

The lifecycle of an interactive lane is driven by Claude Code's `/loop` command: the harness fires the continuation at a fixed cadence, the session works between ticks, and the initial prompt stays short. (Headless lanes need none of this — they are chunked per lifecycle step and resume from the branch.)

**Single flow, no skipping. No "if applicable" twice.** The test-spec decision is ONE binding choice gating plan AND execute as a unit; spec-test-execute is mandatory when the gate ran — TDD-during-implementation is not a substitute.

## Paste 2 — start the loop

After the initial prompt (`prompts/session-template.md`) is accepted, paste this verbatim. Tune the cadence: `5m` default, `10m` for steady state with longer per-iteration work, `15m` for long implementation phases, never below `3m`.

```
/loop 5m Advance one canonical-lifecycle step (the orchestrator skill's references/lifecycle.md owns the lifecycle; references/merge-and-retire.md owns merge tiers, the post-merge chain, and the retire gate). BEFORE each tick: (1) read the program state file named in your mission (~/.claude/orchestrator/programs/<slug>.state.md) for sibling lanes, their owned paths, and the gates the orchestrator holds; (2) depends-on PR? `gh pr view <N> --json mergedAt,mergeStateStatus` — if unmerged do NOT park: stack your branch on it or do in-scope prep; (3) about to edit outside your declared scope? run `git log --since='2h' --all -- <path>` first and surface to the orchestrator instead of editing if a sibling just touched it; (4) `git push` after every commit so the orchestrator's surveys see your state within one tick. Hard rules: when the test-spec gate RAN, write PASS/FAIL/SKIP/BLOCKED markers into the plan file before opening the PR (test-runner green is not a tier marker; prod-data tiers run on staging or are deferred in the plan file with rationale). Apply ALL reviewer findings verbatim. PR body: `Closes #N` + the test-spec rationale + `Depends on #M` if any. Docs-only commits (docs/, *.md, testing/, .github/, .claude/, .vscode/) skip the verify gate via the pre-push hook. MERGE GATE: Tier A — docs-only, CLEAN, every required check SUCCESS or SKIPPED, no review comments, no Depends-on pending, and Tier A was declared in your mission — run `gh pr merge <N> --squash --delete-branch` yourself and continue the post-merge chain. Tier B — everything else: STOP after PR-open, quote `gh pr checks <N>` back, and let the orchestrator's review-merge agent take it. POST-MERGE CHAIN, in order, do not retire early: (i) staging deploy poll — `gh run list --branch main --workflow <name> --limit 1 --json status,conclusion`, quote the conclusion, surface FAILURE with the logs link; (ii) staging E2E Tier 3a marker with PASS + evidence URL if the work touches handlers/runtime/infra/a data path; (iii) stage-aware env-var marker if applicable; (iv) soak issue opened if the change warrants observation; (v) final summary naming shipped PRs, deferred work with tracked issues, and the artifact you produced. CANCEL the loop on: user input genuinely needed; a hard blocker surviving 2 fix attempts; scope creep beyond the agreed PR; or a STALL — 3 consecutive ticks with an identical fingerprint (HEAD sha + PR mergeStateStatus) and no in-scope prep work left. On cancel, append one line to the program's .events.jsonl — what remains plus the last verified fact — then stop.
```

## Why this shape

**State-awareness pre-tick.** Lanes used to rebase blind, edit shared surfaces without checking sibling activity, and miss cross-lane dependencies. The four BEFORE-tick checks let lanes self-coordinate without the orchestrator intervening at every collision: the program state file is the cheap path and covers most cases; `gh`/`git` are the escalation paths when it is ambiguous. Pushing after every commit closes the loop so the orchestrator's survey sees the lane within one tick.

**Brevity.** The orchestrator skill's CORE and `references/` are the source of truth; the directive points at them. What stays inline are the lessons no skill can recover if forgotten in the moment: tier markers, tier classification, the post-merge chain, and the cancel conditions.

**Two tiers, not three.** A blanket "never merge" rule correctly stopped lanes merging red-CI code but made the orchestrator a bottleneck on docs-only PRs (one sat ~14 min idle awaiting a manual merge). Tier A is safe by construction — a pre-push hook already enforces the path regex and branch protection enforces CLEAN + CI. Everything else goes to a delegated review-merge agent, which stops only on a conflict, an open CHANGES_REQUESTED review, or a demonstrably broken branch.

**Post-merge chain.** Lanes used to retire at "PR merged", leaving staging deploys unverified, Tier 3a markers blank, and soak windows unstarted. The chain runs on the same ticks; the retire gate then has evidence to check instead of aspirations.

**One binding gate, not two.** With `spec-test-plan if applicable` AND `spec-test-execute if applicable` as independent gates, a lane could write the plan, write tests TDD-style during implementation, and have the merge gate accept "tests passing" as proof the plan executed. A data-path PR shipped exactly that way — a committed test plan with no tier markers and E2E never executed.

**Markers, never inference.** The gate reads explicit `PASS / FAIL / SKIP / BLOCKED` from the committed plan file. Not build-green, not "the tests obviously cover this". No marker on the row means the tier did not run.

## Cancel conditions — narrow by design

1. **User input genuinely needed** — real ambiguity no reasonable default resolves. Not stylistic preferences, not "should I commit?".
2. **Hard blocker** — a test failure resisting 2 fix attempts, an outage, missing credentials, a BLOCKED tier with no fallback. Unrelated doc/config/tooling drift outside the lane's write scope is not a blocker: record it and keep implementing.
3. **Scope creep** — the work would grow past the agreed PR (e.g. a CRITICAL finding forces touching another lane's surface).
4. **Stall** — 3 consecutive ticks with the same HEAD sha and the same PR `mergeStateStatus`, and nothing left in scope but waiting. A PR once sat ~7h ticking every 5 min to re-emit "still waiting for operator merge".

**Stall vs legitimate wait.** A lane correctly waiting on a dependency or a merge should CANCEL and surface, not keep ticking — the orchestrator resumes it with a fresh dispatch when the dependency lands. Burning ticks during a legitimate wait is the exact failure this guard exists to stop.

## Codex variant — single-paste, no harness

Codex CLI has no `/loop`. Embed the directive at the **end** of the initial prompt as one trailing block; the session self-paces and the cancel conditions become its own discipline:

```
SELF-PACED LIFECYCLE: After each step (spec → review → fixes → test-spec gate → impl-plan → plan-review → implementation → spec-test-execute → merge gate → PR → CI poll), commit your progress and continue to the next until the PR is open and CI/mergeability is quoted back. The test-spec gate is ONE binding decision (RUN both / SKIP both per the rubric in the orchestrator skill). When RAN, spec-test-execute is MANDATORY — write PASS/FAIL/SKIP/BLOCKED markers into the plan file before the PR; test-runner green is not a tier marker. Do NOT run `gh pr merge`; the orchestrator owns the merge gate. Do not treat unrelated root docs/config/tooling drift as a blocker; block only on overlapping uncommitted work inside your lane's write scope. Parallel migration-number collisions are integration work: document them in the PR body, never renumber speculatively while sibling lanes are moving. STOP and surface only when (1) input is genuinely needed, (2) a hard blocker survives 2 fix attempts, (3) scope creeps beyond the agreed PR. Never stop for stylistic decisions or "should I commit?".
```

A silent Codex worker is re-triggered by a new `codex exec` invocation, never by a loop.
