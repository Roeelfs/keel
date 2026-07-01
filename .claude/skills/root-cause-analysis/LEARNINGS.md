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

## Open Questions

- (none yet — append as runs surface them)
