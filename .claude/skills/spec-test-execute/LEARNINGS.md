# LEARNINGS — spec-test-execute

This is the skill's running memory. Read it at task start; append a dated bullet
per non-trivial finding at task end. Prune vague entries and promote recurring
ones (≥3 occurrences) into SKILL.md. Soft cap ~100 lines.

Keep entries **portable** — cite the bug *class* and the evidence pattern that
caught it, never a one-off identifier from a specific codebase (no real table /
RPC / env-var / endpoint names). The seed entries below are de-identified
patterns that recur across stacks. They are starting wisdom, not project-specific.

---

## What Worked

- **Mechanical staging auto-deploy beats "attempt to deploy".** Push to the staging
  ref → poll the CI run → health-check with backoff. Concrete steps unblock E2E
  without a manual hand-off; vague instructions burn minutes and then give up.
- **Monitor a long model-rescue pass by *liveness*, not a wall-clock timer.**
  Process-alive + output-still-growing checks let a legitimate 30–45 min fix finish;
  a hard SIGTERM kills it mid-edit and leaves the tree worse than before.
- **Assertion-strength audit catches weak greens.** A test that asserts "returns
  200" but not the behavior is a GAP, not a PASS. Re-classify shape-only assertions.
- **No free SKIPs.** Require a fallback attempt before accepting SKIP/BLOCKED — many
  "can't run in this env" skips have a viable local fallback (e.g. a throwaway local
  instance of the prod database engine) that converts them to real PASSes.

## What Failed

- **`No tests found` is a result, not a pass.** A grep that matches zero tests must
  become a GAP or a named deferral with an owner and rationale — never get hidden in
  a green summary.
- **A single-run canary passes while concurrency bugs are live.** One request sees no
  concurrent load, no upstream 5xx, no cache expiry. A canary is necessary, not
  sufficient — the deploy tier still needs chaos-level probes.
- **Verify every admission/guard surface, including DB-level ones.** An app-layer
  resolver filtered out stale rows, but a database-level routine still admitted them
  — runtime evidence beat code-only review. For admission control, check every
  surface (including stored procedures / RPCs), not just the application layer.
- **Probe each data touch-point after a migration; don't assume inheritance.** A
  migration updated one table's column but per-row records in a related table didn't
  inherit the change, so a deployed read path rejected valid input. Probe each column
  the migration claims to cover.

## Patterns (promoted — apply on every relevant run)

- **One tier at a time.** Don't start Tier N+1 until Tier N is resolved — prevents
  noise from cascading failures across tiers.
- **The plan file is the ledger.** Update each test's status immediately after it
  runs, not in a batch — resumability depends on it.
- **E2E never gates on deployment.** Always attempt; deploy if needed; mark BLOCKED
  only for tests genuinely impossible in the environment.
- **Per-tier regression sweep after individual fixes** — cheap insurance against one
  test's fix breaking another in the same tier.
- **When staging E2E depends on named accounts/fixtures, verify domain readiness
  first.** A missing UI element is often a fixture-not-ready problem, not a product
  failure — probe the account/data preconditions before classifying the row.
- **N-strike threshold before escalating to a heavier rescue model.** Loop the
  lighter diagnostician a bounded number of times first; escalate too early and you
  waste tokens, too late and you waste wall-clock.

## Open Questions

- (append uncertainties here as runs surface them)
