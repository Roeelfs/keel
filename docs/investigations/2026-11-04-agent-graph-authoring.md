> Grounded 2026-11-04 against sources current as of 2026-11-04 (Claude Code docs and changelog through 2.1.318, Anthropic essays, GitHub issue states, and local code); supersede on re-investigation of this slug

# Investigation: authoring graphs of agents that manage agents, compared with this harness

## Answer

**The name does not exist at Anthropic.** No page in the Claude Code docs index uses the word "graph", and neither Anthropic essay uses "agent graph" or "graph authoring". "Andrew Graph authoring" most likely means "agent graph authoring". The closest real feature is **dynamic workflows**, whose page is titled "Orchestrate subagents at scale with dynamic workflows". "Graph engineering" is a third-party label. A video with that title cannot be ruled out, because the search tool does not index talk titles.

**How far we are.** Of 24 guidance points, we have 5, are partial on 12, are missing 3, and differ on purpose on 4. We are ahead on state kept outside the agent, human gates, and lane isolation. We are behind on mechanical control: nothing caps a lane's turns or spend, nothing counts attempts, and the checks that would stop empty wakes only log. The gap is enforcement, not structure.

**What to do first.** Make the two wake checks block, push a message when a dependency lands, and give Claude lanes the same zero-commit check Codex lanes already have. Do not adopt agent teams, do not port managers into workflow scripts, and do not build a graph file. Reasons are below.

## Problem frame

The founder wants agents managed the way Anthropic says they should be. Anthropic does not publish one standard for this. It publishes five separate approaches and a set of engineering rules. This harness runs two layers that share no schema: long-lived manager sessions driving lanes, and short-lived Workflow scripts inside a turn. Local transcript mining counted 5,260 Agent calls, 3,284 spawn-lane launches, 1,525 Workflow calls and 994 codex-dispatch launches (`scratchpad/localangle/count.py`, medium confidence, tool_use blocks including subagent transcripts).

Anthropic's docs do not describe a manager that lives for days and waits on CI, deploys and a human. So the standard covers our lanes and fan-outs well, and it covers our manager layer only by analogy.

## Corrections to the earlier lane findings

I re-read the code and primary pages before writing this. Five earlier findings were wrong or stale.

1. **The Codex fan-out cap is gone.** The earlier lanes called "fan-out of 5" a prose-only rule. The founder removed the cap today: `manager-contract.md:808` and `~/.claude/CLAUDE.md:122` both say no cap, and the only limit is the provider's quota wall. A session started earlier may still have the old rule loaded. Adding a cross-manager cap is therefore off the list.
2. **Nested dispatch is enforced by the product, not only by prompt text.** `~/.claude/settings.json:8` sets `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=1`. At the limit Claude Code withholds the `Agent` tool (`sub-agents.md` line 1059), and `Workflow` is on the list removed from every subagent (`sub-agents.md` lines 425-438). The leaf line in `agent-prompt-normalizer.py:106` is now mostly redundant for Agent subagents. Headless lanes are root sessions and are not bound by this (`manager-contract.md:624-625`).
3. **`work_state.py` exists.** One lane's `find` missed it because `~/.claude/skills/sessions-to-chips` is a symlink. It is at `keel/.claude/skills/sessions-to-chips/scripts/work_state.py`, 764 lines.
4. **A missing `--cwd` already fails loudly.** `spawn-lane.sh:41` sets `set -euo pipefail`, and line 70 runs the `cd`. The real gap in the Claude path is narrower: a run that exits 0 with HEAD unchanged. Lines 288-301 check only for a dead login. That path also has no empty-output check, contrary to one earlier claim.
5. **`turn_is_empty_rearm` is wired, but only to a log.** `wake_checks` calls it (`manager_arm_guard.py:359-375`) and `decide()` at line 387 does not use the result. The log holds 876 rows: 121 `ready_not_dispatched`, 110 `unbound`, 1 `empty_rearm` (`jq -r '.would_block[]?' ~/.claude/analytics/manager-arm-guard.jsonl | sort | uniq -c`, run 2026-11-04). The check landed today, so one row says nothing about its accuracy yet.

## What Anthropic publishes

Line numbers refer to the `.md` copies fetched on 2026-11-04. Everything in this section is **(vendor-attested, not independently corroborated)**, unless it says otherwise.

**The map of approaches.** `agents.md` compares five: subagents, agent view (research preview), agent teams (experimental, off by default), projects (public beta), and dynamic workflows.

