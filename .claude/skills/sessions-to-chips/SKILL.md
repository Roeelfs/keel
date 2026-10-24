---
license: MIT
name: sessions-to-chips
description: Start and run managers. A manager is one standalone "[Manager] <title>" session that owns ONE program (a goal) and drives it through child sessions, headless lanes and Codex lanes, never implementing itself. Four entry modes. New manager - the human names a goal ("orchestrate", "start a manager", "drive this program", "run 3+ parallel sessions toward one target", a big autonomous project). Resume from sessions - deep-mine scoped Claude desktop sessions for goals, steering, last state, settled calls, dead ends and remaining work, narrate each category as one story with a unit ledger, and give it to one manager (also mine-only audits of parked sessions or session overlap, read-only). Wrap-up - checkpoint every manager before an account switch or usage cap. Account switch - after switching Claude accounts, mine the other account's managers into per-program handoffs, sweep their worktrees for unpushed work, then relay to the managers on this account; a program with no manager here is put to the human, never started unasked. Shared by all: the Manager contract (program state, collisions, lane runtimes, spawn-lane.sh, advance tick, grading, reviews, merge-and-retire) and session hygiene. Starting sessions needs explicit authorization; read context only via permitted interfaces.
---

# sessions-to-chips — managers

The unit of this skill is a **manager**: a standalone desktop session titled
`[Manager] <title>` that owns ONE program (a goal). It verifies facts, starts children, grades
their artifacts, holds the human gates, and keeps its family small. It never does a child's work.

Four modes produce or feed managers. All of them obey the same **Manager contract**
([`references/manager-contract.md`](references/manager-contract.md)) and **session hygiene**
([HYGIENE.md](HYGIENE.md)).

| Mode | Use when | Produces |
|---|---|---|
| **1. New manager** | the human names a goal to drive | one `[Manager] <goal>` |
| **2. Resume from sessions** | parked or finished sessions should be picked up, or audited | one `[Manager] <origin title>` per category (none in mine-only) |
| **3. Wrap-up** | an account switch or usage cap is coming | a checkpoint note per manager; no new managers |
| **4. Account switch** | you just switched accounts and the programs ran on the other one | a handoff per program; ONE catch-up per manager after all sweeps (children, decisions, worktrees); fold notices for absorbed managers; a new manager only where none exists and the human says so |

The app's session tools see **only the account you are signed into**; see Mode 4 before you
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

Start it with `mcp__ccd_session__start_session` (`spawn_task` only where that is all the host
offers). Measured failures (2026-10-14) behind each argument:

- **`use_worktree: true` and `context: "fresh"`.** With `use_worktree: false` the manager shares
  the dispatcher's checkout. The app then refuses to detach it ("a session that shares its parent's
  checkout can't be moved to top level"), and archiving either session drags the other's children
  along. Recovery is archive plus re-dispatch.
