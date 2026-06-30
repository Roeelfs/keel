# Mailbox-mode lane directive

Replaces `/loop` for orchestrator-driven lanes. Lane blocks on a file-system mailbox via background watcher. Wake latency: ~1–8s. Token cost during wait: zero.

## Paste-ready lane prompt

Replace `<LANE_NAME>`, `<LANE_PURPOSE>`. For Codex, replace `$CLAUDE_SESSION_ID` with an explicit key like `lane-name-1`.

```
You are lane session `<LANE_NAME>`. Purpose: <LANE_PURPOSE>.

MAILBOX MODE — instructions arrive via orchestrator-written mailbox file.

Cycle:
1. Start watcher in background (Claude: run_in_background:true; Codex: exec_command — yields ~30s with active session id, poll via write_stdin until exit):
   ~/.claude/skills/orchestrator/scripts/wakeup-wait.sh "$CLAUDE_SESSION_ID" --max-wait-sec 86400
2. End turn.
3. When woken, Read the bash output file (Claude: /private/tmp/.../tasks/<bashId>.output; Codex: session output). Format:
     WAKEUP_FOUND
     wakeup_file=...
     ---
     {"message":"<instruction>","seq":N}
     ---
   Recovery if bashId lost: cat ~/.claude/projects/<slug>/orchestrator-runs/wakeups/$CLAUDE_SESSION_ID.json
4. Execute instruction. Re-arm watcher. End turn.
5. {"message":"retire"} → final status, no re-arm.

Invariants:
- Every turn ends with active watcher OR retire signal received.
- TIMEOUT exit → re-issue watcher (don't interpret as "done").
- Commits: Session-Id trailer via UNQUOTED heredoc (so $CLAUDE_SESSION_ID expands).

First turn: echo $CLAUDE_SESSION_ID, confirm watcher script exists, start watcher, end turn.
```

## Orchestrator side

```bash
~/.claude/skills/orchestrator/scripts/mailbox-send.sh <SID> '{"message":"...","seq":N}'
~/.claude/skills/orchestrator/scripts/mailbox-send.sh <SID> --file /tmp/instruction.json
```

Validates JSON, atomic mv. Last-write-wins (two sends before consume → first lost).

## Cross-harness notes

- Codex has **native background terminals** (preferred): start the watcher as a true background process and wait for completion. Codex shows "Waited for background terminal" when the process exits, surfacing full stdout to the model. No polling needed.
- Codex `exec_command` polling fallback (older versions / when background terminal API unavailable): yields after ~30s with active session id; poll via `write_stdin` until exit.
- Use a stable mailbox key (no `$CLAUDE_SESSION_ID` env var on Codex).
- Codex worktrees: nested `<repo>/<lane>-impl/` only — sibling paths fall back to `/private/tmp/`.
