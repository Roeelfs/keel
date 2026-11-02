---
license: MIT
name: sessions-to-chips
description: Start and run managers. A manager is one standalone "[Manager] <title>" session that owns ONE program (a goal) and drives it through child sessions, headless lanes and Codex lanes, never implementing itself. Three entry modes. New manager - the human names a goal ("orchestrate", "start a manager", "drive this program", "run 3+ parallel sessions toward one target", a big autonomous project). Resume / mine - any resume, account switch or "mine" request runs scripts/mine_all.py once: every account's sessions, every transcript of each session chain, per-program checkpoints, handoffs, then child ledgers, decisions and worktree sweeps, gated by a completeness receipt, then ONE message per manager; a program with no manager here is put to the human, never started unasked (also mine-only audits, read-only). Wrap-up - checkpoint every manager before an account switch or usage cap. Shared by all: the Manager contract (program state, collisions, lane runtimes, spawn-lane.sh, advance tick, grading, reviews, merge-and-retire) and session hygiene. Starting sessions needs explicit authorization; read context only via permitted interfaces.
---

# sessions-to-chips — managers

The unit of this skill is a **manager**: a standalone desktop session titled
`[Manager] <title>` that owns ONE program (a goal). It verifies facts, starts children, grades
their artifacts, holds the human gates, and keeps its family small. It never does a child's work.

Three modes produce or feed managers. All of them obey the same **Manager contract**
([`references/manager-contract.md`](references/manager-contract.md)) and **session hygiene**
([HYGIENE.md](HYGIENE.md)).

| Mode | Use when | Produces |
|---|---|---|
| **1. New manager** | the human names a goal to drive | one `[Manager] <goal>` |
| **2. Resume / mine** (was Modes 2 and 4) | resume parked work, take programs back after an account switch, or "mine" / audit sessions | a completeness receipt, per-program handoffs and ledgers, then ONE message per manager; a new manager only where none exists and the human says so |
| **3. Wrap-up** | an account switch or usage cap is coming | a checkpoint note per manager; no new managers |

The app's session tools see **only the account you are signed into**; see Mode 2 before you
message or start anything after a switch.

`SCR=~/.claude/skills/sessions-to-chips/scripts`

## Starting a manager (every mode)

**One rule: the manager is always its own session.** The session that runs this skill is only the
dispatcher; it starts the manager and stays out of the program. Why: the `[Manager]` title is what
the hygiene Stop hook, `wrapup_roster.py` and `hygiene_candidates.py` key on; children nest under the
session that starts them, so a manager must start them itself; and a dispatcher carries unrelated
context that the manager would re-read every turn. Two cases already satisfy the rule: if you are
the `[Manager]` session for this goal, you are the manager, so start no second one; if the host
cannot start sessions (Codex CLI, a headless lane), the current root is the manager and follows the
contract in place (`references/codex-runtime.md`).

**Model policy.** Managers run Sonnet 5.5 at medium effort and only read, verify and dispatch;
specs and all implementation come from Opus 5.5 lanes or Codex lanes, never from the manager
(manager-contract.md §Model policy).

Start it with `mcp__ccd_session__start_session` (`spawn_task` only where that is all the host
offers). Measured failures (2026-10-14) behind each argument:

- **`use_worktree: true` and `context: "fresh"`.** With `use_worktree: false` the manager shares
  the dispatcher's checkout. The app then refuses to detach it ("a session that shares its parent's
  checkout can't be moved to top level"), and archiving either session drags the other's children
  along. Recovery is archive plus re-dispatch.
- **`model: sonnet`, `effort: medium`.** Managers only read, verify and dispatch. A manager's
  spec and implementation children start on opus (or run as Codex lanes); only mechanical
  children get sonnet/medium.
- **No `initiation: "user_asked"` from an automated turn.** A Workflow completion or another
  session's note is not the user speaking, and the app refuses the start. Use `own_initiative`
  there (it becomes a card), or start from the turn where the user asked. Tell the manager that if
  its own start of a child is refused the same way, it proposes the child as a card and starts it
  when the human says so.
