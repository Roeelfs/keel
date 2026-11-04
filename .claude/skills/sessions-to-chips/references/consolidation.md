# Consolidation — progress is never lost across sessions and accounts

Founder go 2026-11-04: a manager keeps its program's progress somewhere
durable on every wake, and checks it before any chip changes hands. Work that lives only in a dirty
worktree, an unpushed branch, a dead memory link or a handoff sentence is one reaper, compaction or
account switch away from gone.

One owner: `scripts/consolidation_check.py`. It reads; only `--record` writes, and only to the state file.

## Every wake: the consolidation step

Run it after reading the context brief and before working the map:

```
$SCR/consolidation_check.py --program <slug> --record ~/.claude/orchestrator/programs/<slug>.state.md \
  [--claim <repo>:<sha>]... [--pr <owner/name>#<n>]... [--reason <worktree>=<why>]...
```

It checks three things and appends one `## Consolidation <UTC>` block ending in
`Consolidation: OK (0 owed)` or `Consolidation: OWED (<n> owed)`.

1. **Family worktrees are clean and pushed, or carry a named reason.** The family is every manifest
   binding's `worktree`, plus every worktree of a manifest `repos[].path` whose branch names a bound
   ticket. For each `DIRTY`, `UNPUSHED` or `DETACHED` row, do one of:
   - commit the work in that worktree and push it to a `wip/<ticket>-<slug>` branch (one push; never
     to main, never a force-push to a branch another session owns); or
   - name why it may stay local, with `--reason <path>=<why>`: a lane still writing (name its carrier),
     a branch squash-merged as `#<n>` (its commits are on main under another SHA), a scratch probe
     that holds nothing.
   A `MISSING` row is a stale binding: retire it through `work_state.py`. A worktree another session
   owns is never yours to commit: message its owner (`pr-session.mjs who`, `SendMessage`) and record
   that as the reason.
2. **Memory links resolve.** It runs `~/.claude/scripts/memory_link_check.py --gate`: every
   `[[link]]` and `.md` file link resolves, every topic file is in an index, no `MEMORY.md` is past
   its load cap. A `FAIL` names each reason; fix them before ending the turn (rewrite or restore the
   link, index the file, move index lines verbatim to a `MEMORY-*.md` sub-index). Never delete
   memory content to pass it: archive.
3. **Handoff claims are verified with git and gh, never with memory.** Every "committed", "pushed",
   "merged" or "on main" claim the wake inherits (a handoff, a child's end note, the state file, a
   memory line) goes through `--claim <repo>:<sha>` (exists, on a remote branch, on origin's default
   branch) or `--pr <owner/name>#<n>` (state, mergedAt). An `UNCONFIRMED` claim is downgraded in the
   state file and VIEW in the same turn; it is never carried forward at the old confidence.

`--strict` exits 1 when anything is owed, for a caller that must refuse to proceed.

## Before a chip changes hands: start, hand off, archive

Before `start_session`, `hand_off_to_session`, `archive_session`, or retiring a lane, run the step for
that chip's worktree(s) and record it in the program's state file:

```
$SCR/consolidation_check.py --worktree <chip worktree> [--claim ...] --record <slug>.state.md
```

- **Start:** the new chip's base is pushed (`OK`), so it cannot start from work only the parent holds.
- **Hand off:** the handing-off session's worktree is `OK` or carries a named reason, and every commit
  the handoff text cites is `CONFIRMED`. The handoff names the recorded block, not a remembered status.
- **Archive / retire:** the chip's worktree is `OK`, or its work was pushed to a `wip/` branch first.
  Archiving a session whose worktree is `DIRTY` or `UNPUSHED` with no reason is refused: that is the
  untracked-salvage class (3 of 13 "merged" worktrees held untracked work).

The recorded block is the evidence. A later wake reads it instead of re-deriving, and the state
page's machinery footer may cite it; it never replaces `## AT-WAKE`.
