---
name: codex-sessions
description: Mine local Codex sessions, summarize active and recent sessions, and produce an orchestration state artifact.
---

# codex-sessions

This skill exposes `python3 ~/.claude/skills/codex-sessions/scripts/sessions.py`.

## Commands

### `list`
Show Codex sessions from local session metadata and optional filters.

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
- The script is designed to tolerate partial/missing event fields in transcripts.
- `list` is shallow by default and filters only session id/thread title. Use `--deep` when matching cwd/path is needed.
- `mine` parses transcripts and defaults to the last 2 days unless `--since` or `--days` is provided.
- For orchestrator work, run `mine`, then delegate the generated `state-miner-*.md` file to a cheap subagent for the actual synthesis.
- PR/status mining is optional and guarded by `--no-gh` because GitHub access is not guaranteed.
