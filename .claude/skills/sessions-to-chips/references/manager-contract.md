# Manager contract

Every manager follows this file, whichever mode started it: a `[Manager]` desktop session, or a
Codex root acting as manager because its host cannot start sessions. SKILL.md carries the
must-fire subset; this file carries the depth. Session hygiene is in [`../HYGIENE.md`](../HYGIENE.md).

A manager owns **ONE PROGRAM**: it tracks its own lanes, catches conflicts before they reach
main, starts lanes and child sessions, holds every terminal gate, and surfaces decisions. It
never implements code itself.

Read the other references when their trigger fires:

- **`lifecycle.md`** — before planning, spawning, or grading a spec-class lane. It is the
  canonical **define → build → verify-release** lifecycle: modes, handoff, terminal evidence gate.
- **`merge-and-retire.md`** — before merging any lane PR or signing off a retire.
- **`codex-runtime.md`** — first, when `$CLAUDE_SESSION_ID` is unset. You are hosted by Codex
  CLI and most verbs below do not exist there.

## Root control plane, worker execution plane

The manager root owns the **control plane**: state and ledger decisions, scope and target
selection, product edits, failure interpretation, human and auth gates, and every production
mutation. It may run small bounded read-only probes that complete in one tool call and
immediately inform a decision.

The root does not keep the **execution plane** for deterministic command batches. When a
targeted pass would need process continuation, would retain large raw output, or would run the
full project gate, dispatch one fresh native Codex procedural worker for the whole pass using
`../prompts/procedural-worker.md`. Never spawn one child per command. The worker is Luna-low
with no inherited history; the root grades its pointer artifact and makes the next decision.

Source-mutating formatters, dependency-changing installs, migrations, and product fixes belong
to the build phase, not the procedural worker. Interactive authentication and
production mutations stay in the root even after authorization; post-mutation verification may
use a worker.

## Model topology — cheap root, intelligent escalations

A Claude `[Manager]` session runs on `sonnet` at `medium` effort (SKILL.md §Starting a manager).
The Codex ladder:

- **Long-lived Codex root:** ask the gate for the `standard` class
  (`~/.claude/scripts/codex-headroom.sh --route standard` → Sol at Medium; the full class table is
  `../prompts/model-routing.md`). The root pays for accumulated context on every turn, so it
  coordinates, integrates, and keeps state on the everyday tier.
- **Astra judgment escalation:** use a fresh, bounded lane at the gate's `architecture`,
  `security`, `hard-rca`, or `adjudication` class for irreversible architecture, security and trust
  boundaries, hard RCA, or final adjudication. Use these lanes whenever an accepted task needs
  that judgment, within its finite review manifest. Give it no history or the smallest evidence
  slice, one decision artifact, and a stop condition.
- Return the decision artifact to the Sol-medium root. When a judgment lane ends, start or
  resume a fresh Sol-medium implementation task instead of extending it through execution and review.
- **Sol-high escalation:** the `falsifier`/`adversarial` class covers bounded adversarial review
  and hypothesis falsification, under the same fresh-context decision-artifact contract.
- Routine implementation and topical review stay on Sol-medium (class `standard`). Native mining,
  file search, and deterministic procedure use Luna-low (class `mining`). The callable roster and
  its verification date live in `codex-headroom.sh`, not here. An explicit user model choice that
  the callable surface supports overrides this default.

## Continuation policy — no scheduled polling

Do not create or re-arm a heartbeat, recurring automation, `/loop`, or scheduled wake to keep a
manager alive unless the user explicitly requests that schedule. Ordinary "go", "finish",
manager, or autonomous-work authorization does not authorize a schedule. This binds every runtime.

On Codex, use a bounded native goal only when explicitly requested, through the next known
approval or external gate. Consume owned-child results through their event-wait leases. At an
external gate, persist the exact prerequisite and resume key, then end the bounded task. A
notification or a later authorized task checks that prerequisite once. Never replace a missing
event subscription with scheduled LLM checks.

