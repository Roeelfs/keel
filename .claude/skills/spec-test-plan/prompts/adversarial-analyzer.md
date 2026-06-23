# Adversarial Test Analyzer

Identifies failure modes BEYOND the spec — infrastructure gotchas, concurrency races, plumbing wiring drops, cross-boundary failures that specs never mention.

**Agent type:** `general-purpose` | **Model:** `opus`

```
description: "Adversarial analysis — what could go wrong beyond the spec"
prompt: |
  Read the spec at {{SPEC_PATH}} and the project at {{PROJECT_ROOT}}.

  The spec describes what SHOULD happen. Your job is to find what COULD GO WRONG
  that the spec never mentions. These are the tests that prevent production surprises.

  ## Blast Radius Mandate

  A narrow test plan ships bugs. A test plan that only tests the happy path is worse
  than useless — it produces false confidence. Your mandate is WIDE blast radius:
  every mutation has multiple consumers, every infra dependency has failure modes,
  every deploy environment differs from local.

  Concrete bug classes that shipped to production because adversarial analysis
  missed them — treat these as required probes, not optional:

  - A completion callback wired into only some of the terminal/completion paths
    (plumbing trace miss): the resource never returned to its free state on the
    un-wired paths.
  - Concurrent OAuth refresh returning 401 with no re-read from the authoritative
    store (concurrency miss): the second caller didn't see the refreshed token.
  - A "notify destination" path that silently drops when the primary destination-config
    row is missing because no test org exercised the fallback (fallback miss).
  - A status flag that must be set BEFORE an async invoke, or the poller never
    wakes the work (state ordering miss).
  - A function the spec declared "implemented" that was actually a STUB returning
    immediately (stub-not-replaced).
  - A filesystem-existence check against an empty media root that hides ALL assets
    on a cloud runtime where storage is an object store, not a local disk
    (runtime-parity miss).
  - A storage library pin that lacks the cloud-IAM credential signing / object-store
    URL-signing feature the spec assumed it had, so only the deployed environment
    fails (dependency-version miss).
  - Bot/scanner traffic eating most of the ERROR log budget so real 500s were
    invisible for days (observability miss).
  - A mobile serializer/decoder that silently breaks on a schema change (contract miss).
  - An input edge case (e.g. a multi-byte unicode value) rejected by a happy-path
    fixture set that contained no such examples (fixture-variance miss).

  ## Analyze each category — produce 2-3 concrete risks per category:

  ### 1. Environment divergence
  - What works in dev but fails in staging/production?
  - Missing env vars not in the spec? Check deployment manifests for ALL required vars.
  - Code that behaves differently per environment?

  ### 2. Format/encoding mismatches at integration boundaries
  - Values passing between systems with format assumptions? (base64 vs raw, URL encoding, JSON vs form data)
  - External services returning unexpected formats? (reserved field names, different schemas)
  - Encryption keys stored in one format, consumed in another?

  ### 3. Infrastructure/platform incompatibilities
  - Capabilities that differ between deployment targets? (VM vs serverless container, signed URLs, metadata credentials)
  - Quota or rate limits affecting the feature or testing?
  - Rolling deploy risks? (config dropped during parallel updates)

  ### 4. Build/deploy pipeline failures
  - Build-time placeholders that must be resolved?
  - Asset paths breaking under different URL patterns? (trailing slashes, relative vs absolute)
  - CLI flags affecting runtime? (e.g., a transcode/build flag that changes output layout)

  ### 5. Cross-component data flow
  - Multi-step flows: does data from step A actually reach step B?
  - Is data persisted to the right model/store before downstream reads?
  - Reconnect/resume: is state properly hydrated from persistence?

  ### 6. Testing environment limitations
  - What tests might be impossible in test env? (browser sandboxes, rate limits, missing third-party sandboxes)
  - Fallback verification strategy for each limitation?

  ### 7. Third-party service behavior when unconfigured
  - For each third-party integration (reCAPTCHA, OAuth providers, SMS gateways, payment processors):
    does the spec define graceful degradation when API keys/sitekeys are absent or invalid in staging?
  - Risk: unconfigured services throw 500s or silently block all users — not just test accounts.
  - Required: spec must declare fallback mode (bypass flag, mock provider, or explicit error page) per service.

  ### 8. Rate limiting test bypass
  - If the feature includes OTP, SMS, email sending, magic links, or any API rate limit:
    does the spec define a test bypass mechanism? (test phone numbers, mock providers, rate-limit exemption env var)
  - Risk: throttle kicks in during E2E and blocks the entire test suite for hours.
  - Required: bypass path must be documented and exercised in Tier 3 setup; without it, mark as BLOCKED.

  ### 9. Protection boundary audit
  - For features that gate access to sensitive data or documents: enumerate ALL access paths
    (REST endpoints, GraphQL resolvers, view-level checks, document-level checks, upload gates, mobile API, webhooks).
  - Verify EACH path is independently gated — not just the primary UI surface.
  - Risk: primary interface protected, secondary paths (direct URL, API, mobile) left open.
    Gap is invisible to unit tests and happy-path E2E; only targeted boundary probing reveals it.

  ### 10. Concurrency, races, and idempotence
  - For each mutation: what happens if two requests land at the same time? Same key, same row, same file?
  - Token refresh: if two callers refresh simultaneously, does the second one see the new token, or fail with stale 401?
  - File upload: if two requests write the same filename, does one silently overwrite the other?
  - Migration race: if old and new pods both run during a rolling deploy, can old code write a schema new code can't read (or vice versa)?
  - Idempotence: if the same RPC fires twice (retry, network blip), does it produce duplicate work or exactly-once behavior?
  - Required test: for every write path, construct a `ThreadPoolExecutor`-style concurrent test OR document why single-writer is guaranteed.
  - Risk example: a concurrent OAuth refresh shipped a 401 bug because the second caller didn't re-read from the authoritative store; a file-upload path had no collision test until one was added.

  ### 11. State-mutation ordering & multi-phase writes
  - For every flag or status column that drives downstream behavior: when is it set, who reads it, what happens if a reader wins the race?
  - Two-phase writes: is the flag written BEFORE the async invoke, or AFTER? Spec must pick one; test must verify.
  - Error backfill: if a row was already marked complete before the error was known, does the backfill overwrite or preserve the earlier status?
  - Rollback: if mutation A commits and mutation B fails, does the system roll A back or leave a torn state?
  - Required test: for every state transition, write a unit test that reads mid-transition to verify no observer sees an inconsistent state.
  - Risk example: a refresh trigger had to set `is_stale=true` BEFORE invoking the async worker, or the poller would never wake it up.

  ### 12. Plumbing trace — every mutation through ALL consumers
  - For every callback (e.g., a completion callback, `onTerminate`, `onSuccess`): enumerate EVERY terminal path that should invoke it. Unit tests validate the callback exists; integration tests must validate it fires in ALL paths.
  - For every SDK → wrapper → adapter chain (e.g., a client SDK → service tool → HTTP adapter): verify the payload survives each layer. A schema test at only the SDK layer misses drops in the adapter.
  - For every stub / TODO / `// placeholder` / `raise NotImplementedError`: the spec must mark it as "real implementation required before ship" or the plan must include a test that fails if the stub is still present.
  - Required test: add a "plumbing trace" table to the spec — columns: [mutation | consumer | test that verifies consumer fires]. Every row must have a test.
  - Risk example: a real integration helper was wired into only some of the completion paths (health-report + several lifecycle-manager paths); resources never returned to their free state on the un-wired paths. A resource-acquire function was a stub that returned immediately — concurrent runs clobbered each other.

  ### 13. Tenant / org / fixture variance
  - Test accounts in the happy-path E2E org often have ALL optional integrations configured. What breaks for an org missing one?
  - For every fallback chain (e.g., "use A, else B, else C"): is there a test org configured to force each branch?
  - For every fixture: does the test seed cover edge populations — multi-byte unicode values, single-token names, non-ASCII names, records in states with no approval gate, orgs with zero history?
  - Required test: at least ONE E2E test per fallback branch. At least ONE test org per "missing optional integration" scenario. Fixture seed must include input-diverse and edge-case examples.
  - Risk example: a "notify destination" fallback to a secondary integration table was never exercised because the only test org had the primary destination-config row pre-seeded. An unusual-input edge case was rejected because the validation fixture had no such examples.

  ### 14. Observability & log-noise
  - For every new ERROR log or exception path: is it actionable, or is it expected user behavior (bot probes, expired tokens, rate-limited retries)?
  - What's the alerting threshold? If most ERROR slots are routine noise, real P0s are invisible.
  - Does the spec define log levels (INFO/WARN/ERROR) per event class?
  - Does the health / readiness probe exercise the actual code path (e.g., sign a real URL), or is it a shallow "return 200"?
  - Required test: for every new log line, a test asserts the correct level. A deploy-validation test confirms log volume is within the project's defined ERROR budget.
  - Risk example: a WebSocket middleware logged expected token-expiry at ERROR, drowning real 500s (most of the ERROR budget was bot traffic). The bug didn't surface for days.

  ### 15. Runtime parity — local dev vs cloud
  - Enumerate every boundary where local dev diverges from the production runtime:
    - **Storage backend**: local FileSystem storage vs object store (S3/GCS) in prod — `os.path.exists` behavior, signed URLs, IAM.
    - **Runtime**: local dev server / `bun dev` vs serverless container / function / managed compute in prod — cold starts, ephemeral filesystem, connection pooling, concurrent request handling.
    - **IAM / auth**: mounted SA key (local) vs metadata-server credential signing (cloud) — propagation delays (up to several minutes).
    - **Secrets**: `.env` file (local) vs secret manager (prod) — rotation windows, MAC/SECRET_KEY mismatch.
    - **Dependencies**: pinned versions must include required features (e.g., a storage library version that supports cloud-IAM credential signing). Check requirements.txt / package.json against spec assumptions.
    - **DB connection limits**: local Postgres has no effective cap; prod managed Postgres has a fixed max_connections. `CONN_MAX_AGE=0` (default) eats the pool under load.
  - Required test: a deploy-validation tier that EXECUTES production-parity paths — a real signed URL via cloud-IAM credential signing, a real DB connection under simulated load, a real secret-manager fetch.
  - Risk example: an `os.path.exists` check against an object store (`MEDIA_ROOT=""`) always returned False → every admin profile pic was hidden. IAM propagation race: a health endpoint returned 503 for several minutes after deploy.

  ### 16. Consumer contracts — API, mobile, downstream jobs
  - For every API schema change (add/remove/rename field, change type): who consumes this? Mobile app? Partner integrations? Downstream ETL? Cron jobs?
  - Snapshot the serializer/response shape pre-change, assert post-change keeps backward-compatible keys for N deploy cycles.
  - Mobile decoders are especially brittle: a dropped `attachment_url` key crashes the strongly-typed mobile decoder, not a graceful null.
  - For removed fields: is there a deprecation window + dual-read migration, or does the field just vanish?
  - Required test: a contract test per consumer class — mobile serialization snapshot, partner webhook payload snapshot, cron job input-shape test.
  - Risk example: removing URLField columns from an entity serializer would crash mobile decoders without a contract test.

  ## Output

  For each risk, output:

  | ID | Category | Risk | Concrete Test | Tier | Fallback if Blocked |
  |----|----------|------|---------------|------|---------------------|
  | ADV-1 | env divergence | SOME_REQUIRED_SECRET missing in staging | Verify ALL env vars from deploy manifest exist and are non-empty | Deploy | Script that diffs prod vs staging env vars |
  | ADV-2 | concurrency | Two jobs on same org call acquire_resource; share a resource | Dispatch 2 concurrent RPCs, assert distinct resource IDs | Integration | Serialized retry with lock |
  | ADV-3 | plumbing trace | completion callback wired in primary but not error path | Unit test each terminal path invokes the callback | Unit + Integration | Assert-count-greater-than-zero on callback mock |
  | ... | ... | ... | ... | ... | ... |

  Tag all items with [ADV] prefix. Be specific — "something might break" is useless.
  "SOME_REQUIRED_SECRET is in prod .env but not in staging docker-compose" is actionable.
  "concurrent OAuth refresh: 2 parallel callers → 2nd gets 401, needs store re-read" is actionable.

  ## Minimum counts (enforce)

  - At least **2 risks per category** above where the category applies to the spec
  - At least **1 runtime-parity risk** for any spec that ships to a serverless / managed-compute / object-store backend
  - At least **1 concurrency risk** for any spec that writes to a shared resource
  - At least **1 plumbing-trace risk** for any spec that adds a callback, stub placeholder, or multi-layer chain
  - At least **1 contract risk** for any spec that changes API response shapes

  If a category genuinely doesn't apply, state why in one line ("no external writes → no concurrency") rather than skipping silently.
```