- **`model: sonnet`, `effort: medium`.** Managers only read, verify and dispatch. Each manager pins
  its own children the same way unless a child's prompt states a reason for more.
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
   STATE: <only facts not in repo law or the ticket: issue refs, branches, PRs, worktrees>.
   START HERE: <pointers: spec, map, tracker issue; never pasted bodies>.
   GATES: <prod mutations, merges, founder decisions the human holds>.
   ```

   Keep it lean (≤~900 chars). The contract carries the rules; never paste them into the prompt.

## Mode 2 — Resume from sessions

Turn a set of desktop sessions into **one story per category, run by one manager**. A category is
an origin session plus the sessions it spawned (the sidebar nesting). The workflow reads what each
session *found and decided*, not only where it stopped, tells the category as one narrative, reduces
what remains to the fewest units, and gives it to one manager that starts those units.

**Mine-only.** A request to mine, inspect or audit sessions selects mine-only: run steps 1–3 and
report (goals, steering, latest summary and instruction, results, unfinished obligations, overlap).
It stays read-only: create no sessions just because the flow below ends in them.

**Access.** The scripts read the local desktop store. They do not grant permission to inspect
hidden stores or other accounts; never run them against denied paths or to bypass a missing context
connector. Prefer scoped supported reads, then permitted exports, then authorized UI fallback, and
apply the same deep reasoning to that content. If Workflow or `start_session` is unavailable, use
read-only subagents for analysis and return draft prompts; never invent an API or silently create
sessions. `claude-sessions` owns the live Claude survey and decision extractor; `codex-sessions`
owns Codex mining.

There is exactly one decision layer. The **narrator** decides merges, retirements and conflicts
once, with evidence. The **manager** verifies facts and dispatches. **Units** do the work and
inherit the settled calls. No later tier re-decides.

**Deep mining** means `mine_session.py` surfaces the whole arc: the ORIGINAL GOAL, the USER
STEERING ARC (every human turn), the LATEST SESSION SUMMARY (freshest compaction digest, the richest
single source), the EXACT LAST USER INSTRUCTION, and the tail. Each mining agent turns that into
**state** (goal, last state, paste-ready `continuationPhrase`, remaining work) and **intelligence**
(`contribution`, evidence-backed `established` calls, `deadEnds`, `produces` / `needs` handoffs,
`openQuestions`). The narrator stitches the intelligence into the story; the state becomes units.

### 1. Find the target sessions

Desktop sessions (all accounts, dead included) live in
`~/Library/Application Support/Claude/claude-code-sessions/<account>/<org>/local_*.json`, NOT
`~/.claude/sessions/` (live only).

```bash
python3 $SCR/list_sessions.py                  # all accounts grouped
python3 $SCR/list_sessions.py --account <account-id>
python3 $SCR/list_sessions.py --grep "ABC-3"   # match titles from a screenshot
python3 $SCR/list_sessions.py --tree --grep "<term>"   # sidebar nesting
```

Match screenshot titles to rows here (more reliable than the leveldb `pinnedOrder`). Each row gives
`cli`, `branch`, `worktreeName`, `pr`/`prState`. Confirm the set if any title is ambiguous or unmatched.

### 2. Locate transcripts and group

```bash
python3 $SCR/find_transcript.py <cli1> <cli2> ...   # per-worktree, searched across ALL project dirs
python3 $SCR/group_sessions.py --root "<top-level title>"   # an origin + its whole subtree
python3 $SCR/group_sessions.py --grep "Spec " [--categories cats.json]
```

Lineage is `spawnedFrom.sessionId`: the topmost ancestor in the set is the category's **origin**;
everything under it is a **member**. Sessions with no lineage land in `unplaced`: assign them with
the user or a `--categories` file (`{"Apps": ["title substr", ...]}`), never by guessing from one
title. Confirm the groups before mining when `unplaced` is non-empty or a category spans more than
~8 sessions.

### 3. Mine and narrate (one Workflow)

Build `sessions: [{idx,title,cli,worktreeName,branch,pr,transcript}]` (**`title` verbatim**; it
becomes the unit title unchanged), then:

```
Workflow({ scriptPath: "<SCR>/mine_workflow.js",
           args: { mineScript: "<SCR>/mine_session.py", date: "<YYYY-MM-DD>", sessions: [...],
                   groups: [{category, origin:{title,cli}|null, memberClis:[...oldest->newest]}] } })
