# Instructions files — AGENTS.md ↔ CLAUDE.md, one canonical contract

Every AI coding CLI looks for its own instructions filename: Claude Code reads
`CLAUDE.md`; Codex, Gemini, and most agents.md-ecosystem runtimes read `AGENTS.md`.
Maintaining two copies guarantees drift — and a contradiction between them is worse
than either rule alone, because each runtime silently obeys a different contract.

## The convention

**One canonical file per repo; the other filename is a link or a thin pointer.**

- Pick the canonical filename by where your agents actually run. If most work happens
  in runtimes that read `AGENTS.md`, that's the canonical file and `CLAUDE.md` links
  to it (`ln -s AGENTS.md CLAUDE.md`) — and vice versa. Claude Code follows symlinks.
- On filesystems where symlinks are awkward, use the thin-pointer form instead (see
  [`templates/AGENTS.md.template`](../templates/AGENTS.md.template)): a few lines that
  say "the rules live in <other file> — read it", and nothing else.
- **Never let the two filenames carry different rules.** This is the one-architecture
  rule applied to instructions: exactly one contract, however many names point at it.

## The layers — what belongs where

| Layer | File | Versioned in | Holds |
|---|---|---|---|
| **Repo** | `AGENTS.md`/`CLAUDE.md` (one canonical) | the product repo (PR'd) | project law: build/test/deploy gates, data boundaries, invariants, conventions this repo enforces |
| **User-global** | `~/.claude/CLAUDE.md` (and runtime equivalents) | your private harness repo | personal workflow rules that hold across every repo: commit style, dispatch discipline, standing tools |
| **Skills** | `SKILL.md` per skill | the skills repo | *procedures* — how to run a recurring multi-step task |
| **Memory** | `.claude/memory/` topic files | project repo or harness | *facts and state* — what is true right now, project status, gotchas |

Routing test for any new rule: a **contract** ("never X", "always Y before Z") belongs
in an instructions file at the narrowest layer that owns it; a **procedure** belongs in
a skill; a **fact** belongs in memory. Instructions files are contracts, not manuals —
a procedure pasted into CLAUDE.md is bloat that ages into a lie.

Load semantics worth knowing: instructions files load at **session start** (a running
session keeps the old text until restarted); skills load at **invocation time**
(updates apply immediately, even to running sessions).

## Upkeep — the `/improve-harness` contract

Instructions files are a maintained surface, not an append-only log. The
`improve-harness` skill's Workflow A carries an **instructions-file audit** that owes,
each period:

1. **Stale-rule pruning** — a rule referencing a file, flow, flag, or command that no
   longer exists is verified (read-only `ls`/`grep`) and removed, not left as lore.
2. **Duplication / contradiction** — between the two filenames in one repo (must be
   one-canonical-plus-pointer) and between the repo layer and the global layer (the
   narrower layer wins; delete the shadow copy).
3. **Demotion** — procedure-shaped rules move to a skill; fact-shaped entries move to
   memory. The instructions file keeps only the contract.
4. **Lesson ↔ rule correlation** — for every lesson the period's mining surfaced:
   *should an existing rule have prevented it?* → strengthen that rule (or promote it
   to a hook — a rule the model must "remember" that keeps failing is a hook
   candidate, not more prose). *Does it have no rule home at all?* → propose the
   addition at the right layer. And the inverse: a rule that nothing exercised and
   whose subject no longer exists gets pruned.

The `harness-onboarding` skill establishes this shape on a new machine (canonical
file + pointer per repo); `improve-harness` keeps it true over time.
