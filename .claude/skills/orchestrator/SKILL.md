---
license: MIT
name: orchestrator
description: Cross-session orchestrator pattern — orchestrate ONE program (a goal/target) across its own lanes, including fully autonomous stretches (headless no-prompt lanes, un-gated-frontier planning). Program-scoped, never machine-scoped — multiple orchestrators coexist on one machine via program manifests + an ownership/collision protocol. Surfaces state, coordinates conflicts, spawns lanes, never implements directly. Use when running 3+ parallel sessions toward one target or driving a big project autonomously.
---

# Orchestrator

You orchestrate **ONE PROGRAM**: track its lanes, catch conflicts before they hit main, spawn lanes (headless / agent / Codex / chip), hold every terminal gate, surface decisions. You never implement code yourself.

Depth lives in `references/` and is **not** auto-loaded:

- **Read `references/lifecycle.md` before planning, spawning, or grading a spec-class lane** — the canonical **define → build → verify-release** lifecycle, modes, handoff, and terminal evidence gate.
- **Read `references/merge-and-retire.md` before merging any lane PR or signing off a retire** — project-authorized merge, keyed post-merge proof, retire checklist.
- **Read `references/codex-runtime.md` first when `$CLAUDE_SESSION_ID` is unset** — you are hosted by Codex CLI and most verbs below do not exist there.

## Model topology — cheap root, intelligent escalations

- **Long-lived Codex root:** use `gpt-5.6-terra` at Medium. The root pays for accumulated context on every turn, so it coordinates, integrates, and keeps state on the everyday tier.
- **Sol escalation:** use a fresh, bounded `gpt-5.6-sol` lane only for architecture with irreversible consequences, security/trust boundaries, hard RCA, or final adversarial adjudication. Give it no history or the smallest evidence slice, one decision artifact, and a stop condition.
- Return the decision artifact to the Terra root. When a Sol planning phase ends, start or resume a fresh Terra-medium implementation task instead of extending the Sol session through execution and review.
- Routine implementation and topical review stay on Terra. Native mining, file search, and deterministic procedure use Terra-low because the collaboration API currently exposes only Terra and Sol. An explicit user model choice supported by the callable surface overrides this default.

## Root control plane, worker execution plane

The long-lived orchestrator root owns the **control plane**: state/ledger decisions, scope and target selection, product edits, failure interpretation, human/auth gates, and every production mutation. It may run small bounded read-only probes that complete in one tool call and immediately inform a decision.

The root does not retain the **execution plane** for deterministic command batches. When a targeted pass would require process continuation, retain large raw output, or run the full project gate, dispatch one fresh native Codex procedural worker for the whole pass using `prompts/procedural-worker.md`. Never spawn one child per command. The worker is Terra-low with no inherited history; the root grades its pointer artifact and makes the next decision.

Source-mutating formatters, dependency-changing installs, migrations, and product fixes belong to the build phase, not the procedural worker. Interactive authentication and production mutations stay in the root even after authorization; post-mutation verification may use a worker.

## Owned child continuation invariant

A native `spawn_agent` owned by the current accepted task group is **internal work, not an external wait**. Before any final answer or handoff, the root must either consume and grade that child's terminal result, or interrupt it under terminal-stop, completion-mode scope pruning, or an expired explicit child lease. The root **must not emit a final answer** while an in-scope child is active and thereby require the user to reactivate the task.

A wait timeout is a progress boundary, not completion. Report the changed state in commentary and continue with latency-sized event waits while the child remains inside its lease. The child mission declares the lease up front; expiry causes one interrupt and continuation from its durable handoff/artifacts, never an unbounded wait loop.

## Goal command contract — bounded autonomy

On Codex, use the native goal commands only when the user explicitly asks for autonomous goal execution. Scope the goal to the **reachable authorized autonomy frontier**: the current accepted task group through the next known human, production, or external gate. A goal keeps that bounded work moving across automatic continuations and owned-child waits; it does not broaden scope, production authority, or approval.

