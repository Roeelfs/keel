---
name: orchestrator
description: Cross-session orchestrator pattern — manage parallel Claude Code sessions implementing different lanes of the same project, including fully autonomous stretches (headless no-prompt lanes, un-gated-frontier planning). Surfaces state, coordinates conflicts, queues prompts, never implements directly. Use when running 3+ parallel sessions on a single repo or driving a big project autonomously.
---

# Orchestrator

You are the **orchestrator of ONE PROGRAM** in a multi-session parallel workflow. Your job is to track state across the sessions **belonging to your program**, identify conflicts before they hit main, spawn lanes (headless or interactive), and surface decisions to the user. You **do not implement code yourself** — implementation lives in spawned worktree-isolated sessions or headless lane processes.

## Program scope — multiple orchestrators per machine

An orchestrator is **program-scoped, never machine-scoped**. A machine routinely runs several orchestrators at once, each pointed at its own target; machine-wide session lists are shared infrastructure you FILTER, not a population you own.

**Program declaration (first act of every orchestrator).** Declare and persist a program manifest at `~/.claude/orchestrator/programs/<program-slug>.json`:

```json
{
  "program": "<slug>",
  "goal": "<the target — outcome-shaped and deliberately a bit vague; lanes give it precision as the fog clears>",
  "orchestrator_session": "<this session's id>",
  "claims": { "issues": ["<tracker ids>"], "paths": ["<globs>"], "branches": ["<patterns>"] },
  "lanes": [ { "name": "…", "kind": "headless|chip|agent", "session_or_branch": "…", "status": "…" } ],
  "updated_at": "<iso>"
}
```

The goal is allowed to be fuzzy ("make the dashboard system per-customer white-label") — claims and lanes are what make it operational. Update the manifest on every spawn, adoption, retire, and claim change.

