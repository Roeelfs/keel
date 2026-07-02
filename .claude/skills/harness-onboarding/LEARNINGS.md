# LEARNINGS — harness-onboarding

This is the skill's running memory. Read it at task start. This committed copy is a
read-only curated seed — route per-run learnings per `docs/skill-memory.md` (overlay
for operator-private craft, project memory for machine specifics); recurring,
de-identified lessons get promoted here via `/improve-harness` PRs only.

The entries below are portable starting wisdom, not machine-specific.

---

## Patterns

### Copies drift silently; symlinks can't
- Observed on a working machine: one skill root held **21 stale real copies** left by
  an earlier snapshot installer, weeks behind the canonical clone — while the other
  root (symlinked) was always current. Nobody noticed because nothing errors: the
  stale runtime just follows old instructions. The fix is structural, not procedural
  — replace every machine-wide copy with a symlink so drift becomes impossible,
  rather than adding a "remember to re-run the installer" rule.

### Enumerate ALL skill roots before claiming converged
- Every runtime has its own root (`~/.claude/skills`, `~/.agents/skills`, others),
  and the cross-runtime ones are the ones audits forget. A convergence claim that
  checked only the root you use daily is exactly how the 21-copy drift above
  survived. Sweep them all, plus per-repo `.claude/skills/` dirs — a repo-local copy
  SHADOWS the global skill in that repo.

### Never blind-overwrite a diverged copy
- A real-copy that differs from the clone may contain the user's own improvements or
  private content. Diff first; give every delta a home (merge-back PR, overlay, or
  confirmed drop) before the copy becomes a symlink. Overwriting first and asking
  later destroys exactly the local knowledge onboarding is supposed to preserve.

### Know the load semantics before promising "it's applied"
- Skills load at **invocation time** — a symlinked skill edit applies to already-
  running sessions on their next use. Instructions files (`CLAUDE.md`/`AGENTS.md`)
  load at **session start** — running sessions keep the old contract until restart.
  Plugins typically need an app restart. State which class a change falls in when
  reporting "applied everywhere".

## Open Questions

- (none yet — append as onboarding runs surface them)