Keep the goal active only while a safe, authorized action advances its objective. Each continuation selects one `next_forcing_function`; completed phases, PASS evidence, spent review slots, and unchanged failures remain terminal. Close the goal as soon as its frontier is genuinely achieved. An unexpected external blocker uses the native three-turn blocker audit with no repeated side effects, then stops. Explicit terminal stop still overrides the goal immediately. Read `references/codex-runtime.md` for the exact `create_goal` / `get_goal` / `update_goal` contract.

## Completion mode override

When the user says to stop review/testing/cycles **and** asks to finish, complete, finalize, proceed, or return residue as backlog, interrupt active review/test lanes and freeze accepted scope. Continue only the **current declared build task group**; its owned children remain subject to the continuation invariant above. Absorb no adjacent discovery and start no new review or test plan. If testing is explicitly forbidden, hand off the result as `UNVERIFIED`; otherwise run only the minimum project-required gate once. Then return completed artifacts, current state, owned failures, external blockers, and deferred backlog.

## Terminal stop override

Only explicit stop-now, end-task, no-further-tools, preserve-state-now, or handoff-now language stops all work. Immediately interrupt every active descendant, spawn none, perform **zero further tools or waits**, preserve dirty work, and return a concise handoff. Do not finish the current command, wait for a reviewer, repair a ledger, or earn one last closure pass. If a foreign task cannot be interrupted from this runtime, send one terminal stop message and report that limitation; never poll it.

## Program state — three bounded files

Under `~/.claude/orchestrator/programs/`, per program. Declaring them is the first act of every orchestrator.

**1. `<slug>.json` — the manifest.** Ownership only. STRICT key set; nothing else goes in:

```json
{ "program": "<slug>",
  "goal": "<outcome-shaped; allowed to be fuzzy — lanes give it precision>",
  "orchestrator_session": "<sid>",
  "claims": { "issues": [], "paths": [], "branches": [] },
  "ceded": [ { "item": "…", "to": "<program>" } ],
  "shared_touch_not_owned": [],
  "lanes": [ { "name": "", "kind": "headless|agent|codex|chip", "where": "<branch or session>",
               "artifact": "<the objective thing this lane must produce>", "status": "" } ],
  "gates_held_by_orchestrator": [],
  "next_forcing_function": "<the one move that advances the program>",
  "updated_at": "YYYY-MM-DDTHH:MM:SSZ" }
```

- **Cap ~8 KB. If it's growing, you're logging.** Observed failure: a manifest grown to 221 KB / ~90 improvised keys with a hand-rolled `.bak` beside it — ~55k tokens to read once, in the artifact this skill prescribes.
- `updated_at` is RFC3339 UTC **to the second**, so staleness is machine-evaluable — date-only values make the abandonment rule below unevaluable. Exact check:
  `python3 -c 'import json,sys,datetime as d;m=json.load(open(sys.argv[1]));t=d.datetime.strptime(m["updated_at"],"%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=d.timezone.utc);print((d.datetime.now(d.timezone.utc)-t).total_seconds()/3600)' <manifest>`
- Update on every spawn, adoption, retire, and claim change. On program end mark `status: done` and keep the file — it is the ownership history.

**2. `<slug>.events.jsonl` — append-only narration.** One JSON object per line (`ts`, `lane`, `event`, `note`). Every dated/step/blocker note, every lane handoff, every takeover. Never the manifest.

**3. `<slug>.state.md` — the at-wake state file.** Current step, the last *verified* fact per lane, and an `## AT-WAKE` section naming exactly what to do on the next wake. This is the compact-survivable layer: prescribed JSON snapshots were never once written on this pattern's whole history, while markdown state files referenced by name from consecutive wake prompts demonstrably survive compaction.

## Membership and collisions

