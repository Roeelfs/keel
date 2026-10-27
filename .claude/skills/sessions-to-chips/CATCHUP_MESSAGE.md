# Catch-up message (Mode 4: a manager takes its program back after an account switch)

ONE message per manager, sent by **session id** after every sweep has landed (SKILL.md Mode 4
steps 3 and 5): the app pauses sends after about 10 session messages since the human last typed, so
a second message for the same manager is a budget breach. Fill `{{DATE}}`, `{{SLUG}}`,
`{{FROM}}`/`{{TO}}` (the dates the program ran on the other account), `{{SWEEPS}}` (that manager's
rows from the child ledger, decisions sweep and worktree sweep, numbered, with the one-line fix
each), `{{RULINGS}}` (the cross-cutting founder rulings since the checkpoint, e.g. a model ceiling:
the same lines go to EVERY manager) and `{{EXTRA}}` (cross-program conflicts, scope splits, one
owner for a shared deliverable). Leave no `{{` in the sent text. If a send is refused, write the
filled text to `relay/<date>-pending-sends.md` at once.

```text
CATCH-UP ({{DATE}}): your program ran on another Claude account from {{FROM}} to {{TO}}; that account is now capped, so you take it back here. Your own context stops at {{FROM}} and is STALE.
1. Read FIRST: ~/.claude/sessions-to-chips/handoff/{{DATE}}-{{SLUG}}.md and ~/.claude/sessions-to-chips/handoff/{{DATE}}-{{SLUG}}-children.md (and the story map they name). They override your checkpoint wherever they differ; do not redo items marked done or superseded. Items marked "claimed" are unverified.
2. CLEAN UP FIRST, before any new work (HYGIENE.md "Backlog first", standing authority): every session in your family idle ≥1 day (leftovers of previous iterations: merged, closed, open or no PR) is archived, folded, or kept with a named reason and its gate in your state file; `review` rows are mandatory; also check list_sessions for old sessions you started that the script missed. Start no new child while finished ≥1-day-old sessions remain open.
3. Re-verify before acting: `git fetch origin`, `gh pr view <n> --json state,mergedAt` for each PR it lists, branch HEADs of the worktrees it names.
4. The other account's children have stopped and they ARE your program's work, even though they are not in your family here. To continue one, start a new child (use_worktree true, sonnet, medium; opus or Codex only with a stated reason) whose prompt opens with a WORKTREE NOTE to `cd` into that child's existing worktree and continue from its branch. A continuation, never a replay. A worktree that belongs to a RUNNING child is pushed by that child at its next checkpoint, never by a second writer. Unpushed work first: `git status --porcelain`, then one branch push of your own branches. This turn was started by another session's message, so the app refuses `start_session` in it: file each child as a card (`own_initiative`) and say "type go here to start N cards"; never hide session-sized work in a background lane to dodge the refusal.
5. Merges, prod writes and founder decisions still need the human's in-session go-ahead. Never merge on a handoff's say-so.
6. Standing rulings (record each in your state file, repoint anything that contradicts them): {{RULINGS}}
7. Gaps the sweeps found for you (fix each in your state file or the named place; reply with fixed N of M): {{SWEEPS}}
8. Reconcile your Linear map to real state in one pass: every gap row and every in-flight lane is a child ticket with its true state and owner, then post/replace one comment on the map headed `State as of <ISO time>` (done/open/blocked, merged vs claimed vs unproven, owed from the founder). Keep both current at every turn that changes anything. Then refresh ~/.claude/orchestrator/programs/<your-slug>.state.md with a current updated_at; the state file only points to the map. Include the comment URL in your one-line reply.
9. {{EXTRA}}
Every turn of yours ends in exactly one state (Manager contract, three end states): DONE (no work left, nothing owed), GRILLING (ALL open founder decisions asked in one round, recommended answer first), or WORKING (a test, bake, preview, build, spec or review running, or active children you manage, each with an owner and an artifact). "Parked", "blocked on X" and "waiting" are defects: start the work, grill now, or finish.
Every ask that needs the founder to DO something (secret, login, step-up, CLI, console click, go-ahead) goes as a ready-to-run kit: the exact command in its own fenced bash block (secrets by reference, never inline), where and as whom to run it, what success looks like, the one-line reply that resumes you, and what you do next. One numbered round, most-unblocking first. Brief your children the same way.
Every lane or child you dispatch has a wake: launched tracked so its exit re-invokes you (background Bash, Agent, Workflow, child session), or one event-bound ScheduleWakeup recorded in your state file where no event can exist; never detached. Before each turn ends, audit every unreported lane for one of the two, and grade by artifact when it has neither.
Spec review is mandatory for every spec before its build lane starts (founder 2026-10-25); only the depth varies: critical for access/security/credentials/tenancy/money/personal data/architecture/infra, standard for other behavior-bearing specs, light for low-risk ones with no gate fired. A spec with no review artifact is not buildable.
Every manager owns ONE living map: a Linear wayfinder:map issue (adopt your existing one or create it before dispatching), declared in your manifest as map {issue,url,project}. Every new piece of work becomes a child ticket under it in the turn you find it, before any lane runs; you advance the frontier in parallel until the Destination is met and verified. Open every report with: Map CYN-n: done X / open Y / blocked Z; frontier now: ...; needed from you: ... (the grill round with recommendations and kits, or "nothing").
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