- **Check for a live `[Manager]` on the same program first** (`list_sessions`). Two managers on one
  program collide on the same worktrees and PRs. To re-dispatch, archive the old one first, after
  confirming none of its children has live work (`archive_session` is refused while a child works,
  and archiving a parent archives its children).
- **A duplicate title is not an error to guess through.** Take the most recently active
  non-archived row per title, and say which one you picked.
- **A manager the dispatcher started cannot start its own children until the human speaks in it**
  (measured 2026-10-22): the app refuses each start as automated, even with the human's go-ahead
  quoted in the prompt, and the manager files cards instead. Tell the human in one line to click
  the cards, or to type one message in the manager's chat, after which its starts are the human's.
- **"Workspace requires trust approval before starting a session."** Waking an existing session
  (a message, not only a start) reopens it in its worktree, and on an account that has not trusted
  that workspace the send is refused. Do not retry. Ask the human to open one of those sessions and
  accept the trust prompt, with a pre-written `Done` answer, then resend. A fresh `start_session`
  in a new worktree was not blocked by it.

## Mode 1 — New manager

1. Name the program: a short slug and an outcome-shaped goal (it may be fuzzy; lanes sharpen it).
   For a huge or foggy multi-session effort, run `/wayfinder` first and give the manager its map.
2. Check for a live `[Manager]` on the same goal (above). If one exists, hand the request to it by
   session id instead of starting a second.
3. Start ONE session titled `[Manager] <goal>` with this prompt, filled in:

   ```text
   You are the manager for program "<slug>". GOAL: <outcome>.
   CONTRACT: ~/.claude/skills/sessions-to-chips/references/manager-contract.md binds you. Read it
   first, then the reference its triggers name. Your first act is to declare the program's three
   state files (manifest, events, state) under ~/.claude/orchestrator/programs/.
   MODEL POLICY: you run sonnet/medium and never write a spec or code yourself; specs and all implementation go to opus or Codex lanes (contract §Model policy).
   STATE: <only facts not in repo law or the ticket: issue refs, branches, PRs, worktrees>.
   START HERE: <pointers: spec, map, tracker issue; never pasted bodies>.
   GATES: <prod mutations, merges, founder decisions the human holds>.
   ```

   Keep it lean (≤~900 chars). The contract carries the rules; never paste them into the prompt.

## Mode 2 — Resume / mine (one pass; also after an account switch)

Mining is the default and runs ONCE. Every resume, account-switch or "mine" request starts with
this, and with nothing else:

```bash
python3 -I $SCR/mine_all.py              # --dry-run: same receipt, writes nothing under ~/.claude
```

It does every deterministic step in one invocation: all account dirs of the session store (never
`--account` alone); which account this session is on (`CLAUDE_SESSION_ID`, or `--here <prefix>`);
each program and every manager instance it had across accounts, identified by manifest session ids
first, then title (`program_family.py`); every transcript of each session chain
(`transcript_chain.py`); each program's **checkpoint**, derived from the last turn of its manager
on this account and proven by the store's `lastAssistantUuid`, never a typed time; then
`child_ledger.py`, `handoff_sweep.py` and the coverage audit over all accounts, with **holes
widening** until holes = 0 or each is named unreadable with its reason; the state-file fold; one
digest per chain segment. It writes the plan `relay/<date>-mine-plan.json` and the **completeness
receipt** `relay/<date>-completeness-receipt.md` (accounts, sessions per account,
managers/programs, chains and bytes, children ledgered, holes = N, gates).

**What the data shows** (measured 2026-11-01, so do not re-derive it by hand): the store's
`cliSessionId` names only a session's NEWEST transcript; a resume, move or fork mints a new file
whose head `parentUuid` points into the old one (22 multi-file chains in 14 days, Apps spans three
files in two worktrees). `lastActivityAt` also moves on focus and artifact rows (Release:
last turn 10-28T12:38Z, store 10-31T11:27Z, every turn present), and `accountUuid` sits only on
artifact rows, so it never proves which account ran a turn: the store dir does.

