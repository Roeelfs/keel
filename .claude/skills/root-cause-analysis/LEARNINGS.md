# LEARNINGS — root-cause-analysis

This is the skill's running memory. Read it at task start; append a dated bullet per
non-trivial finding at task end. Prune vague entries and promote recurring ones (≥3
occurrences) into `SKILL.md`.

Keep entries specific (cite the failure class + the evidence pattern that caught it),
but **portable** — the reusable lesson, not a one-off codebase detail. Route project
specifics (log group names, which store holds terminal status, hot-zone files) to the
project's own memory, and operator-private craft to the overlay. Soft cap ~100 lines.

The entries below are portable starting wisdom, not project-specific.

---

## What Worked

### Read the terminal status before theorizing
- **A stuck or slow run is not a code wedge until its terminal outcome says so.** Runs
  that end in "resource/capacity/quota not acquired" never executed work code — a
  code-path hypothesis is dead on arrival. Reading the terminal status first repeatedly
  collapses a whole branch of the hypothesis tree in one query.

### Pin the wrong-surface trap early
- **"Zero invocations / no logs" almost always means the WRONG log group, not "it never
  ran".** Resolve endpoint → serving function → its *physical* log group before
  concluding the call never arrived. An explicitly-renamed function does not log to its
  old construct-derived group. This has cost multiple RCAs an hour of confident-but-wrong
  "the request never reached the backend".

### Deploy-timestamp-vs-onset exonerates mechanically
- **A change that deployed *after* the symptom's onset cannot be the cause** — however
  suspicious the diff looks. Pinning the two timestamps first is the cheapest way to clear
  most of the suspect list and stop mis-blame.

### The provider-alignment gate deletes problems instead of moving them
- **When a large internal subsystem exists only to arbitrate a bounded resource you
  self-manage, a provider that owns that resource elastically deletes the subsystem — not
  just the current bug.** The recurring shape: an on-demand workload forced onto a
  persistent-workspace provider, with hand-built pool/lifecycle machinery compensating for
  the mismatch. The machinery *is* the accidental complexity, and its glue is where the
  incidents live. Classify the access pattern, match the provider class, keep only the
  substrate-independent core (idempotency, observability, router).
- **Attribute the symptom to a layer before blaming the vendor.** Often the majority of a
  latency/cost symptom is your own serial orchestration, not the provider's primitive —
  which either strengthens the swap (most of it is deletable) or clears the vendor entirely.

## Patterns

### Local green is structurally blind — name the class, prevent at the un-mockable layer
- The suite mocks exactly the boundary where config-wiring / data-drift / contract /
  architecture defects live, so it goes green *because* the bug hits a tested-correct
  fail-open branch. The prevention lever is a **cheap invariant at the un-mockable layer**
  (synth/build-time infra assertion, a static lint that resolves a value to a real/unique/
  known target, an owner-identity behavioral test) — never "understand the feature better".

### Most guardrails fail adversarial refutation on first draft
- Recurring false-security modes: triggers keyed on artifacts the fix introduced;
  assert-present-somewhere vs. correct-on-the-real-surface; test-exists vs.
  test-exercises-the-failing-path; a guardrail scoped to a broader class than it covers.
  Refute every proposed guardrail (default "insufficient") before shipping it.

### Fail-open is permanent-disable until proven otherwise
- A degraded branch that silently returns a benign shape (empty result + 200, feature
  quietly off) is indistinguishable from a transient blip. Loud-fail or carry a health
  assertion — otherwise the "fix" ships a silently-disabled feature.

### Key the known-error ledger on a stable, PHI-free fingerprint
- Key on a normalized `action` + opaque-`ref` tuple, **never** a message/stack fingerprint.
  The latter fails twice: it leaks PII/PHI into the grouping key, and it re-buckets on any
  refactor that renames frames — so the "same" issue splits and regression detection misses
  the recurrence. The fingerprint is doubly load-bearing: it keys both the ledger *and*
  regression detection.

### Provenance is trustworthy only if server-stamped; high-cardinality ids go on logs/traces
- A provenance id consumed for RCA (correlation / session / release-SHA / PR / actor) is
  trustworthy only if **server-stamped or deploy-time-derived** — a caller-asserted id is a
  log-injection vector. And high-cardinality ids belong on **log fields / trace annotations,
  never metric dimensions** (each unique label spawns a separately-billed time series).

### Phase 5 is symmetric — three BUILD tripwires override the strongest ADOPT signal
- The strongest ADOPT signal (a provider elastically owns a bounded resource your subsystem
  only exists to arbitrate) is overridden when adopting would (a) flatten a data/compliance
  boundary, (b) duplicate a live owned subsystem (relocating the problem, not deleting it),
  or (c) route regulated data upstream of your only redaction boundary / force a BAA pricing
  floor. A gate that only ever says "buy" is miscalibrated.

