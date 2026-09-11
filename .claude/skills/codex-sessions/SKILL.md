---
license: MIT
name: codex-sessions
description: Mine local Codex sessions and summarize active and recent sessions. Reports Codex-side session state only; it does NOT own program state — the orchestrator skill owns the program manifest and slug state file.
---

# codex-sessions

This skill exposes `python3 ~/.claude/skills/codex-sessions/scripts/sessions.py`.

## Commands

### `list`
Show Codex sessions from local session metadata and optional filters. Default listing
includes archive-only rollouts and labels them `archived`; a duplicate live rollout wins.

```bash
python3 ~/.claude/skills/codex-sessions/scripts/sessions.py list --filter <project> --limit 20
python3 ~/.claude/skills/codex-sessions/scripts/sessions.py list --days 1 --limit 20
```

### `survey`
Summarize session transcripts for quick inspection.

```bash
python3 ~/.claude/skills/codex-sessions/scripts/sessions.py survey --days 1 --deep --json --limit 10
python3 ~/.claude/skills/codex-sessions/scripts/sessions.py survey --sid <session-id>
```

### `mine`
Build the latest session-state artifact and a state-miner prompt for the orchestrator.

```bash
python3 ~/.claude/skills/codex-sessions/scripts/sessions.py mine --limit 20 --no-gh
python3 ~/.claude/skills/codex-sessions/scripts/sessions.py mine --since 2026-01-01 --limit 20 --no-gh
```

Artifacts (`last-state.json`, `state-miner-<timestamp>.md`, `survey-<timestamp>.json`)
land in `~/.claude/projects/<slug>/codex-mining/` — `<slug>` is the cwd path with `/`
replaced by `-`, the same per-project convention as Claude's memory dir. The script
never writes into the cwd (a prior version created `./tools/codex-sessions/state/` at
import time, polluting whatever repo you ran it in).

### `extract-decisions`
Deep-walk one Codex rollout into the **cross-runtime structured-decisions JSON** — the
*identical* schema `claude-sessions` `extract-decisions` emits (`runtime: "codex"`), so
`spec-review`'s `design-decisions-extractor` and `improve-harness` consume Codex and
Claude sessions with the same prompt. This is the Codex half of the decision-mining
backbone.

```bash
python3 ~/.claude/skills/codex-sessions/scripts/sessions.py extract-decisions \
  --sid <session-id> --output /tmp/codex-decisions-<sid>.json
```

The walker maps Codex's event schema onto the shared contract:
- **user_turns** from `event_msg.user_message` only — the canonical typed input.
  `response_item.message` frames (the model-IO echo of each turn) are dropped so a turn
  isn't double-counted and its tool attribution isn't split; harness-injected user
  frames (`# AGENTS.md instructions`, attachment manifests, `<skill>` invocations) are
  filtered like Claude's `<…>` frames.
- **tools_after** in codex form (`exec: <cmd>`, `apply_patch: <files>`, `mcp: <tool>`),
  **files_edited_after** from `patch_apply_end.changes`.
- **session_meta** carries the codex-specific `model` / `approval_policy` /
  `sandbox_policy` from `turn_context`.
- **commits_during_session** mined from `git log --grep=Session-Id: <rollout-id>` in the
  session's own cwd (Codex stamps the rollout id as the `Session-Id` trailer).

## Notes
- For an explicit session, `survey --sid <id> --json` reports the durable
  `latest_turn_id`, `last_tool_event`, `last_wait`, and a read-only `native_history`
  comparison. `updated_at` is the latest parsed event time, not the last user input.
- `status` is the latest turn's lifecycle. Completed/interrupted turns stay terminal
  even when their file is fresh; `active` alone does not prove useful progress.
- If `native_history.status` is `behind`, native history/cursors may omit live work
  or completion. A single lagging snapshot may be transient: corroborate with the
  durable turn, tool completions, and owned artifacts. Do not restart from an old
  projected `active` flag or keep waiting on a cursor already proven stale.
- `last_wait.unchanged_count` counts repeated unchanged snapshots, including when
  diagnostic reads occur between waits. Repeated waits are not proof of progress.
  Resolve the exact dependency's durable terminal state or request its owner's
  concrete handoff. Preserve each workstream's scope and its existing gate owner.
- These diagnostics never repair the native database, restart sessions, or launch
  work. An unavailable index comparison must not be interpreted as healthy.
- The script is designed to tolerate partial/missing event fields in transcripts.
- Transcript discovery covers both `~/.codex/sessions` and
  `~/.codex/archived_sessions`; archival state does not imply who archived the task.
- `list` is shallow by default and filters only session id/thread title. Use `--deep` when matching cwd/path is needed.
- `mine` parses transcripts and defaults to the last 2 days unless `--since` or `--days` is provided.
- For orchestrator work, run `mine`, then delegate the generated `state-miner-*.md` file to a cheap subagent for the actual synthesis.
- PR/status mining is optional and guarded by `--no-gh` because GitHub access is not guaranteed.
