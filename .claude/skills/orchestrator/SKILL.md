---
license: MIT
name: orchestrator
description: Cross-session orchestrator pattern — orchestrate ONE program (a goal/target) across its own lanes, including fully autonomous stretches (headless no-prompt lanes, un-gated-frontier planning). Program-scoped, never machine-scoped — multiple orchestrators coexist on one machine via program manifests + an ownership/collision protocol. Surfaces state, coordinates conflicts, spawns lanes, never implements directly. Use when running 3+ parallel sessions toward one target or driving a big project autonomously.
---

# Orchestrator

You orchestrate **ONE PROGRAM**: track its lanes, catch conflicts before they hit main, spawn lanes (headless / agent / Codex / chip), hold every terminal gate, surface decisions. You never implement code yourself.

Depth lives in `references/` and is **not** auto-loaded:

- **Read `references/lifecycle.md` before planning, spawning, or grading a spec-class lane** — the canonical 7-step lane, skip rules, ready-to-execute gate.
- **Read `references/merge-and-retire.md` before merging any lane PR or signing off a retire** — merge tiers, post-merge phase chain, retire checklist.
- **Read `references/codex-runtime.md` first when `$CLAUDE_SESSION_ID` is unset** — you are hosted by Codex CLI and most verbs below do not exist there.

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
| **Headless lane** | a branch/PR | `scripts/spawn-lane.sh --mission <file> --cwd <worktree> --model <alias>` via Bash `run_in_background` | anything shippable; unattended stretches; work needing its own context window |
| **Background `Agent` / `Workflow`** | information: report, verdict, map | `Agent` / `Workflow` tools | mining, research, scope audit, cross-lane verification, judge panels |
| **Codex lane** | an independent review/verify/research/census pass, or a bounded implementation from a written spec | see block below, via Bash `run_in_background` | the lane has a crisp contract and you want it **off the Claude 5-hour window** |
| **Chip session** | human judgment | `spawn_task` — **requires a human click** | grillings, decision gates, and resurrecting a parked lane the human will personally drive (`sessions-to-chips`) — never a substitute for a headless lane in an unattended stretch |

```bash
cd <repo> && echo '' | codex exec --skip-git-repo-check -m gpt-5.6-sol \
  -c model_reasoning_effort=high -s read-only -o <outfile> -- "<prompt>"
```
> **Grade this lane by its ARTIFACT before counting it** — exit 0 is not evidence. Invocation flags, the `wc -l` / severity-grep check, and the DEAD vs **BLOCKED-ON-QUOTA** vs REAL classification live in [`docs/codex-lane-contract.md`](../../../docs/codex-lane-contract.md). Measured 2026-08-02/03: 18 of 52 rollouts hit a quota wall while exiting normally; 20 of 52 completed fine, so a dead lane is never proof the runtime is down.

Then read a **slice** of `<outfile>`. Codex starts **cold** — a lane needing accumulated conversation, harness state, or MCP servers stays on Claude. Do not route through a Claude subagent that only shells out to Codex; that charges the window you are sparing.

**A headless lane is a ROOT session — push whole lifecycle phases into it.** The no-nested-dispatch rule binds Agent-tool subagents, not lanes: a lane may run subagent-driven implementation, review fan-outs, and Workflows internally (grant it explicitly in the mission text). The orchestrator plans and integrates; it does not run review panels itself.

**MCP tiers differ by substrate.** A Task subagent inherits the desktop MCP set (interactive OAuth included); a headless lane gets only static-credential MCPs the spawn wrapper attaches. Interactive-OAuth MCPs do **not** load in `-p` mode — a lane needing a tracker gets it via `--mcp-config` with an API-key header. Anything desktop-MCP-only, the orchestrator does itself. Missions stay self-contained regardless: MCP is for depth, not for the brief.

## Transport, continuation, and the human

- **`ScheduleWakeup` is the continuation mechanism** — one snapshot per wake, never a poll loop. Size the delay to what you are waiting on (a CI run is minutes; a bake is hours). Re-arm only on a **changed fingerprint**; if nothing moved, extend the delay instead of re-firing at the same cadence.
- **The wake prompt is a POINTER** — state-file path + "step N NOW" + the one fact that changed since arming. Never the state itself. (Measured: 97 of 170 wake prompts carried ≥1,000 chars of re-serialized state, up to ~6k, because nothing durable survived the turn boundary. `<slug>.state.md` is what makes the pointer sufficient.)
- **`Monitor` with an until-loop is the sanctioned way to BLOCK on a condition.** Foreground `sleep` is blocked at the tool layer and sleep-bridge poll loops are hook-denied.
- **`AskUserQuestion`** is how a contested claim, a pre-authorization ask, or a genuine judgment call reaches the human. **`PushNotification`** tells an away operator something now needs them.
- **`TaskCreate` / `TaskUpdate`** carry per-lane status the operator can see; prefer them to prose status dumps re-typed each turn.
- **`send_message` is the orch→live-lane transport, and it surfaces as an approval prompt IN THE RECIPIENT** — an unattended lane stalls on it (operator, verbatim: *"Stop sending messages it will make this session stuck."*). Send only from a turn where the operator is present, and **never as the last act of an unattended wake**. For an unattended lane, leave the instruction where the lane reads it on its own next tick — its state file — not in its inbox.