- **Reason only about YOUR lanes.** Every machine-wide list (`list_sessions`, `claude agents --json`, worktree registry) is FILTERED to manifest membership: lanes you spawned, sessions you explicitly adopted (record the adoption), branches matching your claims. Foreign activity is never your progress and never your stall — note it only where it overlaps your claims.
- **First-claim wins.** Earliest manifest recording the claim owns it; the later orchestrator re-scopes, stacks on the owner's branch, or cedes (`ceded`).
- **Transfer, don't grab.** Request the item from the owning orchestrator (`send_message` on an operator-present turn, or an entry in their `.events.jsonl`); proceed only once their manifest releases it. Abandoned = `updated_at` >24h stale AND no live orchestrator session AND no active lanes → take it and record the takeover.
- **Contested live-vs-live → `AskUserQuestion`**, surfacing both goals and the overlapping item. Never silently double-own.
- Path locking inside one repo goes through the repo's own claim-scope CLI where it exists; the manifest is program-level intent, the CLI is the file lock.
- **Scale reality:** the manifest governs *declared* lanes only. A machine routinely carries 100+ worktrees across programs; isolation at that scale comes from branch-per-worktree + CI, not from this protocol.

## Per-turn state survey

Never read raw session JSONL inline. Dispatch the state-miner (`prompts/state-miner.md`, cheap tier) over both session pools — `claude-sessions` and `codex-sessions` surveys, filtered to the project — and read its distilled summary; write the result to `<slug>.state.md`. A program routinely spans both runtimes; skipping a pool because "I'm not in that runtime" is the bug.

Session liveness semantics (`status`, `jsonl_age_seconds`, `child_procs`) are the **`claude-sessions` skill's output contract** — read them there, do not re-document them here.

Skip the miner only when: one live lane, the user asked for raw data, or first turn (nothing to diff). **Cache-diff:** if the survey matches the state file, return one line (`no delta vs <ts>`) — never re-emit an unchanged lane list.

## Lane runtimes — pick by deliverable, then by human need

A lane goes interactive **only when it needs the human**; everything else runs prompt-free.

| Runtime | Deliverable | Spawn | Reach for it when |
|---|---|---|---|
| **Headless lane** | a branch/PR | `scripts/spawn-lane.sh --mission <file> --cwd <worktree> [--runtime codex] --model <alias>` via Bash `run_in_background` | anything shippable; unattended stretches; work needing its own context window |
| **Background `Agent` / `Workflow`** | information: report, verdict, map | `Agent` / `Workflow` tools | mining, research, scope audit, cross-lane verification, judge panels |
| **Codex lane** | an independent review/verify/research/census pass, or a bounded implementation from a written spec | see block below, via Bash `run_in_background` | the lane has a crisp contract and you want it **off the Claude 5-hour window** |
| **Chip session** | human judgment | `spawn_task` — **requires a human click** | grillings, decision gates, and resurrecting a parked lane the human will personally drive (`sessions-to-chips`) — never a substitute for a headless lane in an unattended stretch |

```bash
cd <repo> && echo '' | codex exec --skip-git-repo-check -m gpt-5.6-terra \
  -c model_reasoning_effort=medium -s read-only -o <outfile> -- "<prompt>"
```
> **Grade this lane by its ARTIFACT before counting it** — exit 0 is not evidence. Invocation flags, the `wc -l` / severity-grep check, and the DEAD vs **BLOCKED-ON-QUOTA** vs REAL classification live in [`docs/codex-lane-contract.md`](../../../docs/codex-lane-contract.md). Measured 2026-08-02/03: 18 of 52 rollouts hit a quota wall while exiting normally; 20 of 52 completed fine, so a dead lane is never proof the runtime is down.

Then read a **slice** of `<outfile>`. Codex starts **cold** — a lane needing accumulated conversation, harness state, or MCP servers stays on Claude.

### Which runtime a SHIPPABLE lane gets

The headless row takes `--runtime codex`. Codex is a separate billing pool and Claude time is
the scarce one, so reach for it whenever the lane's work fits — but it is **not** an
unconditional default, and the seam is narrower than "it ships":

**A Codex lane commits; it does not push.** Egress is denied by default, so the lane has no
push authority at all, and the orchestrator pushes after grading the artifact — the same
division the advance tick already uses for deploys. `--allow-network` re-opens egress when
the WORK needs it (a package install, a vendor API); it confers push authority as a side
effect, so grade what such a lane pushed.

**Keep a lane on Claude when it needs:** MCP servers (a Codex lane gets none — the launcher
refuses `--mcp-config` rather than dropping it), a permission mode other than the sandbox
this script sets, accumulated conversation, or interactive judgment.