**The core distinction is who holds the plan.** In subagents, Claude decides turn by turn and results land in its context. In agent teams, the lead decides and results sit in a shared task list. In workflows, a script decides and results sit in script variables, so only the final answer reaches context. Scale for workflows is "dozens to hundreds of agents per run".

**Workflow primitives and limits (`workflows.md`).**
- A workflow is a JavaScript script using `agent()`, `pipeline()`, `parallel()`, `phase()`, `log()`, `args` and `export const meta`.
- It runs 16 concurrent agents by default, set from 1 to 256 by `CLAUDE_CODE_WORKFLOW_MAX_CONCURRENT_AGENTS` (line 355).
- A single `parallel()` or `pipeline()` call takes up to 4,096 items, and a longer list is rejected, not truncated (line 357).
- A run allows 1,000 agents in total (line 358).
- `Date.now()`, `Math.random()` and a no-argument `new Date()` throw, so a relaunch repeats the same calls (line 324).
- A script has no `import()` and no direct file or shell access.
- There is no mid-run user input. For sign-off between stages, run each stage as its own workflow (line 352).
- `schema` gives typed output. Output that fails validation five times fails the call (line 311).
- A silent agent restarts from its prompt, up to six attempts (lines 411-417).
- `agent()` resolves to `null` on an unrecoverable API error (line 305).
- Resume is same-session only and replays in order until the first changed prompt. The page carries no experimental label (line 11).

**Not on the public page.** `isolation: 'worktree'` for `agent()` and a nested `workflow()` call appear only in the bundled `/workflow-authoring` skill text. Probe: `grep -n -E 'isolation|worktree|nested|workflow\(' workflows.md` returned no hits on 2026-11-04.

**Agent teams (`agent-teams.md`).** The plan is a task list with dependencies that unblock automatically. Mailbox delivery is automatic, and "The lead doesn't need to poll" (line 325). `TeammateIdle`, `TaskCreated` and `TaskCompleted` hooks block with exit 2. The limits matter: no nested teams, one team per session, no `/resume` of in-process teammates, and status can lag (lines 490-500). Teams are unavailable in `-p` and SDK sessions, and teammates are not worktree-isolated.

**Subagents (`sub-agents.md`).** Default depth is three layers below the main conversation (line 1059). Default concurrency is 20 per session (line 1086). `isolation: worktree` is available in frontmatter.

**Engineering rules (`multi-agent-research-system`, `building-effective-agents`).**
- Start with the simplest solution and add complexity only when needed.
- Agents use about 4x the tokens of chat, and multi-agent systems about 15x.
- Scale effort: one agent with 3-10 calls for simple tasks, 2-4 subagents for comparisons, more than 10 for complex research.
- Each subagent needs an objective, an output format, tool guidance and clear boundaries. Vague tasks caused duplicate work.
- Early failures included 50 subagents for a simple query and endless searching.
- Subagents store work externally and return lightweight references. The lead saves its plan to memory.
- Get ground truth from the environment at each step, pause for humans at checkpoints, and set stopping conditions such as a maximum iteration count.
- The research essay gives no numeric retry budget, so ours must be our own choice (read via fetch summary, not a full-text search).

**Enforcement rules (`best-practices`).**
- If emphasis on a CLAUDE.md line keeps failing, "that's a sign the line belongs in a hook" (line 67).
- If you reach forty hooks and deny rules, most are probably preferences (line 368).
- A Stop hook with exit 2 sends Claude back to work, and eight blocks in a row are overridden (line 288).
- An unattended run must answer five questions: what done looks like, how it checks itself, what it may touch, what stops it (`--max-turns`, `--max-budget-usd`), and who signs off (line 535).

**The third-party name (corroborated).** An AI Builder Club post says "Graph engineering is the label" for what Anthropic calls orchestrator-workers. A news.lavx.hu article says workflows build a DAG of sub-agent nodes. That second claim is **(unverified)**: it is one secondary source, and Anthropic's page does not use the word.

## Comparison with this harness

Every guidance point below is (vendor-attested, not independently corroborated). Paths: `C` is `keel/.claude/skills/sessions-to-chips/references/manager-contract.md`, `S` is its `scripts/` directory, `G` is `~/.claude/scripts/manager_arm_guard.py`, `L` is `~/.claude/scripts/spawn-lane.sh`, `D` is `~/.claude/scripts/codex-dispatch.sh`.

