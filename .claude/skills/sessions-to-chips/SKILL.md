---
license: MIT
name: sessions-to-chips
description: Start and run managers. A manager is one standalone "[Manager] <title>" session that owns ONE program (a goal) and drives it through child sessions, headless lanes and Codex lanes, never implementing itself. Three entry modes. New manager - the human names a goal ("orchestrate", "start a manager", "drive this program", "run 3+ parallel sessions toward one target", a big autonomous project). Resume from sessions - deep-mine scoped Claude desktop sessions for goals, steering, last state, settled calls, dead ends and remaining work, narrate each category as one story with a unit ledger, and give it to one manager (also mine-only audits of parked sessions or session overlap, read-only). Wrap-up - checkpoint every manager before an account switch or usage cap. Shared by all: the Manager contract (program state, collisions, lane runtimes, spawn-lane.sh, advance tick, grading, reviews, merge-and-retire) and session hygiene. Starting sessions needs explicit authorization; read context only via permitted interfaces.
---

# sessions-to-chips — managers

The unit of this skill is a **manager**: a standalone desktop session titled
`[Manager] <title>` that owns ONE program (a goal). It verifies facts, starts children, grades
their artifacts, holds the human gates, and keeps its family small. It never does a child's work.

Three modes produce managers. All of them obey the same **Manager contract**
([`references/manager-contract.md`](references/manager-contract.md)) and **session hygiene**
([HYGIENE.md](HYGIENE.md)).

| Mode | Use when | Produces |
|---|---|---|
| **1. New manager** | the human names a goal to drive | one `[Manager] <goal>` |
| **2. Resume from sessions** | parked or finished sessions should be picked up, or audited | one `[Manager] <origin title>` per category (none in mine-only) |
| **3. Wrap-up** | an account switch or usage cap is coming | a checkpoint note per manager; no new managers |

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

Include the origin's own session in `sessions` **and** its cli in `memberClis`, so the story carries
its prior state. Omit `groups` for a flat set (no narration). Returns `{ok, failed, stories[],
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
   only DONE-and-merged children, and write `~/.claude/sessions-to-chips/wrapup/<date>-<slug>.md`
   with the surviving set, the gate blocking each item, "Linear owed", "Owed to the founder", and a
   paste-ready continuation phrase. Merges, deploys and prod writes still need the human's
   in-session go-ahead; a blocked item with its gate named is a finished checkpoint.
4. **Converge.** Do not poll. When a session's note arrives, run `wrapup_status.py` once. The
   dispatcher's closing message lists notes written, notes missing, the founder decisions collected
   from the notes (most blocking first), and the before/after session counts.
5. After the switch, resume from the notes: run Mode 2 with
   `group_sessions.py --root "[Manager] <category>"`; each note supplies the surviving set and its
   continuation phrases.

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
  then an owned child still inside its lease. Only then survey, classify, dispatch ONE forcing function.
- **Finite reviews:** `moderate` ≤2 activations, `critical` ≤5, one changed-seam closure, then stop.
- **`send_message` stalls an unattended recipient.** Send only from an operator-present turn, by
  session id, never as the last act of an unattended wake.
- **Merges and prod need the human's in-session go-ahead** unless project law grants that class.
- **Keep your family small** at every stopping boundary ([HYGIENE.md](HYGIENE.md);
  candidates: `scripts/hygiene_candidates.py --manager <id>`). In a `[Manager]` session the
  `manager-hygiene` Stop hook announces each new candidate set.
- **Close out** with ONE summary: shipped (PR and `mergedAt`), parked and why, still unproven.

## References

- [`references/manager-contract.md`](references/manager-contract.md) — the full contract.
- [`references/lifecycle.md`](references/lifecycle.md) — define → build → verify-release.
- [`references/merge-and-retire.md`](references/merge-and-retire.md) — merge, post-merge proof, retire.
- [`references/codex-runtime.md`](references/codex-runtime.md) — when hosted by Codex CLI.
- `prompts/` — lane missions, state miner, model routing, procedural worker.
- [REFERENCE.md](REFERENCE.md) — Mode 2 depth: story structure, unit-prompt rules, completion criteria.
- Private overlay, if present: `~/.claude/skills-overlay/sessions-to-chips/LEARNINGS.md`
  (adopter-private) for project-specific examples and gate commands. Managers append generalizable
  calls there at close-out.
