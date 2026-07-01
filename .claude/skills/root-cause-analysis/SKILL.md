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

Ground the symptom in the **authoritative signal** — the logs, the run's terminal status, the monitoring, the store's actual state — **not** local state, **not** the dispatch/API response (an async invoke hides crashes behind a 200), **not** a screenshot.

**Read the run's TERMINAL status first.** A run that ended in "resource/capacity/quota not acquired" means no work code ever ran — so a code-path wedge is *not* the cause, and theorizing about one wastes the RCA. A stuck or slow run is not evidence of a code wedge until you have read its terminal outcome. First read the outcome; then theorize.

Establish and write down: the **exact symptom**, the **first-seen timestamp** (onset), the **blast radius**, and **which authoritative surface** you are reading (name it — reading the wrong log group manufactures a confident-but-wrong RCA). Frame blast radius as **Kepner-Tregoe IS / IS-NOT** — what *is* affected vs. what is *not*: a valid cause must explain **every IS and every IS-NOT**, and the IS-NOT column is the refutation data a single-cause chain never collects.

**The authoritative signal includes the distributed trace.** Reconstruct the execution path from the span tree (invoke-agent → chat per model call → execute-tool per tool call), including **cross-agent** traces — one agent's failure is often another's ambiguous output several steps upstream. Provenance ids you consume (correlation / session / release-SHA / PR / actor) are trustworthy only if **server-stamped or deploy-time-derived** — a caller-asserted id is untrusted (log-injection class). And never read or forward an **un-scrubbed** trail: an error/trace sink captures *upstream* of business-data redaction, so it must be scrubbed at the write boundary before any agent consumes it.

**Check the known-error ledger first.** Before theorizing, query the ledger (see Phase 8) for a matching **fingerprint** — a prior RCA may already own this exact failure, or show it was resolved-then-reopened (a **regression**, not a fresh bug, with a known prior root cause and fix to start from).

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
- **"Nobody hand-builds this" heuristic.** If the industry solves this capability at the platform layer and no one reimplements it in-app, that is strong evidence to adopt, not build. **Verify it** — invoke the `investigation` skill to ground the claim in real vendor docs and public engineering writeups; don't assert an industry standard from memory.
- **Build-vs-buy gradient (ownership + data posture).** Prefer, in order: (1) a **native primitive of a platform you already run** — you own invocation, the provider owns lifecycle, your data stays in your account; (2) a **more-managed third-party vendor** — less to own, but another vendor + margin + data egress; (3) **hand-build** — only when (1) and (2) genuinely don't fit the access pattern. Benchmark the native primitive first, the fully-managed vendor as the comparison.
- **Attribute latency/cost to the right layer first.** Before blaming a provider for the symptom, measure how much of it is *your own* orchestration vs. the provider's primitive. Frequently most of it lives in the layer you're about to delete — which strengthens the swap, or reveals the provider was never the problem.
- **Cost is measured, not assumed.** A substrate swap's cost case is **proven on a real shadow bake**, never booked in advance. Name the one genuine trap of the new class (e.g. snapshotting large state per run can cost more than the compute of a short run) and design around it (resume-from-image per run, not tight suspend/resume loops).
- **Gate, don't cut over.** Land the alignment as a **gated spike** with a measurement plan and a **concrete thin seam** (a provider-adapter interface with the right verbs), not an immediate migration. Keep the substrate-independent core — idempotency/dedup, terminal observability, the router — and delete only what existed to compensate for the mismatch.

The ADOPT rail is the industry default — the *undifferentiated heavy lifting* (provisioning, scaling, lifecycle, monitoring) belongs to a managed class; only the *differentiating* core stays owned. But **BUILD / keep-owned has equal billing — the paradigm is not "always adopt".** Adopting is the *wrong* answer, and keeping it owned is the honest one, when adoption would:

- **flatten a data / compliance boundary** one external sink cannot honor (two planes forced into one);
- **duplicate a live owned subsystem** that already does most of it — a delete-legacy / one-architecture violation that *relocates* the problem instead of deleting it;
- **route regulated / customer data upstream of your only redaction boundary**, or force a compliance / BAA pricing floor the vendor must clear or be disqualified;
- **buy nothing over what you must build anyway** (e.g. a release identifier you have to stamp regardless).

When the verdict is BUILD, **scope any vendor to exactly the surface your own stack physically cannot reach** and no further — the disciplined way to consume a vendor is by the physical line, not politics.

**Output of this phase:** an explicit **build-vs-adopt decision** with its rationale. If *adopt*: the capability class and the thin seam that survives. If *build / keep-owned*: a one-line statement of why no provider class fits (or which tripwire disqualified it) — so the next RCA doesn't re-open it.

## Phase 6 — Place the fix to deepen the codebase (apply `improve-codebase-architecture`)

Whether you build or adopt, the change must land in the **right place**. Apply the **`improve-codebase-architecture`** principles: the fix should *deepen* the codebase — fold shallow modules, honor the deletion test, and leave **exactly one architecture** behind (delete the path it replaces; no parallel old/new, no "keep it just in case" flag). If Phase 4 classed this as an **architecture defect** (no correct test seam), the deepening *is* part of the fix, not a follow-up — expose the seam the design was hiding.

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

### RCA discipline — the load-bearing rules (recap)

1. Read the **terminal status** before theorizing; read the **right** authoritative surface.
2. Pin **onset vs. deploy timestamp** — a change deployed after onset is exonerated.
3. A **red-capable loop before any fix** — no loop, no root cause.
4. **Local green is structurally blind** to the config / data / contract / architecture classes — name the class, then prevent it at the un-mockable layer.
5. Before inventing architecture, run the **Provider ⋈ Technical-Architecture Alignment** gate — adopt the capability class that owns the problem *or* keep-owned when adopting would flatten a boundary / duplicate a live subsystem / breach a data-compliance line; don't hand-build what the platform layer solves, and don't buy what would relocate the problem.
6. **Adversarially refute** every guardrail before trusting it.
7. The prevention is a **cheap standing invariant added in the same change**, proven on real signal — not a promise to be more careful.
8. **Consume and contribute to the known-error ledger** — check the fingerprint first (is this a regression with a known prior fix?), and write the finding back (KEDB-shaped, stable PHI-free fingerprint) so the next agent inherits it. A static RCA doc is not a ledger.
9. **Blameless** — judge the change and the systems, never the author; scrub the trail at the write boundary before consuming it.

> **See also — incident command (ICS).** This skill drives *post-hoc RCA*, a separate activity from *live* incident command (Google SRE / PagerDuty): during an incident the Incident Commander coordinates mitigation and does **not** touch the system, and the postmortem is written *after*. Don't fold firefighting into the RCA — mitigate first (elsewhere), root-cause here.