## Autonomous stretches — the un-gated frontier

Before any unattended stretch, compute the set of work reachable **without a human approval**. The canonical failure: every lane drives to "green + READY", the DAG roots on one human-merge gate, and the night produces polling wakes and zero development.

1. **Stack, don't park.** A lane blocked on an unmerged PR branches its worktree off that PR's branch, builds there, rebases after the merge. Record the edge in the manifest lane (`stacked_on: <pr>`).
2. **Pre-authorization ask BEFORE the human leaves** (`AskUserQuestion`): present the projected merge stack and ask for standing approval per class. A decline is fine — then plan around the gate by stacking. Discovering the gate at 2am is the failure.
3. **Deliberate park.** Frontier genuinely empty → ONE wake at the human's expected return with a morning summary and the ready-to-merge stack. Never poll a gate only a human can open.
4. **Frontier refresh on every event** — a merge, a lane exit, or an operator message re-opens the computation; newly un-gated work dispatches immediately.

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

1. Run one broad primary wave in parallel. Give each reviewer a self-contained mission and no history, or the smallest slice that contains the evidence.
2. Consolidate and deduplicate once. Falsify the material survivors before fixing them; reviewer output is evidence, not an instruction to apply every finding verbatim.
3. A named finite skill may run its declared investigator, falsifier, security, or bounded cross-examination stages. Those are parts of the declared protocol, not permission to repeat a completed broad stage.
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
- **Chunk by lifecycle step** — background Bash has a runtime cap; a full spec→implement lane gets killed mid-flight. One bounded lane per step, each committing its artifact; the next lane resumes FROM THE BRANCH.
- **`--worktree` on first spawn only; `--cwd <existing-worktree>` on every continuation** — a second `--worktree` collides with the locked one.
- **Verify remotely.** After every lane exit run `git ls-remote --heads origin <branch>` — committed-but-unpushed looks successful and is a stall.
- **Lanes never run the machine's full verify gate** — they background it and die waiting for a notification a `-p` lane can never receive. Targeted checks, commit, push; **CI is the authoritative gate** and the orchestrator watches it.
- **Deletability claims are HYPOTHESES.** Teardown missions instruct: grep-verify call sites, and "if verification shows the code isn't dead, STOP and report — never weaken a test to make deletion pass."
- **Mission content:** goal one-liner · issue ref with the acceptance criteria embedded · owned paths + DO-NOT-TOUCH · lifecycle step · the artifact the orchestrator will grade · expected merge tier · `stacked_on:` edge · "NEVER merge to a protected branch, deploy, or touch prod" · "on a 2nd identical tool denial, print `BLOCKED_ON_CLASSIFIER` and stop" (orchestrator then backs off ≥30 min) · "final reply = one JSON status object". Fresh `--session-id`; scrub `CLAUDE_SESSION_ID`/`CLAUDE_CODE_ENTRYPOINT` from the child env. Keep global hooks in the child. The machine-global heavy lock serializes verify/build — cap concurrent heavy lanes at ~2.

Interactive lanes (human-driven only) use `prompts/session-template.md` + `prompts/loop-directive.md`. Chip prompts stay lean (≤~900 chars): GOAL / STATE (only facts not in repo law or the ticket) / START HERE (pointers, never pasted bodies) / mission-specific GUARDRAIL.

## Before spawning: conflict map

List which paths each in-flight lane owns and name them DO-NOT-TOUCH in the new mission. Usual collisions: a shared layout/data component, an observability module, the lockfile (lockfile churn serializes lanes), per-customer or schema config. Parallel pushes to main collide — stash unrelated working tree, commit narrow, push, pop. Every commit prompt uses an UNQUOTED `<<EOF` heredoc so `$CLAUDE_SESSION_ID` expands in the trailer; `<<'EOF'` ships the literal placeholder.

## Backlog and models

Backlog lives on the repo's tracker, named in its `AGENTS.md` `## Agent skills` block. For a huge/foggy multi-session effort run `/wayfinder` FIRST; to break a settled plan into tickets, `/to-tickets`.

Per-lane model/effort recommendations: `prompts/model-routing.md`. Ad-hoc delegation defaults to **sonnet**; `opus` needs a one-line justification; the deep verify/judge/adversarial bucket is `fable` (Claude) or `gpt-5.6-sol` (Codex).

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
- ❌ Opening a PR, or retiring a lane, with test-plan tiers still FAIL or unjustified-SKIP (`references/merge-and-retire.md`).
- ❌ Skipping the test-plan gate because "this feels straightforward" — apply the rubric mechanically.
