# Skill memory & learnings — route by scope

A skill accumulates two kinds of knowledge: what it **reads** to do its job, and what it **learns** from doing it. Route each learning to exactly one home **by scope**. The committed `LEARNINGS.md` beside a skill is a **read-only curated seed** — never append per-run learnings to it.

## The three homes

| Scope | Example | Home | Shared via |
|---|---|---|---|
| **Universal skill craft** — true for this skill in any repo | "web research legitimately runs 20–40 min; budget for it" | this skill's committed `LEARNINGS.md` (the **seed**) | this repo — **promote-only** |
| **Operator-private skill craft** — cross-project, yours, not for publication | "our Codex CLI hangs at ~40 min on complex specs" | `~/.claude/skills-overlay/<skill>/LEARNINGS.md` (create if absent) | your private harness repo |
| **Project-specific** — true only for the repo you're working in | "in THIS repo, the security review must check the data-store's delete-protection" | the project's `.claude/memory/` (a topic file) | the project repo |

## Rules

- **Read (skill start):** the seed `LEARNINGS.md` here **+** the private overlay if present (`~/.claude/skills-overlay/<skill>/LEARNINGS.md`). Project memory is loaded automatically at session start (`.claude/memory/MEMORY.md`), so you already have it.
- **Write (skill end):** route each new learning to ONE home per the table. Default operator-private craft to the overlay; put project-specific facts in the project's `.claude/memory/`. **Never** hand-append to the committed seed in this repo.
- **Promotion is `/improve-harness`'s job:** a learning that recurs ≥3× across projects/sessions gets **de-identified** and proposed for the public seed here via PR. Promotion is the only way the seed grows — no per-run edits to it.
- **Never** put secrets, customer/PHI data, or internal identifiers in the committed seed or any shared memory — scope those to the private overlay, or keep them out entirely.

Each skill's `## Skill Memory` section points here; this file is the single source for the routing.
