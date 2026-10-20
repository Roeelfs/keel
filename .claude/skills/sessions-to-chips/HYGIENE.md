# Session hygiene — a manager keeps its own family small

**Why.** Every live session is a row the human re-reads to resume. A finished child left open,
or two children on one topic, splits the context and raises the cost of picking the work back
up. A manager's job includes leaving the **fewest sessions that still hold all the context**
(founder, 2026-10-20).

**When.** At every stopping boundary of a manager turn: after a child reports, and before you
end a turn in which nothing in your family is working. Never on a schedule. A `[Manager]`
session also gets the candidate list automatically: the `manager-hygiene` Stop hook announces
it once per new candidate set and continues your turn so you can act.

**Scope.** Only your own family: the sessions you started, and theirs. Never another
manager's family (a nested `[Manager]` owns its own), never another account, never `delete`
(archive only; `unarchive_session` restores).

## 1. List candidates

```bash
python3 -I ~/.claude/skills/sessions-to-chips/scripts/hygiene_candidates.py --manager <your local_ session id>
```

It proposes `archive` (PR merged or closed, idle ≥1h, no live child), `review` (no PR, idle
≥24h) and `converge` (shared tracker id, PR or worktree). These are proposals, not verdicts:
the store does not know what a session is waiting on.

## 2. Verify each one before acting

A candidate is acted on only when **all** of these hold. One failure and it stays.

- Not running: `list_sessions` shows `isRunning: false`.
- Not pinned: the human pinned it on purpose.
- Nothing owed: its last report (`get_session`, or the note you received) has no unanswered
  question to the human, no merge go-ahead pending, no bake owed, and no PR still bound for a
  main-green watch. **A parked founder question is not a reason to keep the session.** Move it
  into your own "Owed to the founder" list, with the exact question and its default, then archive.
- Work is safe: `git -C <worktree> status --porcelain` is empty and `git -C <worktree> log @{u}..`
  prints nothing, or the worktree is shared, gone, or recorded as abandoned on purpose.
- Its follow-ups live somewhere durable: your Units table, the tracker, or a card.

## 3. Archive

`archive_session` on each verified `archive` / done `review` candidate. Archiving a parent
archives its finished children too. The script never proposes a parent with a live child, but
list the children first if you archive anything it did not propose.

## 4. Converge (fold true duplicates)

Fold only sessions that carry **the same deliverable**: the same PR, a follow-up of the same
ticket that the survivor can finish, or a second session reopening the first one's question.
Parallel siblings that produce different deliverables under one ticket (spec H1, H2, H3) are
not duplicates. Keep them. Never fold a running session.

For each fold:

1. Write the folded session's state in ≤900 characters: goal, branch/PR, what is proven, what
   is still unproven, decisions made, dead ends, and the next action plus its owner.
2. `SendMessage` it to the survivor **by session id**: `Taking over from <title> [<id>]: ...`.
3. Run step 2's checks on the folded session, then archive it.

## 5. Report one line

`Hygiene: archived N (<titles>), folded A into B; family X → Y.` No question is needed:
archiving is reversible. Put anything still owed to the human in your normal close-out, not
in this line.
