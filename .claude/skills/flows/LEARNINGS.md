# LEARNINGS — flows

This is the skill's running memory. Read it at task start; append a dated bullet
per non-trivial finding at task end. Prune vague entries and promote recurring
ones (≥3 occurrences) into SKILL.md.

Keep entries specific (cite the bug class + the evidence pattern that caught it),
but **portable** — describe the reusable lesson, not a one-off codebase detail.
Soft cap ~100 lines.

The entries below are the portable patterns distilled from many runs of this skill
across different stacks. They are starting wisdom, not project-specific. An adopter's
accumulated, project-specific findings live in the private overlay if present:
`~/.claude/skills-overlay/flows/LEARNINGS.md` (never in this public repo).

---

## What Worked

- **Flat JSON over a database.** The LLM reads and writes the registry directly; no
  script, no embeddings, no migration tooling needed. Simpler beat sophisticated —
  an initial database design was over-engineered and required scripts just to enforce
  invariants the model can check inline.
- **Step-level `notes` + `requires`.** Protocol details (e.g. "wait for the AI message
  event, not the step-change event") and env-var requirements belong on the step, not
  the flow. This prevents rediscovery when journeys compose primitives.
- **Treat gotchas as blocking operational knowledge, not optional commentary.** Framing
  gotchas to agents as "protocol instructions" during test-plan generation dramatically
  reduces test failures from already-known causes.
- **Variants concept** — same flow × different tenant/fixture/env configs. Forces
  fallback-branch testing and surfaces the "flow verified only in happy-path org"
  anti-pattern.
- **Aggregate release-verification flow.** When a multi-lane release finishes, create or
  update a single journey that composes the primitives (deploy, backend suite evidence,
  browser E2E, mobile/smoke, ledger/marker audit) and records gotchas + step notes
  before declaring READY. Without it, every session rediscovers the same timing,
  cleanup, and "no tests found" semantics.

## What Failed

- **Flows with ONE variant hide fallback bugs.** A journey that exercised only the
  happy-path org shipped a broken fallback branch. Fix: track per-variant run history,
  not per-flow — a flow is "verified" only when every variant has a recent run.
- **Gotchas without pruning become a noise pile.** Registries have grown to 30+ stale
  gotchas. Fix: a `still_relevant: false` flag + periodic audit + migration to step
  notes when a gotcha is high-confidence.
- **Inferring journey verification from primitive tests.** Backend unit/integration
  tests can prove individual lifecycle pieces while every related registry flow still
  has `runs: []`. Report "code path implemented" separately from "journey verified" —
  never infer the composed end-to-end proof from primitive tests alone.
- **Scoring a partial run as a pass.** When part of a journey is driven by the real UI
  but the remainder is finished via the backend API, record the run as `partial` (with
  the real IDs for both halves), not `pass` — so the remaining blocker stays scoped to
  the un-exercised last mile.

## Patterns

- **Journey = composition of primitives via `ref`.** Primitive = reusable unit (login,
  deploy, OTP). Don't inline what should be a ref.
- **Run history max 20** — oldest drops first. Prevents unbounded growth.
- **Per-variant run tracking:** a flow is "verified" only when every variant has a
  recent run. Stale variants = untested branches.
- **Gotcha → step-note migration** high-confidence only. Ambiguous gotchas stay
  flow-level. Migration is semantic and goes through the approval gate in
  spec-test-execute Step 5.5.
- **Invariants enforced on every write:** valid JSON, unique IDs, type-unchanged,
  product-constraint, step XOR action, ref targets exist + active, no cycles. Re-read
  after write.
- **Validate the registry against the project's schema after editing**, if the project
  ships a flow-schema validator. Composite/multi surfaces are often permitted while
  persona/category/runner are restricted to fixed enums — record backend-only proof as
  a `runs[].status=partial` entry rather than marking the whole journey passed before
  the missing evidence exists.

## Open Questions

- When to create a new flow vs add a variant to an existing one? Heuristic: different
  preconditions or forced-branch = variant; different user journey = new flow. Not
  always clear (e.g. "login with OAuth" vs "login with password" — variant of login or
  separate flows?).
- Gotcha → step-note migration criteria (high-confidence only) — what's the test?
  Currently judgment. Could codify but risks rigidity.
- Cross-project flow patterns — should common primitives (login, deploy, upload) have a
  shared template, or does each project own its own? Currently each project owns.
- How does the flow registry interact with the per-skill LEARNINGS.md? Flows are
  per-project runtime state; LEARNINGS is cross-project procedural. Clean split but
  overlap is possible on "flow design patterns."
