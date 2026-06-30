# Loop directive — harness-managed via `/loop`

The lifecycle is driven by Claude Code's `/loop` slash command. The harness fires the continuation at a fixed cadence; the session works between ticks. The initial prompt stays short.

**Single flow, no skipping. No "if applicable" twice.** The test-spec decision is ONE binding choice that gates plan AND execute as a unit. spec-test-execute is mandatory when the gate ran — TDD-during-implementation is not a substitute.

## Spawn flow — two paste actions

### Paste 1 — initial prompt
Just the goal, scope, constraints, memory refs, worktree setup. See `prompts/session-template.md`.

### Paste 2 — start the loop
After Paste 1 is accepted, paste this slash command verbatim. Tune the cadence (`5m` default — minimizes stale time when an agent finishes mid-step and waits for the next loop tick; `10m` for steady-state with longer per-iteration work; `15m` for long-running implementation phases; minimum `3m`):

```
/loop 5m Advance one canonical-lifecycle step (orchestrator §2a owns lifecycle, §11a owns merge tiers, §11b owns post-merge phases, §11 owns retire gate). **MAILBOX CHECK FIRST each tick:** run `~/.claude/skills/orchestrator/scripts/check-wakeup.sh $CLAUDE_SESSION_ID` — if it prints `FRESH_WAKEUP`, the orchestrator left you a message; READ the wakeup JSON, treat its `message` field as the highest-priority instruction for this tick, mark it seen (script does this), and DROP whatever you were planning to do next. Fresh wakeups override the normal /loop plan. **Stall guard SECOND:** run `~/.claude/skills/orchestrator/scripts/stall-check.sh $CLAUDE_SESSION_ID <branch> <pr-number-or-empty>` — if exit 1 (3 consecutive identical fingerprints: same HEAD, same PR mergeStateStatus, same wakeup hash), CANCEL the loop with a one-line stall summary to operator. Do NOT continue ticking on a stalled lane. State-aware THIRD: (1) consult orchestrator state — `ls -t ~/.claude/projects/*/orchestrator-runs/last-state.json | head -1 | xargs cat` — to see live sibling lanes, their lifecycle steps, owned paths, open PRs, security issues, WIP cap; (2) depends-on PR? `gh pr view <N> --json mergedAt,mergeStateStatus` — pause if unmerged; (3) editing files outside your declared scope? `git log --since='2h' --all -- <path>` first — surface to orchestrator if a sibling lane just touched them, do NOT edit; (4) `git push` after every commit so the orchestrator's surveys catch your state within one tick. Hard rules: when test-spec gate RAN, write PASS/FAIL/SKIP/BLOCKED markers in the plan file before opening PR (test-runner green ≠ tier marker; prod-data tiers run on staging or are deferred with rationale). Apply ALL reviewer findings verbatim. PR body: `Closes #N` + test-spec rationale + `Depends on #M` if any. **Docs-only commits never block:** files only under `docs/`, `*.md`, `testing/`, `.github/`, `.claude/`, `.vscode/` skip verify via the pre-push hook; `git commit && git push origin main` directly. **Tier-aware merge gate (§11a):** after PR is CLEAN + all CI green + no review comments + no Depends-on pending, classify the PR. **Tier A (docs-only, declared in Paste 1):** run `gh pr merge <N> --squash --delete-branch` yourself, then run `~/.claude/skills/orchestrator/scripts/cascade-unblock.sh <closed-issue-N>` if the PR closed an issue, then continue post-merge phases (§11b). **Tier B (single-lane code, label `auto-merge-ok` on issue):** STOP, orchestrator merges, cascade fires from there. **Tier C (cross-lane / security / schema / breaking / unresolved review):** STOP, operator merges. Do NOT run `gh pr merge` for Tier B or C. **Post-merge phase chain (§11b, run sequentially, do NOT retire early):** (i) cascade-unblock fired; (ii) staging deploy poll via `gh run list --branch main --workflow <name> --limit 1 --json status,conclusion`, quote conclusion; (iii) staging E2E (Tier 3a) if work touches handlers/runtime/infra/data path — update tier marker with PASS+evidence URL; (iv) stage-aware env-var marker if applicable (function-configuration proof per stage); (v) soak issue opened with `soak` + `soak:<feature>` labels if observation-warranted; (vi) final summary, retire. **Cancel loop on:** (1) user input genuinely needed; (2) hard blocker after 2 fix attempts; (3) scope creep beyond agreed PR; (4) **stall — 3 consecutive ticks with identical fingerprint AND no actionable prep work left in scope** (PR awaiting operator merge with all post-merge prep done = stall, surface and stop).
```

## Why this shape

**Mailbox-first wakeup propagation.** Earlier the wakeup-file pattern was effectively pull-based at the /loop cadence — orchestrator wrote a wakeup, session saw it on the next tick (up to 5 min lag), and even then might miss it if mid-step. The directive now requires `check-wakeup.sh` as the FIRST action of every tick. Fresh wakeups (mtime > .last-seen marker) are highest-priority instructions — the model drops the planned tick, processes the wakeup, marks it consumed, then continues. Idempotent: subsequent ticks see the .last-seen marker and skip silently. Cost: one fast filesystem stat per tick. Benefit: wakeup-to-action drops from ~5 min p50 to ~tick-cadence p50 (1-5 min depending on /loop interval). A past multi-PR cycle had ~30+ min of wakeup-propagation lag that this design eliminates.

**State-awareness pre-tick.** Earlier versions treated each session as isolated — sessions would rebase blind, edit shared-surface files without checking sibling activity, and miss cross-lane dependencies (e.g. a lane expecting another to land first). The 4 BEFORE-each-tick checks consult orchestrator state + gh + git so sessions self-coordinate without needing the orchestrator to manually intervene at every collision. The `last-state.json` consult is the cheap path (covers 90% of cases); gh/git are escalation paths when ambiguous. Sessions push after every commit so the orchestrator's 5-min surveys see their state within one tick — closes the loop.

**Brevity.** Earlier directive enumerated lifecycle/test-spec-gate/merge-gate detail inline, ~1660 chars. Sections in the orchestrator skill (§2a, §11, §11a, §11b) are the source of truth; the directive references them and trusts the session to read. The hard rules that ARE inline (PASS/FAIL/SKIP/BLOCKED markers, tier classification, post-merge phase chain) are the lessons learned that no skill can recover if forgotten in the moment.

**Tier-aware merge gate.** Earlier rule was blanket "STOP for orchestrator merge — do NOT run `gh pr merge` unless explicitly told." That correctly prevented lanes from merging red-CI code PRs (a past incident merged two red-CI PRs) but made the orchestrator a manual bottleneck on safe docs-only merges (a docs PR once sat ~14 min idle waiting for a manual merge). Tier A (docs-only declared in Paste 1, all CI green, no review comments, no Depends-on pending) is now session-merged. Tier B/C still STOP — operator/orchestrator owns the merge gate for code, security, schema, breaking, cross-lane.

**Post-merge phase chain.** Sessions used to retire at "PR merged" — leaving staging deploys unverified, Tier 3a markers blank, and soak windows unstarted. The new chain (§11b: cascade-unblock → staging deploy poll → Tier 3a E2E → stage-aware env-var marker → soak issue → final summary) uses the same /loop ticks; sessions stay alive past merge until verification is real and downstream lanes are cascaded. The retire gate (§11) now has actual evidence to check, not aspirations.

**One binding gate, not two.** Earlier versions had `spec-test-plan if applicable` AND `spec-test-execute if applicable` as independent gates. Sessions could write the plan, write tests TDD-style during implementation, and have the merge gate accept "tests passing" as proof the plan executed. A past data-path PR shipped this way — committed test plan with no tier markers, Deploy + E2E never executed. Single binding decision closes the loophole.

**Marker-based merge gate, no inference.** The merge gate reads explicit `PASS / FAIL / SKIP / BLOCKED` markers from the committed plan file. It does not infer them from test-runner output, build green, or "the tests obviously cover this". If the marker isn't on the row, the tier didn't run.

**Prod-data tiers are explicit.** Some tiers need staging or production-shaped data (Deploy, E2E against rendered output). Two acceptable resolutions: run on staging, or defer in the plan file with rationale (e.g. "Phase 10: operator-driven apply held until user authorization per spec §6"). Silently skipping is not allowed.

## Cancel conditions

The loop cancels under four conditions, narrow by design:

1. **User input genuinely needed** — real ambiguity that no reasonable default resolves. NOT stylistic preferences, NOT "should I commit?" — proceed with project conventions.
2. **Hard blocker** — test failure resisting 2 fix attempts; infra outage; missing credentials; test-plan tier BLOCKED with no fallback. Unrelated doc/config/tooling drift outside the lane's write scope is not a hard blocker; record it and keep implementing from the lane worktree.
3. **Scope creep** — work would grow beyond the agreed PR scope (e.g. a CRITICAL spec finding forces touching another team's surface).
4. **Stall** — 3 consecutive ticks with identical fingerprint AND no actionable prep work left in scope. The fingerprint includes HEAD sha + PR mergeStateStatus + wakeup-file hash; if all three match across 3 ticks AND the model has nothing left to do besides wait, the lane is stalled — cancel and surface a one-line summary. This catches the failure mode seen in a past incident: a PR opened CLEAN, then sat ~7h ticking every 5min producing the same "still waiting for operator merge" response dozens of times. The `~/.claude/skills/orchestrator/scripts/stall-check.sh` helper does the comparison deterministically; run it FIRST each tick and exit on stall before doing more work.

When the session cancels, it summarizes state, names the trigger, surfaces the question.

**Stall vs. legitimate wait.** A lane that's correctly waiting on a Depends-on PR or operator merge IS waiting — but the right "wait" is to cancel the loop and surface, not to keep ticking. Sessions don't burn cycles waiting; they cancel and resume on operator signal (or on the cascade-unblock wakeup file the orchestrator writes when the dependency lands). Burning ticks during legitimate waits is exactly the failure mode this guard exists to stop.

## Tuning the cadence

- **5m** — **default**. Minimizes stale time when an agent finishes mid-step and waits for the next loop tick. Right for spec-review applying findings, plan-review iteration, mid-implementation with frequent commits, and most general lifecycle phases.
- **10m** — steady-state with longer per-iteration work (long unit-test runs, large-task implementation where commits land every 8-15 min, slow Codex turnarounds)
- **15m** — long-running implementation phases where each tick is a meaningful small commit. Avoid for spec/review phases — you'll wait too long between iterations.
- **Don't go below 3m** — agents and tool calls take time; firing the loop while work is in progress creates noise.

Cadence change rationale: default was 10m; switched to 5m because 10m introduced too much idle time when an agent finished a tool call or commit and was waiting for the next directive tick to know what to do next. 5m halves that idle without hitting the 3m noise floor.

## Why `/loop` instead of an embedded directive

Earlier iterations baked the lifecycle into the initial prompt as a long "## Loop directive" paragraph. Failure modes:

- Sessions occasionally "forgot" they were in a loop after long bash / agent dispatches
- The directive paragraph inflated initial prompts to ~10KB (most of it lifecycle prose the harness should own)
- Cadence was implicit ("keep going"), making "stalled" indistinguishable from "between steps"
- A session stalled at the async-CI boundary because the embedded directive never fired again after a tool returned

`/loop` moves cadence into the harness — the right place for it. The cancel directive stays in the loop prompt because that's session-side discipline (when to stop), not harness mechanics (how often to fire).

## Codex variant — single-paste, no harness

Codex CLI has no `/loop` slash command. Embed the directive at the **end** of the initial prompt as a single trailing block. The session self-paces; the cancel conditions become its own discipline:

```
SELF-PACED LIFECYCLE: After each step (spec → review → fixes → test-spec gate → impl-plan → plan-review → implementation → spec-test-execute → merge gate → PR → CI poll), commit your progress and continue to the next until the PR is open and CI/mergeability is quoted back. Test-spec gate is ONE binding decision (RUN both / SKIP both per rubric in the orchestrator skill). When RAN, spec-test-execute is MANDATORY — write PASS/FAIL/SKIP/BLOCKED markers in the plan file before PR; test-runner green ≠ tier marker. Do NOT run `gh pr merge`; orchestrator/operator owns the merge gate unless the current user explicitly tells this session to merge. Do not treat unrelated root docs/config/testing/tooling drift as a blocker; block only on overlapping uncommitted implementation files/migrations/API/mobile files/tests in your lane's write scope. Parallel migration number collisions are integration work: document them in the PR body and do not renumber speculatively while sibling lanes are still moving. STOP and surface to user only when: (1) input genuinely needed, (2) hard blocker after 2 fix attempts, (3) scope creep beyond agreed PR. Do not stop for stylistic decisions or "should I commit?" — proceed with project conventions.
```

Cadence is the worker's own — Codex does not get prompted again automatically. If the session goes silent, the orchestrator must re-trigger via a new `codex exec` invocation, not via `/loop`.