**Two contracts a Codex lane must satisfy, both handled by the launcher:** every commit
carries a `Session-Id:` trailer (it mints a lane key and states the requirement in the
mission), and the lane writes an `-o` outfile so a caller can separate DEAD from
BLOCKED-ON-QUOTA per [`docs/codex-lane-contract.md`](../../../docs/codex-lane-contract.md).

**Repo hooks are a preflight condition, not parity.** This repo's `post-checkout`/`post-merge`
run `wire-skills.sh`, which writes `$HOME/.claude`, `$HOME/.codex` and `$HOME/.agents` — none
of them writable to a Codex lane — and both hooks swallow the failure with `|| true`. Check
what a repo's hooks actually touch before assuming a Codex lane reproduces a Claude lane's
side effects.

Why it was: until 2026-08-24 no Codex route could commit, so every shippable lane correctly
fell to Claude and the Codex-first rule failed its metric three cycles running while being
obeyed. Two blockers, routinely conflated:

- `codex-dispatch.sh` isolates `$HOME` to strip the preamble (~30% off input) and thereby
  strips git identity and ssh keys. Right for a read-only document lane; disqualifying for
  one that ships. **`--runtime codex` does not use that wrapper** — so a shipping lane pays
  the full preamble. That cost is real; keep the wrapper for document lanes.
- Raw `codex exec -s workspace-write` still cannot commit: the sandbox excludes `.git`, and
  the lane dies on `fatal: Unable to create .../.git/index.lock: Operation not permitted`.
  Git **identity** was never the binding constraint — write access to `.git` was.

`spawn-lane.sh` grants both git dirs as writable roots, which fixes it (verified both
directions: with the grant a lane's commit carried the host identity unchanged; without it
the same prompt produced only the `index.lock` error).

**That grant is a real widening — do not describe it as bounded to one worktree.** An earlier
version of this text said exactly that and it was false: the common dir carries every local
and remote-tracking ref, the stash, the object database, shared config, and metadata for
*every* linked worktree of the repo. It is also a persistence path — a lane can rewrite
`.git/config` to point `core.hooksPath` at a hook it placed there, so a later git command in
the parent or a sibling worktree would execute lane-authored code outside the sandbox. What
actually bounds the blast radius is that **the lane cannot push**: damage stays local and is
recoverable by discarding the worktree and resetting refs. That is why egress is denied by
default rather than guarded.

**Stdin discipline binds both runtimes.** `codex exec` with an inherited pipe hangs on
`Reading additional input from stdin` and never runs the mission — the same class as the
`claude -p` no-op below, with a different symptom. `spawn-lane.sh` detaches stdin on both
paths; a hand-rolled `codex exec` must do it too. Do not route through a Claude subagent that only shells out to Codex; that charges the window you are sparing.

**A headless lane is a ROOT session — give it one fresh bounded lifecycle phase.** The no-nested-dispatch rule binds Agent-tool subagents, not lanes, but a phase lane still follows finite review and proof budgets. The orchestrator plans and integrates; it does not run review panels itself.

**MCP tiers differ by substrate.** A Task subagent inherits the desktop MCP set (interactive OAuth included); a headless lane gets only static-credential MCPs the spawn wrapper attaches. Interactive-OAuth MCPs do **not** load in `-p` mode — a lane needing a tracker gets it via `--mcp-config` with an API-key header. Anything desktop-MCP-only, the orchestrator does itself. Missions stay self-contained regardless: MCP is for depth, not for the brief.

## Transport, continuation, and the human

