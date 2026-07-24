# keel — Agent Instructions

Canonical instructions file for this repo (Codex/Gemini read this; `CLAUDE.md` is a
symlink here — one contract, two filenames; see `docs/instructions-files.md`).

**Communication:** Be extremely concise. Sacrifice grammar for concision — drop
articles/filler/preamble; terse fragments over full sentences.

## What this repo is

The public, canonical skills repo. Machines consume it via symlinks from their skill
roots into this clone — an edit here is live everywhere on next skill invocation, no
install step.

## Contracts

- **Public and marker-free.** No secrets, customer names, project-private facts, or
  machine-specific paths in skills or seeds. Operator-private craft goes to the
  machine's `~/.claude/skills-overlay/<skill>/LEARNINGS.md`; machine/project facts go
  to project memory (`docs/skill-memory.md` owns the routing).
- **Committed `LEARNINGS.md` files are curated seeds** — they grow ONLY via
  de-identified promotion (an `/improve-harness` PR), never by hand-appending at task
  end.
- **One skill, one directory** under `.claude/skills/<name>/` with a `SKILL.md`;
  scripts live in the skill's `scripts/`; no cross-skill runtime coupling.
- **Agents follow the same split as skills.** `.claude/agents/` holds only
  vendor-neutral engineering-craft roles — no customer names, project file paths,
  credentials, or platform-branded agents (they go machine-wide via symlink, so a
  leak surfaces in every repo). A project's own agents live in that project's
  repo-local `.claude/agents/`, extending the craft roles, never here.
- **Skills load at invocation time** (edits apply to running sessions on next use);
  instructions files load at session start. Say which class a change is when
  claiming "applied".
- **Dispatched lane prompts must declare leaf-agent scope** — any prompt a skill
  hands to a subagent/Workflow lane includes: "You are a leaf agent: do NOT spawn
  sub-agents or Workflows; do the work inline and return."
- **Dispatched agents return a condensed summary, not a transcript** — target
  1,000–2,000 tokens of conclusions; never raw tool output or file bodies (the
  caller re-reads them on every subsequent turn). Carve-out: ground-truth
  identifiers — exact error text, `file:line` anchors, commit SHAs, ticket IDs,
  command strings — are quoted VERBATIM, never compressed away to hit the target.
