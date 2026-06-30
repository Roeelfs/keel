---
name: sessions-to-chips
description: Mine local Claude Code desktop sessions (including dead, parked, or other-account sessions) to extract each one's last state and remaining work, then create spawn_task completion chips. Use when the user wants to mine/continue local sessions, turn pinned or parked sessions into chips, resume parallel work left off across accounts, or "pick up where my sessions left off". Distinct from the live-only `claude-sessions` survey: this reads the DESKTOP-app session store (any account, dead sessions included) and produces actionable chips.
---

# sessions → completion chips

Turn a set of Claude Code desktop sessions into one cold-start **resume chip** each. A good chip carries the session's **overall goal** (the through-line mission that survived every compaction) and the **exact phrase to continue from where it stopped** — not a vague "do the last mission from the session". Fast path: 5 steps, scripts do the deterministic parts, one Workflow mines all sessions in parallel.

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

## 3. Mine all sessions in parallel (Workflow)
Build `sessions: [{idx,title,cli,worktreeName,branch,pr,transcript}]` (transcript = abs path from step 2; **pass `title` verbatim — it's the session name and becomes the chip title unchanged**), then:
```
Workflow({ scriptPath: "<SCR>/mine_workflow.js",
           args: { mineScript: "<SCR>/mine_session.py", sessions: [...] } })
```
Returns `{ok:[{...chip spec per session}], failed:[]}`. Each agent deep-mines the whole arc (via `mine_session.py` — goal + steering arc + latest compaction summary + last instruction + tail), reasons over the **goal**, checks git/PR state, and returns:
- `sessionGoal` — the overall mission (2-4 sentences, the through-line, not the last step).
- `lastState` — what got done + the exact stop point.
- **`continuationPhrase`** — the paste-ready, user's-voice instruction that resumes from that exact point.
- `gitState{uncommitted,unpushed}`, `remainingWork[]`, `isComplete`.
- `chipTitle` (**= the original session name, verbatim**) / `chipTldr` / `chipPrompt` (5-part: GOAL → DONE → STOPPED → CONTINUE-FROM-HERE → REMAINING STEPS).

Agents are read-only. If you'd rather not run the Workflow, `python3 $SCR/mine_session.py <transcript>` prints the same deep arc for one session by hand.

## 4. Decide which get chips
- `isComplete:true` (PR merged **and** post-merge tail done) → **skip**, just report it as done.
- everything else → one chip.

## 5. Create chips
For each non-complete session, call `mcp__ccd_session__spawn_task` with the mined `chipTitle` (**keep the original session name**) / `chipTldr` / `chipPrompt`. The `chipPrompt` already opens with the overall goal and leads into the exact `continuationPhrase`, so the fresh session inherits the mission, not just a stray last task.

**Critical:** `spawn_task` spins up a FRESH worktree. If `gitState.uncommitted` or `gitState.unpushed`, the chipPrompt MUST start with a ⚠️ note telling the spawned session to `cd` into the existing worktree first (else the work is invisible). The mining agents do this when flagged, but verify before sending.

See [REFERENCE.md](REFERENCE.md) for chip-prompt rules, completion criteria, and the gotchas that cost retries. Also read the private overlay if present: `~/.claude/skills-overlay/sessions-to-chips/LEARNINGS.md` (adopter-private; never in this public repo) — it accumulates project-specific examples (real session titles, named incidents, exact verify-gate commands) that sharpen the chip authoring for your own setup.