| # | Guidance point | Our equivalent | Gap verdict |
|---|---|---|---|
| 1 | A script holds the plan for bounded fan-out | `keel/.claude/skills/spec-review/scripts/spec-review.workflow.js`, `S/mine_workflow.js`, routing at `C:538,560`. No saved workflows: `ls ~/.claude/workflows keel/.claude/workflows <repo>/.claude/workflows` found none, 2026-11-04 | partial |
| 2 | A lead agent decides turn by turn | Manager root owns the control plane, `C:40-46`, but its state lives on disk and it re-derives on each wake | deliberately different |
| 3 | The plan is saved outside context | Manifest, `.events.jsonl`, `.state.md` with AT-WAKE, `C:308-386` | have |
| 4 | Task dependencies unblock automatically | `blocked_by` and `frontier` in `S/work_state.py:228-246,532-541`, derived at wake, nothing pushed | partial |
| 5 | Messages are delivered, the lead does not poll | Rule at `C:191-195`, founder 2026-11-04. It is prose. No code sends it on landing | partial |
| 6 | Each worker gets objective, format, tools, boundaries | Artifact named in the mission, `C:930-936`. `expected_files` has zero hits in `~/.claude/hooks/*`, `S/*`, `SKILL.md` and `C` (grep, 2026-11-04) | partial |
| 7 | Typed worker output with validation | 8 `schema:` uses in `spec-review.workflow.js`. Lane `artifact` is a free string, `S/work_state_store.py:34`. `L` passes no `--json-schema` (grep) | partial |
| 8 | Hand off by reference, not by value | Outfiles in `D`, return contract at `agent-prompt-normalizer.py:109` | have |
| 9 | Scale effort to the task | Spec-review tiers, `~/.claude/CLAUDE.md:71`. No general scaling rule for lanes; `C:808` says dispatch all at once | partial |
| 10 | Ground truth, grade the artifact | `C:930-943`. Codex zero-commit check `L:225-243`, artifact floor `D:330-349`, quota-banner guard `lane-artifact-guard.py`. Claude path checks only auth, `L:288-301` | partial |
| 11 | Stopping conditions, max turns, spend cap | `LEASE` flags stalls but stops nothing, `S/work_state.py:40`. `L` has no `--max-turns` or `--max-budget-usd` (grep, 2026-11-04) | missing |
| 12 | Retry budgets per worker | Policy only, `C:936-941`. Grep for `retry\|attempts?\|max_attempt` in `S/work_state.py` and `S/work_state_store.py`: zero hits. Only the model ladder is automatic, `D:244-254` | missing |
| 13 | Resume from a journal | Hand-written AT-WAKE and handoff notes, `C:936-939`. Survives across sessions, which product resume does not | deliberately different |
| 14 | Human checkpoints; a relayed message is not consent | Merge on the go-ahead, `C:68`. The memory rule that bounced 5 of the founder's "go" messages was corrected 11-04 | have |
| 15 | Concurrency limits, 16 per run and 20 per session | No Codex cap by founder ruling, `C:808`, `~/.claude/CLAUDE.md:122`. Lane rows are global, `S/work_state_store.py:21` | deliberately different |
| 16 | Nesting up to three layers by default | Depth 1, `~/.claude/settings.json:8`. Two-level graphs only | deliberately different |
| 17 | Worktree isolation, partition files | `L:34-35,249`, one writer per file set `C:809`, nested-worktree refusal `~/.claude/hooks/bash-git-guards.sh:5`. Base-pin stays prose | have |
| 18 | A rule that keeps failing belongs in a hook | Hooks cite measured incidents, for example `background-log-poll-guard.py:1-25`. Rules with no hook: effort line (`normalizer` has no effort check), base-pin, scope audit | partial |
| 19 | Keep the enforced set small | 45 hook commands: `jq '[.hooks[][]?.hooks[]?] \| length' ~/.claude/settings.json`, 25 on PreToolUse | partial |
| 20 | Stop hook checks completion | Arm check is live, `G:387`. Wake checks and flags are log-only, `G:359-375,502-504` | partial |
| 21 | Hook gates on worker completion | Hook events registered: PermissionDenied, PostToolUse, PreToolUse, SessionStart, Stop, StopFailure, UserPromptSubmit. There is no SubagentStop or TaskCompleted hook (`jq '.hooks \| keys'`, 2026-11-04) | missing |
| 22 | Say what a run may touch | `L:44` defaults to `bypassPermissions`. Per-repo guards apply. No per-lane path allowlist | partial |
| 23 | Evaluate on real cases with a judge | `verifier` verdicts, `~/.claude/agents/verifier.md`. Mechanics tests, `S/test_advance_tick.py`. No fixed set of real manager runs was found (not probed exhaustively) | partial |
| 24 | Use multi-agent only when value covers cost | Token economy rules and measurements in `~/.claude/CLAUDE.md` §Token & Context Economy | have |