```

Miners run on **haiku** (filling a fixed schema from a digest is extraction); the narrator stays
**sonnet**, because it is the only decision layer. Include the origin's own session in `sessions`
**and** its cli in `memberClis`, so the story carries its prior state. Omit `groups` for a flat set (no narration). Returns `{ok, failed, stories[],
storiesFailed}`. Each story: `managerTitle` / `managerTldr` / `managerPrompt`, `storyMarkdown`,
`units[]`, `flat`, `done`, `warnings[]`. `warnings` lists any obligation the narrator tried to drop;
the script re-adds it as its own unit. Check it, then check the merges it applied (`mergeEvidence`
names the shared ticket or artifact).

### 4. Persist the story, then start the manager

- `done` (no units): report the category as done; start nothing.
- `flat` (one unit): start that unit directly under §Starting a manager's rules; its prompt already
  carries the category context. No manager.
- otherwise:
  1. **Persist first.** Write `storyMarkdown` to
     `~/.claude/sessions-to-chips/maps/<YYYY-MM-DD>-<category-slug>.md`, replacing every
     `{{STORY_PATH}}` (in the file and in `managerPrompt`) with that absolute path.
  2. Start **one manager per category** with `managerTitle` / `managerTldr` / `managerPrompt`. This
     is the only start you do. The prompt points the manager at the Manager contract.
  3. The manager reads the story, verifies the facts it acts on, settles leftover conflicts itself,
     starts each unit from the story's *Unit prompts* in `dependsOn` order (independent units
     together, first wave at most 5), keeps the Units table current, and escalates only at a real
     gate (prod mutation, founder decision, unrecoverable conflict).

Unit titles stay the **original session names** verbatim. The manager is titled
`[Manager] <origin title>` so its row is not a twin of the parked origin session.

**Critical:** a started session gets a FRESH worktree. If a unit's `gitState` is uncommitted or
unpushed, its prompt MUST open with the WORKTREE NOTE telling the session to `cd` into the existing
worktree (the mining agents write it; verify before sending).

Mechanics that cost retries:

- `Workflow({scriptPath})` only loads a script inside the working directory. Copy `mine_workflow.js`
  into the dispatcher's worktree, run it, and delete the copy afterwards.
- A background Workflow returns the story JSON under `result` in its task output file
  (`json.load(...)["result"]`), not at the top level.
- Never name a scratch script after a stdlib module (`select.py`, `json.py`): Python imports it
  ahead of the standard library and the script fails with a circular import.

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
   only DONE-and-merged children, refresh `~/.claude/orchestrator/programs/<slug>.state.md` (Mode 4
   reads it instead of mining the transcript), and write `~/.claude/sessions-to-chips/wrapup/<date>-<slug>.md`
   with the surviving set, the gate blocking each item, "Linear owed", "Owed to the founder" (asked in the manager's own session, never relayed), and a
   paste-ready continuation phrase. Merges, deploys and prod writes still need the human's
   in-session go-ahead; a blocked item with its gate named is a finished checkpoint.
   **Before sending, sweep the children on THIS account** with `child_ledger.py --account <this
   account>` (Mode 4 step 3) and name each manager's `-children.md` in its message, so findings
   that live only in a child's chat get written down while that chat is still readable.
4. **Converge.** Do not poll. When a session's note arrives, run `wrapup_status.py` once. The
   dispatcher's closing message lists notes written, notes missing, which managers hold open founder
   decisions (a count and a session link each, never the decisions themselves), and the
   before/after session counts. See "Founder decisions stay with their manager" below.
5. After the switch, run Mode 4 from a session on the NEW account. The notes on disk are shared
   by both accounts, but the sessions are not.

## Mode 4 — Account switch (take the programs over on the other account)

The point of Mode 3 is this mode. Programs keep running on one account until it is capped, then
continue on another, often switching back and forth. Each account has its own sessions, so a
manager on this account knows only what happened up to the last time it ran here.

**What carries across and what does not.** Session stores are per account:
`~/Library/Application Support/Claude/claude-code-sessions/<account>/<org>/local_*.json`.
Transcripts (`~/.claude/projects/…`), worktrees, git, the tracker and everything under
`~/.claude/sessions-to-chips/` are on the machine and shared. The app's session tools are not:
`list_sessions`, `send_message`, `SendMessage` and `archive_session` reach only the signed-in
account. The other account's sessions show in `ListAgents` as `Remote Control · offline`, and a
message to one is queued to nowhere. Never relay to them.

1. **Find which account you are on.** `grep -l <your CLI session id> "<store>"/*/*/local_*.json`
   names your account directory. `list_sessions.py --grep Manager` lists both accounts' managers
   with their `cli` ids and last activity. The account whose managers are newest is the one
   you are taking over from.
2. **Mine the other account's managers.** First check each program's state file
   (`~/.claude/orchestrator/programs/<slug>.state.md`): if its `updated_at` is after the checkpoint,
   it is the handoff, so skip mining that program. Managers that skipped their state files (all of
   them, 2026-10-14 to 10-22) force this transcript path. Otherwise `find_transcript.py <cli…>`, then
   `mine_session.py <transcript> > digest-<cli>.txt` per manager. Write one handoff per program to
   `~/.claude/sessions-to-chips/handoff/<date>-<slug>.md` with one **haiku** agent per program
   ([prompts/handoff-miner.md](prompts/handoff-miner.md)), all in one message. A program whose
   repo is not the monorepo (a side repo, a game project) gets its repo named in the prompt so `gh`
   and `git` calls hit the right remote. A state file counts as the handoff only if its mtime is
   after the checkpoint AND its events file is as new; record the mtime in the handoff, because a
   fresh-looking state can still be stale (measured: two state files older than their events).
3. **Sweep for what the handoffs miss, BEFORE sending anything.** All four sweeps below run first
   so their findings ride ONE message per manager (see step 5). The decisions sweep and worktree
   sweep are agents: [prompts/decisions-sweep.md](prompts/decisions-sweep.md) and
   [prompts/worktree-sweep.md](prompts/worktree-sweep.md); run both in the same message as the
   child-ledger reconcilers. Handoffs built from transcripts name PRs
   and drop maps, unpushed commits and drafts (measured 2026-10-22: the Release handoff omitted its
   story map, the open wayfinder map PR and an unpushed build-map commit; two more programs had
   unpushed commits nobody had named).
   ```bash
   python3 -I $SCR/handoff_sweep.py --account <other-account-id> --since <checkpoint ISO time>
   ```
   It lists each worktree with unpushed commits, no upstream, untracked files or mass deletions
   (a gutted checkout), with its owning manager, plus every map or note written since the
   checkpoint that no handoff names. Fold each finding into the owning handoff.

   **Then sweep every child session, per manager.** Git is half of it: the other half of lost
   progress is a finding, a decision or a "needs the founder to …" that lives only in a child's
   conversation, which the next account cannot read (measured 2026-10-22: 51 of 119 children were
   AT-RISK, including an invoice at 2x its amount, a prod migration with no apply check, and 3
   pushed commits with no PR from a child that hit its weekly limit).
   ```bash
   python3 -I $SCR/child_ledger.py --account <other-account-id> --since <checkpoint ISO time> --out <dir>
   ```
   It writes one `children-<manager>-<id>.json` per manager (plus one for sessions no manager owns)
   from each child's stored `lastTurnReport`, `postTurnSummary`, PRs and branches. Give each file
   to one **haiku** agent ([prompts/child-ledger-reconciler.md](prompts/child-ledger-reconciler.md)),
   all in one message; each writes `handoff/<date>-<slug>-children.md` with the AT-RISK rows.
   Route the no-manager file's rows to the likeliest program by hand.

   **Then the decisions sweep and the worktree sweep.** A handoff names PRs, not rulings:
   founder rulings, specs, ADRs and cross-cutting calls (a model ceiling, a tool ban) made on the
   other account can sit in one state file of eight. The worktree sweep walks `git worktree list`
   itself, because `handoff_sweep.py` only sees worktrees it can attribute to a manager. The
   worktree of a RUNNING child is pushed by that child; an unowned one is salvaged by the manager
   that owns the ticket. Fold every row into the owning manager's message; every cross-cutting
   ruling goes into EVERY manager's message.
4. **Decide per program**, and say the call in one table:
   - **A manager for it exists on this account** → relay. It keeps its sidebar group, worktree and
     family; the handoff replaces its stale context. Archive older duplicate managers here.
   - **Absorbed or converged managers are still managers.** Read each manifest's `goal`/`absorbs`
     before deciding: if program A absorbed B, the live `[Manager] B` on this account is a duplicate
     owner (measured 2026-10-24: CRM, absorbed into Apps on 10-22, was still live and started a
     second child on Apps' ticket). Send B a fold notice and Apps a takeover note instead of a
     normal catch-up; B hands over its live child at the next checkpoint, then runs hygiene.
   - **No manager here** (the program was born on the other account) → grill the human in this
     session (start one, or leave it standalone; recommended answer first) and START NOTHING
     unasked. If they said "relay to existing managers", never start one on your own; list the
     program and the handoff path instead.
   - **Nothing happened on the other account since the checkpoint** → do not wake it, but check the
     manager's own `lastActivityAt` first: it may have been woken here by the human since (measured:
     a "quiet" manager had started a child that morning).
   - Programs too small for a manager stay standalone.
   - **Config age is never a reason to re-dispatch.** Every account shares one `~/.claude`; run
     `scripts/config_freshness.py` and refresh the `STALE-*` rows by message
     ([references/config-freshness.md](references/config-freshness.md)).
5. **Send ONE message per manager** ([CATCHUP_MESSAGE.md](CATCHUP_MESSAGE.md)) by session id, only
   after every sweep has landed. It carries the handoff and `-children.md` paths, the backlog-first
   order, the manager's sweep rows, the standing rulings, and the one-line reply format. Put
   cross-program findings in `{{EXTRA}}`: two handoffs that contradict each other (name who
   settles it), a scope that moved between programs, one owner for a shared deliverable. Say
   explicitly that the other account's stopped children ARE the program's work.
   Send constraints measured 2026-10-24: (a) the app pauses sends after about 10 session messages
   since the human last typed ("looks like sessions messaging each other automatically"), so one
   message per manager is a budget, not a style: follow-ups for the same manager wait for its reply
   and ride the next batch; (b) the first send to a manager may be refused with "Workspace requires
   trust approval": do not retry, ask the human once for all refused sessions; (c) write every
   message you could not deliver to `relay/<date>-pending-sends.md` the moment it is refused, so
   the resend survives compaction; (d) queued is not read: do not re-send.
6. **Converge.** Do not poll. Append each one-line reply to
   `~/.claude/sessions-to-chips/relay/<date>-replies.md`. The program converges when, per manager:
   catch-up reply (archived N, live children X, decisions held), backlog-first reply (before →
   after, each kept ≥1-day session with its reason), sweep fixes confirmed (fixed N of M), the
   worktree rows pushed by their owners or named as a live child's, and the standing rulings
   recorded in its state file with a fresh `updated_at`. `pending-sends.md` must be empty or
   listed to the human. Close with which managers hold open founder decisions and a link to each;
   the decisions themselves stay in those sessions.
7. **Archiving on the other account is the human's.** When an audit clears the other account's
   sessions, write `relay/<date>-archive-on-<account>.md` listing what to archive and what to keep;
   a kept subtree nested under an archived parent (a manager spawned by another manager) must be
   moved to top level first, or archiving the parent takes it along.
8. **Hygiene asked of the dispatcher is relayed.** The dispatcher has no family
   (`hygiene_candidates.py` returns 0 for it), so "run hygiene" means one line in each manager's
   catch-up, never archiving another program's children from here. Exception: duplicate managers
   of one program on this account, which only the dispatcher can see side by side. To read what
   each manager's pass will propose without acting, run `hygiene_candidates.py --all-managers
   --account <this-account-prefix>` (the default account is the most recently active one, which
   may not be this one). The order inside each manager is fixed: BACKLOG FIRST (every family
   session idle ≥1 day gets a verdict before any new work), then salvage, then the program.

Mechanics that cost retries in this mode:

- In zsh never `read -r cli size path`: `path` is tied to `PATH` and the next command is "not
  found". Use `tpath`.
- The other account's children are `not found` to `get_session` and `list_sessions` here; that is
  expected, never evidence they are dead. Cite their stored ledger row instead.
- Never trust a subagent's count of merged PRs, owners or "live" without the `gh pr view` /
  `git worktree list` line it ran; handoff agents were right on PR states and wrong on owners
  (inferred from branch names) every time: owners are confirmed by the manager that receives them.
- A catch-up that mentions a founder ask puts it in that manager's message, never in the
  dispatcher's closing list ("Founder decisions stay with their manager").
- Reading a session's own `list_events` is a read; messaging it is a send and counts against the
  budget. Prefer `list_events` over a nudge when you only need to know what it is doing.

### Founder decisions stay with their manager

A founder decision is asked, answered and recorded in the session of the manager whose program it
belongs to, because that is where the context, the default and the follow-through live, and the
human's go-ahead must be typed there ("a manager never relays approvals"; it holds equally for a
dispatcher). The dispatcher never compiles a cross-program decision list, never asks the human for
another program's ruling, and never records an answer it heard secondhand. When a sweep finds a
founder ask, it goes into that manager's handoff or message; when a reply mentions one, the
dispatcher leaves it there. The only thing the dispatcher may say about them is where they are.

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
  session only when the human must judge.
- **Grade by ARTIFACT, never the completion envelope.** Salvage a dead lane's worktree
  (`git status --porcelain`) before re-dispatching; a re-dispatch is a continuation, never a replay.
- **Verify before any routing claim:** branch HEAD, `gh pr view --json mergedAt,state`, the spec
  file. Merged is not baked. Confirm the deploy SHA is in the environment before a verify lane.
- **No scheduled polling.** No heartbeat, `/loop`, cron or re-armed wake unless the user asks for
  that schedule. An external gate gets a keyed resume artifact and the turn ends.
- **Overrides first, every tick:** terminal stop (zero further tools), then completion-mode freeze,
  then an owned child still inside its lease. Only then survey, classify, and dispatch every
  independent forcing function at once.
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
  session idle ≥1 day (HYGIENE.md "Backlog first"); Mode 4's catch-up makes this its first step.
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
- [REFERENCE.md](REFERENCE.md) — Mode 2 depth: story structure, unit-prompt rules, completion criteria.
- Private overlay, if present: `~/.claude/skills-overlay/sessions-to-chips/LEARNINGS.md`
  (adopter-private) for project-specific examples and gate commands. Managers append generalizable
  calls there at close-out.