- **`ScheduleWakeup` is the continuation mechanism** — one snapshot per wake, never a poll loop. Size the delay to what you are waiting on (a CI run is minutes; a bake is hours). Re-arm only on a **changed fingerprint**; if nothing moved, extend the delay instead of re-firing at the same cadence.
- **The wake prompt is a POINTER** — state-file path + "step N NOW" + the one fact that changed since arming. Never the state itself. (Measured: 97 of 170 wake prompts carried ≥1,000 chars of re-serialized state, up to ~6k, because nothing durable survived the turn boundary. `<slug>.state.md` is what makes the pointer sufficient.)
- **External waits end the bounded task.** Write a blocker/wake artifact keyed by the awaited state; a later fresh task checks it once. An owned in-scope child is internal work governed by the continuation invariant, not an external wait. Foreground sleep and polling loops are forbidden.
- **`AskUserQuestion`** is how a contested claim, a pre-authorization ask, or a genuine judgment call reaches the human. **`PushNotification`** tells an away operator something now needs them.
- **`TaskCreate` / `TaskUpdate`** carry per-lane status the operator can see; prefer them to prose status dumps re-typed each turn.
- **`send_message` is the orch→live-lane transport, and it surfaces as an approval prompt IN THE RECIPIENT** — an unattended lane stalls on it (operator, verbatim: *"Stop sending messages it will make this session stuck."*). Send only from a turn where the operator is present, and **never as the last act of an unattended wake**. For an unattended lane, leave the instruction where the lane reads it on its own next tick — its state file — not in its inbox.

## Autonomous stretches — the un-gated frontier

Before any unattended stretch, compute the set of work reachable **without a human approval**. The canonical failure: every lane drives to "green + READY", the DAG roots on one human-merge gate, and the night produces polling wakes and zero development.

1. **Stack, don't park.** A lane blocked on an unmerged PR branches its worktree off that PR's branch, builds there, rebases after the merge. Record the edge in the manifest lane (`stacked_on: <pr>`).
2. **Pre-authorization ask BEFORE the human leaves** (`AskUserQuestion`): present the projected merge stack and ask for standing approval per class. A decline is fine — then plan around the gate by stacking. Discovering the gate at 2am is the failure.
3. **Deliberate park.** Frontier genuinely empty → ONE wake at the human's expected return with a morning summary and the ready-to-merge stack. Never poll a gate only a human can open.
4. **Frontier refresh on every event** — a merge, a lane exit, or an operator message re-opens the computation; newly un-gated work dispatches immediately.

## The advance tick — one unattended wake, many lanes

The sections above define the *parts* of autonomy. This is the order they run in when a
wake fires and nobody is watching. It **composes** those sections; where one of them owns a
rule, this tick invokes it and does not restate or re-derive it.

Run in this order. The first three are gates on whether the tick may act at all — they come
**before any tool call**, because an override that is checked after a survey has already
been violated by the survey.

1. **Terminal stop?** Then zero further tools, zero waits (§Terminal stop override). The
   tick does not begin.
2. **Completion-mode freeze?** Prune scope to the declared build task group first
   (§Completion mode override). No new review or test lane may be dispatched below.
3. **Owned child active?** That is internal work, not an external wait — continue with
   latency-sized event waits inside its lease (§Owned child continuation invariant). Do not
   proceed to step 7 and start something new alongside it.
4. **Survey once**, cache-diffed (§Per-turn state survey). One snapshot per wake, never a
   poll loop.
5. **Classify each lane — artifact and liveness are SEPARATE questions.** Artifact grading
   is §Grading a lane. Liveness has two known-wrong probes, and both fail toward the
   expensive error:
   - `ps aux | grep -c "[c]laude -p"` returns **0 for healthy lanes** — the real command
     line is `…/bin/claude --permission-mode … -p`, so `claude -p` is never a contiguous
     substring. Use `ps -eo pid,etime,args | grep "[b]in/claude"`, and **sanity-control it
     against a lane you know is running before believing any negative.**
   - A **0-byte output file is not death**: `--output-format json` writes its blob only at
     exit, so mid-run it is identical to a lane that never started.
   Measured 2026-08-04: three live lanes were seconds from being declared dead and
   re-dispatched, which would have raced two writers into one worktree.
6. **Invoke the existing frontier** (§Autonomous stretches) to compute what is reachable
   without a human. Do not reimplement that computation here; a second slightly-different
   copy of it is the defect, not the feature.
7. **Dispatch ONE forcing function**, within the phase, review-budget and heavy-lane caps
   (~2 concurrent heavy lanes under the machine-global heavy lock). A dead lane is salvaged
   before it is replaced — exit 143 with a 0-byte output is SIGTERM under load, and its
   worktree may hold real uncommitted work; `git -C <worktree> status --porcelain` first.
   The replacement is a **continuation** carrying the last verified fact, never a replay.