**Print the receipt to the human first.** Then by exit code:

- **2, a deterministic gate FAILED.** Fix it (for example `--here` when the account is unknown)
  or put it to the human. Message no manager.
- **3, agent gates OWED.** Run the plan, in order, each phase in ONE message of parallel Agents:
  1. Phase 1, every `handoff:<slug>` step ([prompts/handoff-miner.md](prompts/handoff-miner.md)).
  2. Phase 2, only after phase 1 has landed: every `reconcile:*` step
     ([prompts/child-ledger-reconciler.md](prompts/child-ledger-reconciler.md); its `mode` covers
     the old-descendant (Test B) and orphan-transcript classifiers), the decisions sweep
     ([prompts/decisions-sweep.md](prompts/decisions-sweep.md)) and the worktree sweep
     ([prompts/worktree-sweep.md](prompts/worktree-sweep.md)).
  3. `python3 -I $SCR/mine_all.py --gate <plan>` grades every step by its artifact and re-renders
     the receipt. Re-run only an OWED step, never the mining.
- **0, every gate PASS.** Relay (phase 3). **The dispatcher never messages a manager while the
  receipt shows a FAIL or OWED gate.**

**Mine-only** (mine, inspect or audit): stop after phase 2 and report the receipt and the step
outputs. It stays read-only and creates no sessions.

**Relay: ONE message per manager** (`messages[]` in the plan, [CATCHUP_MESSAGE.md](CATCHUP_MESSAGE.md)),
by session id, carrying its handoff, its `-children` files, its decisions and worktree rows, every
cross-cutting ruling (they go into EVERY manager's message), the backlog-first order, and the
plan's ready-to-run founder kits. Say explicitly that the other account's stopped children ARE the
program's work. By `kind`:

- `catchup`: the manager here keeps its sidebar group, worktree and family; the handoff replaces
  its stale context. Archive older duplicate managers here.
- `fold-notice`: the program was absorbed (manifest `absorbed_by`). The live manager is a duplicate
  owner: it hands its live child over at its next checkpoint and runs hygiene; the absorber gets a
  takeover note in its own message.
- `no-manager-here`: grill the human in this session (start one, or leave it standalone;
  recommended answer first) and START NOTHING unasked. Under "relay to existing managers", list the
  program and its handoff path instead.
- `closed-program-rows`: the family is archived; its rows ride the absorber's message.
- Config age is never a reason to re-dispatch: run `scripts/config_freshness.py` and refresh the
  `STALE-*` rows by message ([references/config-freshness.md](references/config-freshness.md)).

Send constraints (measured 2026-10-24/26): the app pauses sends after about 10 session messages
since the human last typed, so one message per manager is a budget: follow-ups wait for its reply.
A send refused with "Workspace requires trust approval" is not retried: ask the human once for all
refused sessions. Write every undelivered message to `relay/<date>-pending-sends.md` the moment it
is refused. Queued is not read: do not re-send. A catch-up starts the manager's turn as "another
session's message", so the app refuses its `start_session`: close the round with ONE line to the
human naming the managers that need a child, "type `go` in each". Only the signed-in account's
sessions are reachable (`list_sessions`, `SendMessage`, `archive_session`); the other account's
show as `Remote Control · offline` and a message to one is queued to nowhere. Never relay to them.

**Converge.** Do not poll. Append each one-line reply to `relay/<date>-replies.md`. A program is
converged when its manager replied to the catch-up (archived N, live children X, decisions held)
and to backlog-first (before → after), confirmed its sweep fixes (fixed N of M) and worktree rows,
recorded the standing rulings in its state file with a fresh `updated_at`, and its Linear map has a
`State as of` comment newer than the catch-up. `pending-sends.md` must be empty or listed to the
human. Close with which managers hold open founder decisions and a link to each.

**Archiving on the other account is the human's:** write `relay/<date>-archive-on-<account>.md`
(what to archive, what to keep; move a kept subtree under an archived parent to top level first).
**Hygiene asked of the dispatcher is relayed** as one line in each catch-up; the dispatcher has no
family. Exception: duplicate managers of one program on this account. Inside each manager the order
is fixed: BACKLOG FIRST, then salvage, then the program.

**Resuming parked sessions as a NEW manager** (a category with no manager: the `unmanaged` or
`orphans` rows, or sessions the human names): group them with `group_sessions.py --root
"<title>"`, mine and narrate them with the `mine_workflow.js` Workflow, persist the story to
`maps/<date>-<category>.md`, and start one `[Manager] <origin title>` per category under §Starting
a manager. [REFERENCE.md](REFERENCE.md) has the story structure, Workflow arguments and unit
rules; a started unit with uncommitted work opens with the WORKTREE NOTE.

Mechanics that cost retries: zsh ties `path` to `PATH` (`read -r cli size path` breaks the next
command; use `tpath`); the other account's sessions are `not found` to `get_session` here, which
is never evidence they are dead; never trust a subagent's owner or "live" claim without the
`gh pr view` / `git worktree list` line it ran; a founder ask found by a sweep goes into that
manager's message, never the dispatcher's closing list; prefer a session's `list_events` (a read)
over a nudge (a send).

### Founder decisions stay with their manager

A founder decision is asked, answered and recorded in the session of the manager whose program it
belongs to, because that is where the context, the default and the follow-through live, and the
human's go-ahead must be typed there ("a manager never relays approvals"; it holds equally for a
dispatcher). The dispatcher never compiles a cross-program decision list, never asks the human for
another program's ruling, and never records an answer it heard secondhand. When a sweep finds a
founder ask, it goes into that manager's handoff or message; when a reply mentions one, the
dispatcher leaves it there. The only thing the dispatcher may say about them is where they are.