**Outside Anthropic's guidance.** Codex lanes get a small hook set: `~/.claude/hooks/codex-hooks.json.in` defines only PreToolUse, SessionStart and SubagentStart. Red-main ownership and the founder-gate model also have no official analogue.

## Ranked additions

Ranked by measured cost removed per unit of work. Nothing has been changed. The evidence for 1 and 2 comes from one manager over one night (`/private/tmp/claude-501/h1/mine-synth/report.md`, a volatile path).

| Rank | Add | File to change | Incident or metric | Size |
|---|---|---|---|---|
| 1 | Make `empty_rearm` and `human_gate_wake` block, with a reason that says who to message | `~/.claude/scripts/manager_arm_guard.py:387,502-504,549-555` | 14 of 20 fired wakes only re-checked. 7.85M tokens over 27 calls from 02:06 to 08:14. 8 identical re-arms accepted | Small |
| 2 | Push an edge on landing: record who waits, message them when the fix lands, and show waiters in the tick | `tooling/sandbox/main-health-relay.mjs`, `tooling/sandbox/pr-merge` (repo); `S/work_state.py` for the generic waiter view | #5111 sat idle 7 h 46 after #5115 landed at 00:47:38. Related to CYN-3398 | Medium |
| 3 | Fail closed on Claude lanes: an implementation class that exits 3 when HEAD is unchanged, and a read of `is_error` | `~/.claude/scripts/spawn-lane.sh:225-243` copied into `:288-301` | `C:930-935` records 66 turns and $7.24 ending with nothing. The `L` comment records exit 0, 0 bytes, zero work | Small |
| 4 | Add a SubagentStop acceptance gate for Agent lanes, matching rank 3's rule | `~/.claude/settings.json`, new hook beside `lane-artifact-guard.py` | The guard catches only the quota-banner class: 41 lanes across 10 sessions | Small |
| 5 | Add stop conditions and an attempt counter: pass `--max-turns` and `--max-budget-usd`, count carriers per ticket, raise a new flag at the third attempt | `L:248`, `S/work_state.py:44`, `S/work_state_store.py` | One prompt was resent byte-identical 5 times (`C:930-941`). `FLAGS` has no attempt flag | Medium |
| 6 | Typed lane receipt using `--json-schema`: artifact, HEAD, verified, unverified, next action | `L:248`, binding field at `S/work_state_store.py:34` | Grading depends on the manager's judgment of a free string. Codex has no verified equivalent yet | Medium |
| 7 | Scope audit at merge: compare the PR diff with the binding's `paths` | `tooling/sandbox/pr-merge`, `S/work_state.py:272` already intersects paths | Contamination class #478/#479/#481, salvage failed 3 of 3. `expected_files` has no code gate | Medium |
| 8 | Try one saved workflow for an agent-only stage run with no human gate, then decide | New `keel/.claude/workflows/<name>.js`, routing at `C:538` | Session total 78.5M tokens, mostly re-reads. Limited to Claude agents and same-session resume | Medium |
| 9 | Prune: remove the redundant leaf line for Agent subagents and audit hooks that never fire | `agent-prompt-normalizer.py:106,197-217`, `~/.claude/settings.json` | 45 hooks against Anthropic's forty warning. Depth 1 already enforces leafness | Small |

**Founder decision owed on rank 1.** The founder set these checks to shadow today. Recommended: leave them in shadow through one more live manager night, read `would_block` for false positives, and then flip. The reason is that only one `empty_rearm` row exists so far.

**Rank 1 design note.** A refused re-arm must have an exit, or it collides with the arm check that requires a wake. The block reason should name the owner to message (`C:191-195`). A message to that owner should then count as the exit. The earlier loop-inviting wake row is already narrowed to events no session owns (`C:206`).

## What not to add