### Symptom-scoped RCAs never fire on the subsystem's premise — count the fixes
- Observed at scale in one adopter stack: **~35k LOC of pool/lifecycle orchestration** grown
  to accommodate two *real* gaps of a persistent-workspace provider — and **66 lifecycle
  fixes all landed inside the premise**; none asked "should the pool exist?". The premise was
  finally attacked from *outside* (the vendor's own rebuttal), never by an RCA. Per-incident,
  symptom-scoped analysis is structurally blind here: the machine's size reads as evidence of
  its necessity. The tripwire is mechanical — **count prior fixes in the same subsystem at
  Phase 1's ledger check; at ≥3, Phase 5 runs at the subsystem level before fix N lands.**

### An unmeasured premise is unfalsifiable by construction
- In the same case, the founding "~4 min create" was a **dispatcher timeout constant
  remembered as a measurement** (measured provider create: sub-3 s — 1–3% of the pipeline;
  the rest was self-imposed convergence), and the cost fear was **modeled, never invoiced**
  (actual ≈ 1/10th the model). No metric split the provider's layer from the stack's own — so
  no incident could ever contradict the premise. Companion smells found beside it: the
  vendor's canonical primitive for the exact use-case **defined in-code with zero call
  sites**, and a subsystem vocabulary (pool / floor / convergence / admission) absent from
  the vendor's docs. Any number that justifies an architecture must trace to a **measurement
  or an invoice**, and the provider-vs-own-layer split must be instrumented *first*.

### The known-error ledger splits — derive occurrence, git-native curation
- A ledger has two halves with opposite homes, and a single new datastore is usually the
  wrong answer for both. **Occurrence** (signature × release × tenant × count) is runtime
  telemetry → derive it with a GROUP BY over the log store you already own (`HAVING count ≥ 2`
  = recurrence); a second event table beside your logs is a **dual-write anti-pattern**
  (Kleppmann) — lossier than derivation. **Curation** (root cause / fix refs / status) is
  agent bookkeeping with **zero runtime consumers** → version-control it (one file per
  signature; VCS log + commit trailers give fixing-commit/issue/session for free). Residency
  test: *does this data have a runtime/customer consumer?* No → git, not a DB. Add a derived
  index over the git records only when a consumer appears (Backstage outgrow path). Never
  co-locate RCA state with the plane it debugs; `resolved` is bake-gated (merged ≠ resolved).

## Industry grounding / References

Standards the phases implement (URLs live here, not in the terse SKILL.md — Keel house style
for process skills). Liveness-verified 2026-07-01.

- **Blameless postmortem** — assume everyone acted reasonably on the information they had;
  focus on *how*, not *who*. — https://sre.google/sre-book/postmortem-culture/ ·
  https://postmortems.pagerduty.com/culture/blameless/
- **Amazon Correction-of-Error (COE)** — quantified impact, timeline from the first trigger,
  blame-free 5-Whys, action items (owner + priority + due) as the main output. —
  https://aws.amazon.com/blogs/mt/why-you-should-develop-a-correction-of-error-coe/
- **5-Whys is linear/single-cause** (isolates one cause, stops at the first symptom, drifts
  to *who*) → prefer a causal **graph**. — https://www.infoq.com/news/2015/02/five-why/
- **CAST / STAMP (Leveson)** — most accidents have many interacting causes; strengthen the
  whole control structure, don't point-fix. —
  https://github.com/joelparkerhenderson/causal-analysis-based-on-system-theory/blob/main/README.md
- **Kepner-Tregoe IS / IS-NOT** — a valid cause explains every IS *and* every IS-NOT. —
  https://kepner-tregoe.com/blogs/universal-principals-and-kt-problem-analysis/
- **ICS incident command** (post-hoc RCA is a separate activity from live command; the IC
  does not touch the system). — https://sre.google/workbook/incident-response/
- **ITIL known error / KEDB** — "a problem analysed but not resolved"; a queryable store with
  a mutable lifecycle (transition, never delete). — https://en.wikipedia.org/wiki/Known_error ·
  https://wiki.en.it-processmaps.com/index.php/Problem_Management
- **Ledger store-split — curation in git, occurrence derived** — Google SRE stores postmortems
  as documents in a repo and retrofits a derived index (Requiem) *over* them, never in the
  serving DB; Sentry's own internals split curated mutable state (Postgres) from
  fingerprint-keyed occurrence events (ClickHouse); a dual-write beside your log store is a
  named anti-pattern (Kleppmann); when queryability outgrows grep, add a derived index over the
  git source (Backstage), don't relocate authoring. — https://sre.google/sre-book/postmortem-culture/ ·
  https://sre.google/workbook/postmortem-culture/ · https://develop.sentry.dev/application-architecture/overview/ ·
  https://backstage.io/
- **Agent RCA via distributed tracing** — an agent run is a span tree (invoke-agent → chat →
  execute-tool); content capture is opt-in because it can carry sensitive data. —
  https://opentelemetry.io/blog/2026/genai-observability/
- **High-cardinality ids on traces/logs, not metric labels.** —
  https://signoz.io/blog/high-cardinality-data/
- **Redaction at the sink** (Temporal Payload Codec / OTel Collector / Sentry beforeSend —
  scrub before the trail leaves the boundary). —
  https://opentelemetry.io/docs/security/handling-sensitive-data/ ·
  https://docs.temporal.io/payload-codec
- **ADOPT — undifferentiated heavy lifting** (Vogels): own the differentiating core, buy the
  commodity. — https://www.allthingsdistributed.com/2014/11/aws-lambda.html
- **ADOPT exemplars** — fault attribution by a caller-supplied failure *type*
  (https://docs.temporal.io/references/failures); tenant-vs-platform split by error code
  (https://developers.cloudflare.com/workers/observability/errors/); microVM-per-session as
  the managed on-demand-compute class (https://aws.amazon.com/lambda/lambda-microvms/ ·
  https://github.com/firecracker-microvm/firecracker).
- **BUILD tripwire — compliance/BAA floor** for routing regulated data to a third-party
  sink. — https://docs.datadoghq.com/data_security/hipaa_compliance/

## Open Questions

- (none yet — append as runs surface them)
