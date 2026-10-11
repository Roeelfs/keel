---
license: MIT
name: sessions-to-chips
description: Deep-mine scoped Claude desktop sessions for overall goals, steering, last state and unique remaining work, and group them by category into one manager chip + map + sub-chip specs per category (the manager spawns its own sub-chips). Supports read-only mining/audits and explicitly requested resume chips. Use for session mining, parked-session context, overlap review or picking up prior work. Context access must use permitted supported interfaces; creating execution tasks requires explicit authorization.
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

Turn a set of Claude Code desktop sessions into **manager-led categories**: one **manager chip** per category, a durable **map**, and one cold-start **sub-chip spec** per sub-session. The sidebar is two-level (a top-level session with the chips it spawned nested under it); this workflow mirrors that. You spawn only the managers — each manager spawns its own sub-chips. Flat mode (one chip per session, no managers) still applies when the set has no lineage and the user says so. A good sub-chip carries the session's **overall goal** (the through-line mission that survived every compaction) and the **exact phrase to continue from where it stopped** — not a vague "do the last mission from the session". Fast path: 5 steps, scripts do the deterministic parts, one Workflow mines all sessions in parallel.

**What "deep mining" means here:** don't read only the tail. `mine_session.py` surfaces the whole arc — the ORIGINAL GOAL (first human message), the USER STEERING ARC (every human turn, so you see how intent evolved), the LATEST SESSION SUMMARY (the freshest compaction digest: the canonical "Primary Request and Intent / Pending Tasks / Next Step" block — the single richest source of goal+state), and the EXACT LAST USER INSTRUCTION, plus the tail (last assistant text, todos, recent tool uses) for where/why it stopped. The chip is authored by *reasoning over the goal*, then naming the precise next action.

`SCR=~/.claude/skills/sessions-to-chips/scripts`