## Mode 3 — Wrap-up (checkpoint before an account switch or a usage cap)

Run this **instead of mining** when the goal is fewer, converged sessions and a state that survives
the switch: session history is not readable from the other account, so everything must live in
git, the tracker and a note. It is a checkpoint, **not a full stop**: running builds and lanes
finish, nothing new starts.

```bash
python3 -I $SCR/wrapup_roster.py --date <YYYY-MM-DD>   # {managers, superseded, unmanaged, counts}; sends nothing
python3 -I $SCR/wrapup_status.py --date <YYYY-MM-DD>   # one-shot: which sessions have written their note
```

1. **Roster.** `managers` is the newest live `[Manager]` per category; `superseded` are older
   managers of the same category (not messaged, listed with their live children); `unmanaged` are
   recent live sessions no manager parents. The slug match is by title, so near-duplicates (two
   managers for one program under different titles) need a human eye before sending.
2. **Send** (explicit user go-ahead required: it wakes every session and spends usage). Use
   `SendMessage` by **session id**, never by name. Each manager gets its `message`
   ([WRAPUP_MESSAGE.md](WRAPUP_MESSAGE.md)); each unmanaged session gets its own
   ([WRAPUP_UNMANAGED_MESSAGE.md](WRAPUP_UNMANAGED_MESSAGE.md)). The manager message tells the
   manager to checkpoint its children itself, so the dispatcher never messages grandchildren.
