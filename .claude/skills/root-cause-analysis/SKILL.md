---
name: root-cause-analysis
description: Drive an issue to a COMPLETE root-cause analysis — from symptom to a grounded cause to the right remediation and a prevention that holds. Use for an incident, regression, outage, or recurring failure where you owe a real RCA (not just a quick fix). Triggers — "root cause this", "do an RCA", "postmortem", "why did X regress / break in production", "what caused the outage". Orchestrates the diagnosis loop and the architecture-placement pass rather than replacing them.
---

# Root Cause Analysis

Take an issue from *symptom* to a **complete RCA**: the confirmed cause (proven by a red-capable signal), the *right* remediation (build-vs-adopt decided deliberately), a fix that deepens the codebase, and a prevention that has survived adversarial refutation.

This skill is an **orchestrator**, not a parallel copy of its parts. It calls two skills at their proper phases and adds the connective discipline (timeline, failure-classing, the provider-alignment gate, the RCA writeup):

- **`diagnosing-bugs`** — the diagnosis *loop* (build a red-capable feedback signal, reproduce + minimise, rank falsifiable hypotheses, instrument). RCA uses it to find the cause; don't re-implement it here.
- **`improve-codebase-architecture`** — the fix-*placement* rubric (deep modules, deletion test, one architecture left behind). RCA uses it so the fix deepens the codebase instead of bolting on a compensating layer.

Both are referenced **by name** so future updates to them propagate — this skill never forks their content.

## When to use / when not

