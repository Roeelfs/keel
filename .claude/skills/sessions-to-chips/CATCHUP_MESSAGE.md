# Catch-up message (Resume / mine: a manager takes its program back after an account switch)

ONE message per manager, sent by **session id** after every sweep has landed (SKILL.md Mode 2
steps 3 and 5): the app pauses sends after about 10 session messages since the human last typed, so
a second message for the same manager is a budget breach. Fill `{{DATE}}`, `{{SLUG}}`,
`{{FROM}}`/`{{TO}}` (the dates the program ran on the other account), `{{SWEEPS}}` (that manager's
rows from the child ledger, decisions sweep and worktree sweep, numbered, with the one-line fix
each) and `{{EXTRA}}` (cross-program conflicts, scope splits, one owner for a shared deliverable).
A cross-cutting founder ruling is never put in the message: append it to the rulings ledger (the
machine's overlay `rulings-ledger.md`) before sending, and every manager's role load prints it. The
message carries program facts only; the rules come from `/manager-role <slug>` (`references/role.md`).
Leave no `{{` in the sent text. If a send is refused, write the filled text to
`relay/<date>-pending-sends.md` at once.

```text
CATCH-UP ({{DATE}}): your program ran on another Claude account from {{FROM}} to {{TO}}; that account is now capped, so you take it back here. Your own context stops at {{FROM}} and is STALE.
0. Run `/manager-role {{SLUG}}` first and do its wake steps; it prints your role, the rulings in force and the changes since you last loaded them. This message adds program facts only.
1. Read FIRST: ~/.claude/sessions-to-chips/handoff/{{DATE}}-{{SLUG}}.md and ~/.claude/sessions-to-chips/handoff/{{DATE}}-{{SLUG}}-children.md (and the story map they name). They override your checkpoint wherever they differ; do not redo items marked done or superseded. Items marked "claimed" are unverified.
2. CLEAN UP FIRST, before any new work (HYGIENE.md "Backlog first", standing authority): every session in your family idle ≥1 day (leftovers of previous iterations: merged, closed, open or no PR) is archived, folded, or kept with a named reason and its gate in your state file; `review` rows are mandatory; also check list_sessions for old sessions you started that the script missed. Start no new child while finished ≥1-day-old sessions remain open.
3. Re-verify before acting: `git fetch origin`, `gh pr view <n> --json state,mergedAt` for each PR it lists, branch HEADs of the worktrees it names.
4. The other account's children have stopped and they ARE your program's work, even though they are not in your family here. To continue one, start a new child whose prompt opens with a WORKTREE NOTE to `cd` into that child's existing worktree and continue from its branch. A continuation, never a replay. A worktree that belongs to a RUNNING child is pushed by that child at its next checkpoint, never by a second writer. Unpushed work first: `git status --porcelain`, then one branch push of your own branches. This turn was started by another session's message, so the app refuses `start_session` in it: file each child as a card (`own_initiative`) and say "type go here to start N cards"; never hide session-sized work in a background lane to dodge the refusal.
5. Gaps the sweeps found for you (fix each in your state file or the named place; reply with fixed N of M): {{SWEEPS}}
6. Reconcile your Linear map to real state in one pass: every gap row and every in-flight lane is a child ticket with its true state and owner, then post the `State as of <ISO time>` map comment and refresh your state file and page (role wake steps 5-8). Include the comment URL in your one-line reply.
7. {{EXTRA}}
Reply with ONE line: your end state, archived N (before → after), live children X, each kept ≥1-day session with its reason, fixed N of M, and how many founder decisions you hold. Ask the founder those decisions here in your own session and record the answers in your state file; the dispatcher does not collect them.
```

A manager the dispatcher started fresh in this mode gets the Mode 1 prompt instead, with the
handoff path under START HERE and the same points 2 and 4 under STATE.

**Fold notice (an absorbed manager).** When program A absorbed B and `[Manager] B` is still live,
B gets this instead of the catch-up, and A gets a takeover note naming B's live children by session
id: "[Manager] B was absorbed into A on <date> (handover: <path>). Start no further child. Let each
live child reach its next checkpoint (push once, record the PR), send A `Taking over from B: ...`
(≤900 chars), then run hygiene and report before → after; archive yourself only after A
acknowledges, because archiving a parent cascades to a working child."
