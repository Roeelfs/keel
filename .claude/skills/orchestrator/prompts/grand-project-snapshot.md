# Grand-project snapshot — template

The orchestrator's compact-survivable continuity layer. Captures the IN-FLIGHT thread that lives only in conversation memory and would be lost on `/compact` (Claude) or auto-summary (Codex).

This is **not** the session cache (`last-state.json` already covers active lanes). This is the layer above: which **grand project** are we executing, what user guidance recurred, what orchestrator-side decisions were made, what user actions are pending.

## File location

Per project: `~/.claude/projects/<slug>/orchestrator-runs/grand-project-snapshot.json`

Latest-wins. One snapshot per project. If the user pivots to a new grand project, overwrite.

## Schema

```json
{
  "snapshot_at": "2026-04-30T00:30:00Z",
  "session_id": "<$CLAUDE_SESSION_ID or codex SID>",
  "runtime": "claude|codex",
  "project": "<your-repo-slug>",
  "grand_project": {
    "name": "<multi-week initiative name>",
    "phase": "<current phase, e.g. 'Phase 2.5 prod shadow flip pending'>",
    "anchor_spec": "docs/specs/active/<name>.md",
    "anchor_issue": "#71",
    "started_session": "<session-id>"
  },
  "user_recurring_guidance": [
    "verify branch HEAD before classifying RETIRED — JSONL silence ≠ idle",
    "retire only after 'now-flippable post-deploy' markers PASS",
    "staging E2E (Tier 3a) ≠ prod E2E (Tier 3b)",
    "reference sessions by NAME not SID"
  ],
  "in_flight_decisions": [
    "<lane> retired after Tier 3a staging E2E PASS",
    "PR #115 + #116 merged; #117 filed for Phase 2.5 flip",
    "follow-up P2 issue #121 filed"
  ],
  "pending_user_actions": [
    "tomorrow morning: trigger Phase 2.5 prod shadow per #117",
    "<absolute-date+time>: soak Day-1 check-in on #90",
    "follow up with a customer + a teammate on the outstanding lane inputs"
  ],
  "open_questions": []
}
```

## What goes in each field

- **`grand_project`** — the multi-week initiative, not the day's task. If the user invokes the orchestrator and we're working on Spec D Stage 5, the grand project is "Spec D visual system rollout." The current stage is captured in `phase`.
- **`user_recurring_guidance`** — mined from session JSONL: corrections the user has made, emphases that recurred, principles articulated. Distill to short imperatives. **Skip** stylistic preferences and one-off feedback (those go to memory if durable, otherwise to the trash). Cap at ~10 entries — if you're tempted to add more, the durable ones belong in `MEMORY.md` instead.
- **`in_flight_decisions`** — orchestrator-side routing/retire/escalation decisions made THIS session (or recent sessions). Skip decisions already memorialized in PRs, issues, or memory entries.
- **`pending_user_actions`** — what the user said they would do next. Convert relative dates to absolute (e.g. "tomorrow" → `2026-05-01`). These are NOT issues (use the tracker for those) — these are short-horizon items the user is explicitly tracking.
- **`open_questions`** — questions raised this session that the user hasn't yet answered. Empty list is normal.

## When to write

1. **Before `/compact`** (Claude) — proactive, orchestrator drives the user through compaction with state preserved.
2. **Periodically** — after every significant routing decision (lane retire, lane spawn, P0 escalation). Defensive against unplanned compaction.
3. **On explicit user request** — "snapshot the project state" or similar.

## When to read

1. **After `/compact`** — the SessionStart:compact hook (Claude) injects a continuation pointing at the snapshot.
2. **On Codex summary detection** — when a context summary appears in the conversation (Codex auto-compaction), re-read the snapshot to recover the thread.
3. **Cold start** — when the orchestrator skill is invoked in a fresh session that intends to continue an ongoing grand project, read snapshot first to orient.

## What NOT to put in the snapshot

- Full session JSONLs or transcripts (that's what `claude-sessions survey` and `codex-sessions sessions.py mine` are for)
- Active lane state (that's `last-state.json`)
- Code patterns, project conventions, durable user facts (those belong in `MEMORY.md`)
- Backlog items (those belong in your issue tracker)
- Long verbatim quotes (distill)

The snapshot is small (~2-5 KB) and high-signal. If it grows past 10 KB, you're treating it as a transcript — promote durable items to memory or issues.
