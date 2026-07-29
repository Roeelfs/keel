# Merge tiers, post-merge chain, retire gate

The orchestrator holds every terminal gate — but being the merge bottleneck costs ~10-30 min of idle per round with 3+ lanes. Two tiers, both of which keep the human out of the loop unless the change is genuinely contested.

## Tier A — the lane merges itself

All predicates must hold, and all are machine-checkable:

```
diff matches DOCS_ONLY (docs/, *.md, testing/, .github/, .claude/, .vscode/, .changeset/, .gitignore, .gitattributes, LICENSE)
AND mergeStateStatus = CLEAN
AND every required CI check = SUCCESS or SKIPPED
AND reviewRequests = []  AND no review with state CHANGES_REQUESTED
AND the PR body has no unresolved Depends-on
```

Then the lane runs `gh pr merge <N> --squash --delete-branch` itself and continues the post-merge chain. Safe by construction: a pre-push hook already enforces the path regex and branch protection enforces CLEAN + CI green, so the lane merges only what would have merged anyway — minus the wait.

## Tier B — orchestrator delegates a review-merge agent (default-merge, not default-stop)

Everything else: code, cross-lane impact, security-sensitive surfaces (authz, credentials, isolation), schema migrations, breaking API changes, lockfile churn, unresolved review comments. The lane STOPs after PR-open + CI quote-back; the orchestrator dispatches a review-merge subagent that reads the diff, runs the predicate checks, applies review findings verbatim, and merges.

The agent STOPs and surfaces **only** on: (a) a genuine merge conflict, (b) an open CHANGES_REQUESTED review, (c) test/build evidence the change is broken on its own branch. Merging is not a blocker; conflicts are.

**Tier is predicted upfront** in the mission ("expected merge tier: A — docs-only contract surface"). A diff that outgrows its declared tier is a scope-creep signal: the lane re-classifies and STOPs before merging.

**Branch protection is the structural backstop.** Before recommending parallel lanes on a repo, verify required checks exist:
`gh api repos/<owner>/<repo>/branches/main/protection | jq -r '.required_status_checks.contexts'` — absent means the workflow's assumption (platform enforces CI green before merge) does not hold. Flag it as a setup gap. Two PRs were once merged red because a lane read "no required checks reported" as license to merge.

**Scope audit every returned branch** before merge: run the `scope-auditor` agent — it diffs the branch against fresh `origin/main`, classifies each surplus file as acceptable collateral vs contamination, and on contamination prescribes cherry-picking the one clean commit (never rebase a stale branch, never salvage in place).

**Test-spec check at the gate:** if the lane's test-spec gate RAN, the committed plan file must carry explicit `PASS / FAIL / SKIP / BLOCKED` markers on every tier row. An unmarked plan plus a "run" claim is TDD-during-implementation pretending to be spec-test-execute — surface it. Tiers needing prod-shaped data (Deploy, E2E) either run on staging or are explicitly deferred in the plan file with rationale; silently skipped is a red flag. The gate reads markers, it never infers them from test-runner output.

## Post-merge phase chain — lanes do not stop at merge

Stopping at "PR merged" leaves staging deploys unverified, soak windows unstarted, and dependents un-rebased. In order:

1. **Cascade dependents.** For every lane whose manifest entry carries `stacked_on` or a Depends-on for this PR: rebase it onto the new main, or re-dispatch it as a continuation. A retired lane has no tick and cannot be woken by a file — resume it with a fresh dispatch or a paste-ready prompt.
2. **Staging deploy poll** — if the main push auto-deploys, poll `gh run list --branch main --workflow <name> --limit 1 --json status,conclusion` until complete and quote the conclusion. FAILURE → surface with the logs link; do not retire.
3. **Staging E2E (Tier 3a)** — for work touching handlers, runtime, infra, or a data path: run the flow named in the plan file's Tier 3a row and update the marker with PASS/FAIL/SKIP/BLOCKED + an evidence URL.
4. **Stage-aware env-var marker** — for stage-aware code, run the platform's function-configuration probe against staging and prod and paste the resolved values into the marker row.
5. **Soak issue** — if the change warrants observation, open the soak issue with its window end date **before** retire; the calendar artifact starts the timer.
6. **Final summary + retire.**

**Issue triage on shipping.** When a PR merges, verify its `Closes #N` trailers actually closed, then close subsumed-but-not-auto-closed issues (same surface as the diff) with a comment linking the PR, and file any follow-up that the merge deferred — immediately, with triage labels. "I'll remember it" loses it.

**Cross-worktree branch precondition.** When the orchestrator itself commits from any worktree (a marker or docs PR), before `git checkout -b`:
1. `git -C <wt> rev-parse --abbrev-ref HEAD` is `main` — else `checkout main && pull --ff-only`.
2. `git -C <wt> diff origin/main --stat` is empty BEFORE branching.
3. After staging the edit, re-run it and confirm ONLY the expected file appears; extra files → abort and investigate.
4. **Lane-owned worktrees are off-limits** even when they look clean — the lane may switch them at any moment.
A docs PR once inherited a sibling lane's thousands of lines of WIP this way, was admin-merged, and main had to be reverted.

## Retire gate — the overseer checklist

A lane retires only when ALL hold. Any failure → push back with what is missing; do not sign off.

1. Every test-plan tier marker is PASS or justified-non-PASS **in the committed plan file** (read the file; never infer from test-runner output).
2. Staging E2E (Tier 3a) present and PASS if the work touches infra with a staging environment.
3. Stage-aware code carries an env-var capture marker proving values resolve per stage.
4. Any soak window has a tracked issue opened **before** retire, with check-ins from future sessions.
5. The final summary names: shipped PRs, deferred work with tracked issues, soak state, handoff context.
6. The lane's declared **artifact** exists and is pushed — `git ls-remote --heads origin <branch>` confirms it left the machine.
