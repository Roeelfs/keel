# Worktree sweep (Mode 4 step 3) — one sonnet agent, medium effort

Complements `handoff_sweep.py`, which only sees worktrees of sessions it can attribute to a
manager. This one walks `git worktree list` itself, so work whose session is archived or unowned
shows up. Measured 2026-10-24: 10 at-risk worktrees/branches (a 19-commit unpushed stack, a 59-file
dirty tree under an open PR) plus 13 local-only branches, none named in any handoff.

Fill `{{CHECKPOINT}}`, `{{OUT}}` (`~/.claude/sessions-to-chips/relay/<date>-sweep-worktrees.md`),
`{{REPOS}}` (every repo a program touches, e.g. the monorepo plus any side repos), `{{KNOWN}}`
(issues already handled: skip them unless their state changed).

```text
Read-only except the one report file. Find worktrees, branches and local files left over from
sessions on the OTHER Claude account that no live manager owns, or that hold unpushed/dirty work.
Repos: {{REPOS}}. Use `git worktree list --porcelain` (never guess paths). For every worktree whose
branch/session was active since {{CHECKPOINT}}: `git -C <wt> status --porcelain`, `git -C <wt> log
@{u}..` (vs origin/main when no upstream), `gh pr list --head <branch> --state all --json
number,state,mergedAt`. Map worktree/branch to a session with the session stores (both accounts)
and `list_sessions.py`; say whether each owner is a running child, an archived session, or none.
Also list branches whose commits are on no remote and unmerged (upstream gone or empty), newer than
{{CHECKPOINT}}; for each run `git cherry origin/main <branch>` (a squash-merged one under another
head is debris). Skip: {{KNOWN}}. ~85 no-upstream branches with a MERGED PR are noise: exclude.
Note debris separately (untracked scratch under a merged PR, `.codex/worktrees` registrations
pointing at missing dirs needing `git worktree prune`).
Write {{OUT}} (≤4 KB): a table of ONLY at-risk items (path, branch, facts with command output,
inferred owner program and whether that owner is a running child, what to do), then the debris
list. Own scratch subdirectory only. Return the at-risk count and the top 3.
```

Routing rule for the findings: the worktree of a RUNNING child is pushed by that child at its next
checkpoint (never add a second writer under it); an unowned or archived-owner worktree is salvaged
by the manager that owns the ticket, with `git status --porcelain` first and one branch push.
