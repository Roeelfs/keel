> Grounded 2026-11-04 against sources current as of 2026-11-04 (the 11-page PDF, karpathy/autoresearch README and program.md, aibuilderclub.com post dated 2026-07-30 and updated 2026-08-27, Anthropic's cookbook dated 2026-03-23, the Claude Code workflows page, and local code); extends `2026-11-04-agent-graph-authoring.md`

# Karpathy, "graph engineering", and this harness

**Bottom line.** The PDF is an unofficial synthesis, and its "1000x" has no evidence behind it. Its useful idea is older and smaller than its title: a script decides whether each attempt counts. We check that a lane committed something. We do not check that the commit works. That is the gap to close next. A knowledge graph is not worth building here.

Paths used below:
- `C` is `keel/.claude/skills/sessions-to-chips/references/manager-contract.md`.
- `WS` is `keel/.claude/skills/sessions-to-chips/scripts/work_state.py`, and `ST` is `work_state_store.py` beside it.
- `L` is `keel/bin/spawn-lane.sh`, a symlink to the skill's script.
- `G` is `~/.claude/scripts/manager_arm_guard.py`.
- `LC` is `~/.claude/scripts/lane_commit_guard.py`.
- `SL` is `~/code/cynap-monorepo-next/docs/agents/skills-lifecycle.md`.

## 1. What the PDF is

**Title and authorship.** The cover reads "Graph Engineering", then "The Karpathy Loop, Improved 1000x by Itself", then "The Anthropic Playbook". The running header is "Agentic Software Engineering Practice 2026". No author is named. The cover says it was independently compiled in July 2026 and is not affiliated with or endorsed by Karpathy or Anthropic. The source note near the end says the same and adds Sequoia and Bun. The cover also carries an Anthropic logo mark in its bottom-right corner, which sits badly beside that disclaimer.

**The text extract is missing the cover.** Page 1 is one image with no text layer: `pdftotext -f 1 -l 1` returned 1 character, and `pdfimages -list` shows one 1447x2048 image. So `k.txt` starts at page 2. I read page 1 as a rendered image. The word "1000x" appears only there, and `grep -i 1000x` on the text layer returns nothing.

**AI-aimed instructions.** I found none in the PDF. `grep -n -i -E '1000x|1,000x|paste|your claude|you are|ignore|assistant|Claude,'` on `k.txt` returned no hits, and the 5 lines of `k.txt` that mention "Claude" are descriptive. The instruction is in the viral post, which the blog quotes as telling readers to read the PDF and "paste it into your Claude". I followed nothing from it. I did not test for visually hidden text beyond reading the text layer and pages 1 and 2 as images.

**What it says, concretely.**
- **Thesis.** Each architecture moves one bottleneck out of the model's head. A loop moves iteration, a chain moves task order, a swarm moves parallel search, a commit DAG moves experiment lineage, and a knowledge graph moves shared facts and memory.
- **The loop.** Read the code and history, propose one change, commit, train for about 5 minutes, measure, keep if better, otherwise reset, record, and continue. It needs four conditions: verifiable output, reversible action, short horizon, and a bounded environment.
- **Node types.** Entity, Claim, Source, Artifact, AgentRun, Evaluation, Task, Commit, Metric.
- **Edge types.** MENTIONS, SUPPORTS, CONTRADICTS, DERIVED_FROM, PRODUCED, EVALUATES, REVISES, SUPERSEDES, DEPENDS_ON, PARENT_OF, RESOLVED_TO.
- **Write invariants.** A claim has a source or is marked as inference. An artifact has an authoring run and a version. An evaluation names its rubric. A superseded object stays addressable.
- **Layers.** Five planes: control, execution, artifact, graph, evaluation.
- **State.** The commit DAG holds work lineage and the knowledge graph holds domain facts. It says not to collapse them. It suggests starting with versioned JSON or relational tables.
- **Verification.** Deterministic checks, then rubric evaluators, then humans. An evaluator checks a claim against graph edges and returns structured feedback naming the missing evidence. Query answers are graded on the path as well as the answer.
- **Stopping.** A declared budget per run: model calls, agents, concurrency, tool calls, wall clock, tokens, cost, retries, graph writes, and minimum evidence. On exhaustion, return the best artifact and the reason for stopping. Its sample reflection loop stops at 3 rounds. Its sample ratchet is `while True`.
- **Failure modes.** Metrics can be gamed. AgentHub is a sketch. Fan-out is expensive and errors correlate. Fragmenting coupled work lowers quality. A graph only reflects its corpus. A false entity merge contaminates every traversal. Automation scales a wrong objective.

**The blog's summary checked against the PDF.** The cover disclaimer is confirmed, and so is the page count. Two points need correcting.
- The blog's six steps belong to the viral post, not the PDF. The PDF's Table II has a different six: reflective loop, tool use, planning, multi-agent, persistent graph, swarm workflow. The PDF puts the swarm last and the graph before it. Worktrees are a note inside the multi-agent stage.
- The blog's trigger for a graph is that parallelism has become the bottleneck. The PDF's trigger differs: connected queries, evolving relations, provenance or shared world state. The PDF does agree that a graph is often unnecessary, and it says a relational table may be enough.

**Evidence grading.**

| Claim | Grade | Basis |
|---|---|---|
| Improved 1000x | Unsupported | Cover title only. No measurement in the body. The blog also found no benchmark |
| "The Anthropic Playbook" | False attribution | Anthropic's workflows page has 0 hits for `graph` and `DAG` (curl and grep, 2026-11-04). The cookbook does not cover agents, swarms or multi-agent memory |
| Graph as multi-agent shared memory, and PDF Table I's role per pattern | The author's own extrapolation | No cited source says this. A reasonable idea, but untested |
| Anthropic "independently shipped the production version" of AgentHub | Unsupported | Workflows keep state in script variables, with no shared commit graph |
| Autoresearch files, 5-minute budget, keep or reset rule, reset on no improvement | Confirmed | `program.md` and README fetched |
| Knowledge graph cookbook: extract, resolve, NetworkX MultiDiGraph, query | Confirmed | Cookbook page. It now names `claude-haiku-5-5`, and the PDF names `claude-haiku-4-5` |
| 16 concurrent and 1,000 per run | Confirmed | Earlier brief, `workflows.md` lines 355 and 358 |
| The workflow code sample | Wrong API | `gather`, `spawn(` and `tools.glob` each have 0 hits in `workflows.md`. The real calls are `agent()`, `parallel()` and `pipeline()`, and scripts have no direct file access |
| A 1,000-agent run costs tens of dollars | Unverified | `dollars` has 0 hits on the workflows page |
| Fig. 1 "knowledge graph schema" | Not a schema | Its boxes hold placeholder labels such as "Object Above" and "Text Bottom", and none are the PDF's node types |
| 99.8% tests on the Bun port | Confirmed | The Register |
| 750,000 lines in 11 days via dynamic workflows | Partly confirmed | The Register says over a million lines added and does not mention workflows. Only secondary sources tie it to workflows |
| 630 lines, 700 experiments, 20 kept | Unverified at source | Not in the README (grep, 2026-11-04). The PDF cites Fortune, which I did not read |
| AgentHub details | Unverifiable now | `gh repo view karpathy/agenthub` fails to resolve and the URL returns 404 (2026-11-04). Secondary sources say it went private |
| Karpathy's swarm and research-community quotes | Unverified at source | The post was not fetched. The README's opening passage is confirmed |
| Karpathy coined the term | False | The README has no "graph" (fetch summary and grep, 2026-11-04). The blog says he has not used it |

The content is mostly sensible once the title is removed. The Anthropic framing and the 1000x are marketing.

## 2. Practices compared with this harness

Absence probes run 2026-11-04 (`date` printed Wed Nov 4 12:21-12:24 IST):
- `grep -n -E 'max-turns|max-budget|json-schema' L`: no hits.
- `grep -n -E 'attempt' WS ST`: no hits.
- `grep -rIn -i -E 'keep.or.discard|keep_or_discard|git reset --hard|auto.?revert|ratchet'` over the sessions-to-chips skill, `spawn-lane.sh` and `codex-dispatch.sh`: no hits.
- `grep -n -i 'proof\|test' LC`: no hits.
- `grep -n -i memory ~/.claude/hooks/agent-prompt-normalizer.py`: no hits.
- `grep -rIl -E 'autoresearch|val_bpb'` over `keel/.claude`, `~/.claude/scripts` and `~/.claude/hooks`: no hits.

| # | Practice | Our equivalent | Verdict | Worth adding? |
|---|---|---|---|---|
| 1 | A script decides each attempt | `cynap-sandbox verify` receipt, `tooling/sandbox/cynap-sandbox:79,149-168`, at PR level. At lane level only HEAD movement, `L:79-85,321`, `LC:31-48` | partial | **Yes, the top item** |
| 2 | The verifier sits outside what the agent may edit (`prepare.py`, `evaluate_bpb`) | CI required checks are outside the branch's control only in part, since a lane can edit tests. `verifier.md:21-24` requires a test seen failing first, but only when that agent runs | partial | Yes, flag it inside item 1 |
| 3 | Keep or discard on the verdict | The manager grades by judgment, `C:932-938`, and can discard, `C:91`. Nothing mechanical; see the probe | partial | Yes, as "not accepted", never an automatic reset |
| 4 | One row per attempt (`results.tsv`) | `.events.jsonl` is free narration, `C:372`. `lane-parents.jsonl` has 730 rows with no outcome field. No attempt count | partial | Yes |
| 5 | A human-edited instruction file drives the loop (`program.md`) | No per-run file. The nearest are `C` (standing), the mission, the manifest `goal` which may be fuzzy (`C:319`), and the proof ledger (`SL:56`, `spec-test-plan/SKILL.md:77,89`). `improve-harness`'s `<date>-program.md` (`SKILL.md:39,54`) only shares the name: it is a plan the run writes | partial | No new file. The ledger already holds metric-like rows |
| 6 | Fixed time box and a kill rule (5 min, kill at 10) | `LEASE` flags a stall and stops nothing, `WS:40`. No turn or spend flag; see the probe | missing | Yes, old rank 5 |
| 7 | One mutable surface | Binding `paths`, `ST:34`, one writer per file set `C:809`. No merge-time check | partial | Yes, old rank 7 |
| 8 | Reversible by reset | One worktree per lane, and the lane may not push, `L:223` | have | No |
| 9 | Run without a human until stopped | Founder gates, `C:68`. Merge is prod | deliberately different | No |
| 10 | A ratchet over a fixed gold set | `~/.claude/scripts/replay-corpus.py:1-25` grades hook edits on real traffic with a baseline delta. `spec-test` is one-shot. Three marketing skills have `evals/evals.json` | partial | One bounded trial |
| 11 | A typed plan with `depends_on` and `success` per step | Edges: `blocked_by`, `WS:228`, frontier `WS:541`. Per-ticket bake flag `ST:33,112`. No per-node success check on a binding | partial | Add the check as a field, not a file |
| 12 | Artifact contract at each handoff | Named artifact `C:938`. Free string at `ST:34`. Schemas only inside spec-review | partial | Lower priority than item 1 |
| 13 | Criterion-level review verdicts | `verifier.md:21-24` VERIFIED, UNSUPPORTED or CONTRADICTED with a cited command | have | No |
| 14 | A commit DAG with hypothesis, metric and status on each node | Git plus `Session-Id` trailer. `lane-parents.jsonl` holds run-to-parent edges. No `children` or `leaves` | partial | Only the attempt row. We do not search alternatives |
| 15 | No main branch, no merge | Merge to main is the prod deploy | deliberately different | No |
| 16 | Message board between agents | Session messages, rule at `C:191-195`, red-main notices in #5121 | deliberately different | No |
| 17 | Workers write typed findings | **Lanes do not.** They return prose and artifacts; see the normalizer probe. Managers do: the typed `## VIEW` block with `decisions {supersedes}`, `findings`, `dead_ends`, `C:452-463`, `state_view.py:25`, present in 10 state files | partial | One optional field, inside rank 7 below |
| 18 | Persistent knowledge store | 733 memory files. `type` frontmatter on the files, `originSessionId` in 510 of 733. 1,292 `[[name]]` links, of which 163 do not resolve to a memory file (`edges2.py` in my scratch folder, 2026-11-04). Some are ticket IDs or ADR names by design | partial | A link check only, no graph |
| 19 | Claims carry a source or are marked inference | Merged-versus-baked language, and the derived ladder overrides a `done` line, `C:465`. `verifier.md:21-24` | partial | No more than today |
| 20 | Entity resolution | None. Ticket IDs, PR numbers and SHAs are already canonical | missing | No |
| 21 | Evaluator grounded in graph edges | The verifier cites commands and `file:line` instead | deliberately different | No. A command is stronger evidence than an edge |
| 22 | Task-specific context builder | `state_brief.py`, commit 50871dc says every wake starts from it. Not per lane | partial | No |
| 23 | Declared budget per run | Spec-review tiers and caps only (commit ad6fbf0). Nothing for lanes | partial | Two values only: turns and spend |
| 24 | On exhaustion, report the best artifact and why it stopped | Handoff note, `C:940-941`, prose rule | partial | Falls out of the attempt row |
| 25 | Five planes kept apart | Manager, lanes, PRs and outfiles, tracker plus memory, verifier and CI. `C:40-46` | have | No |
| 26 | Define the reducer before fan-out | `spec-review.workflow.js`, routing `C:538,560` (from the earlier brief, not re-read) | have | No |

## 3. What changes in the earlier ranked list

**The list had already moved when I checked it.**
- **Old rank 3 is built.** Commit b5c8667 (11:59 local) added the zero-commit check to Claude lanes, `L:321`, and `is_error` handling, `L:317-319`. ab1c3d4 documents the flag. It applies only with `--class implementation`, because the default class is `standard` (`L:45`). I did not measure adoption, since `lane-parents.jsonl` has no class field.
- **Old rank 4 is in shadow.** `~/.claude/settings.json:138` registers `lane-acceptance-shadow.py`. Its log has 10 rows, all class `other`, and none with `would_block`. It has graded no implementation lane yet, so it is unproven.
- **Old rank 2's repo half is merged.** #5121 has `mergedAt` 2026-11-04T09:34:57Z. Its body says live delivery is unverified, and that idle sessions are reachable only through a later prompt or their PR monitor. It covers red-main waiters only, not the generic waiter view.
- **Old rank 1 is unchanged, as the founder set it.** The log now has 928 rows, with 1 `empty_rearm` and 1 `human_gate_wake`. That is still too little to judge false positives.

**Retractions from the earlier brief.**
1. **"Most likely means agent graph authoring" was wrong.** The founder meant Andrej Karpathy and graph engineering. The open question about who "Andrew" was is closed.
2. **The brief compared the wrong half.** It treated a graph as a graph of agents, meaning who runs after whom. This material mostly means a graph of work and knowledge, meaning what was tried and what is known. So its 24-row table never tested attempts, verifiers or knowledge, and its one-line "the gap is enforcement, not structure" was too narrow. There is also a missing thing: a scripted definition of success per unit of work.
3. **"Graph engineering is the label for orchestrator-workers" is only one post's reading.** The PDF defines it as durable shared state in typed graphs. The brief should not have treated that label as settled.
4. **"Nothing has been changed" and rank 2 were stale when committed.** #5121 merged 16 minutes before the brief's commit (90e29e6, 11:50 local). I did not establish which state the brief's probes saw.
5. **"Our derived state avoids that class" overclaimed.** Bindings are durable rows with leases, `ST:33-34`, `WS:40,379-381`. We avoid the Invoker hazard because our lease flags a stall and gates nothing. It is not because all our state is derived. A lease that gates something would bring the hazard back.
6. **Row 23 missed `replay-corpus.py`.** That is a real fixed-corpus judge for hook edits, with a baseline. Row 21 is now stale, and row 19's count is now 47 hooks.

**"No declared graph file", tested both ways.**
- *Against the rejection.* The PDF's Week 1 stage is exactly a declared plan: JSON steps with `depends_on` and `success`, validated before running. "Anthropic has none" is true but weak, because nothing says Anthropic is the bar. The durable-ledger argument is also weaker than stated (retraction 5). And we do hold a declared success contract already, in the proof ledger (`spec-test-plan/SKILL.md:77,89`), so a declared artifact is not foreign here.
- *For the rejection.* The edges already live in Linear and `blocked_by` (`WS:228`), and the frontier is derived (`WS:541`). A second file of edges would give the rule two owners, which the global rules call a design defect. The PDF itself recommends a plan only when the path varies, and it allows tables instead of a graph.
- *Verdict.* The rejection stands for edges and is withdrawn for success checks. Add one field to a binding that points at a check. Do not add a graph file.

**The blog's "not until parallelism is the bottleneck", tested on us.** Its trigger has fired, since we run parallel lanes as normal: 730 lane rows. So that argument does not by itself excuse us from steps 4 to 6. Those steps still do not earn their cost. The coordination failures on record are about ownership and waiting, such as two sessions fixing one red main and #5111 sitting idle. Those are edges between sessions, and the tracker and #5121 are the right homes. I found no recorded incident caused by lanes lacking a shared domain graph. That absence comes from the two briefs' evidence, not a full transcript search.

**New ranked list.**

| Rank | Change | Old rank | Why here | Files | Size |
|---|---|---|---|---|---|
| 1 | Lane proof and attempt row: `--proof <argv>`, run by the launcher after the lane, one outcome row per attempt, and a flag at the third failure | New, absorbs the counter from old 5 | Moves the check from activity to result | `L:321`, `LC`, `WS:44`, `ST:33-34` | Medium |
| 2 | Wake checks block | 1 | Largest measured cost, 7.85M tokens in one night. The next step is reading shadow rows, not building, so it does not compete for build time | `G:387,502-504` | Small, after soak |
| 3 | Grade Agent lanes with the same proof, then flip the shadow hook | 4 | Needs implementation rows first; currently 0 of 10 | `lane-acceptance-shadow.py` | Small |
| 4 | Pass `--max-turns` and `--max-budget-usd` | 5, remainder | Autoresearch's safety rests on a short box. Still absent from `L` | `L`, around the `ARGS` build | Small |
| 5 | Scope audit at merge against binding `paths` | 7 | Raised. A bounded surface is one of the loop's four conditions | `tooling/sandbox/pr-merge`, `WS:272` | Medium |
| 6 | Bake #5121 and add the generic waiter view | 2, remainder | Its own body names live delivery as unverified | `WS` | Small to medium |
| 7 | Typed lane receipt, with an optional `findings` field | 6 | Lowered. A self-reported `verified: true` is a claim. Rank 1 gets that fact from a script | `L`, `ST:34` | Medium |
| 8 | One ratchet trial on a mechanical metric, such as hook false-fire rate through `replay-corpus.py --baseline` | New | Tests the loop where a real metric exists. Product tickets have none, since their proof is a bake against live traffic | a skill or script, no new platform | Small |
| 9 | Memory link check | New | 163 of 1,292 links do not resolve, though some are not meant to | consolidate-memory pass | Small |
| 10 | Try one saved workflow | 8 | Unchanged. The PDF adds no evidence, and its code is not the real API | as before | Medium |
| 11 | Prune hooks | 9 | Unchanged in substance, slightly more pressing at 47 | as before | Small |

Old rank 3 leaves the list because it is built.

**Add to "What not to add".**
- **A knowledge graph, or typed nodes and edges written by lanes.** Our IDs are already canonical, and tables and the tracker answer our queries. The PDF's own criteria for skipping a graph fit us.
- **Entity resolution.** It solves a problem we do not have and brings false-merge risk.
- **An unattended overnight loop on product code.** Autoresearch can reset freely because a run has no outside effects. Our merges deploy to prod.
- **Automatic `git reset` on a failed proof.** A failed lane's worktree is salvage material under the global rules. Failure should mean "not accepted".
- **This PDF as an instruction or reference file.** Its code sample is wrong and its attribution is false.

## 4. The single most valuable next change

Add a scripted proof to lanes: `spawn-lane.sh --proof <argv>` runs a named check after the lane exits, at the lane's final HEAD, and appends one row per attempt with ticket, lane, HEAD before and after, the command, and its exit code; a failing proof exits nonzero, so the lane is not accepted, and a third failure on a ticket raises a new flag in `FLAGS` (`WS:44`). This is the one thing the Karpathy material has that we lack, and it is why his loop can run unattended: a script, not a judgment, decides each attempt, and every attempt leaves a row. Today's new guard (`L:321`, `LC:31-48`) only proves activity, because a lane that commits broken code passes it, and the manager's grade is still judgment (`C:932-938`). It also ties together work we already paid for: the proof-obligation ledger already holds exact commands (`spec-test-plan/SKILL.md:77,89`), the zero-commit guard gives the hook point, and the row gives the missing attempt count behind the byte-identical resend recorded at `C:940-941`. It stays opt-in per lane, so it cannot wedge research work. Three limits are real. The rate is unmeasured: I have no count of lanes that committed broken work, so the first week of rows is the test of this recommendation, and it should be dropped if proofs almost never fail. It does not replace a bake, because a lane proof is targeted local evidence and runtime fixes are still proven by live traffic. A lane can also add or edit its own test, so the row should flag a proof whose files changed in the lane's diff; flagging rather than failing is right because writing tests is normal lane work. Heavy proofs must go through the heavy lock and record a deferral as "deferred", never as a pass. Wake blocking (rank 2) has the larger measured cost, but its next step is waiting on shadow rows, so this is the most valuable thing to build now.

## Could not verify

- Whether the PDF hides text visually. I read the text layer of all pages and only pages 1 and 2 as images.
- The viral post itself. I know it only through the blog's quotes.
- AgentHub's contents, because the repository is unavailable. Karpathy's quoted posts, the Fortune piece, and PDF references [8] and [11] were not read.
- Exact wording in the README and `program.md`. I read them through a fetch summary and targeted greps, not line by line.
- How many lanes pass `--class implementation`, and whether a proof gate would catch anything.
- #5121's live delivery. Its own body says this is unverified.

## Sources

Fetched 2026-11-04: https://github.com/karpathy/autoresearch, https://raw.githubusercontent.com/karpathy/autoresearch/master/program.md, https://raw.githubusercontent.com/karpathy/autoresearch/master/README.md, https://www.aibuilderclub.com/blog/graph-engineering-karpathy-loop, https://platform.claude.com/cookbook/capabilities-knowledge-graph-guide, https://code.claude.com/docs/en/workflows.md, https://www.theregister.com/devops/2026/05/14/anthropics-bun-rust-rewrite-merged-at-speed-of-ai/5240381. Search results only: https://the-decoder.com/bun-ditches-zig-for-rust-with-help-from-claude-fable-5-writes-over-a-million-lines-of-code-in-11-days/, https://themenonlab.blog/blog/agenthub-karpathy-github-for-ai-agents. GitHub API: autoresearch has 99,211 stars and 13,680 forks, last pushed 2026-03-26; `karpathy/agenthub` does not resolve.