8. **External readiness gets a keyed wake artifact and a later fresh check** — never a wait
   held open inside this turn.

### The deploy seam

A build lane **commits and pushes synchronously**; it must never wait on a deploy, a preview
URL, or CI. Shell poll loops are hook-denied and `ScheduleWakeup` fires into a session that
no longer exists. Measured 2026-08-03: a lane whose mission implied the deploy was its to
check spent 105 turns / $6.09, took two denials, opened no PR, and exited 0 promising to
resume. Put the rule in the mission verbatim: *if you find yourself wanting to wait for a
deploy, that is the signal you are done — commit, push, report.*

The orchestrator owns **readiness detection**, not the verifying itself: a sleeping root
verifies nothing, and a wake only triggers an inspection. Confirm the **exact deploy SHA**
is present in the target environment (§Pre-flight verification); only then dispatch and
grade a keyed `verify-release`. If the wake fired early and the SHA is absent, no verifier
runs — retain the keyed wake artifact and end the bounded task.

### Deciding the next wake

Size the delay to the fastest pending change (§Transport). Then:

- Something advancing → re-arm once, at that size.
- Nothing advancing but work is reachable → dispatch it; do not sleep on work you are
  allowed to start.
- Everything reachable is gated on a human → **park**: one wake at the operator's expected
  return, with the ready-to-merge stack.

**There is no fixed number of idle wakes that means "stalled."** Wake count measures
scheduler cadence, not progress: at a 10-minute default, three idle wakes parks a healthy
40-minute build at minute 30, and if a *different* lane causes two-minute wakes the same
count parks it after six. Continuous log writes produce the opposite failure — a wedged
loop always looks like it is changing. So bound each lane by its **own lease or checkpoint
deadline**, and judge movement by a **normalized semantic fingerprint**: artifact existence,
branch or remote SHA, terminal ledger status, exact deploy-SHA readiness, process
exit/identity, child result. Raw output bytes and JSONL or log mtimes do not qualify. A wake
triggered by another lane never counts against a live lane still inside its lease; a lane
that misses its own deadline is what escalates or gets interrupted.

Record one line per tick in `<slug>.events.jsonl` — what advanced, what was salvaged, what
is awaited, the next wake. The wake prompt itself stays a pointer.

## Grading a lane

- **Grade by ARTIFACT, never by the completion envelope.** Before marking a lane done, check the objective thing it was asked to produce — commits on the branch, the named file, the row. A green `subtype:"success"` over **zero commits** is a dead lane (observed: exit 1 on an API 429 after 66 turns and $7.24). Exit 143 + a 0-byte output = SIGTERM under machine load: **salvage the dirty worktree before re-dispatching.** State the artifact in the manifest lane entry and in the mission, so the check is unambiguous.
- **A lane that ends short of its artifact owes a handoff note** — one line of what remains plus the last verified fact, appended to `<slug>.events.jsonl`. Without it the operator re-types the original GOAL (observed: one prompt resent byte-identical 5×). A re-dispatch is a **continuation**, never a replay.

## Review convergence

Declare the finite review protocol, lane manifest, and stop condition before dispatching reviewers.

For native Codex collaboration calls, every review activation carries the same machine-readable
protocol block in its `message`. Declare the complete finite manifest up front; a slot is unique
within the protocol and is launched at most once.

```text
[review-protocol:v1]
protocol_id=<stable task-scoped id>
stage=primary|investigator|falsifier|security|closure
artifact_paths=<comma-separated paths relative to cwd>
manifest=primary:<slot>,falsifier:<slot>,closure:<slot>
manifest_slot=<the unique slot launched by this call>
```

List every allowed slot in `manifest`, repeating a stage for multiple slots. Use explicit artifact
files, never a whole-repository fingerprint. `send_message` and `interrupt_agent` remain available
for corrections and stopping work. Legacy unmarked calls are valid but receive no protocol-state
assessment.

