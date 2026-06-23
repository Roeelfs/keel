# LEARNINGS — spec-test-plan

This is the skill's running memory. Read it at task start; append a dated bullet
per non-trivial finding at task end. Prune vague entries and promote recurring
ones (≥3 occurrences) into SKILL.md. Soft cap ~100 lines.

Keep entries **portable** — cite the bug *class* and the evidence pattern that
caught it, never a one-off identifier from a specific codebase (no real table /
RPC / env-var / endpoint names). The seed entries below are de-identified
patterns that recur across stacks (web apps, payment integrations, async/worker
systems, multi-tenant services, infra migrations). They are starting wisdom, not
project-specific.

---

## What Worked

- **Run the coverage reviewers AFTER the plan is drafted.** Reviewers that read
  the spec *through the lens of the test plan* find spec semantic bugs that tests
  alone never surface — they compare plan assertions against spec claims with cold
  eyes. This pass is not optional.
- **The deploy tier must be chaos-level, not a 200-OK smoke test.** 200-OK probes
  pass while concurrent races, permission/IAM propagation lag, env-var drift, and
  real object-storage signed-URL paths all fail in prod. Exercise the real path.
- **Any scheduled/async job needs a deploy row that probes the *actual* invocation
  with the production identity** — not an HTTP smoke test. A job can be unschedulable
  or lack invoke permission and silently never run despite green local tests.
- **Webhook/subscription specs: assert the subscribed event *set* equals the spec
  set,** not just that the endpoint URL is registered. Happy-path 5 events register;
  the other events fire and silently drop.
- **Plumbing trace every mutation through ALL consumers.** For each callback /
  serializer / downstream reader, enumerate every terminal path that should fire it.
  Unit tests validate the wiring exists; integration tests validate it fires in
  *each* path — a real integration helper wired into only some completion paths is a
  classic silent drop.

## What Failed

- **A single happy-path test tenant masks fallback bugs.** A feature shipped broken
  because every E2E ran against the one tenant that had the primary configuration
  row, so the fallback branch never fired. Require ≥1 tenant variant per fallback
  branch.
- **Coverage count without adversarial depth = false confidence.** A structurally
  "green" plan can still ship many prod bugs. Count of rows is not depth of
  coverage; the adversarial/blast-radius pass is the gate against this.
- **JSON templates in model prompts get echoed back as fake findings.** Use prose
  structure + minimum-count requirements, never fill-in-the-blank templates.

## Patterns (promoted — apply on every relevant run)

- **Two-phase writes:** any flag that drives async behavior must declare write-order
  (commit the flag BEFORE the async invoke, or after) and the test must verify it —
  otherwise the consumer reads a stale value.
- **Multi-tenant aggregate rules become per-surface matrices.** "X is tenant-scoped"
  must be enumerated per tool/endpoint (same-tenant succeeds / wrong-tenant denied /
  zero side effects), not asserted once.
- **Runtime-parity probes:** storage backend, connection pooling, permission model,
  dependency-version features — each needs a deploy-tier test on the real prod path,
  not a local mock.
- **Stub detection:** for every `TODO` / not-implemented / placeholder return, the
  plan needs a test that fails if the stub is still present at ship.
- **Strong model on surface extraction is load-bearing** whenever the spec touches
  multi-tenant state or cross-cutting invariants — a lighter model under-extracts.

## Open Questions

- (append uncertainties here as runs surface them)