- **Agent teams.** They are experimental, unavailable in `-p`, have no nesting and no resume, and are not worktree-isolated. They cannot host our lanes. Borrow the hook idea only.
- **Managers as workflow scripts.** A workflow has no mid-run input, cannot wait on CI or a deploy, and resumes only in its own session. Managers exist for exactly those gaps.
- **A declared graph file or a shared schema across layers.** Anthropic has none. `work_state.py` already derives ready work from tracker edges. A durable dispatch ledger brings its own failures: Invoker documents a stale row leasing a merge gate before its prerequisite.
- **A global Codex cap.** The founder ruled this out on 2026-11-04.
- **Deeper nesting.** Depth 1 is a working guard and two levels are the standing rule.
- **Recurring wakes or a polling heartbeat.** The standing rule forbids them.
- **Our own workflow journal.** The product fixed this: 2.1.305 stopped re-running finished `pipeline()` and `parallel()` agents, and 2.1.318 stopped re-running finished agents after a usage limit. We run 2.1.317 (`claude --version`), so 2.1.318 is a free pickup.
- **An effort-declaration hook.** No incident supports it, and we are already over forty hooks.

## Elevation

These go beyond Anthropic's docs. Each is **(vendor-attested, not independently corroborated)**, where the "vendor" is the repo's own code, which I grepped on 2026-11-04.

- **Attempt budget.** `eddieran/lindy-orchestrator` reads `max_retries_per_task` (`orchestrator.py:261`) and has `_handle_retry` (`:784`). `gabrielkoerich/orchestrator` stops on `max_attempts` and flags a retry loop when the same error repeats three times (`scripts/run_task.sh:365-372`). This supports rank 5.
- **Fail-closed artifact gate.** The AWS sample infers failure from "No commits, no PR, or agent reported error". It is the clearest published version of rank 3, though it is not a Claude Code harness.
- **Wave scheduling.** lindy caps workers with a thread pool (`:311`) and uses `as_completed` (`:415`). Its delivery check (`:677`) was reported as warn-only; I confirmed the call site, not the behavior.
- **Durable ledger hazard.** Invoker's incident doc shows the cost of a lease table. Our derived state avoids that class.

## Contrarian evidence

- **Anthropic says to add complexity only when needed.** Every row above adds machinery to a harness already past the forty-hook warning. Ranks 1, 3 and 9 change or remove code more than they add it. Ranks 5 to 8 should wait for evidence.
- **The wake evidence is one session.** The 14 of 20 figure and the 7 h 46 stretch come from one manager on one night. Treat them as a strong signal, not a rate.
- **Push edges can fail silently.** #75438, #104789 and #102778 are open reports of lost or inert completion notices. The mining report also saw no child notifications from 09:10 to 13:05 on 11-03, cause unknown. So rank 2 must not remove the single event-bound fallback wake.
- **A refused re-arm could strand a manager** if the message it sends is lost. That is why the design note matters and why shadow data comes first.
- **Blocks can be overridden.** A Stop hook that blocks eight times in a row loses. Our guard blocks once per turn, so this should not bite, but the flip must keep that property.
- **Workflows may beat our lanes on cost for pure fan-out.** That argues for trying rank 8 sooner. I have no measurement either way.

## Tips and gotchas

