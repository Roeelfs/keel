# Account switch: lose no progress

**This is the point of Mode 2.** The founder switches Claude accounts on the spot, mid-work, when one
hits its cap. Every session that was working on the old account just before the switch holds
in-progress work that stops at the cap and cannot be resumed from the new account. Mode 2 succeeds
only when each of those sessions has an owner here and every in-progress one is continued by a new
child in its existing worktree. A clean receipt that leaves work stranded is a failed round.

## What failed on 2026-11-23/24 (measured)

- **Ledgered is not routed.** The coverage audit proved every active session was in some ledger,
  yet 7 of the 49 sessions active that day on the old account were named in no handoff: the old
  `[Manager]` sessions themselves and standalone children. No manager here owned them.
- **"Live children 0" was read as done.** Managers answered the catch-up with their children on
  THIS account. The other account's stopped children were in their `-children` files, but nobody
  was required to restart them. A second message per manager was needed to get continuation cards.
- **A shortened path lost a whole program.** One message named `security-hardening-children-<id>.md`
  without its timestamp prefix. The manager ran `find -name` on it, found nothing, and filed 0 cards
  for 11 at-risk children.
- **Replies to the dispatcher bounced.** Managers replied to the dispatcher's 8-character id, which
  `send_message` rejects, so two replies never arrived and had to be read with `list_events`.

## The rules

1. **Switch-window gate** (`scripts/switch_coverage.py`, graded by `mine_all.py --gate` as
   `switch-window`). For each account other than this one, take its newest `lastActivityAt`. Every
   non-archived session active within 36 hours before that moment must have its 8-char short id
   in a handoff file written in this round. An account idle more than 7 days is not a switch and
   is skipped. FAIL writes `relay/<date>-unrouted-sessions.md`. Route each row in
   `handoff/<date>-uncovered-sessions.md` (full id, owner slug, state, worktree, branch, PR; check
   `git status --porcelain` and whether the worktree HEAD is a merged PR's head), or add
   `<shortid> <reason>` to `relay/switch-exclude.txt` for personal work. Then re-gate.
2. **Continuation is counted, not implied.** Every catch-up carries the continuation step:
   for every IN-PROGRESS or BLOCKED row in the manager's `-children` files, file a card whose
   prompt opens with a WORKTREE NOTE; founder-blocked rows are asked in the manager's own chat;
   DONE rows are recorded and closed. The reply line includes
   `in-progress N, cards filed N, closed N, founder asks N`.
3. **Absolute paths only** in every message: the full filename with its timestamp prefix, never a
   shortened or `…` form.
4. **Replies.** Give the dispatcher's full `local_<uuid>` in the message, and tell the manager to
   also print its reply line in its own chat. If a reply never arrives, read it with
   `list_events` (a read), never a nudge (a send).
5. **Converged** additionally requires, per manager: cards filed + founder asks + closed = the rows
   in its `-children` files, by count. Any shortfall gets one correction message with the rows named.
6. **Then the human's step:** list the managers holding unstarted cards. They type `go` in each,
   because cards filed in a turn that another session started cannot start themselves.

## What the session store shows (measured 2026-11-01)

The store's `cliSessionId` names only a session's NEWEST transcript; a resume, move or fork mints a
new file whose head `parentUuid` points into the old one (22 multi-file chains in 14 days).
`lastActivityAt` is epoch milliseconds and also moves on focus and artifact rows. `accountUuid`
sits only on artifact rows, so it never proves which account ran a turn: the store dir does. A
child links to its parent by `spawnedFrom.sessionId`. Handoffs name sessions by 8-char short id,
so coverage greps the short id.
