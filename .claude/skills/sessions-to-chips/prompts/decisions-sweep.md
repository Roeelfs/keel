# Decisions sweep (Mode 4 step 3) — one sonnet agent, medium effort

Runs BEFORE any catch-up is sent, so its findings ride the same single message per manager.
Measured 2026-10-24: 48 present / 7 stale / 6 dropped groups; the worst gap was a founder ruling
(model ceiling) recorded in one state file of eight.

Fill `{{DATE}}`, `{{CHECKPOINT}}` (ISO time of the last checkpoint), `{{OUT}}`
(`~/.claude/sessions-to-chips/relay/<date>-sweep-decisions.md`), `{{REPO}}`.

```text
Read-only except the one report file. Goal: check that decisions, rulings, specs and files made on
the OTHER Claude account reached the managers' current state, and find any that were dropped.
Previously made: ~/.claude/sessions-to-chips/handoff/ and maps/ and wrapup/ files since {{CHECKPOINT}},
and the founder-ruling lines in ~/.claude/orchestrator/programs/*.state.md and *.events.jsonl (jq,
never grep conclusions). Current: the {{DATE}} handoffs and every program's state file (note each
file's mtime: a stale one was not updated on this account). Also the specs/ADRs/investigations
created or revised since {{CHECKPOINT}}: `git log origin/main --since=... --stat -- docs/specs
docs/adr docs/investigations` in {{REPO}}, and whether the owning manager's state names each.
Verdict per item: PRESENT, STALE (state contradicts it), DROPPED (in no current manager file).
Read the whole relevant section before judging; a keyword miss is not DROPPED: search by ticket id
AND distinctive terms and print the probe command next to each DROPPED claim.
Look specially for CROSS-CUTTING rulings (model ceiling, tool bans, standing authorizations): they
must be in EVERY program's state, not one. Check ownership claims between state files (two files
naming different owners of one ticket or PR is a finding).
Write {{OUT}} (≤4 KB): only STALE and DROPPED rows with owner program and the one-line fix, then a
PRESENT/STALE/DROPPED count. Own scratch subdirectory only. Return the count line and the top 3.
```

Then fold each row into the owning manager's catch-up as a numbered finding, and every cross-cutting
ruling into every catch-up (the "standing rulings" line in CATCHUP_MESSAGE.md).
