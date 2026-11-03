# Harness program 2026-11-03 (improve-harness, scoped run: steps 1-3)

Scoped run: lanes A, B, E, G ran as read-only native subagents; F (falsifier) ran as one native
sonnet subagent over all items, **not** a Workflow, so there is no Workflow F run id and the
step-3 criterion is only partly met. Skipped: C (quarterly), D (no incident cluster known),
steps 4, 5 and 4f (nothing mutated). The program lives here, not in
`~/.claude/analytics/harness-improvement/`, until the founder approves writing to that repo.
Lane reports (session scratchpad, not persisted): `laneA|B|E|G|F/report.md`. Lane E and G
reports are stubs on disk; their content exists only in their hand-back messages, so the
falsifier could not check their raw claims.

## Cross-cutting finding
Desktop runs claude-code **2.1.309** (58 processes, `ps`), not the CLI's 2.1.317. Lane B's
2.1.316/2.1.317 deltas do not apply to Desktop sessions (P12, SubagentStop double-fire fix,
idle-compaction watch). `~/.claude/CLAUDE.md` is exactly 35,943 B, the ratchet limit in
`check-overlay-size.sh`, so any edit must be byte-neutral or raise the recorded value.

## Verdicts

| ID | Item | Verdict | Class |
|---|---|---|---|
| P1 | Commit form: `--trailer "Session-Id: $CLAUDE_SESSION_ID"` is refused by the native worktree guard (152 denied, 0 succeeded; literal id succeeded 95). Emit the literal id in SessionStart `additionalContext` **only in a linked worktree**; also change `hooks/bash-advisories.py:147`; say "plain, separate command". | SURVIVES+refine | founder (CLAUDE.md reword) |
| P2 | `serialize-heavy-ops`: wrap only `heavy \| tail/head`; never `cynap-sandbox verify` (exit masking, `verify-command-safety.sh:60-72`); change heredoc deny text only; fix in keel, gate on `replay-corpus.py --baseline`. | REFINE | founder (keel hook + install) |
| P3 | Prune `~/.claude/CLAUDE.md` (35,943 B vs 24,000 target); operator carve-out line 71 moves only if `operator-workspace-context.sh` also states it; "fable retired" is at 118 and 136, not x3. Update ratchet value. | REFINE | founder (protected file) |
| P4 | keel `AGENTS.md:31` "1 PR in its lifetime" is stale (#1-#4 exist). | SURVIVES | safe-auto |
| P5 | Unblock-card enforce: keep shadow. Needs the 30-consecutive-row hand-read (>=21 genuine, `unblock-card.py:29-33`); 7-row sample ~3/7 does not meet it; newest rows are self-referential. | REFINE | founder |
| P6 | Log-only SubagentStop / PreCompact / PostCompact hooks; dedupe by `agent_id` (Desktop 2.1.309 double-fires); never injecting (2026-09-08 note: +23,784 B). | REFINE | founder (settings.json) |
| P7 | Codex 0.163.0 -> 0.166.0 with trusted_hash + dispatch-test gates; probe memory v2 default. | SURVIVES | needs go |
| P8 | Codex config drift: `~/.codex/config.toml` gpt-6.1-sol xhigh vs 10-20 ruling medium; `.codex-lean` gpt-6-sol. Interactive only (dispatch passes `-m`/effort). | REFINE | founder |
| P9 | Rewrite opus subagents to sonnet. | **KILLED**: contradicts 11-01 policy; opus share rising is the policy working; gate already enforces Role/reason. | n/a |
| P10 | Session turn cap ~1000. | **KILLED**: habit with no mechanism; an injecting hook repeats 2026-09-08. | n/a |
| P11 | Desktop floor 126-132k: A/B only on Desktop; part of the 45k gap vs sdk-cli is uncontrollable. | REFINE | founder |
| P12 | `autoCompactWindow` on sonnet agents. | **KILLED for Desktop** (2.1.309 ignores it); re-propose once Desktop >= 2.1.316. | n/a |
| P13 | figma/supabase/cowork skills resident though disabled (`@synced`, two account dirs `809737ac…`, `aed0b02d…`). Root cause unverified; probe with a fresh Desktop session. | REFINE | safe-auto probe |
| P14 | Prune 0-use skills: shrinks to copywriting + copy-editing (pair), content-strategy, langfuse (edit `docs/vendor-upstreams.md` too), work-report, flows, harness-onboarding. Keep tdd, resolving-merge-conflicts, diagnosing-bugs, spec-visualization, standards-spec-review, triage (referenced). Run the parent probe per skill first. | REFINE | founder |
| P15 | workflow-wake: staging owner moved; re-enroll or unload. Plist PATH also names stale Claude 2.1.295. | SURVIVES | founder |
| P16 | `worktree-reaper.sh` +76 uncommitted, no owner (confirmed); 178 worktrees / 277 memory-sync paths unconfirmed. | PARTIAL | founder |
| P17 | Retire dead reply-shape metrics; verify the TRENDS file name first (none in `analytics/harness-improvement/`). | SURVIVES | safe-auto |
| P18 | Kill `analytics/plugin-drift.jsonl` item; `bashOutputMaxChars` is a real key (4 binary hits), kill is prioritisation only. | REFINE | safe-auto |

## SKIP_OR_WATCH
SKIP: Supabase hint hook (execute_sql failure 2%); classifier-repeat hook (3/314 sessions); poll-loop guard; Codex sleep (0.75%); `onFailure:"block"` (SDK only); `CLAUDE_CODE_DISABLE_NESTED_SESSION_ID`; fast mode Opus 4.8; Sonnet 4.5 retirement (no hard ids); fork subagents.
WATCH: Read-stub removal 2.1.317 (tool-result bytes); Monitor-started commands bypass the `updatedInput` rewrite in `serialize-heavy-ops`; `sed -i` allow-list (2.1.310); GPT-6.1 Terra routing; reply-volume drift median 629 -> 808; Desktop idle compaction (2.1.314, unconfirmed).

## DID_NOT_SURVIVE
P9, P10, P12 (probes above). Model-why regex-salvage (2 denials after `dca5ebf`). `DISABLE_MICROCOMPACT` is a dead var (0 hits in 2.1.317 and 2.1.309) though set in the live env, origin untraced.

## OPEN (each re-derivable)
- 10-19 items P5.14, P5.15, P4.6, P5.2b, P6.2, P6.6, P6.8, P7.1-3: no landing commit (`git -C ~/.claude log --since=2026-10-19 --format=%s`); re-sequence or drop.
- #4503 bake UNPROVEN. 450k subagent compaction criterion UNPROVEN, 3rd cycle: kill next run if P6 not shipped.
- 11-01 manager-sonnet policy: grade 2026-11-10+ with >=7 post days (3 days so far, main ctx sonnet share 77% vs 45.5%).
- Lane E metrics vs 10-19: ctx/day +17% main, +29% all-Claude; per-turn flat (avg 240.9k); compaction null control 417k held (416.2k, n=209); max session turns 2,529 vs <=1,200 target FAILED; Desktop floor 126-132k vs <=118k FAILED.
- Lane G: gate-carrier 92%, relay_when 2.8% (target <=2%), unblock-card shadow criterion 1 met (4.3% would-fire), criterion 2 owed.
