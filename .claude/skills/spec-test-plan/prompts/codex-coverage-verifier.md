# Codex Coverage Verifier (file-review mode)

Cross-references the test plan against the spec to find gaps. Two parallel `codex exec` runs. Never use `companion review`.

Both agents read the spec + test plan and probe SPECIFIC risk classes — not generic
"find gaps". The risk classes are derived from real production bugs that shipped
despite "PASS" test plans (sandbox-lifecycle and prod-reliability audits). Each bug
class represents a category the standard test plan consistently misses.

## Agent A — Standard Coverage

Verifies every spec requirement has a test and assertions are load-bearing.

Use Bash with `run_in_background: true` (no trailing `&`):

```bash
cd <PROJECT_ROOT> && echo '' | codex exec --skip-git-repo-check \
  -m gpt-5.6-sol \
  --config model_reasoning_effort="high" \
  --config service_tier="fast" \
  --sandbox read-only \
  --full-auto \
  "Read the test plan at <RELATIVE_TEST_PLAN_PATH> and the spec at <RELATIVE_SPEC_PATH>.

For every spec requirement, verify:
1. At least one test row covers it.
2. The assertion is strong enough to catch regressions (not just 'returns 200').
3. Error paths and edge cases mentioned in the spec have tests.
4. Every callback, hook, or onSuccess handler is tested in ALL terminal paths, not just the primary one.
5. Every stub or 'placeholder' or 'TODO' in the spec has a test that would fail if the stub is still present.
6. Every state-mutation flag has a test verifying the correct write-order (e.g., flag set BEFORE async invoke).

Report uncovered requirements, weak assertions, over-tested areas, and untested consumers of mutations. Be specific — cite spec section and test row by name." \
  2>&1 | tee /tmp/codex-cov-std-$$.txt
```

## Agent B — Adversarial Coverage

Probes the 7 systemic gaps that ship bugs to prod despite a green test plan.

Separate Bash call, also `run_in_background: true`:

```bash
cd <PROJECT_ROOT> && echo '' | codex exec --skip-git-repo-check \
  -m gpt-5.6-sol \
  --config model_reasoning_effort="high" \
  --config service_tier="fast" \
  --sandbox read-only \
  --full-auto \
  "Read the test plan at <RELATIVE_TEST_PLAN_PATH> and the spec at <RELATIVE_SPEC_PATH>. Also read enough of the codebase to ground your analysis in real infrastructure (settings, deployment manifests, requirements pins, storage config).

Probe each gap class below. For each gap, propose a specific test with tier and priority.

Gap 1 — Runtime parity (local dev vs prod cloud):
- Does the plan test against the actual production storage backend (object store) or only local FileSystem/mocks?
- Does the plan probe IAM propagation, secret-manager fetch, connection pooling under load?
- Are dependency version pins verified to contain the features the spec assumes (e.g. a storage library version that supports cloud-IAM credential signing)?
- Does the plan check env-drop scenarios (ALLOWED_HOSTS missing, SECRET_KEY mid-rotation)?
- Real bug: an os.path.exists check always returned False on an object store and hid every admin profile pic.

Gap 2 — Concurrency & races:
- For every shared resource write (DB row, file, cache key, token, sandbox), does the plan have a concurrent-caller test?
- Token refresh: does the plan verify the second concurrent refresh re-reads from the authoritative store?
- Upload collisions: does the plan force 2+ writers to the same filename?
- Migration race: does the plan simulate old+new pods in flight?
- Real bug: a concurrent OAuth refresh shipped 401 because the second caller had no re-read path against the authoritative store.

Gap 3 — Plumbing trace (every mutation × every consumer):
- For every callback (completion callback, onSuccess, onTerminate): does the plan enumerate and test every terminal path that should invoke it?
- For every SDK → wrapper → adapter chain: does a test exist for each layer, not just the top?
- Are there stubs / NotImplementedError / TODO markers in the spec that the plan doesn't explicitly test for removal?
- Real bug: a completion callback was wired into only some terminal paths; resources never returned to free on the rest. A resource-acquire function was a stub that shipped.

Gap 4 — State-mutation ordering & idempotence:
- Does the plan specify and test the write-order for multi-phase writes? (flag BEFORE invoke vs after)
- Does the plan test idempotent retries — same RPC twice produces the same final state?
- Does error backfill preserve or overwrite earlier error messages?
- Real bug: a refresh trigger had to set is_stale=true before the async worker invoke or the poller never fired.

Gap 5 — Tenant / fixture variance:
- For every fallback chain (use A else B else C), is there at least one test org configured to force each branch?
- Are fixture seeds input-diverse (multi-byte unicode values, non-ASCII names, edge populations)?
- Does the plan identify which tests depend on pre-seeded data that might only exist in one org?
- Real bug: a notify-destination fallback was never exercised because the only test org had the primary destination-config row; a validation queue rejected unusual-input records because the fixture had no such examples.

Gap 6 — Observability / log-noise:
- Does the plan audit log levels (INFO vs WARN vs ERROR) for every new event?
- Does the plan verify alerting thresholds are set against actionable (not bot-noise) baselines?
- Are health/readiness probes exercising the real code path (sign a real URL) or returning a shallow 200?
- Real bug: a WS middleware logged expected token-expiry at ERROR; most prod ERROR slots were bot traffic, so real 500s were invisible for days.

Gap 7 — Consumer contracts (API, mobile, downstream):
- For every schema change: is there a contract snapshot test for each consumer class (mobile app decoder, partner webhook, cron job input)?
- Are removed fields covered by a deprecation window or dual-read path?
- Does the plan flag JSON-shape changes as blocking on mobile contract tests?
- Real bug: removing URLField columns from an entity serializer would crash mobile decoders without a contract test.

Additionally check:
- Format/encoding mismatches at integration boundaries
- Deploy-time failures (missing migrations, config drift)
- Test-env limitations without documented fallback

For every finding, specify: spec_section, risk_class (one of: runtime-parity/concurrency/plumbing-trace/state-ordering/tenant-variance/observability/contract/format-encoding/deploy/test-env), failure_scenario (concrete 'what breaks' story), proposed_test, tier (unit/integration/chain/deploy/e2e), severity (critical/high/medium/low).

Minimum 3 findings per applicable gap class. If a gap class genuinely does not apply, state why in one line rather than skipping silently." \
  2>&1 | tee /tmp/codex-cov-adv-$$.txt
```

## Rules

- `run_in_background: true` on each Bash call — **no trailing `&`**. Two separate Bash calls = parallel execution with completion notifications.
- `echo '' |`, `read-only` sandbox, relative paths
- **No JSON templates or markers in the prompt** (Codex echoes them back as fake output)
- Prompts are prose with explicit gap-class probes and real-bug citations

## Reading results

Wait for both background notifications. Read output files with Read tool. Parse findings as prose — not JSON. Merge into Step 7 reconciliation.

## When a finding fires

Each finding from Agent B translates into a new test row at the specified tier.
Tag with `[ADV]` prefix. Prioritize critical/high before shipping the test plan.
