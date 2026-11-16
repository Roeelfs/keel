# Worktree sweep (Resume / mine, plan phase 2) — one sonnet agent, medium effort

Complements `handoff_sweep.py`, which only sees worktrees of sessions it can attribute to a
manager. `mine_all.py` fills the inputs in its plan step `worktree-sweep` (`{{KNOWN}}` is the
`handoff_sweep.py` output it already ran). This one walks `git worktree list` itself, so work whose session is archived or unowned
shows up. Measured 2026-10-24: 10 at-risk worktrees/branches (a 19-commit unpushed stack, a 59-file
dirty tree under an open PR) plus 13 local-only branches, none named in any handoff.

Fill `{{CHECKPOINT}}`, `{{OUT}}` (`~/.claude/sessions-to-chips/relay/<date>-sweep-worktrees.md`),
`{{REPOS}}` (every repo a program touches, e.g. the monorepo plus any side repos), `{{KNOWN}}`
(issues already handled: skip them unless their state changed).

```text
Read-only except the one report file. Find worktrees, branches and local files left over from
sessions on the OTHER Claude account that no live manager owns, or that hold unpushed/dirty work.
Repos: {{REPOS}}. For each repo run `python3 -I <skill>/scripts/handoff_sweep.py --repo <repo>
--since {{CHECKPOINT}}` (JSON out): it walks `git worktree list --porcelain` and every local branch
with no worktree, and gives each row a content-based `landed` verdict (merged PR head, merge-tree,
cherry) plus its owner session. Never re-derive that verdict by hand with `git log` or
`git cherry`: ancestry calls a squash-merged branch unpushed. Report a row only when `atRisk` is
true. For each, say whether the owner is a running child, an archived session, or none (session
stores of both accounts, `list_sessions.py`). Skip: {{KNOWN}}.
Note debris separately (untracked scratch under a merged PR, `.codex/worktrees` registrations
pointing at missing dirs needing `git worktree prune`).
Write {{OUT}} (≤4 KB): a table of ONLY at-risk items (path, branch, facts with command output,
inferred owner program and whether that owner is a running child, what to do), then the debris
list. Own scratch subdirectory only. Return the at-risk count and the top 3.
```

Routing rule for the findings: the worktree of a RUNNING child is pushed by that child at its next
checkpoint (never add a second writer under it); an unowned or archived-owner worktree is salvaged
by the manager that owns the ticket, with `git status --porcelain` first and one branch push.