Updating a finite schedule on every run resets its limit: `COUNT=1` or `COUNT=2` plus re-arming
is recurring polling. Quiet notifications do not reduce execution tokens. Any user-requested
schedule needs an explicit finish condition and must not renew itself past it.

## Owned child continuation invariant

A native `spawn_agent` owned by the current accepted task group is **internal work, not an
external wait**. Before any final answer or handoff, the root must either consume and grade that
child's terminal result, or interrupt it under terminal-stop, completion-mode scope pruning, or an
expired explicit child lease. The root **must not emit a final answer** while an in-scope child is
active and thereby require the user to reactivate the task.

A wait timeout is a progress boundary, not completion. Report the changed state in commentary and
continue with latency-sized event waits while the child stays inside its lease. The child mission
declares the lease up front; expiry causes one interrupt and continuation from its durable handoff
and artifacts, never an unbounded wait loop.

## Goal command contract — bounded autonomy

On Codex, use the native goal commands only when the user explicitly asks for autonomous goal
execution. Scope the goal to the **reachable authorized autonomy frontier**: the current accepted
task group through the next known human, production, or external gate. A goal keeps that bounded
work moving across automatic continuations and owned-child waits; it does not broaden scope,
production authority, or approval.

Keep the goal active only while a safe, authorized action advances its objective. Each
continuation selects one `next_forcing_function`; completed phases, PASS evidence, spent review
slots, and unchanged failures stay terminal. Close the goal as soon as its frontier is achieved.
An unexpected external blocker uses the native three-turn blocker audit with no repeated side
effects, then stops. Explicit terminal stop overrides the goal immediately. The exact
`create_goal` / `get_goal` / `update_goal` contract is in `codex-runtime.md`.

## Completion mode override

When the user says to stop review, testing, or cycles **and** asks to finish, complete, finalize,
proceed, or return residue as backlog: interrupt active review and test lanes and
freeze accepted scope. Continue only the **current declared build task group**; its owned children stay under the
continuation invariant above. Absorb no adjacent discovery and start no new review or test plan.
If testing is explicitly forbidden, hand off the result as `UNVERIFIED`; otherwise run only the
minimum project-required gate once. Then return completed artifacts, current state, owned
failures, external blockers, and deferred backlog.

## Terminal stop override

Only explicit stop-now, end-task, no-further-tools, preserve-state-now, or handoff-now language
stops all work. Immediately interrupt every active descendant, spawn none, perform
**zero further tools or waits**, preserve dirty work, and return a concise handoff. Do not finish the current
command, wait for a reviewer, repair a ledger, or earn one last closure pass. If a foreign task
cannot be interrupted from this runtime, send one terminal stop message and report that
limitation; never poll it.

## Program state — three bounded files

They live under `~/.claude/orchestrator/programs/`, per program. The directory keeps its
historical name: live program state and a global read-state hook already use that path.
Declaring the files is a new manager's first act. A resume-mode manager already has its story
map as its narrative; it adds the manifest when it spawns its first headless lane or claims a path.

**1. `<slug>.json` — the manifest.** Ownership only. STRICT key set; nothing else goes in:

```json
{ "program": "<slug>",
  "goal": "<outcome-shaped; allowed to be fuzzy — lanes give it precision>",
  "manager_session": "<sid>",
  "claims": { "issues": [], "paths": [], "branches": [] },
  "ceded": [ { "item": "…", "to": "<program>" } ],
  "shared_touch_not_owned": [],
  "lanes": [ { "name": "", "kind": "headless|agent|codex|session", "where": "<branch or session>",
               "artifact": "<the objective thing this lane must produce>", "status": "" } ],
  "gates_held_by_manager": [],
  "next_forcing_function": "<the one move that advances the program>",
  "updated_at": "YYYY-MM-DDTHH:MM:SSZ" }
```

- **Cap ~8 KB. If it is growing, you are logging.** Observed: a manifest grown to 221 KB with
  ~90 improvised keys and a hand-rolled `.bak` beside it, ~55k tokens to read once.