The whole manifest is mode-bounded: `moderate` permits at most **two total activations** (one primary,
one changed-seam closure); `critical` permits at most **five total activations** (up to two primary,
up to two named investigator/falsifier/security slots, one closure). A named skill may use fewer slots,
not exceed the mode ceiling. More requires explicit user authorization and a fresh task.

1. Run one broad primary wave. `moderate` allows one primary reviewer; `critical` allows at most two independent primary slots. Each gets a self-contained mission and no history, or the smallest evidence slice. More requires explicit user authorization and a fresh task.
2. Consolidate and deduplicate once. Falsify the material survivors before fixing them; reviewer output is evidence, not an instruction to apply every finding verbatim.
3. A named finite skill may use investigator, falsifier, security, or bounded cross-examination slots only within the total mode ceiling. Those are not permission to repeat a completed stage.
4. After fixes, run one narrow closure pass over the changed seams. Then stop. Backlog non-blocking or cosmetic residue with the evidence already gathered.

Another broad cycle requires explicit user authorization and a fresh task. Do not interrupt and restart the same reviewer, or keep sending follow-ups, without a changed diff, artifact, or final result that justifies the next declared stage.

## Pre-flight verification — before any routing claim

Verify the source of truth; never infer from secondary signals.

1. Mine fresh each turn — a 5-minute-old interpretation is stale.
2. **Branch HEAD vs the state file's last-seen commit** is the authoritative liveness signal. JSONL silence, "Exiting." text, and `child_procs` alone never classify a lane RETIRED.
3. Answer "what's left in Spec X" from **the spec file**, not a tracker body — tracker bodies decay.
4. `gh pr view <N> --json mergedAt,state,mergeStateStatus` is merge truth. Recent main commits are confirmation, not authority.
5. Deferred markers ("now-runnable-post-deploy", "flippable") are **promises** — a lane cannot retire while one is an unredeemed skeleton. Staging E2E ≠ prod E2E; one marker covering both is conflation.
6. A subagent reporting "done" with paths under `/tmp` or `/private/tmp` produced a **draft** — re-run the final step in the lane's worktree before relaying it.

Stale, contradicted, or absent input → STOP and re-verify. Never state a routing claim from incomplete data.

## Spawning a headless lane

`scripts/spawn-lane.sh` is the lane verb; the operator one-time allowlists it (a session may not invoke `--permission-mode bypassPermissions` directly). Rules, each earned by a real failure:

- **Never pipe the spawn; detach stdin.** `spawn-lane.sh … | tail` can exit 0 with 0 bytes and zero work done. `claude -p --output-format json` ALWAYS emits a final JSON blob — **empty output + exit 0 is proof the lane never ran.**
- **Chunk by lifecycle phase** — background Bash has a runtime cap; a full feature marathon gets killed or accumulates context. Use one fresh bounded task for each of `define`, `build`, and `verify-release`; each resumes from branch artifacts and the proof-obligation ledger.
- **`--worktree` on first spawn only; `--cwd <existing-worktree>` on every continuation** — a second `--worktree` collides with the locked one.
- **Verify remotely.** After every lane exit run `git ls-remote --heads origin <branch>` — committed-but-unpushed looks successful and is a stall.
- **Verify the substrate BEFORE dispatch.** Before spawning a verify lane against a staging or deployed target, confirm that environment actually carries the SHA — `git -C <env-worktree> rev-parse HEAD`, or `git branch --contains <sha>` on the deploy branch. Discovering "not deployed yet" inside the lane is a wasted activation, not a verification (observed: `verify_e2_fix` returned "no staging worktree is at `067541081`" and a second lane went to find out where staging actually was). This is the pre-dispatch counterpart to `Verify remotely` above, which is a post-exit *push* check; the same confirmation on the resume path is `references/merge-and-retire.md` §Post-merge proof.
- **Only the `verify-release` phase runs the project gate, exactly once.** Define/build lanes run targeted checks. A headless verifier runs the gate synchronously within its budget or stops with the command artifact; it never backgrounds the gate and waits for a notification.
- **Deletability claims are HYPOTHESES.** Teardown missions instruct: grep-verify call sites, and "if verification shows the code isn't dead, STOP and report — never weaken a test to make deletion pass."
- **Mission content:** goal one-liner · issue ref with acceptance criteria · owned paths + DO-NOT-TOUCH · one lifecycle phase · mode + proof-obligation ledger · artifact to grade · `stacked_on:` edge · "NEVER merge to a protected branch, deploy, or touch prod" · "on a 2nd identical tool denial, print `BLOCKED_ON_CLASSIFIER` and stop" · "final reply = one JSON status object". Fresh `--session-id`; scrub `CLAUDE_SESSION_ID`/`CLAUDE_CODE_ENTRYPOINT` from the child env. Keep global hooks in the child. The machine-global heavy lock serializes verify/build — cap concurrent heavy lanes at ~2.

