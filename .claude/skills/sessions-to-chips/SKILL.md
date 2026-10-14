---
license: MIT
name: sessions-to-chips
description: Deep-mine scoped Claude desktop sessions for goals, steering, last state, the intelligence each produced (settled calls, dead ends, handoffs) and unique remaining work, then narrate each category as ONE story with a unit ledger run by a single orchestrator chip. Supports read-only mining/audits and explicitly requested resume chips. Use for session mining, parked-session context, overlap review or picking up prior work. Context access must use permitted supported interfaces; creating execution tasks requires explicit authorization.
---

# sessions → completion chips

## Choose mining or continuation

This is the existing Claude Desktop **deep-mining entrypoint**. A request to mine,
inspect or audit sessions selects **mine-only**: collect context and analyze goals,
steering, latest summary/instruction, results and unfinished obligations. Do not
create chips or resume work merely because the legacy workflow below ends in them.

For mine-only audits and overlap/consolidation analysis, read the shared
[contextual audit workflow](../claude-sessions/references/session-audit.md) and
[supported interfaces](../claude-sessions/references/supported-interfaces.md).
That workflow adds read-only parallel dossiers, overlap mapping and acceptance
before parking; its instructions live in one place, rather than a second mining
implementation. Invoke `$sessions-to-chips` with “mine-only; audit these sessions”.

For explicitly requested resume chips, preserve the deep-mining and chip rules
below, but first verify callable interfaces and authorized scope. The legacy
filesystem scripts are not a permission grant to inspect hidden stores or other
accounts. Do not run them against denied paths or use them to bypass a missing
context connector. Prefer scoped supported direct reads, permitted exports, then
authorized UI fallback; apply the same deep reasoning to that content. If Workflow
or spawn_task is unavailable, use available read-only subagents for analysis and
return draft continuation prompts; do not invent an API or silently create tasks.

`claude-sessions` remains the live Claude Code survey/decision extractor and owns
the shared audit instructions. `codex-sessions` owns Codex mining. Their distinct
extraction helpers and existing output contracts remain separate.

## Legacy resume-chip workflow

Turn a set of Claude Code desktop sessions into **one story per category, run by one orchestrator**. A category is an origin session plus the sessions it spawned (the sidebar nesting). The workflow reads what each session *found and decided*, not only where it stopped, tells the category as a single narrative, reduces what remains to the fewest units of work, and gives the whole thing to **one orchestrator chip** that dispatches those units.

There is exactly one decision layer. The **narrator** decides merges, retirements and conflicts once, with evidence. The **orchestrator** verifies facts and dispatches. **Units** do the work and inherit the settled calls. No later tier re-decides.

**What "deep mining" means here:** `mine_session.py` surfaces the whole arc: the ORIGINAL GOAL, the USER STEERING ARC (every human turn), the LATEST SESSION SUMMARY (freshest compaction digest, the richest single source), the EXACT LAST USER INSTRUCTION, and the tail. Each mining agent turns that into two things: **state** (goal, last state, the paste-ready `continuationPhrase`, remaining work) and **intelligence** (`contribution`, evidence-backed `established` calls, `deadEnds`, `produces` / `needs` handoffs, `openQuestions`). The narrator stitches the intelligence into the story; the state becomes the units.

`SCR=~/.claude/skills/sessions-to-chips/scripts`

## 1. Find the target sessions
Desktop sessions (all accounts, dead included) live in `~/Library/Application Support/Claude/claude-code-sessions/<account>/<org>/local_*.json`, NOT `~/.claude/sessions/` (live-only).

```bash
python3 $SCR/list_sessions.py                  # all accounts grouped
python3 $SCR/list_sessions.py --account <account-id>
python3 $SCR/list_sessions.py --grep "ABC-3"   # match titles from a screenshot
python3 $SCR/list_sessions.py --tree --grep "<term>"   # sidebar nesting
```
Match screenshot titles to rows here (more reliable than the leveldb `pinnedOrder`). Each row gives `cli`, `branch`, `worktreeName`, `pr`/`prState`. Confirm the set if any title is ambiguous or unmatched.