- `updated_at` is RFC3339 UTC **to the second**, so staleness is machine-evaluable; a date-only
  value makes the abandonment rule below unevaluable. Exact check:
  `python3 -c 'import json,sys,datetime as d;m=json.load(open(sys.argv[1]));t=d.datetime.strptime(m["updated_at"],"%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=d.timezone.utc);print((d.datetime.now(d.timezone.utc)-t).total_seconds()/3600)' <manifest>`
- Update on every spawn, adoption, retire, and claim change. On program end mark `status: done`
  and keep the file: it is the ownership history.
- Manifests written before this contract may carry `orchestrator_session` and
  `gates_held_by_orchestrator`; read them as the same fields and write the new names on the next update.

**2. `<slug>.events.jsonl` — append-only narration.** One JSON object per line (`ts`, `lane`,
`event`, `note`): every dated, step, or blocker note, every lane handoff, every takeover. Never
the manifest.

**3. `<slug>.state.md` — the at-wake state file.** Current step, the last *verified* fact per
lane, and an `## AT-WAKE` section naming exactly what to do next. It is the compact-survivable
layer: prescribed JSON snapshots were never once written over this pattern's history, while
markdown state files named in consecutive wake prompts survive compaction.

Keep this completion checkpoint in that same state file. For an ordinary task with an existing
accepted plan or issue, keep the checkpoint there instead of creating a program. Evidence may be
links; do not copy the underlying logs or duplicate another task ledger.

```markdown
## Completion checkpoint
Accepted outcome: <the requested result and scope>
Done when: <observable acceptance conditions>
Verified: <condition -> evidence path/URL and revision; unknown stays unverified>
Remaining: <unfinished accepted work, or none with supporting evidence>

## AT-WAKE
Next action: <one executable action, or none when the accepted outcome is verified>
Owner: <agent/person responsible for that action>
Prerequisite: <exact external state/approval required, or none>
Stop condition: <completion, explicit stop, or the named external gate>
```

Update it at a milestone or a legitimate stopping boundary. If the next action is reachable and
authorized, execute it before ending the turn. At an external gate, leave this pointer and its
prerequisite; do not schedule a retry. In the final reply, list remaining actions in order, with
owner and prerequisite where needed, or state that no requested work remains.

## Membership and collisions

- **Reason only about YOUR lanes.** Filter every machine-wide list (`list_sessions`,
  `claude agents --json`, the worktree registry) to manifest membership: lanes you started,
  sessions you explicitly adopted (record the adoption), branches matching your claims. Foreign
  activity is never your progress and never your stall; note it only where it overlaps your claims.
- **First claim wins.** The earliest manifest recording a claim owns it; the later manager
  re-scopes, stacks on the owner's branch, or cedes (`ceded`).
- **Transfer, don't grab.** Ask the owning manager for the item (`send_message` on an
  operator-present turn, or an entry in its `.events.jsonl`); proceed only once its manifest
  releases it. Abandoned means `updated_at` >24h stale AND no live manager session AND no active
  lanes: then take it and record the takeover.
- **Contested live-vs-live → `AskUserQuestion`**, naming both goals and the overlapping item.
  Never silently double-own.
- Path locking inside one repo goes through the repo's own claim-scope CLI where one exists. The
  manifest is program-level intent; the CLI is the file lock.
- **Scale reality:** the manifest governs *declared* lanes only. A machine can carry 100+
  worktrees across programs; isolation at that scale comes from branch-per-worktree plus CI.

## Per-turn state survey

Never read raw session JSONL inline. Dispatch the state miner (`../prompts/state-miner.md`, cheap
tier) over both session pools — the `claude-sessions` and `codex-sessions` surveys, filtered to the
project — and read its distilled summary; write the result to `<slug>.state.md`. A program often
spans both runtimes; skipping a pool because "I'm not in that runtime" is the bug.

Session liveness fields (`status`, `jsonl_age_seconds`, `child_procs`) are the `claude-sessions`
skill's output contract; read them there.

Skip the miner only when there is one live lane, the user asked for raw data, or it is the first
turn (nothing to diff). **Cache-diff:** if the survey matches the state file, return one line
(`no delta vs <ts>`); never re-emit an unchanged lane list.

