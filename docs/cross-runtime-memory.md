# Cross-runtime memory — one project store, both runtimes

**Finding first:** there is nothing to *symlink*. Curated project memory is already a
single store that both Claude Code and Codex address by the **same slug convention**, so
they are matched by path, not by a link. A symlink only helps when two runtimes look in
*different* per-project locations — these don't.

## The two memory systems (only one is shared, by design)

| System | Location | Nature | Cross-runtime |
|---|---|---|---|
| **Curated project memory** | `~/.claude/projects/<slug>/memory/` — `MEMORY.md` index + one `*.md` per fact | hand/agent-authored, per-project, slug-keyed, machine-local | **Shared.** Claude Code owns it natively; Codex reads it via a `~/.codex/AGENTS.md` instruction. This is the store to share. |
| **Codex native memory** | `~/.codex/memories_1.sqlite` (`stage1_outputs` → `selected_for_phase2`) | auto-generated from Codex's own rollouts by a background pipeline; machine-managed | **Not shared, not shareable.** It's a sqlite cache, not curated markdown — you can't symlink markdown into it, and it duplicates what the curated store holds deliberately. Leave it to Codex. (Observed empty/dormant in practice.) |

`<slug>` = the project's cwd with every `/` replaced by `-`
(e.g. `/Users/x/code/proj` → `-Users-x-code-proj`). Both runtimes derive it the same way,
which is *why* they already converge on one directory.

## Why not a symlink

- The curated store already lives at one canonical path both runtimes compute from the
  cwd. Nothing points anywhere else, so there is no second location to link to the first.
- The only other memory is Codex's sqlite — a machine-managed cache in a different format.
  Symlinking markdown into it is meaningless; it isn't a curated store and shouldn't
  mirror one.
- Keeping memory **machine-local** is a hard requirement (it holds project-private facts,
  sometimes PHI/secrets). It never goes into keel or any remote — so there is also nothing
  to share *through* the public repo; the sharing is purely local, by path convention.

## What actually needs hardening (the real ask behind "match memories")

1. **Read the whole store, not just the index.** Codex's per-project instruction should
   load `MEMORY.md` *and then follow its pointers / `[[links]]` into the relevant topic
   files on demand — the same way Claude Code's memory system does. Loading only the index
   gives Codex the table of contents but not the facts.
2. **Write back into the shared store.** When Codex learns a durable, project-specific
   fact, it should write it into `~/.claude/projects/<slug>/memory/` in the *same format*
   (one `*.md` per fact with frontmatter, plus a one-line pointer in `MEMORY.md`) — not
   only into its own sqlite. That makes the store genuinely bidirectional: a lesson Codex
   learns is there for Claude Code next session, and vice-versa.
3. **keel owns the wiring.** A fresh machine's Codex has none of this. The recommended
   `~/.codex/AGENTS.md` per-project instruction (below) is keel-owned guidance;
   `harness-onboarding` installs/refreshes it so every machine shares memory the same way.

## The recommended `~/.codex/AGENTS.md` per-project instruction

`~/.codex/AGENTS.md` is Codex's global instructions file (its analog of
`~/.claude/CLAUDE.md`) — machine-local, not part of keel. Onboarding should ensure its
per-project block reads and writes the shared store:

```markdown
## Per-project context & memory (shared with Claude Code)
At session start in any project, resolve <slug> = cwd with `/` → `-`, then:
1. Read `~/.claude/projects/<slug>/memory/MEMORY.md` (the index).
2. Follow its pointers into the specific `*.md` topic files relevant to the task —
   this is the SAME curated store Claude Code uses; load facts on demand, not just the index.
When you learn a durable, project-specific fact, WRITE IT BACK into that same dir:
one `*.md` per fact (frontmatter: name, description, metadata.type), plus a one-line
pointer in `MEMORY.md`. Keep PHI/secrets in this machine-local store — never in the repo
or any remote. This is the store shared with Claude Code, so both runtimes compound the
same memory.
```

## Load semantics & scope

- Instruction files (`~/.codex/AGENTS.md`, `~/.claude/CLAUDE.md`) load at **session start** —
  a running session keeps its old contract until restart.
- The memory dir is per-project and machine-local. It is the one place project-private
  facts live; keel (public) and every remote stay marker-free (see [`../AGENTS.md`](../AGENTS.md)).