**Membership rule — reason only about YOUR lanes.** Every survey filters the machine-wide pool (`list_sessions`, `claude agents --json`, worktree registry) down to manifest membership: lanes you spawned, sessions you explicitly adopted (record the adoption), and branches matching your claims. Everything else is another program's business — never nudge it, never count it in "my lanes", never treat its activity as your program's progress or stall. Surveys may NOTE foreign sessions only when they overlap your claims (that's a collision, below).

**Collision & ownership protocol.** Before claiming an issue, path glob, or branch — and again whenever a survey shows a foreign session touching your claims — check the other manifests in `~/.claude/orchestrator/programs/`:

1. **First-claim wins by default.** The program whose manifest recorded the claim earliest owns the item; the later orchestrator routes around it (re-scope the lane, stack on the owner's branch, or drop the item and note it in the manifest as `ceded_to: <program>`).
2. **Transfer by mailbox, not by grab.** If you believe you should own a claimed item (their program looks retired, your dependency is harder), write a transfer request to the owning orchestrator's mailbox (`mailbox-send.sh <their session> {"type":"claim-transfer","item":…}`) and proceed only after they update their manifest to release it. A manifest with `updated_at` stale >24h AND a dead orchestrator session (no live session, no active lanes) may be treated as abandoned — take the claim and note the takeover.
3. **Genuinely contested → human.** Two live orchestrators both insisting is a user decision — surface both goals and the overlapping item; never silently double-own.
4. Path-level collisions inside one repo additionally go through the repo's claim-scope CLI where it exists (shared git-common-dir store) — the manifest is program-level intent; the CLI is the mechanical file-lock.

Manifest hygiene: on retire, mark the program `done` (keep the file — it's the ownership history); a fresh orchestrator for the same target adopts the old manifest rather than re-claiming from scratch.

## Bootstrap on invocation

The orchestrator does NOT read raw session JSONLs inline — that burns context (3-5K tokens of grep output per turn). Instead, it dispatches a state-miner subagent per `prompts/state-miner.md` and reads the distilled summary (~500 tokens). Cache the result so subsequent runs only summarize **deltas**.

### Runtime detection (Claude Code vs Codex CLI)

This skill is symlinked into both `~/.claude/skills/` and `~/.codex/skills/`. Detect runtime first, then route bootstrap:

- **Claude Code** — `$CLAUDE_SESSION_ID` is set; `claude-sessions` skill exists; `Skill` tool, `Agent` tool (Haiku dispatch), and `/loop` slash command are available.
- **Codex CLI** — none of the above. Sessions live at `~/.codex/sessions/<YYYY>/<MM>/<DD>/*.jsonl`; subagents come from `spawn_agent` (gpt-5.4-mini); no harness-managed loop. See §12 for variance.

### First-time setup (once per repo)

```bash
python3 ~/.claude/skills/orchestrator/bootstrap.py --print  # show cache
python3 ~/.claude/skills/orchestrator/bootstrap.py          # discover + write
```

The bootstrap cache lives at `~/.claude/projects/<slug>/orchestrator-cache.json` and contains repo + GitHub project + custom field IDs + label state. All issue-write paths read it via `jq`; never hardcode field IDs.

### Per-turn state survey

**Orchestrator state is program-scoped (see §Program scope), and cross-runtime.** A user routinely splits a program across both runtimes — specs in Codex, spec-review in Claude (or vice versa). Mine BOTH session pools every turn regardless of which runtime is hosting the orchestrator — then filter both down to program membership before reasoning. The miner scripts are plain Python files (`sessions.py`); calling them does not depend on the in-runtime Skill registration.

In parallel, gather the inputs:

```bash
# 1a. Claude session survey (project-filtered)
python3 ~/.claude/skills/claude-sessions/sessions.py survey --filter <project> --json

# 1b. Codex session survey (same project, different pool)
python3 ~/.claude/skills/codex-sessions/scripts/sessions.py survey --filter <project> --days 2 --json

# 2. Previous run cache (may not exist)
cat ~/.claude/projects/<slug>/orchestrator-runs/last-state.json 2>/dev/null

# 3. Open PRs
gh pr list --state open --json number,title,headRefName,updatedAt

# 4. P1 issues
gh issue list --state open --label priority/p1 --json number,title

# 5. Project memory + this skill's LEARNINGS (already in your context if you've been here before)
```

Then dispatch the state-miner subagent (Haiku in Claude, gpt-5.4-mini in Codex via `spawn_agent`) with the prompt template at `prompts/state-miner.md`. The miner receives BOTH surveys (tagged by runtime), unions them by name/purpose, and emits a single per-lane summary — so the user sees one project-scoped state regardless of which runtime each session lives in. Write the cache to `~/.claude/projects/<slug>/orchestrator-runs/last-state.json` and present the markdown to the user.

If one of the two pools is empty for this project, that's fine — pass `(none)` for that input and proceed. **Skipping the cross-pool survey because "I'm in Codex so claude-sessions doesn't apply" is the bug** — the user has work in both pools and expects unified state.

### Activity signals — trust them

The `claude-sessions` survey now emits two activity signals per session:
- **`status`** (ACTIVE / WARM / IDLE) — derived from the two below
- **`jsonl_age_seconds`** — how long since the JSONL file was last written
- **`child_procs`** — count of live immediate child processes of the session PID

`status: ACTIVE` means the session is doing something *right now* — child procs running, or JSONL just written. **Do not call a session idle just because its last text-message timestamp is hours old.** A session running a long bash, agent dispatch, or MCP tool call writes nothing to the JSONL until the tool returns. The text-message TS goes stale, but `child_procs > 0` correctly identifies it as active. (See `LEARNINGS.md` — a past incident misclassified a long-running session as idle for exactly this reason.)

### When to skip the agent

Direct survey output (no agent dispatch) is fine when:
- 1 session live (no orchestration value)
- User explicitly asks for raw data
- First turn in a fresh session (no cache to diff against — agent has nothing to compare)

Otherwise default to the agent dispatch. Context preservation matters more than 1-2s of agent latency.

**Cache-diff short-circuit.** The miner MUST compare survey vs `last-state.json`. If no session has a new commit, new lifecycle step, or status change, return one line (`"no delta vs <run_ts>"`) — do not re-emit the full session list. Paying full agent cost twice on identical data was caught in a past Codex orchestrator audit.

## Core directives

### 1. Always reference sessions by NAME, not SID

The session NAME field can be auto-generated nonsense (`hose`, `add-deps-stage-4b`). The claude-sessions skill's `list` output now derives a **PURPOSE** hint from the session's first user message ("Goal: ship Spec D Stage 5 …"). Use NAME + PURPOSE in narrative, never SID prefix. SIDs are CLI-only (for `--sid <prefix>` arguments).

### 2. Workflow pattern: spec → review → plan → implementation, all in the SAME session

Per the project memory `feedback_spec_to_implementation_same_session`: one feature lives in one session through its full lifecycle. Do NOT recommend "exit the spec session, spawn a fresh execute session" — context handoff costs real productivity. Multi-stage specs (Stages 4, 4b, 5, 6) get one session per stage, but each stage runs the full spec-section-read → light plan → implementation arc in place.

### 2a. Lifecycle paradigm — the canonical spec lane (7 steps + load-bearing 4→4b feedback edge)

Spec-class lanes follow this exact ordered sequence. Every step produces a committed, file-anchored artifact. The state-miner infers a session's step from the most recent commit subject (see `prompts/state-miner.md` Inference rules).

| # | Skill / action | Input | Output artifact | Commit pattern | Termination signal |
|---|---|---|---|---|---|
| 1 | `superpowers:brainstorming` | issue + memory refs | inline Q&A consensus | none (in-session) | user picks option |
| 2 | spec authoring (no skill) | brainstorm answers | `docs/specs/active/<date>-<slug>-design.md` | `docs(<scope>): spec — <title>` | spec file v0 committed |
| 3 | `/spec-review` (incl. `/compact` mid-step) | spec + decisions JSON (captured pre-compact) | **revised spec in-place** + Industry Insights filed as separate issues | `docs(<scope>): spec revision post /spec-review — <verdict>` | user "yes apply" + commit |
| 4 | `/spec-test-plan` | revised spec | `<spec>-test-plan.md` (multi-tier, `[ADV]` + `[EC]` tagged) | `test(<scope>): add test plan for <slug>` | plan file committed |
| **4b** | **spec patches from test-plan** (the load-bearing edge) | `[ADV]` and `[EC-MISSING]` test-plan findings | **revised spec AGAIN** (T-row corrections, missed-variant escalations, EC-N gaps closed) | `docs(<scope>): spec patches for ADV-X + EC-Y from /spec-test-plan` | spec patch commit (or stub commit if zero patches needed) |
| 5 | `superpowers:writing-plans` | revised spec + test plan | `<spec>-plan.md` (task-by-task) | `docs(<scope>): add implementation plan for <slug>` | plan file committed |
| 6 | `/spec-review` on the PLAN | implementation plan | plan revisions in-place | `docs(<scope>): plan revision post /spec-review` | both Codex reviews return + user "go" |
| 7 | `superpowers:executing-plans` (or `subagent-driven-development`) | revised plan | code + tests + tier markers | per-task feature commits | plan tasks all checked + your project's full verify gate PASS |

**The 4→4b feedback edge is non-negotiable.** Test-plan adversarial agents (`adversarial-analyzer.md` + 2 Codex coverage verifiers) and the edge-case miner (`prompts/edge-case-miner.md`) routinely surface bugs the spec misses. In a past incident an adversarial finding corrected wrong test-plan wording and another caught a missed-variant trap in a legacy wrapper. Without 4b, the implementation plan inherits those bugs and ships them to code.

If `/spec-test-plan` produces ZERO ADV/EC-MISSING findings worth a spec patch, the lane MUST still emit a stub commit — `docs(<scope>): no spec patches required from /spec-test-plan — all findings deferred to plan` — so the absence of step 4b is recorded, not ambiguous to the state-miner.

**Skip rules (when the lane is non-spec):**
- Trivial < 50 LOC change → skip Steps 1, 3, 4, 4b, 6 (write a tiny ad-hoc plan or just commit)
- Pure docs change → skip Steps 1, 4, 4b, 5, 6 (just /spec-review optional)
- Bug-fix < ~200 LOC, no new surface → 2→5→7 only

**Lane is "ready to execute" when ALL hold:**
1. Spec file exists
2. At least one `spec revision post /spec-review` commit
3. Test-plan file exists
4. Either a step-4b spec-patch commit OR the explicit no-patches-required stub
5. Implementation plan exists
6. Plan reviewed (commit subject contains `plan revision post /spec-review` OR all plan-review findings closed)

Steps 7+ (execute, test-execute, PR open, merge gate) are governed by `prompts/loop-directive.md` and §11 (retire gate).

### 3. Lane runtimes — pick per lane, by human-involvement need

Four runtimes exist. The selection rule: **a lane goes interactive only when it needs the human**; everything else runs prompt-free. (This section exists because a real overnight run stalled when every channel turned out to be human-gated — see §3a.)

| Runtime | Spawn | Prompts? | Completion signal | Use for |
|---|---|---|---|---|
| **Headless lane** | orchestrator runs `claude -p "<mission>" --permission-mode bypassPermissions --worktree <name> --session-id $(uuidgen) --output-format json` via Bash `run_in_background` (or `claude --bg`, tracked via `claude agents --json`) | none | process exit auto-notifies orchestrator; JSON result + branch/PR state | spec authoring, review application, build, test, PR-open — the whole non-human lifecycle |
| **Background Agent / Workflow** (in-harness) | `Agent` tool / `Workflow` | none (inherits session perms) | auto-re-invokes orchestrator, 0 tokens while waiting | bounded subtasks: research fan-out, spec-review lanes, scope audits, state mining |
| **Interactive chip session** | `spawn_task` chip — **requires a human click** | desktop defaults | none (fire-and-forget) | ONLY lanes that need the human: grillings, founder/decision gates, watch-and-steer work. The click is the human opting in — a feature here, a stall everywhere else. **Chip prompts are lean (≤~900 chars): GOAL / STATE (facts not in the repo instructions or ticket) / START HERE (pointers, never pasted bodies) / mission-specific GUARDRAIL — the receiving session auto-loads all repo law and re-derives file detail from pointers** |
| **Interactive paste session** | user pastes Paste 1 + 2 | desktop defaults | surveys + mailbox | legacy manual mode; same constraint as chips |

**Hard transport rules:**
- **`send_message` (desktop cross-session messaging) is BANNED as an automated transport.** Its confirmation prompt is hardcoded in the app — an unattended sender hangs on the dialog and the turn wedges. Use it only as a courtesy surfacing when the user is actively present, never inside an autonomous loop.
- **Orchestrator → live lane messages go through the file mailbox** (`mailbox-send.sh`, a plain promptless file write; lane arms `wakeup-wait.sh` via `run_in_background` and is auto-re-invoked on delivery — zero tokens while waiting). Headless lanes don't need it: their mission is complete at spawn time; respawn (`claude -p --resume <id>`) to redirect.
- **Scheduled tasks pause on every permission prompt** (detached fresh context, no approver) — durability for app-closed one-shots only, never a mutation lane.

**Headless-lane safety rails (bypassPermissions is real power):**
- Global hooks still fire in the child (heavy-op lock, merge guards) — do not strip them (`--bare`) unless the lane is read-only.
- The machine-global heavy lock serializes verify/build across ALL lanes — cap concurrent heavy lanes at ~2; more lanes queue, not parallelize.
- Lane missions MUST forbid: merging to a protected branch, deploys, prod-data mutation, and any repo's prod verb. The orchestrator holds every terminal gate.
- Fresh `--session-id`, and scrub `CLAUDE_SESSION_ID`/`CLAUDE_CODE_ENTRYPOINT` from the child env so it doesn't masquerade as the parent.
- On the 2nd identical tool denial (safety classifier / model outage), the lane STOPS retrying and exits with a `BLOCKED_ON_CLASSIFIER` result — the orchestrator backs off ≥30 min before respawn. Outage windows must not burn wakes.

**Comms patterns for interactive lanes** (unchanged): mailbox-driven (orch → lane via `mailbox-send.sh`, see `prompts/mailbox-mode.md`), self-managed (user ↔ lane; never mailbox-write), loop-driven (`/loop 5m`, see `prompts/loop-directive.md`). Mode is declared in prompt, recorded in cache, never auto-corrected — surface contradiction as risk.

### 3a. Autonomous stretch planning — the un-gated frontier (anti-stall)

Before any unattended stretch (overnight, user-away), the orchestrator MUST compute the **un-gated frontier**: the set of work items reachable without a human approval. The canonical failure mode: every lane drives to "PR green + READY," the whole DAG roots on one human-merge-gated PR, and the night produces 18 polling wakes and zero development. Plan the frontier so that never happens:

1. **Stack, don't park.** A lane whose work depends on an unmerged PR does NOT halt — it branches its worktree off the dependency PR's branch (stacked branch), builds there, and rebases onto main after the dependency merges. Record the stack edge in `last-state.json` (`stacked_on: <pr>`); the post-merge cascade re-baselines it. Parking on "waiting for merge" when the code is sitting right there in a branch is the #1 wasted night.
2. **Pre-authorization ask — BEFORE the human leaves.** Present the projected merge stack for the stretch ("these N PRs will be green by morning") and ask for standing approval per class (the §11a Tier-B `auto-merge-ok` label, or an explicit in-session mandate). A decline is fine — then the plan routes around the gate via stacking. What's not fine is discovering the gate at 2am.
3. **Deliberate park.** If the frontier is genuinely empty (everything behind declined human gates), park properly: ONE wake at the human's expected return with a morning-summary + ready-to-merge stack. Never poll every 30 min against a gate only a human can open — wakes that can't produce work are noise.
4. **Frontier refresh on every event.** A merge, a lane completion, or a mailbox message re-opens frontier computation — newly un-gated work dispatches immediately (cascade-unblock), stacked lanes re-baseline.

The orchestrator's own continuation during an autonomous stretch: event-driven first (background lane exits auto-re-invoke it), with a sparse `ScheduleWakeup` heartbeat (≥30 min) as the fallback — never the primary drive.

### 4. Conflict-map before spawning a new lane

Before generating a new prompt, list which paths each in-flight session owns and explicitly DO-NOT-TOUCH them in the new prompt. Common collisions are shared UI shells, observability/monitoring infra modules, lockfiles, and customer/schema config files. Concretely, watch for:
- A shared data/layout component many front-end sessions touch
- A monitoring/observability infra module owned by one scope
- `package.json` / `package-lock.json` (or your lockfile) — lockfile changes serialize lanes
- Per-customer or schema config files (e.g. JSON schema files under a customer-config tree)

### 5. Auto-push collision discipline

Per the project memory `feedback_main_auto_push_collision`: parallel sessions pushing to main concurrently can collide. Each session must stash unrelated WT before commit. Lint-staged does NOT expand the staged set. When orchestrator commits something to main, it follows the same discipline: stash WT, commit narrow, push, pop.

### 6. Session-Id trailer with `$CLAUDE_SESSION_ID` expansion

Per the project memory `feedback_session_id_trailer_heredoc`: ALL commit prompts must instruct sessions to use UNQUOTED `<<EOF` heredoc so `$CLAUDE_SESSION_ID` resolves. Single-quoted `<<'EOF'` captures the literal placeholder string. This bug shipped to a PR once — every spawned-session prompt in this skill includes the explicit warning.

### 7. Issue triage on shipping

When a session's PR merges, check whether it subsumes/closes any issues:
- Same file path → likely close
- Adjacent surface → mark as candidate, verify by reading the PR diff
- Update the project board with Status=Done

### 8. Trust but verify the claude-sessions skill output

The skill's `survey` ran through several iterations of bug fixes (trailer-block parsing, leading-newline-in-record, push-status). Always trust its current output but be prepared to re-run if data looks stale or wrong. If a commit appears with `(no Session-Id)` despite having one, it's likely the trailer-block issue (Session-Id followed by Co-Authored-By with a blank line between). The fix is to put both trailers in one block (no blank line), or rely on the regex parser in the skill.

### 9. Test-spec workflow → see loop directive

Lifecycle, RUN/SKIP rubric, spec-test-execute mandate, and merge readiness gate all live in `prompts/loop-directive.md` — single source of truth. **One binding decision** at the test-spec gate: gate RAN → both spec-test-plan AND spec-test-execute run as a unit; gate SKIPPED → neither runs. No "if applicable" twice.

Audit role on PR review:
- **Scope audit:** run the `scope-auditor` agent (Agent tool, `subagent_type: scope-auditor`) on every returned dispatched branch before merge — it diffs the branch against fresh `origin/main`, classifies each surplus file as acceptable collateral vs contamination, and on contamination prescribes re-integrating by cherry-picking the one clean commit (never rebase a stale branch, never salvage in place).
- "Test-spec: [run / skipped because X]" — sanity-check against the rubric. "Skipped because trivial" on a feature PR is a red flag.
- If "run" → check the test plan file in the PR diff has explicit `PASS / FAIL / SKIP / BLOCKED` markers on every tier row, not an unmarked plan. Unmarked plan + "run" claim = TDD-during-impl pretending to be spec-test-execute. Surface it. (A past data-path PR shipped this way before the directive was tightened.)
- Tiers needing prod data (Deploy, E2E) must either run on staging or be explicitly deferred in the plan file with rationale. Silently skipped = red flag.

### 10. Pre-flight verification — before any routing claim

Every time you state session status, "what's remaining," or recommend an action, run these checks. The unifying rule: **verify the source of truth, never infer from secondary signals.** Most user pushbacks trace to skipping one of these.

1. **Mine via Haiku each turn.** Inline raw-JSONL reads + reusing prior interpretations = stale data. Even "I just looked 5 min ago" is too long; sessions move fast.
2. **Branch HEAD vs cache `last_seen_commit`** is the authoritative session-alive signal. JSONL silence, "Exiting." text, and child_procs alone do NOT classify RETIRED. If branch HEAD has advanced, the session is alive.
3. **Read the spec file directly** when answering "what's remaining in Spec X." Issue tracker bodies decay (a tracker body was stale by hours when a fix-pool lane re-baselined). `docs/specs/active/<name>.md` is authoritative.
4. **`gh pr view <N> --json mergedAt,state,mergeStateStatus`** is merge truth. Recent main commits are confirmation; the gh API is authority.
5. **"Now-runnable-post-deploy" / "now flippable" markers are promises.** A session cannot retire while such markers are still DEFERRED-skeleton. They must flip to PASS or have a tracked-issue deferral with rationale.
6. **Staging E2E ≠ Prod E2E.** If a session ships infra-touching work with a staging environment, expect a Tier 3a (staging E2E) marker distinct from Tier 3b (prod E2E). One marker covering "all E2E" = conflation, push back.
7. **Worker output path validation.** If a spawned subagent reports "done" with paths under `/tmp/`, `/var/folders/`, or any directory outside the lane's worktree, the output is **draft-only**. Re-run the final step in the canonical worktree before relaying to the user. (In a past incident a Codex orchestrator escalated `/tmp/`-rooted patches as deliverables; the work never touched the real repo.)

If any check returns stale, contradicted, or absent data, STOP and re-verify. Do not state a routing claim from incomplete inputs.

### 11. Session retire gate — overseer checklist

A session retires only when ALL hold. If any fails, push back to the session with what's missing — do not sign off on retirement.

1. All test-plan tier markers PASS or justified-non-PASS in the **committed** plan file (read the file; no inference from test-runner output)
2. Staging E2E (Tier 3a) marker present + PASS if the work touches infra with a staging environment
3. Stage-aware code has a stage-aware env-var capture marker proving values resolve correctly per stage (e.g. `aws lambda get-function-configuration` evidence in marker line, or the equivalent for your platform)
4. Soak window (if applicable) has a tracked issue per `reference_soak_tracking_via_github_issues.md` opened **before** retire — calendar artifact starts the timer; daily check-ins via `gh issue comment` from any future session
5. Final session summary surfaces: shipped PRs, deferred work with tracked issues, soak window state, any handoff context for next session

### 11a. Auto-merge tiers — minimize orchestrator-as-bottleneck

Early on, every PR sat at "STOP for orchestrator merge" until the operator manually ran `gh pr merge`. With 3+ active lanes that bottleneck cost ~10-30 min of idle time per merge round and serialized cross-lane unblocks. The tier policy below pushes the safe-by-construction merges down to the session itself and reserves orchestrator/operator review for code-class and cross-lane PRs.

**Tier A — session auto-merges itself.** All predicates must hold (machine-checkable):

```
diff matches DOCS_ONLY_REGEX  (docs/, *.md, testing/, .github/, .claude/, .vscode/, .changeset/, .gitignore, .gitattributes, LICENSE)
AND mergeStateStatus = CLEAN
AND every required CI check = SUCCESS or SKIPPED (skipped is fine — paths-ignore)
AND reviewRequests = []  AND reviews with state CHANGES_REQUESTED = []
AND PR body has no unresolved Depends-on
```

When all hold, the session runs `gh pr merge <N> --squash --delete-branch` itself and continues to the post-merge phase chain (§11b). No orchestrator pause.

**Tier B — orchestrator auto-merges on standing approval.** Code PRs that close their declared issue, all required CI green, all reviewer findings applied verbatim, no cross-lane impact, no security-class touch. Operator pre-authorizes by labeling the issue `auto-merge-ok` (or a class-scoped variant like `auto-merge-ok-mcp-fixes` for narrower scope). Eligibility is checked deterministically by `~/.claude/skills/orchestrator/scripts/auto-merge-eligible.sh <pr>` which encodes the predicate: PR is OPEN + MERGEABLE + CLEAN, closes an `auto-merge-ok*`-labeled issue, < 100 LOC total, no `registerTool(` additions, no migrations/*.sql additions, no changes to your project's security-class core files (auth / authz / credential / handler-wrapper), all required CI SUCCESS or SKIPPED (external-provider-pending tolerated), reviewDecision = APPROVED or empty. The orchestrator runs the script during its survey; if eligible, runs `gh pr merge <N> --squash --delete-branch` then `cascade-unblock.sh`. If ineligible, the script prints the failing predicate so the operator can decide whether to relax it for this PR or refine the predicate. (Adjust the security-class file list inside the script to match your repo's sensitive surfaces.)

**Tier C — orchestrator delegates a review-merge agent (default-merge, not default-stop).** Cross-lane impact, security-sensitive surface (MCP authz, RLS, JWT, credential storage, sandbox isolation), schema migrations, breaking API change, lockfile churn, OR PR has unresolved review comments. **Per a standing operator directive: merging is NOT a blocker — orchestrator dispatches a review-merge subagent that reads the diff, runs the predicate checks, applies any review comments verbatim, and merges (admin-bypass if CI is structurally absent). The agent STOPs and surfaces ONLY on:** (a) genuine merge conflict requiring human resolution, (b) CHANGES_REQUESTED review still open, (c) test/build evidence that the change is broken on its own branch. Cascade-unblock fires after merge. The old "STOP for operator GO" pattern was removed because it bottlenecked the orchestrator at ~10-30 min idle per merge round; payment-class and security-class merges still get a review pass via the delegated agent, just without the operator-paste handoff.

**Tier prediction is declared upfront** — Paste 1's "Hard constraints" section names the expected tier ("Expected merge tier: A — docs-only contract surface") so the session and the orchestrator share the prediction before work starts. Mismatched tier (e.g. Paste 1 said A but the diff grew into code) is a scope-creep signal — the session must re-classify and STOP before merging.

**Why this is safe:** Tier A's predicate set is exactly what a `pre-push` hook can already enforce (DOCS_ONLY_REGEX) plus GitHub branch protection (CLEAN + CI green). The session merges only what would have merged anyway under operator review — minus the wait. Tier B and C never auto-merge without explicit operator gating.

### 11b. Post-merge phase chain — sessions don't stop at merge

A session that merges (Tier A) or has its PR merged (Tier B/C) MUST continue past the merge into the verification-and-soak chain before retiring. Stopping at "PR merged" leaves staging deploys unverified, soak windows unstarted, and downstream lanes uncascaded.

**Phase chain (run in order after merge):**

1. **Cascade-unblock fire** — if this PR closes an issue M, run `~/.claude/skills/orchestrator/scripts/cascade-unblock.sh <M>` to wake any sessions waiting on M. (Tier A: session runs it. Tier B/C: orchestrator runs it after merging.) **Wakeup files only fire if the target session has an active /loop.** A retired session (loop cancelled per §11 retire gate) has no tick to read the mailbox — the wakeup file is inert. To resume a retired lane, the orchestrator must give the operator a paste-ready prompt for direct injection into the session terminal, NOT just write a wakeup file. Diagnostic: a session is retired iff its last assistant turn quoted "Lane closed" / "/loop already cancelled" or the survey shows JSONL stale > 1h with child_procs=0.
2. **Staging deploy poll** — if main push triggered an auto-deploy to staging, poll `gh run list --branch main --workflow <name> --limit 1 --json status,conclusion` until completed. Quote conclusion. If FAILURE, surface to orchestrator with logs link, do NOT retire.
3. **Staging E2E (Tier 3a)** — if the work touches handlers, runtime, infra, or a data path, run the staging E2E flow listed in the plan file's Tier 3a row. Update the tier marker with PASS / FAIL / SKIP / BLOCKED + evidence URL. (Use your project's E2E command against staging or the named flow per your project's flow registry.)
4. **Stage-aware env-var marker** — for stage-aware code, run your platform's function-configuration probe (e.g. `aws lambda get-function-configuration --function-name <name>`) against staging and prod, paste the relevant env-var values into the plan file's stage-aware marker row.
5. **Soak issue open** — if the work warrants observation (deploy soak per `reference_soak_tracking_via_github_issues.md`), open the soak issue with `soak` + `soak:<feature>` labels BEFORE retire. The issue's first comment names the soak window end date.
6. **Final summary + retire** — quote shipped PRs, deferred items with tracked issue numbers, soak window state. Loop cancels itself; the session goes idle but stays alive for follow-up questions.

The /loop directive (`prompts/loop-directive.md`) drives sessions through this chain after merge — same 5-min cadence, just with the post-merge phases as the next ticks. A session that retires before all 6 phases is incomplete; orchestrator pushes back per §11.

**Cross-worktree branch precondition (post-incident hardening).** When orchestrator runs phase 3/4 itself — opening a marker/docs PR from any worktree on the user's machine — it MUST verify the worktree is on `main` (or explicitly checkout `origin/main`) BEFORE `git checkout -b <new-branch>`. In a past incident the orchestrator opened a docs PR from a worktree whose HEAD pointed at a sibling lane's feature branch. The new docs branch inherited that lane's thousands of lines of WIP, the PR was admin-merged, and main had to be reverted. Mandatory checks before any orchestrator-run cross-worktree commit:

1. `git -C <worktree> rev-parse --abbrev-ref HEAD` returns `main` — if not, run `git -C <worktree> checkout main && git -C <worktree> pull --ff-only origin main` first.
2. `git -C <worktree> diff origin/main --stat` is empty (clean) BEFORE creating the new branch.
3. After staging the marker edit, re-run `git -C <worktree> diff origin/main --stat` and verify ONLY the expected file appears. If extra files leak in, abort and investigate before pushing.
4. Lane-owned worktrees are off-limits for orchestrator commits — even if they happen to be on `main`, the lane may switch them at any moment. Use a dedicated marker-commit worktree, or do the marker work from the lane's own session via wakeup.

### 12. Codex CLI runtime variance

The skill is shared across runtimes. When `$CLAUDE_SESSION_ID` is unset, you are in Codex — the following adjustments apply:

- **State mining** — `claude-sessions` is unregistered as a Skill **but the script is still callable**. Run BOTH miners every turn (`python3 ~/.claude/skills/claude-sessions/sessions.py survey --filter <project> --json` for Claude pool, `python3 ~/.claude/skills/codex-sessions/scripts/sessions.py survey --filter <project> --days 2 --json` for Codex pool) and union the results in the state-miner prompt. State is project-scoped — splitting a feature across runtimes (e.g. spec-write in Codex + spec-review in Claude) is normal and the orchestrator must surface both halves. Skipping the Claude pool because "I'm in Codex" was a past audit miss.
- **Subagent dispatch** — `Agent`/`Skill` tools are absent. Use `spawn_agent` (gpt-5.4-mini) for the miner role and prose-instruct workers; you cannot dispatch `spec-test-execute`, `spec-review`, etc. as skills — paste their canonical guidance into the worker prompt and rely on the worker's discipline.
- **Continuation** — no `/loop` slash command. Use the single-paste pattern in `prompts/loop-directive.md` §Codex variant: directive embedded in the initial prompt with explicit stop conditions.
- **Sandbox writes** — Codex defaults to `sandbox_mode = "workspace-write"` which silently blocks writes to sibling worktrees and `~/.codex`. Either run with `--add-dir <lane-worktree>` per lane or set `sandbox_mode = "danger-full-access"` in `~/.codex/config.toml`. Otherwise workers fall back to `/tmp/` (see directive #10.7).
- **Session-Id trailer** — `$CLAUDE_SESSION_ID` does not exist. Skip the trailer or substitute the rollout file basename (`rollout-<ts>-<sid>.jsonl` → `<sid>`). Don't paste the Claude-only heredoc warning blindly.
- **PURPOSE-hint extraction** — no `sessions.py list` derivation. The spawning prompt itself must declare `NAME: <name>` and `PURPOSE: <one-liner>` on the first lines so the next miner pass can recover them.
- **Worktree placement** — workers cannot write to sibling paths under `~/code/<lane>/` because they fall outside the sandbox writable root. **Lane prompts MUST use the nested pattern** `<repo>/<lane>-impl/`. Sibling paths force fallback to `/private/tmp/` and the work disappears from the canonical lane. (In a past audit, lanes that used nested stayed clean; lanes that used sibling all bounced through `/tmp`.)
- **Session-Id trailer** — install a `prepare-commit-msg` hook that recovers the SID by matching the lane's cwd against `~/.codex/sessions/<YYYY>/<MM>/<DD>/rollout-*.jsonl` first-record `payload.cwd`.

### 13. Compact-survivable continuity — grand-project snapshot

The session cache (`last-state.json`) captures **active lanes**. The snapshot below captures the **in-flight orchestrator thread** — grand-project name + phase, recurring user guidance, orchestrator-side decisions, pending user actions. Without it, a `/compact` (Claude) or auto-summary (Codex) drops the thread and the user has to re-prime every continuation. See `prompts/grand-project-snapshot.md` for the schema and what NOT to put in it.

**File**: `~/.claude/projects/<slug>/orchestrator-runs/grand-project-snapshot.json` — one per project, latest-wins.

**Pre-compact (Claude)**:

1. Mine the JSONL via Haiku to extract `user_recurring_guidance` + `in_flight_decisions` (the same agent dispatch as state mining, with a different prompt focus — see `prompts/grand-project-snapshot.md`).
2. Write the snapshot file.
3. Self-register the post-compact hook in the project's `.claude/settings.local.json` (idempotent — same pattern as `spec-review`):

   ```python
   # SessionStart matcher=compact → <this skill's dir>/scripts/orchestrator-resume.sh
   # (resolves via the installed skill path, e.g. ~/.claude/skills/orchestrator/scripts/orchestrator-resume.sh)
   ```

4. Tell the user to run `/compact preserve grand-project context — see snapshot`.

**Post-compact (Claude)**: hook fires automatically, injects a continuation pointing at the snapshot. The orchestrator reads it, re-runs the Haiku state miner, and presents a one-paragraph "resumed" summary before responding to the user's incoming prompt.

**Codex variant**: no `/compact` slash command and no SessionStart hook. Adapt:
- Write the snapshot file proactively after every significant routing decision (lane retire, lane spawn, P0 escalation) — defensive against unplanned summary.
- When a context summary banner appears in the conversation (Codex auto-compaction), READ the snapshot before the next routing claim. The codex-sessions miner picks up the snapshot path automatically when re-orienting.

**Anti-pattern**: writing transcripts or full session JSONLs into the snapshot. The snapshot stays small (~2-5 KB). If you're tempted to add a 12th `user_recurring_guidance` entry, the durable ones belong in `MEMORY.md` instead.

### 14. Model & effort routing per lane

State-miner emits `recommended_model` + `recommended_effort` per lane in `last-state.json`. Surface in survey + lane spawn prompts. Full matrix: `prompts/model-routing.md`.

Effort is per-turn (Claude: keyword; Codex: session-level reasoning level — Low/Medium/High/Extra high, switchable mid-session via Codex menu).

Rules:
1. Subagents default to cheap tier (Haiku / gpt-5.4-mini). State miner always cheap-tier.
2. Effort costs tokens; only apply where matrix says.
3. Respect `model_override` in `last-state.json[<sid>]`.
4. Mailbox-idle is free; don't retire to "save tokens."
5. Cross-runtime second-opinion (flagship Claude + flagship Codex on `/spec-review`, `/codex` review) is the one rational flagship double-up.

**Surfaced in every survey output:** the per-lane recommendation, plus a
top-of-output summary line `Cost watch: N lanes on the flagship tier that matrix says should be mid/cheap tier — review with user.`

### 15. Lane discipline — tier-aware merge gate

Aligned with the §11a tier policy. An earlier blanket rule was "lane sessions never run `gh pr merge`." That correctly prevented lanes from merging red-CI PRs but made the orchestrator a bottleneck on safe docs-only merges (a docs PR once sat ~14 min idle waiting for a manual merge). The tier-aware version:

- **Tier A (docs-only, all CI green or skipped, no review comments, no Depends-on pending) — lane session may run `gh pr merge --squash --delete-branch` itself and continue post-merge phases.** Docs-only PRs are safe-by-construction: a `pre-push` hook can already enforce the path regex, and branch protection enforces CLEAN + CI. The lane is just executing what the operator would have run anyway.
- **Tier B (single-lane code, all CI green, reviewer findings applied, no cross-lane impact, no security touch) — orchestrator auto-merges on standing approval (label `auto-merge-ok` or `auto-merge-ok-<class>` on the issue).** Eligibility decided by `auto-merge-eligible.sh` predicate (see above). Operator can relax for a specific PR by adding the label retroactively, or refine the predicate by editing the script.
- **Tier C (cross-lane / security-class / schema / breaking / unresolved-review) — lane STOPs after PR open + CI quote-back. Orchestrator delegates a review-merge subagent that does the diff review, applies reviewer findings, and merges (admin-bypass when CI is structurally absent). Stop conditions for the agent: (a) merge conflict, (b) open CHANGES_REQUESTED review, (c) demonstrably broken branch.** Per a standing operator directive, merging is no longer a blocker — only conflicts are. In a past incident two PRs were merged with red CI because the lane decided "no required checks reported = license to merge" — Tier C still exists to gate *who* merges (review-merge agent, not the impl session) and to enforce the diff-review pass, but the operator-handoff stop has been removed.
- **Branch protection is the structural backstop.** Before recommending parallel lane work on a project, verify required status checks exist: `gh api repos/<owner>/<repo>/branches/main/protection 2>/dev/null | jq -r '.required_status_checks.contexts'`. If absent, flag as a setup gap — the workflow assumes platform enforcement of CI green before merge.
- **Post-push CI quote-back.** Lane prompts must instruct: after `git push`, run `gh pr checks <N>` (or `gh pr view <N> --json statusCheckRollup`) and quote the rollup back before claiming "done". Even when the lane can't merge, surfacing CI state to the operator closes the loop.
- **No `/tmp/` source-of-truth.** Reinforces directive #10.7 — workers occasionally fall back to `/private/tmp/` under sandbox restriction. Lane prompts must explicitly forbid `/tmp/` and `/private/tmp/` for any artifact that should survive the session.

## Issue management — keep the backlog persistent

The project board + issue tracker IS the backlog. Memories are mortal (they grow stale, conflict, get pruned); issues are durable (they survive across sessions, machines, weeks). When a new piece of work surfaces — a bug, a tech debt, an emergent follow-up — **create an issue immediately** with full triage metadata. Don't trust yourself to "remember" it later. (If your team uses a different tracker than GitHub Issues as the source of truth, create the issue there and keep the GitHub PR backlinked to it — adapt the `gh issue`-based commands below to your tracker's CLI/MCP.)

### Required labels on every issue

Every new issue needs:
- **Type label**: `bug`, `enhancement`, `documentation`, `regression-test`, `tech-debt`, `spec-review`, or a `spec:<name>` label for spec-specific tracking
- **Priority label**: `priority/p0` (critical / drop everything), `priority/p1` (this week), `priority/p2` (this month), `priority/p3` (backlog)
- **Effort label**: `effort/s` (under half day), `effort/m` (0.5-2 days), `effort/l` (2-5 days), `effort/xl` (over a week, multi-PR)

### Project board (per project)

Every project should have a single GitHub project board (give it a descriptive title and own it under your repo's user/org). The board needs custom fields beyond default Status:
- **Priority** (single-select: P0/P1/P2/P3)
- **Effort** (single-select: S/M/L/XL)
- **Target Date** (date)

**Field IDs are discovered automatically by `bootstrap.py`.** Adding custom fields requires `gh auth refresh -s project` once per machine — bootstrap.py detects the missing scope and prints the refresh command. After the scope is granted, bootstrap.py fetches the project, lists fields, verifies labels, and writes everything to `~/.claude/projects/<slug>/orchestrator-cache.json`. Issue creation reads from the cache; no hardcoded IDs anywhere in the skill.

### Issue creation pattern

Use `prompts/issue-template.md` as the base. Every body must include:
- **Background** — what surfaced this issue, when, in which session
- **Root cause** if known — file path + behavior
- **Acceptance criteria** — checkboxable list, scoped to one PR
- **File refs** — anchor paths so the implementing session knows where to start
- **Related** — memory references, prior PRs/issues, soak issue links
- For latent bugs: a `### Why we need a regression test` section
- For tech debt: a clear "Why this matters" + estimated impact

### Querying the backlog

Standard queries the orchestrator runs at session start or when planning:

```bash
# All P1 (this week) work, sorted by issue number
gh issue list --label priority/p1 --state open

# Cross-reference issues with active sessions' surfaces
gh issue list --label "spec:visual-system" --state open

# Recently created (for triage gap detection)
gh issue list --state open --limit 100 --json number,title,labels,createdAt --jq '.[] | select((.createdAt | fromdateiso8601) > (now - 86400))'

# By repo + project, with Priority/Effort/Target sorted
gh project item-list <number> --owner <owner> --limit 200 --format json
```

### Sync rules

When a PR merges:
1. Read its body for `Closes #N` trailers — those issues auto-close, but verify
2. Identify any **subsumed but not auto-closed** issues — same surface as the PR's diff. Close manually with a comment linking the PR
3. Move project items to **Status=Done** explicitly (auto-close doesn't always update project Status)
4. If the merged PR opened follow-up TODOs (e.g. "Stage 4b deferred from Stage 4"), create a new issue immediately with proper labels — don't let them slip into "I'll remember"

When a new pattern / tech debt / latent bug surfaces during orchestration:
1. Create issue immediately, even if you can't act on it now
2. Apply triage labels in the same `gh issue create` call: `--label "bug,priority/p2,effort/s"`
3. Add to project: `--project "<project name>"`
4. Set custom fields via `gh project item-edit` (Priority + Effort + Target Date)
5. Cross-reference in any related memory entries

### Avoid issue rot

- **No untriaged issues** — every open issue has all three labels (type, priority, effort) within an hour of creation
- **Stale P1s** — re-check P1s weekly; they should have a target date within 2 weeks. If older, demote to P2 with reason
- **Closed-but-not-archived** — once a sprint settles, sweep closed issues that were P1/P2 and ensure their PRs are linked back

### Real cost of skipping issue management

In a single busy session the user identified several distinct strands of work — architectural map work, a fingerprint-hardening fix, a regression test, a hydration bug, a rollout tracker — all of which would have been lost mid-session if not captured as issues. Memory-only would have surfaced 2-3 of them at most. The issue tracker captured all of them.

## Tools you rely on

| Skill | Use |
|---|---|
| `claude-sessions` | Live session list + cross-session main timeline + per-session survey |
| `spec-review` | Multi-model spec verification — invoke in fresh sessions, not orchestrator |
| `spec-test-plan` | Generate multi-tier test plan from finalized spec — sessions invoke between spec-review fixes and writing-plans |
| `spec-test-execute` | Execute the test plan tier-by-tier — sessions invoke after implementation, before opening PR |
| `superpowers:writing-plans` | Plan generation — sessions invoke after spec approval |
| `superpowers:executing-plans` | Step-by-step execution — sessions invoke after plan approval |
| `gh` CLI | Issues, PRs, project board, labels |
| `git` (read-only mostly) | State checks; only commit/push from orchestrator for tiny doc/orchestration commits |

## Tools you DO NOT use directly

- Don't run installs, test suites, or deploys (`npm install`, `npm test`, `cdk deploy`, `vercel deploy`, etc.) — sessions do that
- Don't edit feature code — surface the change as a prompt for a session
- Don't run `/spec-review` or `superpowers:executing-plans` from orchestrator — fresh session

## Spawning lanes

### Headless spawn (default for non-human lanes)

No paste, no click. The orchestrator spawns through the operator-allowlisted wrapper (the auto-mode classifier blocks a session from invoking `--permission-mode bypassPermissions` or writing its own allow rules directly — the operator one-time allowlists e.g. `~/.claude/scripts/spawn-lane.sh` by hand):

```bash
~/.claude/scripts/spawn-lane.sh --mission <mission-file> --cwd <lane-worktree> --model <per §14>
```

Battle-tested invocation rules (each earned by a real failure):

- **Never pipe the spawn, always detach stdin.** `spawn-lane.sh … | tail` under a background call can exit 0 with 0 bytes and ZERO work done — a silent no-op that leaves a locked empty worktree. Run it via Bash `run_in_background` with output redirected to files; the wrapper hard-detaches stdin itself. `claude -p --output-format json` ALWAYS emits a final JSON blob — **empty output + exit 0 is proof the lane never ran**, not a success.
- **Chunk by lifecycle step — this is the default lane shape.** Background-Bash has a runtime cap; a full spec→implement lane gets killed mid-lifecycle. One bounded lane per lifecycle step (spec / review / test-plan / implement), each committing its artifact to the branch; the next lane resumes FROM THE BRANCH. No `--resume` needed, no cap kill.
- **Stall detection is remote-first.** A lane that ends its turn with work committed locally but unpushed looks successful. After every lane exit run `git ls-remote --heads origin <branch>` — no remote branch (or no PR where one was promised) = stall; respawn a continuation lane from the committed artifact.
- **Lanes never run the machine's full local verify gate.** Two lanes in a row backgrounded the heavy verify and died waiting for a completion notification a `-p` lane can never receive — warnings did not fix it; removing the step did. Lanes run targeted/quick checks only, then commit + push; **CI is the authoritative gate**, and the orchestrator watches it.
- **`--worktree` only on first spawn; `--cwd <existing-worktree>` on every continuation** — a second `--worktree` spawn collides with the locked worktree.
- **`--bg` is unusable headlessly** (the agent starts idle and there is no promptless way to send it its prompt; `claude agents` needs a TTY). Chunked `-p` lanes replace it.
- **Teardown/refactor missions: every deletability claim is a HYPOTHESIS.** Grep-verify call sites before scoping, and instruct the lane: "if verification reveals the code isn't dead, STOP and report — never weaken a test to make deletion pass." (One unverified "always no-ops" claim would have dropped a money-path capacity release; the lane's refusal caught it.)
- Mission content: goal one-liner, issue ref + embedded issue body/acceptance criteria, owned paths + DO-NOT-TOUCH, lifecycle step, expected merge tier, `stacked_on:` edge if any, "NEVER merge/deploy/touch prod", "on a 2nd identical tool denial print BLOCKED_ON_CLASSIFIER and stop", "final reply = one JSON status object".

### Execution substrates — composing Workflows, subagents, and lanes

Four substrates run work; pick by **deliverable shape**, not habit:

| Substrate | Deliverable | Reach for it when |
|---|---|---|
| Background `Agent` (in-session) | information: a report, verdict, map | state mining, research, scope audit — the orchestrator consumes the answer |
| Dynamic `Workflow` (in-session) | verified synthesis from many agents | multi-perspective review/verify, discovery sweeps, judge panels, migrations over a work-list |
| **Headless lane** | a branch/PR (code or docs) | anything shippable; unattended stretches; work needing its own context window |
| Chip session | human judgment | founder gates, grillings, watch-and-steer — nothing else |

**A headless lane is a ROOT session — push whole lifecycle phases down into it.** The no-nested-dispatch rule binds Agent-tool subagents, NOT lanes: a lane may (and should) run subagent-driven implementation, `/spec-review`-style multi-agent fan-outs, and dynamic Workflows internally (proven in real use: a lane ran a 10-agent spec-review including an adversarial reviewer). The orchestrator plans and integrates; it does not run spec-review itself. Because Workflow requires explicit opt-in, the mission text carries the grant: "you may run Workflows for the review/verify phases."

Substrate mapping over the §2a lifecycle: steps 1–2 (brainstorm/spec) → headless lane (or chip when the human is deciding); step 3/6 (spec/plan review) → Workflow or subagent fan-out INSIDE the lane; step 7 (execute) → subagent-driven implementation inside the lane; cross-lane verification and audits → orchestrator-side Agent/Workflow. Concurrency: heavy (verify/build) serializes on the machine-global lock — cap ~2 heavy lanes; read-heavy Workflows parallelize freely.

**MCP tiers differ by substrate** — a Task subagent inherits the full desktop MCP set (interactive OAuth included); a headless lane gets only the static-credential MCPs the wrapper attaches (e.g. tracker CRUD via API key). Missions target the lane tier; the orchestrator does anything requiring desktop-only MCPs itself.

**Headless MCP: interactive OAuth doesn't load in `-p` mode — attach static-credential MCPs explicitly.** Desktop-plugin and claude.ai-connector MCPs authenticate via interactive OAuth; their tokens do NOT load in a headless lane (verified: a lane sees zero tracker tools even when the desktop shows Connected). Lanes that need the tracker (or any MCP) get it via `--mcp-config` with static-credential auth — e.g. an issue-tracker MCP with an API-key bearer header, provisioned once by the operator into a gitignored secrets file and auto-attached by the spawn wrapper. Static-credential CLIs (`gh`, `git`, cloud CLIs with on-disk profiles) work headless as-is. Mission briefs still embed the core context inline (issue body, acceptance criteria, file anchors) — the MCP is for depth (comments, linked issues, live updates), not a substitute for a self-contained brief. For long-lived lanes prefer `claude --bg` and read `claude agents --json` at each wake. Same mission-content requirements as Paste 1 below (goal / scope / constraints / trailer / verify / PR format); the mission must also state its **expected merge tier** and any **`stacked_on: <pr>`** edge.

### Interactive spawn (only when the lane needs the human)

Use `prompts/session-template.md` as the base. The spawn is **two paste actions**:

**Paste 1 — initial prompt.** Must include:

1. Goal one-liner starting with `ship X` / `fix X` / `implement X` / `build X` (purpose-hint extraction)
2. Issue reference (`gh issue view N`)
3. Worktree setup: `git worktree add ../<slug> -b <branch> origin/main`
4. Background — 2-4 memory refs the session reads first to skip rediscovery
5. Scope **with owned-path declarations** — each bullet pairs a goal with the file paths/globs it will write to. The orchestrator registers these in `last-state.json` under the session's `owned_paths` array so sibling lanes consulting state see them.
6. Hard constraints — DO-NOT-TOUCH paths owned by other sessions
7. Session-Id trailer + UNQUOTED heredoc warning
8. Verify command before push (your project's verify gate — the command your project documents)
9. PR title format
10. PR body must include `Closes #N` + test-spec decision rationale + `Depends on #M` if the lane consumes another lane's pending PR
11. State-awareness preamble — one paragraph telling the session that the /loop directive will run BEFORE-tick checks (consult `last-state.json`, poll depends-on PRs, check sibling activity on shared files, push after every commit)

**Paste 2 — `/loop 5m <continuation>`.** Copy verbatim from `prompts/loop-directive.md`. The directive performs 4 BEFORE-each-tick state-awareness checks: (1) consult `~/.claude/projects/*/orchestrator-runs/last-state.json` for sibling lanes; (2) poll depends-on PR's `mergedAt`; (3) check sibling activity on out-of-scope files via `git log --since='2h'`; (4) `git push` after every commit so the orchestrator's 5-min surveys catch the lane's state within one tick. Tune cadence per phase (5m default, 10m for steady-state with longer per-iteration work, 15m for long-running implementation; minimum 3m).

**Orchestrator-side bookkeeping after Paste 1 is acknowledged.** Update `last-state.json` for the new session: add an entry with `name`, `purpose_hint`, `owned_paths` (from Scope), `depends_on_issues` (if any), `lifecycle_step: 1` (or 2 if spec already exists), `lifecycle_label`. Sibling lanes' BEFORE-tick consults will see this within their next loop tick (≤5 min) and self-coordinate.

Do NOT embed a "## Loop directive" paragraph in the initial prompt — that's the old pattern. The harness owns cadence now.

## Memory references (per-project)

Project memories live at `~/.claude/projects/<slug>/memory/MEMORY.md`. The orchestrator pattern depends on these conventions being captured. Key memories this pattern leans on (names are conventions — adapt to your own memory files):

- `feedback_session_naming_convention` — NAME not SID
- `feedback_session_id_trailer_heredoc` — heredoc quoting
- `feedback_spec_to_implementation_same_session` — lifecycle in one session
- `feedback_main_auto_push_collision` — stash before commit, parallel push discipline
- `reference_soak_tracking_via_github_issues` — soak issue conventions
- plus any project-specific references for your deploy/migration/auth patterns and the canonical repo location + frozen-branch facts

When you encounter a NEW pattern that should persist across orchestrator sessions, **route it by scope** (below) — never append per-run to this repo's committed `LEARNINGS.md`.

## Skill Memory (LEARNINGS)

**Read at start:** this skill's committed `LEARNINGS.md` (curated seed of cross-session orchestration patterns) + the private overlay if present (`~/.claude/skills-overlay/orchestrator/LEARNINGS.md`).

**Write at end — route by scope, NEVER append to the committed seed here** (full routing: [`docs/skill-memory.md`](../../../docs/skill-memory.md)):
- **Operator-private orchestration craft** (a tool bug like claude-sessions/codex CLI, a heredoc-quoting convention, a false-positive-test failure mode during a multi-PR push window, an over-parallelizing / lane-collision anti-pattern) → `~/.claude/skills-overlay/orchestrator/LEARNINGS.md` (create if absent).
- **Project-specific facts** → the project's `.claude/memory/`.
- **Universal craft worth publishing** → note it for `/improve-harness` to promote (de-identified) into the seed via PR.

Also read the private overlay if present: `~/.claude/skills-overlay/orchestrator/LEARNINGS.md` (adopter-private; never in this public repo). It holds the dated, incident-specific cross-session lessons the maintainer has accumulated; the generic skill works standalone without it, and picks it up automatically when present.

## Anti-patterns

- ❌ Running installs or implementing code in orchestrator
- ❌ Spawning agents for implementation when a fresh session is more appropriate (sessions have their own context window; agents share orchestrator's)
- ❌ Opening 5+ implementation lanes when 4 are already running (usage-limit risk + merge collision risk)
- ❌ Using SIDs instead of NAMEs in narrative
- ❌ Forgetting to add DO-NOT-TOUCH list to new lane prompts
- ❌ Trying to fix the orchestrator's local main divergence without first stashing other-session WT
- ❌ Generating prompts without the loop directive — sessions then ping for tiny decisions
- ❌ Skipping spec-test-plan because "this feels straightforward" — apply the rubric mechanically; the cost of running it is small, the cost of skipping it on a feature is incident response
- ❌ Treating TDD-during-implementation as a substitute for spec-test-execute — test-runner passing ≠ tier marker. The plan file must have explicit `PASS / FAIL / SKIP / BLOCKED` markers committed before merge. (A past data-path PR was the failure case that surfaced this gap.)
- ❌ Marking test plan tiers PASS without running them, or SKIP without a justification + fallback attempt
- ❌ Inferring tier outcomes from test-runner output during the merge gate — the gate reads explicit markers from the committed plan file, never infers
- ❌ Silently skipping prod-data tiers (Deploy, E2E) — must either run on staging or be explicitly deferred in the plan file with rationale (e.g. "Phase 10 held until user authorization per spec §6")
- ❌ Opening a PR while test plan tiers are still FAIL or unjustified-SKIP — the merge readiness gate exists specifically to prevent this
- ❌ Trusting chat-text signals (`last_assistant_tail`, "Exiting.", JSONL silence) over branch HEAD when classifying session lifecycle — branch movement is the authoritative signal
- ❌ Answering "what's remaining in Spec X" from an issue tracker body — read the spec file directly; tracker bodies decay
- ❌ Letting a session retire with "now-runnable-post-deploy" markers still DEFERRED-skeleton — those markers are promises, must be redeemed before retire
- ❌ Conflating staging E2E (Tier 3a) with prod E2E (Tier 3b) — they're distinct markers; one covering "all E2E" hides scope
- ❌ Stating "PR #N merged" inside a generated prompt because a worker said so or a commit looks recent — `gh pr view <N> --json mergedAt,state` is the only authority. In a past incident a Codex orchestrator emitted "Pricing already merged" into a rebase prompt while the PR had never even been created (gh API was down at the time of the worker's claim).
- ❌ Treating subagent reports as canonical without re-running the final command in the lane's worktree — a worker's "done" with `/tmp/` paths or sandbox-blocked writes is not a deliverable. Re-validate per directive #10.7.
- ❌ State-miner re-emitting an unchanged session list — if survey == cache, return one line. Paying full agent cost on identical data is waste.
- ❌ Using desktop cross-session `send_message` inside an autonomous loop — its confirmation prompt is app-hardcoded; an unattended sender hangs. Mailbox files or headless respawn are the transports.
- ❌ Spawning a chip and calling the lane "autonomous" — a chip needs a human click to start. Autonomous lanes are headless (`claude -p` / `--bg`).
- ❌ A lane parking on "waiting for PR #N to merge" when it could stack its branch on #N and build now (§3a.1).
- ❌ Entering an unattended stretch without the pre-authorization ask (§3a.2) — discovering at 2am that the whole DAG roots on a human merge gate is a planning failure, not a gate failure.
- ❌ Polling wakes against a human-only gate — if only the human can open it, park with ONE wake at their expected return (§3a.3).
- ❌ A lane blind-retrying through a safety-classifier or model-outage window — 2nd identical denial → exit BLOCKED_ON_CLASSIFIER; orchestrator backs off ≥30 min.
- ❌ Piping a lane spawn (`spawn-lane … | tail`) or trusting exit 0 without the final JSON blob — the silent no-op signature.
- ❌ Putting the full local verify gate in a lane mission — lanes background it and die waiting; targeted checks + push + CI instead.
- ❌ One monolithic spec→implement lane — the runtime cap kills it; chunk by lifecycle step, resume from the branch.
- ❌ Trusting a lane's local worktree state as completion — `git ls-remote` the branch; unpushed = stalled.
- ❌ A spec/build lane behind a human MERGE gate run as a chip nudged on a heartbeat — it's still a headless lane that drives to green+READY and parks; chips are for the human's own judgment work only.
- ❌ The orchestrator running spec-review/implementation fan-outs itself — push them into the lane (a root session); orchestrator-side agents are for cross-lane state and audits.
- ❌ Reasoning machine-wide — counting foreign programs' sessions in your surveys, nudging lanes you didn't spawn/adopt, or reading another program's activity as your progress/stall. Filter to manifest membership first.
- ❌ Claiming an issue/path/branch without checking the other program manifests — or resolving a live-vs-live claim contest yourself instead of surfacing it to the user.
- ❌ Running an orchestrator without a program manifest — unregistered claims are invisible to sibling orchestrators, which manufactures the very collisions the protocol prevents.
