# Config freshness: when a live session runs on old config

A long-running session (a manager above all) can lag behind harness changes. **Re-dispatching a
manager because the harness changed is almost never the fix.** Measure first:

```bash
python3 -I ~/.claude/skills/sessions-to-chips/scripts/config_freshness.py   # [Manager] rows
python3 -I ~/.claude/skills/sessions-to-chips/scripts/config_freshness.py --grep "<title>" --json
```

## What a running CLI picks up by itself (measured and sourced 2026-10-22)

| Changed on disk | Running session | Source |
|---|---|---|
| Hook registrations, permissions, `env` in settings.json | LIVE: the settings watcher reloads them | code.claude.com/docs/en/settings.md, "applies most edits to the running session without a restart, including edits to `permissions`, `hooks`" |
| Hook script bodies | LIVE: run from disk per event (transcripts show new bodies firing) | measured 10-22 |
| Agent definitions, the skill list | LIVE | sub-agents.md, skills.md |
| A skill's body after it was invoked | FROZEN in the conversation | skills.md, "does not re-read the skill file on later turns" |
| `~/.claude/CLAUDE.md`, repo AGENTS.md/CLAUDE.md | Re-read on compaction; mid-session edits UNPROVEN | context-window.md, "Re-injected from disk" |
| `enabledPlugins`, plugin MCP servers, `model`/`effortLevel` keys, a newer CLI build | Only a NEW CLI process | plugins/loading.md, "don't reach this layer until you run `/reload-plugins` or start a new session" |

**Accounts share one config.** Every desktop account runs its CLI with the same `HOME` and no
`CLAUDE_CONFIG_DIR` (`ps eww <pid>`, 10-22), so a change "made in the other account" is the same
`~/.claude` and keel files. An account switch swaps the OAuth token, not the hooks.

## Verdicts and the fix for each

| Verdict | Meaning | Fix |
|---|---|---|
| `FRESH` | nothing changed since its CLI started | none |
| `FRESH-ON-RESUME` | no CLI process; the next message spawns one from current disk | none |
| `STALE-REREAD` | instructions or skill bodies changed after start | one **refresh message**: the commits, and the files to Read again (CLAUDE.md, the contract, any skill it runs) |
| `STALE-RESTART` | plugins, MCP, model keys or the CLI build changed | refresh message now; the process restart waits for the next desktop relaunch (below) |
| `OLDER-TWIN` | a newer live session holds the title (often the other account's pre-switch manager) | hygiene candidate, never a refresh target |

**There is no agent verb that restarts another session's CLI.** `stop_session` only interrupts a
turn; the process stays. Never kill a CLI process yourself. A restart-class change reaches a session
when the human relaunches the desktop app (every session resumes from current disk; `--resume`
re-reads settings.json) or when the app reaps the idle process. So: send the refresh message, list
the restart-class items as owed, and ask for a relaunch only when one of them blocks real work
(e.g. a lane needs a plugin's MCP tools and has no fallback).

**Re-dispatch** (archive and start a new manager) only when the conversation itself is the problem:
it runs on a superseded contract it cannot re-read its way out of, its context is past saving, or it
sits on the wrong account for the work. Config age alone never qualifies.

## When to run it

- After any harness change you want live managers to act on (a contract, a CLAUDE.md rule, a
  spec-review lane): run the probe, then send the refresh message to the `STALE-*` rows only.
- After an account switch (Mode 3 step 5), before resuming from the notes.
- When a manager behaves as if a rule does not exist: probe it before arguing with it.