- **Use** when an incident/regression/outage/recurring-failure demands a *complete* RCA: cause **and** the right fix **and** a prevention. The deliverable is an RCA document plus the fix.
- **Not** for authoring a fresh feature (that's the spec flow), and not for a trivial local bug with an obvious fix — just fix it. If all you need is the raw diagnosis *loop*, invoke `diagnosing-bugs` directly; reach for RCA when you also owe the remediation decision and the prevention.

## Skill Memory (LEARNINGS.md)

**Before starting:** read `LEARNINGS.md` in this skill directory, and the private overlay if present — `~/.claude/skills-overlay/root-cause-analysis/LEARNINGS.md` (adopter-private accumulated learnings; never in this public repo). Apply the distilled patterns.

**Before ending — route each learning by scope; NEVER hand-append to this repo's committed `LEARNINGS.md` (a read-only curated seed):** operator-private RCA craft → `~/.claude/skills-overlay/root-cause-analysis/LEARNINGS.md` (create if absent); project-specific facts (log group names, which store holds terminal status, hot-zone files) → the project's `.claude/memory/`; universal craft worth publishing → note it for `/improve-harness` to promote (de-identified) into the seed via PR. Full routing: [`docs/skill-memory.md`](../../../docs/skill-memory.md).

---

## Phase 1 — Read the terminal signal before theorizing

**Write the anchor before you touch anything — so the session always knows what it is pinning down.** State, in one place you keep re-reading: the **single exact symptom** (one failing behavior in one sentence — not "something is wrong with X"), the **authoritative surface** you will read it on (named), and **one falsifiable hypothesis** you are testing right now. An RCA that cannot name its one symptom and its one current hypothesis has already drifted — the commonest failure is a session that widens into "the whole subsystem is flaky" and then chases every anomaly it trips over, pinning down nothing. Re-state the anchor whenever the trail forks; if what you are now chasing is not the symptom you wrote down, either move the anchor deliberately or drop the tangent (hypothesis-driven debugging: characterize the failure, form one hypothesis, change one variable at a time). **A guessed cause that was never reproduced is not an anchor** — never inherit a prior session's or sub-agent's cause claim without re-deriving the symptom from a live reproduction; a guess that hardened into a durable anchor is how an investigation spends many runs solving the wrong problem (the classic case: chasing the wrong variant for a dozen runs because the first session guessed it from a code artifact and never reproduced the failing state).

Ground the symptom in the **authoritative signal** — the logs, the run's terminal status, the monitoring, the store's actual state — **not** local state, **not** the dispatch/API response (an async invoke hides crashes behind a 200 / 202-accepted ack), **not** a screenshot.

**Read the run's TERMINAL status first.** A run that ended in "resource/capacity/quota not acquired" means no work code ever ran — so a code-path wedge is *not* the cause, and theorizing about one wastes the RCA. A stuck or slow run is not evidence of a code wedge until you have read its terminal outcome. First read the outcome; then theorize. (Async/queued work is modeled the same way everywhere: a status is authoritative only when it is *terminal* — an accepted/queued/running state is not an outcome.) **A terminal code's label is not its meaning** — read what condition actually set it before trusting the word. A retry/ceiling/timeout code can fold an *unrelated* failure (a readiness probe, a downstream call, a smoke check) into a label that names the wrong layer; confirm the measured condition, not just the string, or you will RCA the layer the label blames instead of the one that broke.

Establish and write down: the **exact symptom**, the **first-seen timestamp** (onset), the **blast radius**, and **which authoritative surface** you are reading (name it — reading the wrong log group manufactures a confident-but-wrong RCA). Frame blast radius as **Kepner-Tregoe IS / IS-NOT** — what *is* affected vs. what is *not*: a valid cause must explain **every IS and every IS-NOT**, and the IS-NOT column is the refutation data a single-cause chain never collects.

**The authoritative signal includes the distributed trace.** Reconstruct the execution path from the span tree (invoke-agent → chat per model call → execute-tool per tool call), including **cross-agent** traces — one agent's failure is often another's ambiguous output several steps upstream. Provenance ids you consume (correlation / session / release-SHA / PR / actor) are trustworthy only if **server-stamped or deploy-time-derived** — a caller-asserted id is untrusted (log-injection class). And never read or forward an **un-scrubbed** trail: an error/trace sink captures *upstream* of business-data redaction, so it must be scrubbed at the write boundary before any agent consumes it.

**Verify you are reading the RIGHT source before you conclude anything — including "there are no logs."** When a serving component's log/telemetry destination is derived from an internal identifier (a construct id, a build hash, an auto-generated name) rather than a stable one, that identifier can drift or point at a **stale/orphaned** destination that has been silent for months. So a `0 results` / "no logs / it never arrived" reading must first raise the hypothesis **"wrong or stale destination"** before "the call never happened" — confirm the destination actually serves the surface (and is live, by its last-event timestamp) before treating absence as evidence. A stale dashboard or a coarse pre-aggregated view is the same trap: mid-incident, read raw/live signal, not a pre-built view that encodes a now-stale "normal."

**Evidence-citation discipline — quote the literal signal; a relayed claim is unverified.** Every assertion about what a log, metric, or trace shows must carry the **literal line or row** plus its provenance: the exact source you read it from, its timestamp, and the exact query/filter that produced it. A paraphrase ("the logs show it failed") is not evidence — it is precisely where false positives and mis-read / mis-counted logs enter. A claim **relayed** by a sub-agent, a tool summary, a dashboard, or a previous turn is **UNVERIFIED** until you re-read the literal line at the authoritative source yourself: sub-agents and summaries confabulate log evidence with total confidence, and citing a source you did not open is the single most common way an RCA reaches a confident-but-wrong conclusion. In the writeup, mark each fact **observed** (you read the line) or **inferred** (you concluded it), never silently promote an inference to an observation, and count from the raw rows — never from a remembered or summarized total. Temporal correlation in a trace is a lead, not a cause; confirm the mechanism. And a **status label** relayed as settled — "pre-existing", "known-flaky", "dead code", "safe to disable", "already fixed" — is the same unverified relayed claim: re-run the exact discriminating check (the failing test on a clean baseline, the live-caller search, the writer-provenance read) before you build on it. Such labels propagate agent-to-agent on faith and are a top source of both false positives and mis-scoped fixes.

**Check the known-error ledger first.** Before theorizing, query the ledger (see Phase 8) for a matching **fingerprint** — a prior RCA may already own this exact failure, or show it was resolved-then-reopened (a **regression**, not a fresh bug, with a known prior root cause and fix to start from). While there, **count prior fixes in this same subsystem** — different fingerprints included. The fingerprint check catches same-signature regressions; the count catches something it can't: if this is the **≥3rd fix landing in one subsystem**, the incident escalates — Phase 5 runs at the *subsystem* level ("should this machinery exist at all?"), not just for this fix (see the fix-clustering tripwire there).

## Phase 2 — Pin onset vs. change timeline

Build the timeline before naming a culprit.

- When did the symptom **start** (onset)?
- What **changed** near it — deploys, config/flag flips, data migrations, dependency bumps, an upstream provider incident?

**A change that shipped *after* onset is mechanically exonerated** — do not blame it, however suspicious it looks. A change that shipped just *before* onset is the prime suspect but still owes the Phase 3 loop. Any claim about *what changed* — including a sub-agent's or reviewer's — is **UNVERIFIED** until grounded in the diff, the deploy log, or a direct query. Reconstruct the timeline as an **Amazon Correction-of-Error (COE)** chronology — from the *first trigger*, not from when you noticed.

**Blameless, as an agent rule (Google SRE / PagerDuty).** Judge the systems and the change, never the author — the agent-equivalent of blaming a person is premature culprit-fixation on a suspicious diff. Ask *what could have led any reasonable change to produce this?* Suspicion is not causation.

## Phase 3 — Diagnose to the cause (invoke `diagnosing-bugs`)

Now find the actual cause. Invoke the **`diagnosing-bugs`** skill and follow it: build a tight, **red-capable** feedback loop that goes red on *this exact symptom*, reproduce and minimise, generate 3–5 ranked **falsifiable** hypotheses, instrument one variable at a time.

**Do not theorize a fix before that loop exists and goes red.** RCA without a red-capable signal is a guess wearing a document. If you genuinely cannot build a loop, say so explicitly and get the artifact/access you need — do not proceed to a fix on a hunch.

## Phase 4 — Classify the failure (local green is structurally blind)

With the cause in hand, classify it — the class dictates the prevention:

| Class | What it is | Can the local suite see it? |
|---|---|---|
| **Code defect** | logic / type error in a covered path | Yes — a unit/integration test can catch it |
| **Config / env-wiring** | missing env-map key, grant on the wrong role, stale snapshot/SSM value, build- or deploy-time-only defect | **No** — type-check and unit tests are structurally blind |
| **Data-drift** | passes on a fresh store, breaks on existing / at-scale data | **No** — fresh-fixture green hides it |
| **Contract / literal-disagreement** | two sources of truth disagree (two string literals, a hardcoded recipient, an allowlist vs a registry) | **Rarely** — only if a parity test exists |
| **Architecture defect** | no correct test seam exists; the design itself prevents locking the bug down | **No** — the finding *is* the missing seam |

Name the class explicitly. **Local green is necessary but not sufficient**: the suite mocks exactly the boundary where the config/data/contract classes live, so it can go green *because* the bug hits a tested-correct fail-open branch. The class you name is what Phase 8's prevention must target.

A linear **5-Whys** chain is insufficient here — it isolates a single cause, stops at the first symptom, and drifts toward *who*. Think in a **causal graph** of interacting contributing factors (CAST / STAMP, Why-Because Analysis): most failures have several, and the fix strengthens the *class*, not the one point that broke.

## Phase 5 — Provider ⋈ Technical-Architecture Alignment (the remediation gate)

**The paradigm.** Before designing a bespoke architecture to fix the root cause, ask: **does an existing provider / vendor / platform-class already own this capability — such that adopting it *deletes* the problem instead of relocating it?** Do not invent a new architecture when a capability class already solves it. The `><` is the *join* between what a provider gives you and the technical architecture you'd otherwise hand-build — align to the provider's capability rather than compensating for its absence in glue code.

Often the bug you are RCA-ing is a *symptom of a mismatch*: a workload forced onto the wrong provider class, patched with hand-built machinery to make the mismatch behave. That machinery is the accidental complexity — and its bugs are the incident. Run these tests:

- **Ownership-inversion test.** Is there a large internal subsystem that exists **only** to arbitrate a bounded resource *you* self-manage? If a provider owns that resource elastically, adopting it *deletes* the subsystem outright — contention becomes a raisable provider quota, not your reducer/reaper/supervisor glue. (Illustrative, generic: a warm-pool + lifecycle state machine hand-built to force an *on-demand* workload onto a *persistent-workspace* provider — the managed on-demand-compute class owns that lifecycle for you, so the state machine is deletable, not portable.) This is the strongest signal to swap the substrate rather than patch it.
- **Access-pattern ↔ provider-class match.** Classify the workload's real access pattern — on-demand spawn-and-teardown vs. persistent stateful workspace; stream vs. batch; request/response vs. long-running; read-heavy vs. write-heavy. Then pick the provider class *built* for that pattern. A mismatch between the real pattern and the class you forced it onto is usually the root of the accidental complexity.
- **"Nobody hand-builds this" heuristic — run it as a field survey per use-case.** If the industry solves this capability at the platform layer and no one reimplements it in-app, that is strong evidence to adopt, not build. Make it concrete: **name 3+ real providers/platforms in the same class and how each serves this exact workload** (in their docs' own vocabulary). If all of them serve it with provider-owned lifecycle and your stack hand-rolls a different paradigm, the hand-build is the anomaly that owes the justification. **Verify it** — invoke the `investigation` skill to ground the claim in real vendor docs and public engineering writeups; don't assert an industry standard from memory.
- **Build-vs-buy gradient (ownership + data posture).** Prefer, in order: (1) a **native primitive of a platform you already run** — you own invocation, the provider owns lifecycle, your data stays in your account; (2) a **more-managed third-party vendor** — less to own, but another vendor + margin + data egress; (3) **hand-build** — only when (1) and (2) genuinely don't fit the access pattern. Benchmark the native primitive first, the fully-managed vendor as the comparison.
- **Attribute latency/cost to the right layer first.** Before blaming a provider for the symptom, measure how much of it is *your own* orchestration vs. the provider's primitive. Frequently most of it lives in the layer you're about to delete — which strengthens the swap, or reveals the provider was never the problem.
- **Audit the incumbent premise's provenance.** Every load-bearing number justifying the *existing* architecture must trace to a **measurement or an invoice** — never a timeout constant remembered as a measurement, a hard cap misread as a latency, or a modeled cost never checked against a bill. If no metric even splits the provider's layer from your own (provider-create vs. your convergence), the premise is **unfalsifiable by construction** — instrument that split before treating the premise as true.
- **Cost is measured, not assumed.** A substrate swap's cost case is **proven on a real shadow bake**, never booked in advance. Name the one genuine trap of the new class (e.g. snapshotting large state per run can cost more than the compute of a short run) and design around it (resume-from-image per run, not tight suspend/resume loops).
- **Gate, don't cut over.** Land the alignment as a **gated spike** with a measurement plan and a **concrete thin seam** (a provider-adapter interface with the right verbs), not an immediate migration. Keep the substrate-independent core — idempotency/dedup, terminal observability, the router — and delete only what existed to compensate for the mismatch.

**Accommodation tripwires — signals the architecture itself is the mismatch.** A vendor gap can be *real* and still not justify the machinery built around it: the failure mode is **accommodating a real gap with an invented paradigm** instead of re-selecting the primitive (or vendor) — on premises nobody measured. Symptom-scoped RCAs are structurally blind to this (each fix lands *inside* the premise; the machine's size reads as evidence of its necessity), so check these mechanically — any one fires this gate on the **subsystem**, not just this incident:

1. **Management-to-workload ratio** — the lifecycle/orchestration code around a vendor integration dwarfs the workload it dispatches.
2. **Invented vocabulary** — the subsystem's nouns (pool, floor, convergence, admission, wake) appear nowhere in the vendor's docs: you are building a shadow platform for the vendor's missing paradigm.
3. **Fix clustering** — this is the **≥3rd fix in the same subsystem** (Phase 1's count). Each prior fix was symptom-scoped; none re-questioned the premise. Run this phase at the subsystem level — *"should this machinery exist at all?"* — before landing fix N.
4. **Unmeasured premise numbers** — the founding latency/cost figure traces to a constant or a model, not a measurement or an invoice (the provenance audit above).
5. **Defined-but-never-wired vendor primitives** — the vendor's canonical primitive for this exact use-case is declared in your types/config with **zero call sites**. That's the smell you already half-knew.

The ADOPT rail is the industry default — the *undifferentiated heavy lifting* (provisioning, scaling, lifecycle, monitoring) belongs to a managed class; only the *differentiating* core stays owned. But **BUILD / keep-owned has equal billing — the paradigm is not "always adopt".** Adopting is the *wrong* answer, and keeping it owned is the honest one, when adoption would:

- **flatten a data / compliance boundary** one external sink cannot honor (two planes forced into one);
- **duplicate a live owned subsystem** that already does most of it — a delete-legacy / one-architecture violation that *relocates* the problem instead of deleting it;
- **route regulated / customer data upstream of your only redaction boundary**, or force a compliance / BAA pricing floor the vendor must clear or be disqualified;
- **buy nothing over what you must build anyway** (e.g. a release identifier you have to stamp regardless).

When the verdict is BUILD, **scope any vendor to exactly the surface your own stack physically cannot reach** and no further — the disciplined way to consume a vendor is by the physical line, not politics.

**Output of this phase:** an explicit **build-vs-adopt decision** with its rationale. If *adopt*: the capability class and the thin seam that survives. If *build / keep-owned*: a one-line statement of why no provider class fits (or which tripwire disqualified it) — so the next RCA doesn't re-open it.

## Phase 6 — Place the fix to deepen the codebase (invoke `improve-codebase-architecture`)

Whether you build or adopt, the change must land in the **right place**. **Invoke the `improve-codebase-architecture` rubric and follow it** — pull its principles by reading its `SKILL.md` and `codebase-design/SKILL.md` directly rather than firing it via the Skill tool (reading the rubric is the right way to consume another skill inside a pipeline, not a downgrade to paraphrase). Run its Explore-phase questions against the fix: which modules are shallow (interface nearly as complex as implementation), does the deletion test *concentrate* complexity or merely *move* it, where does a pass-through layer beg to be folded. If Phase 4 classed this as an **architecture defect** (no correct test seam), the deepening *is* part of the fix, not a follow-up — expose the seam the design was hiding.

**Delete-legacy / one-architecture gate — the fix must pass this before Phase 7.** This gate is RCA's own, layered on top of the deep-module rubric above; it is *not* part of `improve-codebase-architecture`'s own checks (those stop at deepening candidates), so don't attribute it to that skill. Answer all three explicitly in the RCA document:

- **What path does this fix replace?** Name it. If the fix genuinely adds a *new* capability and replaces nothing (not a fix/workaround pair), say so and why — that is a legitimate "none", not a loophole.
- **Is the replaced path deleted in this same change?** If not, name the specific reason (a staged rollout with a committed removal date; a shared path other callers still need). "I'll delete it later" is a **FAIL** — a fix that leaves a compensating layer next to the thing it compensates for is not placed, it's added.
- **How many architectures exist for this capability after the fix lands?** State the number. Anything other than **one** — a backwards-compat shim, a dual old/new path, a "keep it just in case" flag — is a **FAIL** by default and needs the same explicit justification as above.

A FAIL on any of the three sends the fix back to re-placement — do not carry a second architecture for a capability that already had one into Phase 7.

## Phase 7 — Adversarially refute the fix / guardrail

Before trusting the remediation — **especially any guardrail** meant to prevent recurrence — try to **refute** it. Run a separate skeptical pass that defaults to "insufficient" until proven, checking:

- Does the guardrail trigger on artifacts the **fix itself introduced**, rather than on the real failing surface? (false-security)
- Does it assert the value is **present somewhere**, rather than **correct on the real surface**?
- Does a test **exist** but not **exercise the failing path**? (a dry-run/safe-mode green that skipped the mutating phase; a test that sits in no CI merge-gate glob; a job that reports green while never running)
- Is the guardrail **scoped to a broader class** than it actually covers?
- Is a **known-error record's fingerprint release-fragile** — keyed on stack frames or message text so a refactor re-buckets it and its stale/regressed status silently never fires? (The ledger key must be a normalized `action` + opaque-`ref`, never raw stack/message — see Phase 8.)

Empirically, a majority of proposed guardrails fail at least one of these on first draft. **Do not ship a prevention that has not survived this refutation.**

## Phase 8 — Write the RCA + the standing invariant

Produce the complete RCA document:

- **Symptom** — exact, with the authoritative-signal evidence from Phase 1.
- **Timeline** — onset vs. changes; what was exonerated and *why*.
- **Root cause** — the confirmed hypothesis and the **red-capable signal** that proved it.
- **Failure class** — from Phase 4.
- **Remediation** — the build-vs-adopt decision and the Provider-alignment rationale from Phase 5.
- **Fix placement** — how it deepens the codebase and which legacy path it deletes.
- **Prevention — the standing invariant.** The lever is a **cheap invariant at the un-mockable layer**, *not* "understand the feature better". Add it in the **same change**: a synth/build-time infra assertion, a static lint that resolves the value to a *real / unique / known* target (presence alone is not enough), or an owner-identity behavioral test — chosen to convert **this exact failure class** from a deploy-only defect into a local-green failure. It must have survived Phase 7. Record it as a **COE-style action item** (named owner, priority, due date), not a vague intention.
- **Fail-open note** — if any degraded branch silently returns a benign shape (empty result + 200, feature silently off), treat it as **permanent-disable until proven otherwise**: loud-fail or carry a health assertion.

**Write it back to the known-error ledger (ITIL known error / KEDB).** A static RCA document is not queryable — the next agent can't inherit it. Emit the finding as a **KEDB-shaped record**: id / **fingerprint**, `root_cause`, `workaround`, `permanent_solution`, `status`, `owner`, related-incident refs — with a **mutable status lifecycle** (`open → resolved-in-change → superseded → stale/regressed`), updated when the permanent fix lands (transition, never delete). **Key it on a stable, PHI-free fingerprint: a normalized `action` + opaque-`ref` tuple — never raw stack frames or exception text.** A message/stack key fails twice: it leaks PII/PHI into the grouping key, *and* it is release-fragile (a refactor renames frames, the "same" issue splits into new buckets, and regression detection misses the recurrence). This closes the loop that makes the harness followable — Phase 1's check-first read is only as good as what prior RCAs wrote here.

**Where the ledger lives — split it; don't build a datastore for it.** Two halves, opposite homes (this is Phase 5's *derive/reuse over build* applied to the ledger itself). **Occurrence** ("which signature failed, on which release, in which tenant, how often") is runtime telemetry → **derive it from the log/telemetry store you already own** — a read-time GROUP BY on the stable signature + release id, `HAVING count ≥ 2` for recurrence. A second event table beside your logs is a **dual-write anti-pattern**: lossier than derivation and duplicating a table you already have. **Curation** (root cause, fixing PR/issue/session, status, superseded-by) is agent-authored bookkeeping with **zero runtime consumers** → keep it **version-controlled**: one record per signature in the repo, where your VCS log + commit trailers supply the fixing-commit/issue/session provenance *for free*. Add a derived DB index *over* the git records only when a runtime consumer actually appears (the outgrow path) — never relocate authoring. Two rules fall out: **don't co-locate the RCA state with the plane it debugs** (you can't write to a store that's down to record why it's down), and **`resolved` is bake-gated** — a merged fix is not resolution until real traffic confirms it.

### RCA discipline — the load-bearing rules (recap)

1. **Anchor the issue, then read the terminal status** before theorizing — name the one exact symptom + one falsifiable hypothesis, read the **right** authoritative surface (verify it serves the surface and is live before trusting a `0 results`), and **quote the literal signal**: a paraphrased, mis-counted, or sub-agent-relayed log claim is UNVERIFIED (confabulation is the default failure), and a terminal code's label is not its meaning until you confirm what set it.
2. Pin **onset vs. deploy timestamp** — a change deployed after onset is exonerated.
3. A **red-capable loop before any fix** — no loop, no root cause.
4. **Local green is structurally blind** to the config / data / contract / architecture classes — name the class, then prevent it at the un-mockable layer.
5. Before inventing architecture, run the **Provider ⋈ Technical-Architecture Alignment** gate — adopt the capability class that owns the problem *or* keep-owned when adopting would flatten a boundary / duplicate a live subsystem / breach a data-compliance line; don't hand-build what the platform layer solves, and don't buy what would relocate the problem.
6. **Place the fix to leave exactly one architecture** — invoke the deep-module rubric (`improve-codebase-architecture`), delete the path the fix replaces **in the same change**, and clear the delete-legacy / one-architecture gate before Phase 7; a compensating layer left beside the thing it compensates for is not placed, it's added.
7. **Fix clustering fires a premise re-audit** — the ≥3rd fix in one subsystem escalates Phase 5 to the subsystem itself ("should this machinery exist?"); any number justifying the incumbent architecture must trace to a **measurement or invoice** (an unmeasured premise is unfalsifiable by construction), and the field survey names how real peers serve the use-case.
8. **Adversarially refute** every guardrail before trusting it.
9. The prevention is a **cheap standing invariant added in the same change**, proven on real signal — not a promise to be more careful.
10. **Consume and contribute to the known-error ledger** — check the fingerprint first (is this a regression with a known prior fix?), and write the finding back (KEDB-shaped, stable PHI-free fingerprint) so the next agent inherits it. A static RCA doc is not a ledger.
11. **Blameless** — judge the change and the systems, never the author; scrub the trail at the write boundary before consuming it.

> **See also — incident command (ICS).** This skill drives *post-hoc RCA*, a separate activity from *live* incident command (Google SRE / PagerDuty): during an incident the Incident Commander coordinates mitigation and does **not** touch the system, and the postmortem is written *after*. Don't fold firefighting into the RCA — mitigate first (elsewhere), root-cause here.
