# The spec → review → test flow

keel's three big skills form a pipeline: write a spec, review it with a panel of
models, then plan and execute real tests against the implementation. The throughline
is **judging work against intent, by independent perspectives, with evidence** —
the three things a single agent reviewing its own output cannot give you.

## spec-review — a panel, not a mirror

[`.claude/skills/spec-review/`](../.claude/skills/spec-review/)

A long session that produces a spec accumulates blind spots: the author (human or
model) is too close to it. `spec-review` breaks that with a linear, no-compaction
flow:

1. **Mine the session's decisions.** `claude-sessions` turns the transcript that
   produced the spec into structured JSON — user-turn windows, files edited,
   commits, rejected alternatives. A dossier agent distills it. Now reviewers can
   check the spec against what you actually *decided*, not just what got written
   down. (Skippable if the spec arrived from elsewhere.)

2. **Dispatch nine reviewers in parallel**, each with one job:

   | Lane | Model | Job |
   |------|-------|-----|
   | Completeness | Claude (Opus) | Does the spec honor the mined decisions and corrections? |
   | Codebase verifier | Claude (Sonnet, Explore) | Do referenced files exist? Duplicates? Stale code? |
   | Architecture auditor | Claude (Opus) | Fit, simplicity, abstraction level, maintenance cost |
   | Edge-case miner | Claude (Opus) | Semantic boundary enumeration — cardinality, lifecycle, tenancy, encoding, time, concurrency, permission, resource, schema-evolution, forbidden-but-valid |
   | Security miner | Claude (Opus) | Audits against **your** `docs/security-policy.md` + portable categories; cites the rule each finding violates |
   | Spec-drift scout | Claude (Sonnet) | Scans sibling worktrees/specs/recent pushes for parallel work that conflicts |
   | Codex standard | GPT-class (web) | Completeness/feasibility, API claims checked against primary sources |
   | Codex adversarial | GPT-class (web) | Attack surface, race conditions, rollback safety, cross-referenced to real CVEs/post-mortems |
   | Codex research auditor | GPT-class (web) | *Elevation, not defects* — OSS libraries and big-company patterns that already solve this, with URLs |

3. **Cross-examine genuine disagreements.** When Claude and Codex disagree on a
   MAJOR+ finding, the coordinator feeds each model the other's argument (up to two
   rounds) and presents both positions to *you* — it never silently picks a winner.

4. **Report, then fix the prose only.** Findings go in a report (consensus issues,
   model-only findings, edge cases, security, drift, industry insights). Only real
   design defects get written back into the spec — as corrected *prose*, never as
   review scaffolding (no traceability matrices or "EC-N" tables bolted onto your
   spec).

The security miner is the part you customize: it reads *your* policy file and cites
it, so the audit is grounded in your system's actual rules rather than generic
hygiene. See [`templates/security-policy.example.md`](../templates/security-policy.example.md).

## spec-test-plan — E2E-first, no theatre

[`.claude/skills/spec-test-plan/`](../.claude/skills/spec-test-plan/)

Generates a lean test plan whose **spine is real staging verification**: for each
way a customer experiences the feature, what they trigger, what the system should
produce, and *how you'd observe success on real staging* — which UI surface, which
log line, which data result. Unit/integration tests are added only where they're
cheap and catch a regression the E2E path wouldn't surface.

It reads `docs/testing-config.md` to know your actual commands, staging URLs, and
test accounts — so the plan references real selectors and real log strings, not
placeholders. Things that genuinely need human setup (third-party creds, hardware)
are flagged as blocking dependencies; deploying to staging is **not** one of them.

## spec-test-execute — run it, triage failures, loop

[`.claude/skills/spec-test-execute/`](../.claude/skills/spec-test-execute/)

Executes the plan tier by tier, marking each test PASS / FAIL / SKIP / BLOCKED in
the plan file. On failures it fans out **parallel failure-diagnostician agents**,
escalates genuinely-stuck tests to a deeper rescue pass, and loops (bounded) until
the plan is green or honestly blocked. The deliverable is a real, evidence-backed
verification — "I deployed it, ran it as a customer would, here's the log line that
proves it worked" — not a green checkmark with nothing behind it.

## How they share a vocabulary

All three skills normalize findings to one **severity taxonomy** (CRITICAL / MAJOR /
MINOR) so a Codex "high" and a Claude "MAJOR" mean the same thing across the
pipeline, and so what blocks a ship is unambiguous.