3. **What each session does:** finish in-flight work to a checkpoint, push its own branch once or
   record worktree/branch/PR, post one tracker comment and set state per ticket it touched, archive
   only DONE-and-merged children, refresh `~/.claude/orchestrator/programs/<slug>.state.md` (Mode 2
   folds it into the handoff), and write `~/.claude/sessions-to-chips/wrapup/<date>-<slug>.md`
   with the surviving set, the gate blocking each item, "Linear owed", "Owed to the founder" (asked in the manager's own session, never relayed), and a
   paste-ready continuation phrase. Merges, deploys and prod writes still need the human's
   in-session go-ahead; a blocked item with its gate named is a finished checkpoint.
   **Before sending, sweep the children on THIS account** with `child_ledger.py --account <this
   account> --since <the manager's last turn> --out <dir>` and name each manager's `-children.md`
   in its message, so findings that live only in a child's chat get written down while that chat
   is still readable.
4. **Converge.** Do not poll. When a session's note arrives, run `wrapup_status.py` once. The
   dispatcher's closing message lists notes written, notes missing, which managers hold open founder
   decisions (a count and a session link each, never the decisions themselves), and the
   before/after session counts. See "Founder decisions stay with their manager" above.
5. After the switch, run Mode 2 from a session on the NEW account. The notes on disk are shared
   by both accounts, but the sessions are not.

## Manager contract — the rules that must fire

Depth and evidence for each rule are in [`references/manager-contract.md`](references/manager-contract.md).

- **Never implement.** Code, installs, review panels and long gates go into a lane or child.
- **One program, your lanes only.** Filter every machine-wide list to your manifest's membership.
  First claim wins; transfer, don't grab; a live-vs-live contest goes to the human.
- **Program state is three bounded files, declared first in either mode,** under `~/.claude/orchestrator/programs/`: a manifest
  (strict keys, ≤~8 KB, `updated_at` to the second), an append-only `.events.jsonl`, and a
  `.state.md` with a completion checkpoint and `## AT-WAKE`.
- **Pick the lane runtime by deliverable:** headless lane (`~/.claude/scripts/spawn-lane.sh`) for a
  branch or PR, `Agent`/`Workflow` for information, a Codex lane for a crisp off-window pass, a child
  session only when the human must judge. **Probe a headless Claude lane first:**
  `scripts/lane_probe.sh <model>` (rc 0 ok, 1 refused/capped, 2 no output). A lane can be capped (429)
  while desktop sessions work, and a dead lane exits 0 with 0 tokens. Rc 1 means use an in-session
  `Agent` or a desktop session instead. The probe is necessary, not sufficient (2026-10-24: it passed
  right after a lane died on 429), so re-probe at dispatch and still grade by artifact.
- **Grade by ARTIFACT, never the completion envelope.** Salvage a dead lane's worktree
  (`git status --porcelain`) before re-dispatching; a re-dispatch is a continuation, never a replay.
- **Verify before any routing claim:** branch HEAD, `gh pr view --json mergedAt,state`, the spec
  file. Merged is not baked. Confirm the deploy SHA is in the environment before a verify lane.
- **Every dispatch has a wake.** A lane is launched tracked (event-driven: background Bash, `Agent`,
  `Workflow`, child session) or, where no event can exist, with ONE event-bound `ScheduleWakeup`
  armed and recorded in the state file; never detached. Audit every unreported lane before ending
  a turn (manager-contract.md "Every dispatch has a wake").
- **No scheduled polling.** No heartbeat, `/loop`, cron or re-armed wake unless the user asks for
  that schedule. An external gate gets a keyed resume artifact and the turn ends.
- **No stop without an armed wake** — it wins where the bullet above differs: a turn ends WORKING only with ONE event-bound wake armed and recorded in `## AT-WAKE` (429s, caps, CI, "waiting on X" included); only DONE and GRILLING end unarmed (manager-contract.md "No stop without an armed wake"; Stop guard `hooks/manager-arm-guard.sh`).
- **Overrides first, every tick:** terminal stop (zero further tools), then completion-mode freeze,
  then an owned child still inside its lease. Only then survey, classify, and dispatch every
  independent forcing function at once.
- **One living map per manager.** The program's goal is a Linear `wayfinder:map` issue (manifest `map`);
  every new piece of work is filed as a child ticket in the turn it is found, before any lane runs;
  the manager advances the frontier in parallel until the Destination is met; every report opens with
  the Map line (done/open/blocked, frontier, needed from you). Contract §Every manager owns one living map.
- **Spec review is mandatory, depth by risk.** Every spec is `/spec-review`ed before its build lane
  starts; tier (critical|standard|light) follows risk (access/security/architecture/infra = critical),
  lanes are chosen per spec and configurable. A spec with no review artifact is not buildable
  (contract §Spec review is mandatory).
- **Parallel by default.** Dispatch the whole independent set each tick (Codex ≤5, one writer per
  file set); a blocker blocks only its dependents. Contract §Parallel by default.
- **Three end states only: DONE, GRILLING, WORKING.** A manager session ends every turn either
  with no work left (family archived, nothing owed), or having grilled the founder on ALL open
  decisions in one round (recommended answer first), or actively doing and managing work (test,
  bake, preview, build, spec, review, or active children and lanes, each with an owner and an
  artifact). "Parked", "blocked on X", "waiting" and "N items owed" are defects: start the work,
  grill the decision now, or finish. Contract §Open items.
- **A founder ask arrives as a ready-to-run kit.** Anything the human must DO (secret, login,
  step-up, CLI, console click, go-ahead) comes with the exact command in its own fenced `bash`
  block (secrets by reference, never inline), where and as whom to run it, what success looks like,
  the one-line reply that resumes you, and what you do next. Steps you can run, you run. One
  numbered round, most-unblocking first. Contract §Open items.
- **No open items — grill them.** Decide what is reversible or in-brief yourself; grill founder
  decisions in your own session, whole frontier, recommended answer first, and keep working while
  they wait. No state file, note or close-out carries an open-questions list. Contract §Open items.
- **Finite reviews:** `moderate` ≤2 activations, `critical` ≤5, one changed-seam closure, then stop.
- **`send_message` stalls an unattended recipient.** Send only from an operator-present turn, by
  session id, never as the last act of an unattended wake.
- **Merges and prod need the human's in-session go-ahead** unless project law grants that class.
- **Keep your family small** at every stopping boundary ([HYGIENE.md](HYGIENE.md);
  candidates: `scripts/hygiene_candidates.py`, run from the manager itself). In a `[Manager]` session the
  `manager-hygiene` Stop hook announces each new candidate set. Hygiene is standing: run it when
  the hook, the founder or another session asks, with no confirmation (HYGIENE.md "Authority").
  **Backlog first:** before engaging with new work (a catch-up, handoff, new unit), clear every family
  session idle ≥1 day (HYGIENE.md "Backlog first"); Mode 2's catch-up makes this its first step.
- **Harness changed? Refresh, don't re-dispatch.** Hooks, permissions and agents reach a running
  session live; CLAUDE.md, skill bodies already invoked, plugins and the CLI build do not.
  `scripts/config_freshness.py` names each stale session and its fix (a refresh message naming the
  files to re-read; restart-class items wait for the next app relaunch). Never kill a CLI process.
  Detail: [`references/config-freshness.md`](references/config-freshness.md).
- **Close out** with ONE summary: shipped (PR and `mergedAt`), parked and why, still unproven.

## References

- [`references/manager-contract.md`](references/manager-contract.md) — the full contract.
- [`references/lifecycle.md`](references/lifecycle.md) — define → build → verify-release.
- [`references/merge-and-retire.md`](references/merge-and-retire.md) — merge, post-merge proof, retire.
- [`references/config-freshness.md`](references/config-freshness.md) — stale config in a live session: detect, refresh, restart.
- [`references/codex-runtime.md`](references/codex-runtime.md) — when hosted by Codex CLI.
- `prompts/` — lane missions, state miner, model routing, procedural worker.
- [REFERENCE.md](REFERENCE.md) — new managers from parked sessions (Mode 2): story structure, unit-prompt rules, completion criteria.
- Private overlay, if present: `~/.claude/skills-overlay/sessions-to-chips/LEARNINGS.md`
  (adopter-private) for project-specific examples and gate commands. Managers append generalizable
  calls there at close-out.