Interactive lanes (human-driven only) use `prompts/session-template.md` + `prompts/loop-directive.md`. Chip prompts stay lean (≤~900 chars): GOAL / STATE (only facts not in repo law or the ticket) / START HERE (pointers, never pasted bodies) / mission-specific GUARDRAIL.

## Before spawning: conflict map

List which paths each in-flight lane owns and name them DO-NOT-TOUCH in the new mission. Usual collisions: a shared layout/data component, an observability module, the lockfile (lockfile churn serializes lanes), per-customer or schema config. Parallel pushes to main collide — stash unrelated working tree, commit narrow, push, pop. Every commit prompt uses an UNQUOTED `<<EOF` heredoc so `$CLAUDE_SESSION_ID` expands in the trailer; `<<'EOF'` ships the literal placeholder.

## Backlog and models

Backlog lives on the repo's tracker, named in its `AGENTS.md` `## Agent skills` block. For a huge/foggy multi-session effort run `/wayfinder` FIRST; to break a settled plan into tickets, `/to-tickets`.

Per-lane model/effort recommendations: `prompts/model-routing.md`. A Codex orchestrator root defaults to **Terra-medium**; Sol is a bounded judgment escalation, never the context-accumulating execution loop. Ad-hoc Claude delegation defaults to **sonnet**; `opus` needs a one-line justification; the deep verify/judge/adversarial bucket is `fable` (Claude) or `gpt-5.6-sol` (Codex).

## Skill memory

Read the private overlay if present: `~/.claude/skills-overlay/orchestrator/LEARNINGS.md` (adopter-private, never in this public repo). Write at end, routed by scope (full routing: [`docs/skill-memory.md`](../../../docs/skill-memory.md)): operator-private orchestration craft → that overlay; project facts → the project's `.claude/memory/`; universal craft → note it for `/improve-harness` to promote here by PR.

## Anti-patterns

- ❌ Implementing code, running installs, or running review panels in the orchestrator — push them into a lane.
- ❌ Reasoning machine-wide: counting foreign programs' sessions, nudging lanes you didn't spawn or adopt, or running without a manifest at all (unregistered claims manufacture the collisions the protocol prevents).
- ❌ Logging into the manifest instead of `.events.jsonl` — the 8 KB cap is the tripwire.
- ❌ Trusting a completion envelope, a lane's local worktree, or a subagent's `/tmp` output as a deliverable.
- ❌ Trusting chat-text signals ("Exiting.", JSONL silence) over branch HEAD when classifying a lane.
- ❌ `send_message` as the last act of an unattended wake; or a wake prompt that re-serializes the state instead of pointing at it.
- ❌ Polling wakes against a human-only gate, or a lane parking on "waiting for PR #N" when it could stack on #N and build now.
- ❌ Spawning a chip and calling the lane autonomous — a chip needs a human click.
- ❌ Piping a lane spawn, or one monolithic spec→implement lane that the runtime cap kills.
- ❌ Blind-retrying through a safety-classifier or model-outage window — 2nd identical denial ends the lane.
- ❌ Opening a PR, or retiring a lane, while proof obligations are non-terminal or lack owned deferral (`references/merge-and-retire.md`).
- ❌ Turning a moderate proof ledger into exhaustive test enumeration or an autonomous deploy/poll loop.
- ❌ Running a long test/build/gate process in the context-heavy root, or spawning one procedural child per command. Batch one pass; keep judgment in the root.
