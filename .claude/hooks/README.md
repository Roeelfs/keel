# keel hooks — portable SEEDS, not the running copies

The scripts in this directory are **vendor-neutral seeds**: the smallest correct version
of a guard, safe to drop onto any machine. They are *not* the hooks a configured machine
actually runs.

## The relationship

A machine's live hooks live in `~/.claude/hooks/` and are wired from `~/.claude/settings.json`.
Those copies routinely **diverge upward** from these seeds, because a live hook accumulates:

- **repo-scoping** — `case "$cwd" in */<repo>*)` guards that name a specific repository.
  Those can never live here: this repo is public and marker-free, so a rule naming a
  customer repo, tracker prefix, or machine path is a contract violation.
- **machine-specific paths** — a project's memory dir or a local CLI.
- **operator-private craft** — the same split that governs skills: the committed seed is
  de-identified, the private detail stays on the machine.

Measured 2026-07-24, that divergence was real and large for the then-current resource
serializer. That retired example remains in dated harness analytics; the live comparison
today is `warn-if-worktree-launch.sh`, which is 49 lines here and 110 lines live.

## What this means in practice

- **Do NOT "sync" the two directions blindly.** Copying live → seed leaks machine and
  customer specifics into a public repo. Copying seed → live silently deletes hard-won
  guards and can un-wedge a real safety block.
- **A fix that is genuinely generic belongs in BOTH** — de-identify it, land it here, and
  apply the same change to the live copy.
- **A fix that names a repo, path, or tenant belongs ONLY in the live copy** (or in that
  repo's own `.claude/`).
- Hooks are **not** auto-wired by `tooling/wire-skills.sh` — unlike skills and agents,
  which are symlinked into the runtime roots, hooks are deliberately copied and adapted,
  because wiring one machine-wide without reading it is how you fail closed on real work.

## Before changing a live hook

A hook can block a tool call. Replay it against the **actual transcripts** that motivated
it — it must fire at the real friction point, stay silent on a healthy session, and emit a
bounded number of times over a long incident. A dry-run against fixtures you invented
proves only that the hook matches your model of the bug. See
`.claude/skills/improve-harness/GOTCHAS.md`.