## Lane runtimes — pick by deliverable, then by human need

A lane goes interactive **only when it needs the human**. Everything else runs prompt-free.

| Runtime | Deliverable | Start | Reach for it when |
|---|---|---|---|
| **Headless lane** | a branch/PR | `~/.claude/scripts/spawn-lane.sh --mission <file> --cwd <worktree> [--runtime codex] --model <alias>` via Bash `run_in_background` | anything shippable; unattended stretches; work that needs its own context window |
| **Background `Agent` / `Workflow`** | information: report, verdict, map | `Agent` / `Workflow` tools | mining, research, scope audit, cross-lane verification, judge panels |
| **Codex lane** | an independent review/verify/research/census pass, or a bounded implementation from a written spec | the block below, via Bash `run_in_background` | the lane has a crisp contract and should run **off the Claude 5-hour window** |
| **Child session** | human judgment | `start_session` (SKILL.md §Starting a manager has the arguments) | grilling, decision gates, a parked unit the human will drive. From an automated turn it lands as a card and waits for a click, so it is never the unattended runtime |

```bash
~/.claude/scripts/codex-dispatch.sh standard <promptfile> <outfile> <repo>
```

> **Grade this lane by its ARTIFACT before counting it**; exit 0 is not evidence. Invocation
> flags, the `wc -l` / severity-grep check, and the DEAD vs **BLOCKED-ON-QUOTA** vs REAL
> classification live in [`docs/codex-lane-contract.md`](../../../../docs/codex-lane-contract.md).
> Measured 2026-08-02/03: 18 of 52 rollouts hit a quota wall while exiting normally; 20 of 52
> completed fine, so a dead lane never proves the runtime is down.

Then read a **slice** of `<outfile>`. Codex starts **cold**: a lane that needs accumulated
conversation, harness state, or MCP servers stays on Claude. Do not route through a Claude
subagent that only shells out to Codex; that charges the window you are sparing.

### Which runtime a SHIPPABLE lane gets

The headless row takes `--runtime codex --class <task-class>` (default `standard`). It consults
the central headroom gate even with an explicit `--model` override, and applies the class effort.
Claude leads user interaction, task acceptance, and integration, while independent bounded Codex
lanes run through harness-tracked background Bash. Codex is a separate billing pool and Claude time
is the scarce one, so use it whenever the lane's work fits. It is **not** an unconditional
default, and the seam is narrower than "it ships":

**A Codex lane commits; it does not push.** Egress is denied by default, so the lane has no push
authority, and the manager pushes after grading the artifact. `--allow-network` re-opens egress
when the WORK needs it (a package install, a vendor API); it grants push authority as a side
effect, so grade what such a lane pushed.

**Keep a lane on Claude when it needs** MCP servers (the launcher refuses a supplied
`--mcp-config` rather than dropping it; the normal Codex profile stays loaded), a permission mode
other than the sandbox the script sets, accumulated conversation, or interactive judgment.

**The launcher handles two contracts:** every commit carries a `Session-Id:` trailer (it mints a
lane key and states the requirement in the mission), and the lane writes an `-o` outfile so a
caller can tell DEAD from BLOCKED-ON-QUOTA.