## 1. Find the target sessions
Desktop sessions (all accounts, dead included) live in `~/Library/Application Support/Claude/claude-code-sessions/<account>/<org>/local_*.json` — NOT `~/.claude/sessions/` (that's live-only).

```bash
python3 $SCR/list_sessions.py                  # all accounts grouped
python3 $SCR/list_sessions.py --account <account-id>   # "another account" = a different account-uuid
python3 $SCR/list_sessions.py --grep "ABC-3"   # match titles from a screenshot
```
If the user gave a screenshot/pinned list, match those titles to rows here (title match is more reliable than the leveldb `pinnedOrder`). Each row gives `cli` (cliSessionId), `branch`, `worktreeName`, `pr`/`prState`. Confirm the set with the user if any title is ambiguous or unmatched.

## 2. Locate transcripts
```bash
python3 $SCR/find_transcript.py <cli1> <cli2> ...   # searches ALL project dirs
```
GOTCHA: transcripts are per-worktree (`~/.claude/projects/<worktree-slug>/<cli>.jsonl`), not the main project dir.

## 2b. Group into categories (manager + subs)
```bash
python3 $SCR/list_sessions.py --tree --grep "<term>"       # see the sidebar structure first
python3 $SCR/group_sessions.py --root "<top-level title>"   # a manager + its whole subtree
python3 $SCR/group_sessions.py --grep "Spec " [--categories cats.json]
```
Lineage is `spawnedFrom.sessionId`: the topmost ancestor present in the set is the **manager**, everything under it is a **sub-session**. Sessions with no lineage land in `unplaced` — assign each a category with the user or a `--categories` file (`{"Apps": ["title substr", ...]}`); never guess a category from one title. A category with a single session needs no manager: it falls back to a flat chip. Confirm the groups with the user before mining when `unplaced` is non-empty or a category spans more than ~8 sessions.

## 3. Mine all sessions in parallel (Workflow)
Build `sessions: [{idx,title,cli,worktreeName,branch,pr,transcript}]` (transcript = abs path from step 2; **pass `title` verbatim — it's the session name and becomes the chip title unchanged**), then:
```
Workflow({ scriptPath: "<SCR>/mine_workflow.js",
           args: { mineScript: "<SCR>/mine_session.py", sessions: [...],
                   groups: [{category, manager:{title,cli}|null, memberClis:[...]}] } })
```
`groups` comes from step 2b (omit it for flat mode). Include the manager's own session in `sessions` **and** its cli in `memberClis` so the manager chip inherits its prior state. Returns `{ok:[{...spec per session}], failed:[], managers:[{category, managerTitle, managerTldr, managerPrompt, mapMarkdown, subChips[]}], managersFailed:[]}`. Each agent deep-mines the whole arc (via `mine_session.py` — goal + steering arc + latest compaction summary + last instruction + tail), reasons over the **goal**, checks git/PR state, and returns:
- `sessionGoal` — the overall mission (2-4 sentences, the through-line, not the last step).
- `lastState` — what got done + the exact stop point.
- **`continuationPhrase`** — the paste-ready, user's-voice instruction that resumes from that exact point.
- `gitState{uncommitted,unpushed}`, `remainingWork[]`, `isComplete`.
- `chipTitle` (**= the original session name, verbatim**) / `chipTldr` / `chipPrompt` (5-part: GOAL → DONE → STOPPED → CONTINUE-FROM-HERE → REMAINING STEPS).

Agents are read-only. If you'd rather not run the Workflow, `python3 $SCR/mine_session.py <transcript>` prints the same deep arc for one session by hand.

## 3b. Consolidate (built into the workflow)
Between mining and manager authoring, `mine_workflow.js` runs one **sonnet reviewer per category**. It reads the mined results and returns `merges` (with `high|medium|low` confidence), `drops` (with named evidence), `keepSeparate` and `managerDecisions`. High-confidence merges are applied directly, so you spawn fewer sub-chips. Medium/low merges and the open judgement calls are **not** applied: they go into the map under "Decisions owed to the manager", and the manager settles them using [MANAGER_PLAYBOOK.md](MANAGER_PLAYBOOK.md). Check `consolidations[]` in the result when something looks over-merged: the rationale names the shared ticket/artifact.

## 4. Decide who gets work
- `isComplete:true` (PR merged **and** post-merge tail done) → **no sub-chip**; it stays a row in the map, marked done.
- everything else → one sub-chip spec (`spawn:true`).
- a category whose sub-sessions are all complete → no manager; report the category as done.

## 5. Write the map, then spawn the managers
Per manager in `managers[]`:
1. **Persist first** (a deliverable blocked on a spawn goes to disk before you report it). Write `mapMarkdown` to `~/.claude/sessions-to-chips/maps/<YYYY-MM-DD>-<category-slug>.md` and `subChips` as JSON to `<same-stem>.chips.json`. Substitute those two absolute paths for `{{MAP_PATH}}` / `{{CHIPS_PATH}}`, and the absolute path of this skill's `MANAGER_PLAYBOOK.md` for `{{PLAYBOOK_PATH}}`, in `managerPrompt`.
2. Call `mcp__ccd_session__spawn_task` **once per category** with `managerTitle` / `managerTldr` / `managerPrompt`. This is the only spawn you do.
3. The manager reads the map and the playbook, settles the owed merge/split/order decisions itself, then spawns each `spawn:true` entry of the chips file via `spawn_task` in `dependsOn` order (independent entries together, first wave capped at 5), keeps the map's status table current, and never does sub-session work itself. It escalates to the human only at a real gate (prod mutation, a founder decision, unresolvable conflict).

Sub-chip titles stay the **original session names** verbatim; only the manager chip is prefixed `[Manager]`. Each sub-chip's prompt already opens with the overall goal and leads into the exact `continuationPhrase`, so a fresh session inherits the mission, not a stray last task.

**Critical:** `spawn_task` spins up a FRESH worktree — for managers too (a manager that is a real top-level session keeps its prior worktree in the map, not in its cwd). If `gitState.uncommitted` or `gitState.unpushed`, the chipPrompt MUST start with a ⚠️ note telling the spawned session to `cd` into the existing worktree first (else the work is invisible). The mining agents do this when flagged, but verify before sending.

See [REFERENCE.md](REFERENCE.md) for chip-prompt rules, completion criteria, and the gotchas that cost retries. Also read the private overlay if present: `~/.claude/skills-overlay/sessions-to-chips/LEARNINGS.md` (adopter-private; never in this public repo) — it accumulates project-specific examples (real session titles, named incidents, exact verify-gate commands) that sharpen the chip authoring for your own setup.
