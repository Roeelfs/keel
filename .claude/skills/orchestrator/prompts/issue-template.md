# Issue creation template

Every new issue created during orchestration uses this template. Fill in the bracketed sections, run `gh issue create` with all three label classes attached. (If your team's source-of-truth tracker is not GitHub Issues, create the issue in that tracker instead and keep the GitHub PR backlinked to it — adapt the `gh` commands below to your tracker's CLI/MCP.)

---

## Title format

Lead with a tag in square brackets, then the actual issue:
- `[Hardening] X` — defense-in-depth fixes
- `[Tech Debt] X` — known suboptimal pattern
- `[Test] X` — regression test additions
- `[Reliability] X` — uptime / observability work
- `[Spec D] X` — spec-specific tracking
- `[Docs] X` — documentation work
- `[Epic] X` — large multi-PR work
- `[Umbrella] X` — meta tracker for many child issues

Keep titles under 80 chars. Specifics in the body, not the title.

## `gh` invocation

```bash
gh issue create \
  --title "[Tag] Concise title" \
  --label "bug,priority/p2,effort/s,spec:visual-system" \
  --project "<Your Project Board>" \
  --body "$(cat <<'EOF'
## Background
[What surfaced this — session name, date, context. Why does it matter NOW?]

## Root cause (if known)
[File path + line + behavior. If not known, write "TBD — needs investigation".]

## Acceptance criteria
- [ ] [Concrete deliverable 1]
- [ ] [Concrete deliverable 2]
- [ ] [Test coverage criterion if applicable]

## File refs
- `path/to/file.ts` — what role it plays
- `path/to/test.ts` — existing tests to extend

## Related
- PR #N (the merge that surfaced this)
- Memory: `feedback_X.md`
- Issue #M (related but not duplicate)

## Priority + sizing rationale (optional)
[Why P1 vs P2? Why M effort vs L?]
EOF
)"
```

After creation, set project custom fields. **Read all IDs from the bootstrap cache** — never hardcode:

```bash
CACHE=~/.claude/projects/$(pwd | sed 's|/|-|g')/orchestrator-cache.json
PID=$(jq -r '.project.id' "$CACHE")
PROJECT_NUM=$(jq -r '.project.number' "$CACHE")
PROJECT_OWNER=$(jq -r '.project.owner' "$CACHE")
PRI_FID=$(jq -r '.fields.Priority.id' "$CACHE")
EFF_FID=$(jq -r '.fields.Effort.id' "$CACHE")
DATE_FID=$(jq -r '.fields["Target Date"].id' "$CACHE")
PRI_P1=$(jq -r '.fields.Priority.options.P1' "$CACHE")
EFF_M=$(jq -r '.fields.Effort.options.M' "$CACHE")

# Find the item ID for the issue we just created (replace <N> with issue number):
ITEM_ID=$(gh project item-list "$PROJECT_NUM" --owner "$PROJECT_OWNER" --limit 200 --format json \
  | jq -r --arg n "<N>" '.items[] | select(.content.number == ($n|tonumber)) | .id')

# Apply Priority + Effort + Target Date:
gh project item-edit --id "$ITEM_ID" --field-id "$PRI_FID" --project-id "$PID" --single-select-option-id "$PRI_P1"
gh project item-edit --id "$ITEM_ID" --field-id "$EFF_FID" --project-id "$PID" --single-select-option-id "$EFF_M"
gh project item-edit --id "$ITEM_ID" --field-id "$DATE_FID" --project-id "$PID" --date 2026-05-09
```

If the cache is empty or stale (no `Priority` field, missing options, etc.), run the bootstrap to refresh:

```bash
python3 ~/.claude/skills/orchestrator/bootstrap.py
```

For a brand-new project that doesn't yet have the custom fields or labels, the bootstrap script reports each gap with the `gh` command needed to create it. Run those once, then re-run bootstrap to repopulate the cache.

## Triage rubric

### Priority

- **P0** — production is broken; user-visible breakage; security incident. Drop everything.
- **P1** — current week. Either a real bug that bites users imminently, or a blocker for currently-active spec work.
- **P2** — current month. Tech debt with clear blast radius; reliability improvements; small features that improve developer velocity.
- **P3** — backlog. Nice-to-have; low impact; do when free or never.

### Effort

- **S** (under half day) — 1-3 file change, no tests changing semantics, no infra
- **M** (0.5-2 days) — multi-file feature, new tests, possibly migration
- **L** (2-5 days) — multi-PR or scope spanning multiple components
- **XL** (over a week, multi-PR) — epic, spec-required, infra changes, lockfile churn

### Target Date

- P1 → within 7 days
- P2 → within 30 days
- P3 → no target (or 90+ days if you genuinely intend to do it)

## When NOT to create an issue

- **Single-session debug work** — if you're investigating something and resolve it within the session, don't post-create an issue. The PR and Session-Id trailer cover it.
- **In-progress patterns being captured** — these belong in memory, not issues. Memory is for conventions/preferences; issues are for work.
- **Decisions to discuss with the user** — those are session messages, not issues.

## When you MUST create an issue

- A bug surfaces but you decide to fix later
- A spec drafts a multi-PR plan with deferred phases
- A test gap is identified that needs adding
- A dependency change is queued for a future window
- A tooling bug is found (in skill, in CLI, in CI) that's outside scope
- An external tracking signal arrives (a tracker ticket, chat thread, customer report) that maps to repo work
