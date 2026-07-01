---
name: spec-test-plan
description: Generate a lean, E2E-first test plan from a spec. The spine is real staging verification — deploy, run the actual feature/automation the way a customer would, read the logs, confirm customer-facing output. Unit/integration tests only where they're cheap and catch real regressions. No shortcuts, no smoke-test theatre.
---

# Spec Test Plan — E2E / Real-Staging First

Produces a test plan whose center of gravity is **proving the feature works in real staging the way a customer experiences it** — not a pyramid of unit tests. The question every plan must answer: *if we deployed this to a customer right now, what would they do, and how do we confirm it actually worked end-to-end?*

**Trigger:** "generate test plan", "test plan for this spec", "testing plan".

## Skill Memory (LEARNINGS)

**Before starting:** Read `LEARNINGS.md` in this skill directory (curated seed) + the private overlay if present (`~/.claude/skills-overlay/spec-test-plan/LEARNINGS.md`).

**Before ending — route each learning by scope; NEVER append to this repo's committed `LEARNINGS.md`** (full routing: [`docs/skill-memory.md`](../../../docs/skill-memory.md)): operator-private skill craft → the overlay (create if absent); project-specific facts → the project's `.claude/memory/`; universal craft → note it for `/improve-harness` to promote (de-identified) into the seed via PR.

## Principles (read first)

1. **E2E on real staging is the spine, not the tip.** The plan leads with: deploy to staging → run the real feature/automation as a customer would → read the actual logs → confirm the actual customer-facing output. Unit and integration tests are supporting cast — include them only where they're cheap and catch a regression a human would otherwise miss.
2. **No shortcuts.** A curl against `/health` is not a test. Mocking the thing under test is not a test. "Tests pass locally" is not staging verification. The plan must exercise the real deployed path on real infrastructure with real data flow.
3. **Understand the system, then test the customer's experience.** Before writing rows, state in 3-5 lines what this feature *is* from the customer's seat and what "working" looks like to them. Every E2E scenario maps to that.
4. **Lean.** No blast-radius checklists, no state-mutation matrices, no spec-patch feedback commits, no tier taxonomy for its own sake. If a section doesn't help someone verify the feature works, cut it.

## Flow

### 1. Read the spec + the project's test reality

- Read the spec fully.
- Read `testing/config.md` (project root) if it exists — this is the source of truth for **how to run real tests here**: staging URLs, deploy command, test accounts, E2E runners, how to run an automation, where logs live, known limitations. If it's missing, infer from the codebase and tell the user to create one.
- Read `testing/flows.json` if it exists — accumulated E2E flow knowledge and gotchas from past cycles. Treat gotchas as blocking operational knowledge (e.g. "wait for `ai_message`, not `step_change`"). Reuse existing flows; don't reinvent them.

Write the 3-5 line "what the customer does / what working looks like" summary now.

### 2. Extract the customer-facing surfaces (one focused pass)

Dispatch **one** agent (`Agent`, `subagent_type: general-purpose`, model `opus`) with the spec + flow context:

> Read `<spec-path>` and this flow context. List every way a customer (or the customer's data flowing through the system) experiences this feature end-to-end. For each: what the customer does/triggers, what the system should produce, how you'd observe success on real staging (which UI surface, which log line, which DB/automation result, which channel message). Then list the smallest set of unit/integration tests that catch a real regression the E2E path wouldn't obviously surface. Be concrete — real selectors, real log strings, real commands, real test org (your project's test org, e.g. `acme-e2e`). Flag anything that genuinely needs human setup (third-party dashboard creds, hardware) as a blocking dependency. Deploying to staging is NOT a blocking dependency.

Wait for it.

### 3. Write the plan

**Output file:** `<spec-dir>/<spec-name>-test-plan.md`. Structure:

```markdown
# Test Plan: <title>

## What working looks like (customer's seat)
<3-5 lines — the feature from the customer's perspective and the definition of "done">

## Blocking dependencies
<only things requiring human action outside the agent — creds, hardware. "Deploy to staging" is NOT one.>

## Prerequisites
<test org, accounts, env vars/flags, fixtures, flow `requires`. Mark staging deploy steps "(auto-resolvable by spec-test-execute)">

## E2E on staging (the spine)
| ID | Customer action / trigger | How to run it | Observable success signal | Status |
|----|---------------------------|---------------|---------------------------|--------|
| E2E-1 | <what the customer does> | <exact command / browser steps / automation run> | <exact UI text / log line / DB row / channel message to confirm> | PENDING |

For each E2E row, specify:
- The real runner (Playwright on staging URL, Chrome extension for auth/visual, or the platform's automation runner).
- **How to read the logs** — exact log group / structured-log query / dashboard page — and what a healthy vs failed run looks like there. Reading logs is part of the test, not optional.
- Tenant/org variants if behavior differs by org.

## Integration tests (only where they earn their place)
| ID | What it covers | Why E2E won't catch it | Status |

## Unit tests (cheap regression guards only)
| ID | What it covers | Status |

## Verification commands
<exact commands to run each tier, including the staging deploy + health-confirm sequence>
```

Rules for the rows:
- **Specific, not generic** — exact selectors, exact assertions, exact log strings, exact commands.
- Every E2E scenario names its success signal in something a customer or operator would actually see (rendered output, a channel reply, a portal value, a real log line) — never just "200 OK".
- Don't pad the unit/integration tables. If the E2E path already proves it, don't duplicate it.

### 4. Commit

```bash
git add <test-plan-file>
git commit -m "test(<scope>): E2E-first test plan for <spec-name>"
```

### 5. Optional Codex coverage check (only for risky specs)

For auth / money / data-migration / deletion specs, dispatch one Codex pass (Bash, `run_in_background: true`, no `&`) to find E2E gaps:

```bash
cd <PROJECT_ROOT> && echo '' | codex exec --skip-git-repo-check \
  -m gpt-5.5 --config model_reasoning_effort="high" --config service_tier="fast" \
  --sandbox read-only --full-auto \
  "Read the test plan at <RELATIVE_TEST_PLAN_PATH> and spec at <RELATIVE_SPEC_PATH>. Focus on the E2E-on-staging section. What customer-facing failure modes would these scenarios miss in real staging — env/infra divergence, multi-step chain breaks, format/encoding at boundaries, deploy-time drift, observability gaps where a failure would look like a success? List each: failure scenario, the staging E2E test to add, how to observe it failing. Max 12. Skip unit-test nitpicks." \
  2>&1 | tee /tmp/codex-cov-$$.txt
```

Read the output, add the real E2E gaps to the spine, re-commit. Skip this step entirely for low-risk specs.

## When NOT to use
- Trivial specs (<50 lines) — a short manual E2E checklist in the PR is enough.
- Specs with no customer-facing change — a couple of integration tests, skip the E2E spine.