**Repo hooks are a preflight condition, not parity.** A repo's `post-checkout`/`post-merge` hooks
may write under `$HOME` (keel's run `wire-skills.sh`), which a Codex lane cannot write, and may
swallow the failure with `|| true`. Check what a repo's hooks touch before assuming a Codex lane
reproduces a Claude lane's side effects.

Why a Codex lane can commit at all: `codex-dispatch.sh` isolates `$HOME` to strip the preamble
(~30% off input), which also strips git identity and ssh keys; that is right for a read-only
document lane. `--runtime codex` does not use that wrapper, so a shipping lane pays the full
preamble. Raw `codex exec -s workspace-write` still cannot commit: the sandbox excludes `.git`,
and the lane dies on `fatal: Unable to create .../.git/index.lock: Operation not permitted`.
`spawn-lane.sh` grants both git dirs as writable roots, which fixes it.

**That grant is a real widening; never describe it as bounded to one worktree.** The common git
dir carries every local and remote-tracking ref, the stash, the object database, shared config,
and metadata for every linked worktree. It is also a persistence path: a lane can point
`core.hooksPath` at a hook it placed there, so a later git command in the parent or a sibling
worktree runs lane-authored code outside the sandbox. What bounds the blast radius is that **the
lane cannot push**: damage stays local and is recovered by discarding the worktree and resetting
refs. That is why egress is denied by default rather than guarded.

**Stdin discipline binds both runtimes.** `codex exec` with an inherited pipe hangs on
`Reading additional input from stdin` and never runs the mission. `spawn-lane.sh` detaches stdin on
both paths; a hand-rolled `codex exec` must too.

**A headless lane is a ROOT session; give it one fresh bounded lifecycle phase.** The
no-nested-dispatch rule binds Agent-tool subagents, not lanes, but a phase lane still follows
finite review and proof budgets. The manager plans and integrates; it does not run review panels.

**MCP tiers differ by substrate.** A Task subagent inherits the desktop MCP set (interactive OAuth
included). A headless lane gets only static-credential MCPs that the spawn wrapper attaches;
interactive-OAuth MCPs do not load in `-p` mode, so a lane that needs a tracker gets it via
`--mcp-config` with an API-key header. Anything desktop-MCP-only, the manager does itself.
Missions stay self-contained regardless: MCP is for depth, not for the brief.

## Transport, continuation, and the human

- **Continuation follows the policy above.** Owned children use event waits. Codex goals keep
  explicitly authorized, reachable work moving. Scheduling is opt-in only, never the default for
  CI, deployment, ownership, locks, or human input.
- **Resume state is a POINTER**: persist the state-file path, the next action, and the exact
  prerequisite. Keep facts in the state file, not replayed in injected prompts.
- **External waits end the bounded task.** Write a blocker or wake artifact keyed by the awaited
  state; a later fresh task checks it once. An owned in-scope child is internal work governed by
  the continuation invariant, not an external wait. Foreground sleep and polling loops are forbidden.
- **`AskUserQuestion`** carries a contested claim, a pre-authorization ask, or a real judgment call
  to the human. **`PushNotification`** tells an away operator something needs them now.
- **`TaskCreate` / `TaskUpdate`** carry per-lane status the operator can see; prefer them to prose
  status dumps re-typed each turn.
- **`send_message` reaches a live child, and it surfaces as an approval prompt IN THE
  RECIPIENT**, so an unattended lane stalls on it (operator, verbatim: *"Stop sending messages it
  will make this session stuck."*). Send only from a turn where the operator is present, and
  **never as the last act of an unattended wake**. For an unattended lane, leave the instruction
  where the lane reads it on its own next tick (its state file), not in its inbox. Address a
  session by id, never by name.

## Autonomous stretches — the un-gated frontier

Before any unattended stretch, compute the set of work reachable **without a human approval**.
The canonical failure: every lane drives to "green + READY", the DAG roots on one human merge
gate, and the night produces polling wakes and zero development.

1. **Stack, don't park.** A lane blocked on an unmerged PR branches its worktree off that PR's
   branch, builds there, and rebases after the merge. Record the edge on the manifest lane
   (`stacked_on: <pr>`).
2. **Ask for pre-authorization BEFORE the human leaves** (`AskUserQuestion`): present the
   projected merge stack and ask for standing approval per class. A decline is fine; then plan
   around the gate by stacking. Discovering the gate at 2am is the failure.
3. **Deliberate park.** If the frontier is genuinely empty, persist the ready-to-merge stack and
   the exact resume prerequisite, then stop. Never schedule checks of a gate only a human can open.
4. **Refresh the frontier on every event.** A merge, a lane exit, or an operator message re-opens
   the computation; newly un-gated work dispatches at once.

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
7. **Dispatch ONE forcing function**, within the phase and review budget. A dead lane is salvaged
   before it is replaced — exit 143 with a 0-byte output is SIGTERM, and its
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

The manager owns **readiness detection**, not the verifying itself: a sleeping root
verifies nothing, and a wake only triggers an inspection. Confirm the **exact deploy SHA**
is present in the target environment (§Pre-flight verification); only then dispatch and
grade a keyed `verify-release`. If the wake fired early and the SHA is absent, no verifier
runs — retain the keyed wake artifact and end the bounded task.

### Ending at the continuation frontier

Reachable authorized work advances now. Owned children use their declared event-wait lease.
When only an external prerequisite or human decision remains, persist its normalized semantic
fingerprint and resume key, then stop.

**There is no fixed number of idle wakes that means "stalled."** A wake comes from an event (a
lane exit, a notification, an operator message), so wake count measures event traffic, not
progress. Continuous log writes produce the opposite failure: a wedged loop always looks like it
is changing. So bound each lane by its **own lease or checkpoint
deadline**, and judge movement by a **normalized semantic fingerprint**: artifact existence,
branch or remote SHA, terminal ledger status, exact deploy-SHA readiness, process exit and
identity, child result. Raw output bytes and JSONL or log mtimes do not qualify. A wake triggered
by another lane never counts against a live lane still inside its lease; a lane that misses its
own deadline is what escalates or gets interrupted.

Record material transitions in `<slug>.events.jsonl`. An unchanged external check does not
justify another scheduled check. There is no default wake cadence.

## Grading a lane

- **Grade by ARTIFACT, never by the completion envelope.** Before marking a lane done, check the
  objective thing it was asked to produce: commits on the branch, the named file, the row. A green
  `subtype:"success"` over **zero commits** is a dead lane (observed: exit 1 on an API 429 after 66
  turns and $7.24). Exit 143 with a 0-byte output is SIGTERM under machine load: **salvage the dirty
  worktree before re-dispatching.** Name the artifact in the manifest lane entry and in the
  mission, so the check is unambiguous.
- **A lane that ends short of its artifact owes a handoff note**: one line of what remains plus the
  last verified fact, appended to `<slug>.events.jsonl`. Without it the operator re-types the
  original GOAL (observed: one prompt resent byte-identical 5×). A re-dispatch is a
  **continuation**, never a replay.
- **A child session's report is a claim.** Check its PR (`gh pr view <n> --json mergedAt,state`)
  and branch before updating a ledger row. Merged is not baked.

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
files, never a whole-repository fingerprint. `send_message` and `interrupt_agent` stay available
for corrections and stopping work. Legacy unmarked calls are valid but get no protocol-state assessment.

The whole manifest is mode-bounded: `moderate` permits at most **two total activations** (one
primary, one changed-seam closure); `critical` permits at most **five total activations** (up to
two primary, up to two named investigator/falsifier/security slots, one closure). A named skill may
use fewer slots, never more than the mode ceiling. More needs explicit user authorization and a
fresh task.

1. Run one broad primary wave. `moderate` allows one primary reviewer; `critical` allows at most
   two independent primary slots. Each gets a self-contained mission and no history, or the
   smallest evidence slice.
2. Consolidate and deduplicate once. Falsify the material survivors before fixing them; reviewer
   output is evidence, not an instruction to apply every finding verbatim.
3. A named finite skill may use investigator, falsifier, security, or bounded cross-examination
   slots only within the mode ceiling. They are not permission to repeat a completed stage.
4. After fixes, run one narrow closure pass over the changed seams. Then stop. Backlog
   non-blocking or cosmetic residue with the evidence already gathered.

Another broad cycle needs explicit user authorization and a fresh task. Do not interrupt and
restart the same reviewer, or keep sending follow-ups, without a changed diff, artifact, or final
result that justifies the next declared stage.

## Pre-flight verification — before any routing claim

Verify the source of truth; never infer from secondary signals.

1. Mine fresh each turn; a 5-minute-old interpretation is stale.
2. **Branch HEAD vs the state file's last-seen commit** is the authoritative liveness signal. JSONL
   silence, "Exiting." text, and `child_procs` alone never classify a lane RETIRED.
3. Answer "what's left in spec X" from **the spec file**, not a tracker body; tracker bodies decay.
4. `gh pr view <N> --json mergedAt,state,mergeStateStatus` is merge truth. Recent main commits are
   confirmation, not authority.
5. Deferred markers ("now-runnable-post-deploy", "flippable") are **promises**: a lane cannot retire
   while one is an unredeemed skeleton. Staging E2E is not prod E2E; one marker covering both is
   conflation.
6. A subagent reporting "done" with paths under `/tmp` or `/private/tmp` produced a **draft**:
   re-run the final step in the lane's worktree before relaying it.

Stale, contradicted, or absent input → STOP and re-verify. Never state a routing claim from
incomplete data.

## Spawning a headless lane

`~/.claude/scripts/spawn-lane.sh` is the lane verb (a symlink that `wire-skills.sh` keeps pointing
at this skill's `scripts/spawn-lane.sh`). The operator allowlists that path once; a session may not
invoke `--permission-mode bypassPermissions` directly. Each rule below was earned by a real failure:

- **Repo lane hook.** `<lane-cwd>/.claude/lane-env.sh` is sourced under the spawner's
  `set -euo pipefail` with `$RUNTIME` in scope; it may export `LANE_MCP_CONFIG` (passed to a Claude
  lane as `--mcp-config`). Export it only for `RUNTIME=claude`: a codex lane refuses supplied MCP
  config with exit 2. The file must be TRACKED, because a worktree lane sees only tracked files.
- **Never pipe the spawn; detach stdin.** `spawn-lane.sh … | tail` can exit 0 with 0 bytes and zero
  work done. `claude -p --output-format json` ALWAYS emits a final JSON blob, so **empty output plus
  exit 0 proves the lane never ran.**
- **Chunk by lifecycle phase.** Background Bash has a runtime cap; a whole-feature marathon gets
  killed or piles up context. Use one fresh bounded task for each of `define`, `build`, and
  `verify-release`; each resumes from branch artifacts and the proof-obligation ledger.
- **`--worktree` on first spawn only; `--cwd <existing-worktree>` on every continuation.** A second
  `--worktree` collides with the locked one.
- **Verify remotely.** After every lane exit run `git ls-remote --heads origin <branch>`;
  committed-but-unpushed looks successful and is a stall.
- **Verify the substrate BEFORE dispatch.** Before spawning a verify lane against a staging or
  deployed target, confirm that environment carries the SHA: `git -C <env-worktree> rev-parse HEAD`,
  or `git branch --contains <sha>` on the deploy branch. Finding "not deployed yet" inside the lane
  wastes an activation (observed: a verify lane returned "no staging worktree is at `<sha>`" and a
  second lane went to find where staging was). This is the pre-dispatch counterpart of *Verify
  remotely*; the same check on the resume path is `merge-and-retire.md` §Post-merge proof.
- **Only the `verify-release` phase runs the project gate, exactly once.** Define and build lanes
  run targeted checks. A headless verifier runs the gate synchronously within its budget or stops
  with the command artifact; it never backgrounds the gate and waits for a notification.
- **Deletability claims are HYPOTHESES.** Teardown missions say: grep-verify call sites, and "if
  verification shows the code isn't dead, STOP and report; never weaken a test to make deletion pass."
- **Mission content:** goal one-liner · issue ref with acceptance criteria · owned paths and
  DO-NOT-TOUCH · one lifecycle phase · mode and proof-obligation ledger · artifact to grade ·
  `stacked_on:` edge · "NEVER merge to a protected branch, deploy, or touch prod" · "on a 2nd
  identical tool denial, print `BLOCKED_ON_CLASSIFIER` and stop" · "final reply = one JSON status
  object". Fresh `--session-id`; scrub `CLAUDE_SESSION_ID`/`CLAUDE_CODE_ENTRYPOINT` from the child
  env. Keep global hooks in the child.

Interactive lanes (human-driven only) use `../prompts/session-template.md` and
`../prompts/loop-directive.md`. A new interactive lane's prompt stays lean (≤~900 chars): GOAL /
STATE (only facts not in repo law or the ticket) / START HERE (pointers, never pasted bodies) /
mission-specific GUARDRAIL. A resumed unit carries its mined 5-part prompt instead
(`../REFERENCE.md` §Unit-prompt rules).

## Before spawning: conflict map

List which paths each in-flight lane owns and name them DO-NOT-TOUCH in the new mission. Usual
collisions: a shared layout or data component, an observability module, the lockfile (lockfile
churn serializes lanes), per-customer or schema config. Every commit instruction must let the
session-id trailer expand: write the body to a file and run
`git commit -F <file> --trailer "Session-Id: $CLAUDE_SESSION_ID"`. A quoted `<<'EOF'` heredoc ships
the literal placeholder, and an unquoted one also runs any backtick in the body.

## Merge and retire

Use the project's own merge verb and approval rule; a manager never merges without the human's
in-session go-ahead unless project law grants that change class. The retire checklist, keyed
post-merge proof, and PR preconditions are in `merge-and-retire.md`.

## Backlog and models

Backlog lives on the repo's tracker, named in its `AGENTS.md` `## Agent skills` block. For a huge
or foggy multi-session effort run `/wayfinder` FIRST; to break a settled plan into tickets,
`/to-tickets`.

Per-lane model and effort: `../prompts/model-routing.md`. Every dispatch names its model and
effort on purpose. Ad-hoc Claude delegation defaults to **sonnet**; `opus` needs a one-line
justification; the deep verify/judge/adversarial bucket is `fable` (Claude) or Codex's bounded
`adjudication`/`security` class at high effort. `codex-headroom.sh --route` owns the Codex model
id; never restate it here.

## Close-out and skill memory

Close out with ONE summary to the human: shipped (PR and `mergedAt`), parked and why, still
unproven. Read the private overlay if present, `~/.claude/skills-overlay/sessions-to-chips/LEARNINGS.md`
(adopter-private, never in this public repo). At close-out, route each learning by scope (full
routing: [`docs/skill-memory.md`](../../../../docs/skill-memory.md)): operator-private manager craft
→ that overlay; project facts → the project's `.claude/memory/`; universal craft → note it for
`/improve-harness` to promote here by PR.

## Anti-patterns

- ❌ Implementing code, running installs, or running review panels in the manager. Push them into a lane.
- ❌ Reasoning machine-wide: counting foreign programs' sessions, nudging lanes you did not start or
  adopt, or running without a manifest once you hold lanes (unregistered claims manufacture the
  collisions the protocol prevents).
- ❌ Logging into the manifest instead of `.events.jsonl`. The 8 KB cap is the tripwire.
- ❌ Trusting a completion envelope, a lane's local worktree, or a subagent's `/tmp` output as a deliverable.
- ❌ Trusting chat-text signals ("Exiting.", JSONL silence) over branch HEAD when classifying a lane.
- ❌ `send_message` as the last act of an unattended wake, or a wake prompt that re-serializes the
  state instead of pointing at it.
- ❌ Polling wakes against a human-only gate, or a lane parking on "waiting for PR #N" when it could
  stack on #N and build now.
- ❌ Starting a child session from an automated turn and calling the work autonomous. It lands as a
  card that needs a human click; unattended work goes to a headless lane.
- ❌ Piping a lane spawn, or one monolithic spec→implement lane that the runtime cap kills.
- ❌ Blind-retrying through a safety-classifier or model-outage window. The 2nd identical denial ends the lane.
- ❌ Opening a PR, or retiring a lane, while proof obligations are non-terminal or lack an owned
  deferral (`merge-and-retire.md`).
- ❌ Turning a moderate proof ledger into exhaustive test enumeration or an autonomous deploy/poll loop.
- ❌ Running a long test, build, or gate process in the context-heavy root, or spawning one
  procedural child per command. Batch one pass; keep judgment in the root.
