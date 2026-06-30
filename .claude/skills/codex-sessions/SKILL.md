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

Artifacts are written to `STATE_DIR/`:
- `last-state.json`
- `state-miner-<timestamp>.md`
- `survey-<timestamp>.json`

`STATE_DIR` defaults to:
- `<cwd>/tools/codex-sessions/state/` if that directory exists in the cwd (in-repo layout — back-compat)
- otherwise `~/.claude/projects/<slug>/codex-mining/` where `<slug>` is the cwd path with `/` replaced by `-`

### `export-messages`
Normalize a Codex rollout into Claude-shaped JSONL records (`{"message": {"role": ..., "content": ...}}`) so downstream extractors that assume Claude's schema (e.g. `spec-review`/prompts/design-decisions-extractor.md) work unchanged across both runtimes.

```bash
python3 ~/.claude/skills/codex-sessions/scripts/sessions.py export-messages \
  --sid <session-id> --output /tmp/codex-export.jsonl
```

The output is a JSONL where each line has the same shape as a Claude session record. Walking codex's `event_msg.user_message`, `event_msg.assistant_message`/`agent_message`/`final_answer`, and `response_item.message` payloads. Tool calls and metadata are dropped — only conversational turns are emitted.

## Notes
- The script is designed to tolerate partial/missing event fields in transcripts.
- `list` is shallow by default and filters only session id/thread title. Use `--deep` when matching cwd/path is needed.
- `mine` parses transcripts and defaults to the last 2 days unless `--since` or `--days` is provided.
- For orchestrator work, run `mine`, then delegate the generated `state-miner-*.md` file to a cheap subagent for the actual synthesis.
- PR/status mining is optional and guarded by `--no-gh` because GitHub access is not guaranteed.