- `agent()` returning `null` does not say why, so a script cannot tell a rate limit from a login failure (#100380, open). The tool also keeps dispatching queued agents after a rate-limit stop (#93728, open).
- A usage-limit pause works only in interactive claude.ai sessions, not `-p` or SDK (`workflows.md` lines 398-402). Our headless lanes fail instead of pausing.
- `isolation: worktree` branches from the default branch by default, not the parent HEAD (`sub-agents.md` line 313). Do not assume it stacks on your branch.
- Open worktree reports to watch: #92573 (slot reuse with file loss), #104928 (resume runs in the main checkout), #104026 (concurrent `git worktree add`). Changelog 2.1.311 fixed worktree removal under a running child, though #94221 is still open. Our own reaper hazard is separate: `reference-reaper-removes-merged-locked-worktrees.md` in memory.
- Background subagents can die on OAuth expiry while the main session continues (#106631, open). Headless `-p` reportedly burns about 1.8x more of the window (#97074, reporter claim, unverified).
- Agent teams on: any named `Agent` call becomes a teammate. Leave that variable off.
- `--max-budget-usd` uses a client-side estimate (`cli-reference.md` line 105). Treat it as a brake, not an invoice.
- **Absence probe on notification fixes.** `grep -n -i notification changelog.md`, filtered to agent lines, found 2.1.299 (better wording) and 2.1.260 (a SendMessage wake fix), but no line saying dropped completion notices are fixed. #45581, #68997, #69732 and #78338 are closed. Whether they are truly fixed is **(unverified)**.

## Dropped or downgraded

- `claudeissues.com` links returned no HTTP response to curl on 2026-11-04. I dropped them and cite the same issue numbers on GitHub.
- The changelog claim "2.1.307 fixed journal replay" was wrong: the line is in 2.1.305. The claim "2.1.314 capped continuations at three" had no matching line, so I dropped it.
- The unread OSS repos surfaced by repo search (multi-agent-runner, MrRobot, chipping-orchestrator, gram, yardsort, delilah) are not cited, because nobody inspected their code.
- The Codex "self-serialize" inference had no transcript behind it, and the cap it concerned is gone.

## What to research next

- Read a week of `would_block` rows after shadow data accumulates, and measure false positives for `empty_rearm`.
- Measure how many of our lanes would have tripped rank 3, by replaying past lanes in `~/.claude/state/lane-parents.jsonl` against their branch HEADs.
- Check whether `codex exec` has a verified output-schema flag, which rank 6 needs for parity.
- Compare the token cost of one real spec-review stage run as a workflow with the same work done through lanes.
- Find out why child notifications stopped from 09:10 to 13:05 on 11-03. The mining report points to the desktop host.
- Ask the founder whether "Andrew" was a person or a talk. If it was, this brief should be rechecked against that source.

## Sources

Live on 2026-11-04 (HTTP 200):

- https://code.claude.com/docs/llms.txt
- https://code.claude.com/docs/en/workflows.md
- https://code.claude.com/docs/en/agents.md
- https://code.claude.com/docs/en/agent-teams.md
- https://code.claude.com/docs/en/sub-agents.md
- https://code.claude.com/docs/en/agent-sdk/subagents.md
- https://code.claude.com/docs/en/agent-sdk/typescript.md
- https://code.claude.com/docs/en/best-practices
- https://code.claude.com/docs/en/changelog
- https://code.claude.com/docs/en/cli-reference.md
- https://code.claude.com/docs/en/hooks.md
- https://www.anthropic.com/engineering/multi-agent-research-system
- https://www.anthropic.com/engineering/building-effective-agents
- https://www.aibuilderclub.com/blog/graph-engineering-with-claude-code
- https://news.lavx.hu/article/dynamic-workflows-bring-parallel-agent-coordination-to-claude-code
- https://github.com/eddieran/lindy-orchestrator
- https://github.com/gabrielkoerich/orchestrator
- https://github.com/Neko-Catpital-Labs/Invoker/blob/HEAD/docs/incidents/2026-06-03-stale-downstream-launch-dispatch.md
- https://aws-samples.github.io/sample-autonomous-cloud-coding-agents/architecture/orchestrator/
- https://github.com/anthropics/claude-code/issues/ followed by 45581, 68997, 69732, 78338, 75438, 104789, 102778, 94221, 92573, 104928, 104026, 100380, 93728, 106631, 97074

Local code, read 2026-11-04:

- `/Users/roeealfasi/code/keel/.claude/skills/sessions-to-chips/references/manager-contract.md:40-46,68,191-195,206,308-386,538,560,624-625,808-809,930-943`
- `/Users/roeealfasi/code/keel/.claude/skills/sessions-to-chips/scripts/work_state.py:40,44,228-246,272,532-541`
- `/Users/roeealfasi/code/keel/.claude/skills/sessions-to-chips/scripts/work_state_store.py:21,34`
- `/Users/roeealfasi/code/keel/.claude/skills/spec-review/scripts/spec-review.workflow.js`
- `/Users/roeealfasi/.claude/scripts/spawn-lane.sh:34-35,41,44,70,225-243,248-249,288-301` (symlink into keel)
- `/Users/roeealfasi/.claude/scripts/codex-dispatch.sh:244-254,330-349`
- `/Users/roeealfasi/.claude/scripts/manager_arm_guard.py:355-375,387,502-504,549-555`
- `/Users/roeealfasi/.claude/hooks/agent-prompt-normalizer.py:106,109,197-217`
- `/Users/roeealfasi/.claude/hooks/lane-artifact-guard.py:1-24`
- `/Users/roeealfasi/.claude/hooks/bash-git-guards.sh:5`
- `/Users/roeealfasi/.claude/settings.json:8`
- `/Users/roeealfasi/.claude/CLAUDE.md:71,122`
- `/Users/roeealfasi/.claude/analytics/manager-arm-guard.jsonl` and `/Users/roeealfasi/.claude/analytics/lane-deaths.jsonl`
- `/private/tmp/claude-501/h1/mine-synth/report.md` (volatile)