## 2. Locate transcripts and group
```bash
python3 $SCR/find_transcript.py <cli1> <cli2> ...   # transcripts are per-worktree, searched across ALL project dirs
python3 $SCR/group_sessions.py --root "<top-level title>"   # an origin + its whole subtree
python3 $SCR/group_sessions.py --grep "Spec " [--categories cats.json]
```
Lineage is `spawnedFrom.sessionId`: the topmost ancestor present in the set is the category's **origin**; everything under it is a **member**. Sessions with no lineage land in `unplaced`: assign them with the user or a `--categories` file (`{"Apps": ["title substr", ...]}`), never by guessing from one title. Confirm the groups before mining when `unplaced` is non-empty or a category spans more than ~8 sessions.

## 3. Mine and narrate (one Workflow)
Build `sessions: [{idx,title,cli,worktreeName,branch,pr,transcript}]` (**`title` verbatim**; it becomes the chip title unchanged), then:
```
Workflow({ scriptPath: "<SCR>/mine_workflow.js",
           args: { mineScript: "<SCR>/mine_session.py", date: "<YYYY-MM-DD>", sessions: [...],
                   groups: [{category, origin:{title,cli}|null, memberClis:[...oldest->newest]}] } })
```
Include the origin's own session in `sessions` **and** its cli in `memberClis`, so the story carries its prior state. Omit `groups` for a flat set (no narration). Returns `{ok, failed, stories[], storiesFailed}`.

Each `stories[]` entry: `orchestratorTitle` / `orchestratorTldr` / `orchestratorPrompt`, `storyMarkdown`, `units[]`, `flat`, `done`, `warnings[]`. `warnings` lists any obligation the narrator tried to drop; the script re-adds it as its own unit, so check it, then check the merges it did apply (`mergeEvidence` names the shared ticket/artifact).

## 4. Persist the story, then spawn the orchestrator
Per story:
- `done` (no units): report the category as done; nothing to spawn.
- `flat` (one unit): spawn that unit directly with `spawn_task`; its prompt already carries the category context inline. No orchestrator.
- otherwise:
  1. **Persist first.** Write `storyMarkdown` to `~/.claude/sessions-to-chips/maps/<YYYY-MM-DD>-<category-slug>.md`, replacing every `{{STORY_PATH}}` (in the file and in `orchestratorPrompt`) with that absolute path.
  2. Call `mcp__ccd_session__spawn_task` **once per category** with `orchestratorTitle` / `orchestratorTldr` / `orchestratorPrompt`. This is the only spawn you do.
  3. The orchestrator reads the story, verifies the facts it acts on, settles any leftover conflict itself, spawns each unit from the story's *Unit prompts* in `dependsOn` order (independent units together, first wave at most 5), keeps the Units table current, and escalates only at a real gate (prod mutation, founder decision, unrecoverable conflict).

Unit titles stay the **original session names** verbatim. The orchestrator is titled `[Manager] <origin title>` so its row is not a twin of the parked origin session. The sidebar nests by whichever session calls `spawn_task`, so the orchestrator must spawn its units itself: runner session > `[Manager]` orchestrator > units.

**Critical:** `spawn_task` creates a FRESH worktree. If a unit's `gitState` is uncommitted or unpushed, its prompt MUST open with the WORKTREE NOTE telling the session to `cd` into the existing worktree (the mining agents do this; verify before sending).

See [REFERENCE.md](REFERENCE.md) for the story structure, chip-prompt rules, completion criteria and the gotchas that cost retries. Also read the private overlay if present: `~/.claude/skills-overlay/sessions-to-chips/LEARNINGS.md` (adopter-private) for project-specific examples and gate commands; the orchestrator appends generalizable calls there at close-out.
