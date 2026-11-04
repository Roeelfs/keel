# keel hooks — the one owner of every generic hook

A hook here is the running copy, not a seed. A machine wires it by **symlink** from
`~/.claude/hooks/<name>` to this directory, and `~/.claude/settings.json` calls the
`~/.claude/hooks/` path. An edit here is live on the next tool call that fires it.
One owner per file: never keep a second copy of a hook that lives here.

## What lives here, what stays on the machine

- **Here:** a hook that reads the same on a stranger's machine. It may write its own log
  under `~/.claude/analytics/`, call a sibling by `~/.claude/hooks/<name>` or its own
  directory, and call a keel script by `~/.claude/scripts/<name>`.
- **On the machine only:** a hook that names a repo, tracker prefix, customer, machine path
  or operator ruling, or that cites a private evidence file. This repo is public and
  marker-free (`AGENTS.md`), and `.githooks/pre-commit` blocks most such text. A hook that
  needs one private rule stays private whole; it is never split into a public copy plus
  a private delta.
- A machine-only hook may import a keel hook's module from `~/.claude/hooks/` (the link
  makes it a sibling), never the other way round.

`tooling/sandbox/install-resource-hooks.py` treats a hook that already links to its keel
source as current, so re-running it never turns a link back into a copy.

Hooks are still **not** auto-wired by `tooling/wire-skills.sh`: a hook can block every tool
call on the machine, so wiring one is a deliberate act (read it, link it, register it in
`settings.json`, run `~/.claude/scripts/replay-hook.sh syntax`).

`session-start.sh`, `session-end.sh`, `heartbeat-reaper.sh` and `serialize-heavy-ops.sh`
are starter hooks for a new machine; nothing here requires them.

## Before changing a hook

A hook can block a tool call. Replay it against the **actual transcripts** that motivated
it — it must fire at the real friction point, stay silent on a healthy session, and emit a
bounded number of times over a long incident. A dry-run against fixtures you invented
proves only that the hook matches your model of the bug. See
`.claude/skills/improve-harness/GOTCHAS.md`. `hook-syntax-sentinel.py` reports a hook that
stops parsing in the same turn, including one reached through a symlink.
