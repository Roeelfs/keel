# Catch-up message (Mode 4: a manager takes its program back after an account switch)

Send by **session id** to the existing manager on the account you are now on. Fill
`{{DATE}}`, `{{SLUG}}`, `{{FROM}}`/`{{TO}}` (the dates the program ran on the other account) and
`{{EXTRA}}` (program-specific items: cross-program conflicts, scope splits, unpushed work the
sweep found). Leave no `{{` in the sent text.

```text
CATCH-UP ({{DATE}}): your program ran on another Claude account from {{FROM}} to {{TO}}; that account is now capped, so you take it back here. Your own context stops at {{FROM}} and is STALE.
1. Read the handoff FIRST: ~/.claude/sessions-to-chips/handoff/{{DATE}}-{{SLUG}}.md, and the story map it names. It overrides your checkpoint wherever they differ; do not redo items it marks done or superseded. Items marked "claimed" are unverified.
2. Re-verify before acting: `git fetch origin`, `gh pr view <n> --json state,mergedAt` for each open PR it lists, branch HEADs of the worktrees it names.
3. The other account's children have stopped and they ARE your program's work, even though they are not in your family here. To continue one, start a new child (use_worktree true, sonnet, medium) whose prompt opens with a WORKTREE NOTE to `cd` into that child's existing worktree and continue from its branch. A continuation, never a replay. Unpushed commits listed in the handoff ride that child's next push.
4. Run hygiene on your own family (HYGIENE.md, standing authority): your pre-switch children are mostly merged/done.
5. Merges, prod writes and founder decisions still need the human's in-session go-ahead.
6. {{EXTRA}}
Reply with ONE line: archived N, live children X, the single most blocking founder decision.
```

A manager the dispatcher started fresh in this mode gets the Mode 1 prompt instead, with the
handoff path under START HERE and the same point 3 under STATE.
