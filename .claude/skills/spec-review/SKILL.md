---
name: spec-review
description: Multi-model spec verification pipeline. Linear flow (no compaction) — mines session design decisions PLUS the spec's full context lineage (ticket, cited ADRs, prior sessions, memory, known-error ledger) into generated review questions, dispatches 12 parallel reviewers (9 Claude including provider-fit, edge-case, security, observability, live-evidence premise auditor, and cross-worktree drift scout + 3 Codex including industry research) plus the investigation skill's dynamic Workflow grounding the elevation lane, then runs a per-finding falsifier wave (a disprove-step on every CRITICAL/MAJOR before it reaches the report) and fixes only real design defects in the spec prose. Never injects review scaffolding (matrices/EC/Sec/Obs/Drift tables) into the spec.
---

# Spec Review — Multi-Agent Verification Pipeline

12 focused reviewers run in parallel — 9 Claude agents (completeness, codebase, architecture, provider-fit, edge-case miner, security miner, observability auditor, **live-evidence premise auditor**, spec drift scout) + 3 Codex (standard + adversarial + industry research) — each with a tight prompt and one job, **plus the investigation skill's dynamic Workflow grounding the elevation lane** (it frames the spec's core themes against THIS codebase, fans out across sources, adversarially cross-verifies, and returns code-anchored industry-standard + best-in-class elevation evidence). Before the wave, a **Context Dossier Miner** walks the spec's full lineage (ticket, cited-ADR bodies, prior program sessions, project memory, known-error ledger, flow registry, open PRs) and GENERATES spec-specific review questions injected into every lane. After the wave, a **per-finding falsifier pass** attempts to refute every CRITICAL/MAJOR before it reaches the report. The drift lane scans sibling worktrees/specs/open PRs across the project scope so parallel work does not silently diverge. All Codex agents have web access enabled. The coordinator synthesizes and applies fixes.

**Trigger:** "review this spec", "verify the spec", "run spec review", "gap analysis"

**Prompt templates:** `prompts/design-decisions-extractor.md`, `prompts/context-dossier-miner.md`, `prompts/completeness-reviewer.md`, `prompts/codebase-verifier.md`, `prompts/architecture-auditor.md`, `prompts/provider-fit-auditor.md`, `prompts/edge-case-miner.md`, `prompts/security-miner.md`, `prompts/observability-auditor.md`, `prompts/live-evidence-auditor.md`, `prompts/spec-drift-scout.md`, `prompts/spec-drift-investigator.md`, `prompts/finding-falsifier.md`, `prompts/codex-standard-reviewer.md`, `prompts/codex-adversarial-reviewer.md`, `prompts/codex-research-auditor.md`

## Skill Memory (LEARNINGS.md)

**Before starting:** Read `LEARNINGS.md` in this skill directory. Also read the private overlay if present — `~/.claude/skills-overlay/spec-review/LEARNINGS.md` (adopter-private accumulated learnings; never in this public repo). Apply entries under **What Worked** and **Patterns**; use **Open Questions** to spot decisions that still need care.

**Before ending — route each learning by scope; NEVER append to this repo's committed `LEARNINGS.md` (a read-only curated seed):** operator-private skill craft → `~/.claude/skills-overlay/spec-review/LEARNINGS.md` (create if absent); project-specific facts → the project's `.claude/memory/`; universal craft worth publishing → note it for `/improve-harness` to promote (de-identified) into the seed via PR. Full routing: [`docs/skill-memory.md`](../../../docs/skill-memory.md).

---

## Severity Taxonomy (shared across spec-review, spec-test-plan, spec-test-execute)

Canonical severity vocabulary. Every finding normalizes to one of these three. Reviewer outputs that use different words (critical/high/medium/low) map as shown.

| Unified | Codex (critical/high/medium/low) | Claude (CRITICAL/MAJOR/MINOR) | What it means |
|---|---|---|---|
| **CRITICAL** | critical | CRITICAL | Security, data loss, compliance, or rollback safety. Block ship. |
| **MAJOR** | high, medium (when user-facing) | MAJOR | Correctness, availability, contract break. Fix before release. |
| **MINOR** | low, medium (when internal-only) | MINOR | Performance, cosmetic, edge case. Can ship with a tracked follow-up. |

Research Auditor's **ELEVATE** and **CAUTION** tags are NOT in this scale — they live in the Industry Insights section and require user judgment.

---

## Why This Exists

A spec written in a long session accumulates blind spots. This skill breaks that with:
1. **Session decision-mining** — recovers the design decisions, rejected alternatives, and user corrections from the session so reviewers judge against intent, not just the prose. Runs as a direct agent dispatch — **no compaction, no hooks, no resume dance.**
2. **11 parallel reviewers** — each with a focused prompt and one job
3. **Multi-model** — Claude (Opus/Sonnet) + 3x Codex GPT-5.6-sol (standard + adversarial + industry research)
4. **Web-enabled research** — all Codex agents run with network access so findings are grounded in real public implementations, CVEs, post-mortems, and RFCs — not just training-data recall
5. **Semantic boundary mining** — the edge-case miner enumerates entity/state/value boundaries the spec is silent on (cardinality, lifecycle, tenancy, encoding, time, concurrency, permission, resource, schema-evolution, forbidden-but-syntactically-valid)
6. **Project-policy security mining** — the security miner reads `docs/security-policy.md` (filled by the user from `templates/security-policy.example.md`) plus the project root `CLAUDE.md`/`AGENTS.md`, and audits the spec against your project's stated rules plus portable security categories (authN/authZ, secret/credential storage, tenant/org isolation, input validation & injection, data-boundary separation, privilege escalation, allowlist/denylist gaps, output sanitization). Cites the project's own policy in every finding — no inventing rules
7. **Cross-worktree drift scouting** — the spec drift scout checks recently pushed changes, dirty worktrees, architecture changes, sibling specs, and in-progress parallel work across the same project scope, then dispatches narrow follow-up investigators only when material drift is found
8. **Code-grounded industry elevation** — the **investigation skill** runs as a dynamic Workflow over the spec's core themes: it frames them against THIS codebase first (every claim cites a real `file:line`), fans out across primary sources, adversarially cross-verifies each load-bearing claim *in code* (refuted/unchecked claims are partitioned out before synthesis), and returns a verified industry-standard + best-in-class elevation brief. This **deepens the elevation lane** — it is the evidence-and-industry backbone that the Codex Industry Research Auditor's single-model external scan gets cross-checked against, so an ELEVATE suggestion two independent lanes agree on lands at high confidence, and an unverified one is flagged as such
9. **Provider-fit auditing** — the **Provider-Fit Auditor** runs the **Provider ⋈ Technical-Architecture Alignment** check: does the spec hand-build an architecture a provider/platform-class already owns (an access-pattern↔class mismatch that ships as compensating glue — tomorrow's incident), *or* adopt a vendor where keeping it owned is the honest answer (adoption would flatten a data/compliance boundary, duplicate a live owned subsystem, or route regulated data upstream of redaction)? Balanced both ways — it flags hand-building-what-a-class-owns AND adopting-what-should-stay-owned, so the "should we build this at all?" question is answered *before* the design ships. And it fires on **inherited** architecture too (PF-7): when the spec extends an existing vendor-adjacent subsystem, it audits whether that subsystem exists only to *accommodate a provider mismatch* — tripwires: fix-cluster history ≥3, management-to-workload LOC ratio, invented vocabulary absent from the vendor's docs, premise numbers that trace to constants/models instead of measurements/invoices, and the vendor's canonical primitive defined with zero call sites
10. **Observability & traceability auditing** — the **Observability & Traceability Auditor** audits whether the spec ships its own telemetry: named structured events with a request-threading correlation id + a release/version stamp, an **authoritative terminal status** for async work (never inferred from a dispatch/`202` ack), metrics emitted at a granularity their alarms can actually see, a stable PII-free error fingerprint, observable fail-open branches, and a nameable log/telemetry destination. Its premise: a change that ships without its instrumentation is a future RCA run blind — the false-positive, wrong-source, and "we can't tell what failed" incidents all trace back to a spec that never said how the thing would be seen. Distinct lane from the security miner (policy) and edge-case miner (semantic boundaries)

> **Findings, not procedures.** This skill reports problems and fixes real design defects in the spec *prose*. It must NEVER inject its own scaffolding into the spec file — no traceability matrices, no EC-N / Sec-N / DRIFT-N tables, no "review lanes" or checklists. Those live in the **review report** (a sibling file or chat output), never in the spec. A spec describes the design; it does not carry the machinery of the review that touched it.

---

## Flow

### Step 1: Identify the Spec

Confirm which spec file to review. If not provided:
```bash
ls -lt docs/specs/*.md | head -5
```

Read the spec file completely.

### Step 2: Capture context + mine session decisions (linear — no compaction)

The flow is a straight line: capture context → mine decisions → dispatch reviewers → report → apply real fixes → commit. **No `/compact`, no post-compact hook, no state file, no resume.** Do both of the following inline, then go straight to Step 3.

**2a. Write the "why" context block** (5-10 lines, from the conversation you already have):
- **Goal:** What problem prompted this spec?
- **Trigger:** What started this work?
- **Target outcome:** What does success look like?
- **Scope boundaries:** What was ruled out?

Skip implementation details, design debates, and rejected alternatives. Keep this block in hand for the reviewers.

**2b. Generate the session-decisions JSON** (the structured artifact the dossier agent reads). Pick the matching runtime; record the output path and runtime.

- **Claude Code** (`$CLAUDE_SESSION_ID` is set):
  ```bash
  python3 .claude/skills/claude-sessions/sessions.py extract-decisions \
    --sid "$CLAUDE_SESSION_ID" \
    --output "/tmp/spec-review-decisions-${CLAUDE_SESSION_ID:0:8}.json"
  ```
  (The path is repo-relative; if the skill is installed globally, use its installed path — e.g. `~/.claude/skills/claude-sessions/sessions.py` — instead.)
- **Codex** (driving from a Codex session instead): same command, Codex miner, identical output schema (`runtime: "codex"`):
  ```bash
  python3 .claude/skills/codex-sessions/scripts/sessions.py extract-decisions \
    --sid "<codex-rollout-id>" \
    --output "/tmp/spec-review-decisions-codex.json"
  ```
  (The rollout id is the newest `~/.codex/sessions/**/rollout-*.jsonl`'s `session_id`, or `codex-sessions/scripts/sessions.py list`. Use `~/.claude/skills/...` paths if installed globally.)

If decision-mining fails or there's no session to mine (e.g. the spec arrived from elsewhere), skip it — proceed with just the spec + the 2a context block. The reviewers still run; they simply lose the decisions cross-check. Not a blocker. **On a RESUMED session with an empty transcript, mine the PRIOR session's transcript (where the decisions were actually made) — resolve it via Session-Id trailers on commits touching the spec — rather than falling straight back to a spec-derived proxy dossier.**

**2c. Dispatch the Context Dossier Miner** (`prompts/context-dossier-miner.md`) — **mandatory, in parallel with Step 3**:
- **Agent type:** `general-purpose` | **Model:** `opus`
- It mines the planes no reviewer reads on its own: the tracker ticket body + comments + blocker graph, every cited ADR/doc BODY (citation-inversion check + zero-call-site primitives + numbered-artifact collisions), prior program sessions (cross-session decision mining), project memory + the known-error/RCA ledger + fix-cluster history, the flow registry, sibling specs and open PRs.
- It returns a **ground-truth dossier** + **8–15 generated, spec-specific review questions**, each tagged with the lane that should own it.
- **Inject its output into every reviewer prompt** in Step 4 (append the dossier + that lane's questions to each prompt). The generated questions also seed the Codex adversarial `<FOCUS_TEXT_FROM_COORDINATOR>` block — this mechanizes the pre-injection practice (coordinator-scanned concerns confirm at ~85–100% across runs) instead of leaving it to coordinator diligence.

**2d. Mechanical pre-filter (coordinator, inline, cheap).** Before spending reviewer tokens, resolve every deterministically-checkable claim yourself: `git fetch origin` + pin the merge-base; grep symbols the spec names; check the live-schema snapshot for named tables/columns; run any existing parity/allowlist test the spec touches; `gh pr list --state open` for surface overlap. Facts resolved here go into the dossier as ground truth — a claim answerable by a query never goes to an LLM lane.

**2e. Pick the review profile — sanctioned, logged, never silent.** Right-sizing is allowed ONLY as a named profile, and the report must state which profile ran and which lanes were dropped:
- **full** (default for any spec doc): all 12 reviewers + investigation.
- **focused** (surgical single-seam change): codebase-verifier + edge-case miner + live-evidence (if a live surface) + ONE Codex adversarial + the falsifier wave. Dossier miner still runs.
- **hotfix** (prod-down, minutes matter): codebase-verifier + one Fable `critic` seeded with the dossier's generated questions.
Rules: (a) **domain-triggered lanes are non-droppable** — a spec adding a credential/table/authz surface always gets the security miner, a spec touching a live runtime always gets live-evidence, whatever the profile; (b) **line-count is not the risk axis, blast-radius is** — a 47-line spec touching a core reducer gets `full`; (c) **lane-manifest assertion**: before reporting, verify every announced lane actually produced output (list the output files/agent returns) — announced-but-never-dispatched lanes have happened twice; (d) the report's reviewer line lists dropped lanes as `SKIPPED (<profile>)`, never silently.

### Step 3: Synthesize the Decisions Dossier

Dispatch the **Design Decisions Extractor** agent using `prompts/design-decisions-extractor.md`:
- **Agent type:** `general-purpose` | **Model:** `haiku`
- Fill in `{{DECISIONS_JSON_PATH}}` with the path from 2b and `{{RUNTIME}}` with the runtime (`claude`/`codex`)

The agent reads the structured JSON (user-turn windows, files-edited, commits, tool distribution) and returns a dossier: key decisions, rejected alternatives, user corrections, scope, concerns, requirement quotes, gaps & ambiguities. **You do NOT read the JSON yourself.** (Skip this step if 2b was skipped.)

### Step 4: Dispatch 12 Reviewers in Parallel

Read the spec with fresh eyes. Then dispatch ALL 12 primary reviewers simultaneously — they are independent. Append the Context Dossier (Step 2c) + that lane's generated questions to every prompt. **Keep lanes independent — no shared scratchpad, no lane sees another lane's output** (shared-context debate amplifies correlated bias; independence keeps errors uncorrelated for the falsifier + synthesis).

**Agent 1 — Completeness & Alignment** (`prompts/completeness-reviewer.md`):
- **Type:** `general-purpose` | **Model:** `opus`
- **Input:** spec path, dossier content, context block
- **Job:** Cross-check dossier against spec. Decisions reflected? Rejected alternatives sneaking in? User corrections honored? Structural completeness. Requirements coverage.

**Agent 2 — Codebase Verifier** (`prompts/codebase-verifier.md`):
- **Type:** `Explore` | **Model:** default (sonnet)
- **Input:** spec path, project root
- **Job:** Do referenced files exist? Duplicates? Stale code? Repeat-fix hotspots? Dependency impact?

**Agent 3 — Architecture & Simplicity** (`prompts/architecture-auditor.md`):
- **Type:** `general-purpose` | **Model:** `opus`
- **Input:** spec path, project root
- **Job:** Architectural fit, abstraction level, peer consistency, simplicity, workaround detection, maintenance burden, **platform invariants compliance** (if the project has a `docs/PLATFORM-INVARIANTS.md` file, spec claims are cross-checked against every invariant — violations are CRITICAL/MAJOR by default), and **deep-module fit** — it invokes the `improve-codebase-architecture` + `codebase-design` rubric (reading their `SKILL.md`s directly rather than paraphrasing from memory — so future updates to them propagate) and audits the spec's proposed design against the deletion test, shallow-vs-deep modules, and testability-through-the-interface, naming the deeper shape where the spec bolts on a shallow layer — **plus a delete-legacy / one-architecture gate**: does the spec delete the code path it replaces in the same change, and how many architectures exist for the touched capability afterward? A shim / dual old-new path / "keep it just in case" flag is a CRITICAL FAIL.
- **ADR-conformance lane:** in the same wave, dispatch the dedicated `adr-auditor` agent (Agent tool, `subagent_type: adr-auditor`) — it classifies every spec decision **CONFORMS | STRAYS | NEEDS-APPROVAL** against the Accepted ADRs and platform invariants, and hard-stops any spec that changes an Accepted ADR/invariant without an explicit founder-approval marker.

**Agent 3b — Provider-Fit Auditor** (`prompts/provider-fit-auditor.md`) — first-wave primary (co-dispatched with 1–9; the letter suffix groups it with the Architecture Auditor #3, its sibling — unlike the second-wave 6b):
- **Type:** `general-purpose` | **Model:** `opus`
- **Input:** spec path, project root
- **Job:** Run the **Provider ⋈ Technical-Architecture Alignment** check on the spec's proposed design — ownership-inversion, access-pattern↔provider-class match, "nobody hand-builds this" run as a **field survey per use-case** (name 3+ real providers in the class and how each serves the workload), the build-vs-buy gradient (native-primitive > managed-vendor > hand-build; data posture), the **BUILD-is-correct counter-check** (an adopt that flattens a data boundary, duplicates a live owned subsystem, or routes regulated data upstream of redaction is a wrongful-adopt → CRITICAL), gate-don't-cutover for substrate swaps, and the **inherited-premise audit** (PF-7 — the inverse question on pre-existing architecture the spec extends: accommodation-of-mismatch tripwires incl. fix-cluster history, unmeasured premise numbers, never-wired vendor primitives). Distinct from the Architecture Auditor (which does deep-module fit + simplicity *within* the chosen build) — this lane audits the prior question, *whether to build at all or align to a provider-class*. Balanced both ways: never an "always buy" bias. Its CRITICAL/MAJOR findings feed the Step 5 defect pipeline alongside the Architecture Auditor.

**Agent 4 — Edge-Case Miner** (`prompts/edge-case-miner.md`):
- **Type:** `general-purpose` | **Model:** `opus`
- **Input:** spec path, project root, dossier content
- **Job:** Semantic boundary enumeration on every entity/parameter/state/operation the spec defines — cardinality (0/1/N/max+1), lifecycle states (pre/mid/terminated/post-deletion), tenancy (right/wrong/cross/non-existent), encoding (null/empty/NUL/unicode/max-size+1), time (epoch/DST/skew/leap), concurrency, permissions, resource limits, schema-evolution, forbidden-but-syntactically-valid. Distinct lane from the adversarial reviewer (which targets infra/concurrency/env-divergence) — minimum 18 EC-N rows for non-trivial specs, with `EXPLICIT/IMPLICIT/MISSING` spec-coverage flags.

**Agent 5 — Security Miner** (`prompts/security-miner.md`):
- **Type:** `general-purpose` | **Model:** `opus`
- **Input:** spec path, project root, dossier content
- **Job:** Project-policy security mining. Reads `docs/security-policy.md` (filled by the user from `templates/security-policy.example.md`) + the project-root `CLAUDE.md`/`AGENTS.md`, then audits the spec against your project's stated rules plus portable security categories: authentication & authorization (correct identity source for authz claims, least privilege), secret & credential storage, tenant/org isolation, input validation & injection (SQL/command/path-traversal/SSRF), data-boundary separation, privilege escalation, allowlist/denylist gaps, output sanitization. Flags every Sec-N policy violation. Distinct lane from edge-case-miner (semantic boundaries) and Codex Adversarial (generic infra/race/IAM). Minimum 8 Sec-N rows for non-trivial security-touching specs. **Cites source policy** in every finding — no inventing rules.

**Agent 5b — Observability & Traceability Auditor** (`prompts/observability-auditor.md`) — first-wave primary (co-dispatched with 1–9; the letter suffix groups it with the Security Miner #5, its sibling):
- **Type:** `general-purpose` | **Model:** `opus`
- **Input:** spec path, project root, dossier content
- **Job:** Audit the spec's production observability, tracing, and debuggability plan — does it ship its instrumentation in the same change (observability-driven development); name its structured events + fields + a request-threading **correlation id**; propagate standard **trace context** (W3C `traceparent`) across service/async boundaries; stamp telemetry with the **release/version** (onset-vs-deploy); record an **authoritative terminal status** for async/queued work rather than inferring success from a dispatch/`202` ack; emit **metrics at a granularity its alarms can see**; keep high-cardinality/PII out of metric labels and secrets/PII/PHI out of all fields; fingerprint failures on a **stable PII-free action+ref key**; make **fail-open branches observable**; and name the **log/telemetry destination** that serves the surface. Distinct lane from the Security Miner (policy violations) and Edge-Case Miner (semantic boundaries). Minimum 6 Obs-N rows for a runtime-touching spec, severity per the prompt's taxonomy. Its findings get their own report section (like Edge-Case/Security) — not cross-examined.

**Agent 5c — Live-Evidence Premise Auditor** (`prompts/live-evidence-auditor.md`) — first-wave primary; **gated: dispatch only when the spec touches a LIVE surface** (existing runtime path, deployed config/flag, prod data, wired provider); greenfield-only specs record `SKIPPED (no live surface)`:
- **Type:** `general-purpose` | **Model:** `opus` | **Strictly read-only**
- **Input:** spec path, project root, dossier content, the project's documented evidence surfaces (observability CLI/profiles, DB read tools, schema snapshots — from CLAUDE.md/AGENTS.md and the operator overlay)
- **Job:** Extract the spec's **load-bearing premises** and FALSIFY each against live evidence, not prose: the DEPLOYED value of every flag/config the design assumes; live schema/signatures/rows (provenance `SELECT DISTINCT`s, duplicate keys under a proposed unique constraint, dedup-key dry-runs against the real fleet, row-size × page-size × channel-cap arithmetic); **upstream trigger liveness** for any flow the spec extends or bakes against (0-invocations = the bake plan is theatre); DNS/infra reads for provisioning claims; and **budget traceability** — every timeout/budget/cap number must trace to a measurement or a named repo constant. Includes the **bake-feasibility check**: prove the spec's own §bake can actually run (trigger alive, auth reachable, metric emitted). Output is the LE-N table; its CRITICAL/MAJOR rows feed the Step 5 defect pipeline. This is the lane for the single biggest documented miss class — the unverified live-state premise.

**Agent 6 — Spec Drift Scout** (`prompts/spec-drift-scout.md`):
- **Type:** `general-purpose` | **Model:** `sonnet`
- **Input:** spec path, project root, dossier content
- **Job:** Search the whole local project scope, not just the current worktree: recent pushed refs, dirty worktrees, architecture docs, feature surfaces, sibling specs, review files, and test plans. Produces evidence-backed drift candidates and a narrow investigator dispatch plan. This is a scout pass — it does not edit files or deep-read every candidate.

**Agent 7 — Codex Adversarial Review:**
- **Execution:** `codex exec` via Bash with `run_in_background: true`
- **Model:** GPT-5.6-sol, high reasoning effort
- **Input:** The SPEC FILE content (NOT git diff — the companion's `adversarial-review` reviews git changes, which is wrong for spec review)
- **Job:** Attack surface analysis. Auth/permissions, data loss, rollback safety, race conditions, version skew, observability gaps, architectural fit, simplicity.

**Agent 8 — Codex Standard Review:**
- **Execution:** `codex exec` via Bash with `run_in_background: true`
- **Model:** GPT-5.6-sol, high reasoning effort
- **Input:** The SPEC FILE content (NOT git diff)
- **Job:** Completeness, correctness, feasibility, type safety, implementation gaps, stale code detection. **Web access enabled** — Codex cross-references API/library/standard claims against authoritative sources.

**Agent 9 — Codex Industry Research Auditor:**
- **Execution:** `codex exec` via Bash with `run_in_background: true`
- **Model:** GPT-5.6-sol, high reasoning effort
- **Input:** The SPEC FILE content (NOT git diff)
- **Job:** **Elevation, not defect-hunting.** Pick 3-6 core themes from the spec. For each, research the web + GitHub for (a) maintained OSS libraries that already solve it, (b) public engineering writeups from big companies (Stripe/Netflix/Google/Meta/Airbnb/etc.) showing how they shipped it at scale, (c) production gotchas those companies hit. Output grounded, URL-cited refactor suggestions. Two soft severities: **ELEVATE** (proven public pattern worth adopting) and **CAUTION** (spec contradicts established best practice).

**IMPORTANT: Do NOT use the companion script's `review` or `adversarial-review` commands.** Those commands review git working tree diffs — they feed Codex the code changes, NOT the spec file. For spec review, Codex must read and review the SPEC document.

**Composing the Codex prompts:** Use the exact dispatch patterns from `prompts/codex-standard-reviewer.md`, `prompts/codex-adversarial-reviewer.md`, and `prompts/codex-research-auditor.md`. Before dispatching, scan the spec for 3-6 specific risk concerns to inject into the adversarial prompt's `<FOCUS_TEXT_FROM_COORDINATOR_IF_ANY>`.

**All 12 primary reviewers dispatch at the same time.** The 9 Claude agents via the Agent tool, all 3 Codex reviews via separate Bash calls.

**Dispatch invariants** (all mandatory):
- `run_in_background: true` on the Bash tool — **no trailing `&`** in the command. Three separate Bash calls = parallel execution with completion notifications.
- `echo '' |` prefix — prevents stdin hang
- `$$` in output path — prevents collisions (three distinct output files: `codex-spec-std-$$.txt`, `codex-spec-adv-$$.txt`, `codex-spec-research-$$.txt`)
- `2>&1 | tee FILE` — captures output (no `&`)
- **All three Codex calls use `--sandbox workspace-write` + `--config sandbox_workspace_write.network_access=true`** — web access is required for all of them, not just research
- RELATIVE spec path (not absolute)
- **No JSON templates, no markers, no output format examples in the prompt** — Codex echoes them back as fake output
- **Never use `companion review` or `companion adversarial-review`** — those review git diffs, not spec files

**Agent 11 (same parallel wave) — Investigation Workflow (elevation grounding).** In the same wave as the 12 reviewers, launch the **investigation skill** on the spec's core themes — this is the deepened elevation lane (see Step 5c). It runs as a background dynamic Workflow, so launch it now and collect it in Step 4c alongside Codex.

1. Scan the spec for its **3–6 core themes** — reuse the same scan that seeds the Codex Research Auditor (Agent 9).
2. Invoke the investigation skill (it **always** runs as a dynamic Workflow — frame → research → adversarial-verify → synthesize) with a premise like:
   > Ground the **industry standard + best-in-class elevation** for these spec themes, framed against THIS codebase: `<themes>`. Spec: `<spec path>`. Return the verified industry-standard + elevation evidence — each claim code-anchored (`file:line`) or carrying a live source URL.
   Use `Skill(skill="investigation")` with that premise, or launch its `DEEP-WORKFLOW.md` template directly via the Workflow tool with `args.premise = <the premise>` and `args.n` sized to the theme count (3–6).
3. It writes a grounded brief to `docs/investigations/YYYY-MM-DD-<slug>.md`. Its `industry_standard` + `elevation` sections feed the **Industry Insights** section in Step 5c — they do **not** enter the defect-classification pipeline (Step 5) and are **never** injected into the spec.

**Why a separate lane from Codex Industry Research (Agent 9):** the investigation lane is **code-grounded** (it frames against this repo *before* searching) and **verified in code** (claims partitioned verified vs untrusted before synthesis); the Codex auditor is a **second model's external-only** scan. Run both — two independent lanes agreeing on an ELEVATE = high confidence; investigation's verified evidence wins when it contradicts an unverified Codex ELEVATE/CAUTION.

**Runtime note:** the investigation skill + Workflow tool are **Claude Code-only**. When you drive spec-review from another runtime (e.g. Codex CLI, where Step 2b had no `$CLAUDE_SESSION_ID`), skip this lane — the Codex Industry Research Auditor (Agent 9) carries the elevation lane alone.

### Step 4b: Progressive Drift Investigation

When the **Spec Drift Scout** returns, read its report immediately. Do not wait for Codex if the scout has already finished — use that time to dispatch narrow second-wave investigators while the Codex reviews continue.

**When to dispatch drift investigators:**
- Scout reports `Needs Investigator: yes`
- Any `DRIFT-N` finding is CRITICAL or MAJOR
- Recommended action is `combine-specs`, `move-section`, `split-new-spec`, `create-missing-spec`, or `update-other-spec`
- The scout found a dirty or recently pushed worktree that appears to own the same architecture boundary or feature surface

**How to dispatch:**
- Use `prompts/spec-drift-investigator.md`
- One investigator per drift candidate or tightly related cluster
- Max 5 investigators by default; if more are needed, group by feature surface and ask the user before expanding
- Each investigator gets the target spec, the scout finding, exact paths/worktrees/specs to read, and one narrow question
- They are read-only. They may propose patches or moves, but they do not edit sibling worktrees

**How to handle results:**
- `update-current-spec` with CRITICAL/MAJOR severity can be applied in Step 5c if evidence is clear and the change is within the target spec's scope
- `update-other-spec`, `combine-specs`, `move-section`, `split-new-spec`, and `create-missing-spec` require an explicit user decision or a follow-up issue; do not silently edit other active worktrees
- `mark-intentional` entries go into the report and, if confirmed by the user, into project memory as an acknowledged divergence
- False positives go under Resolved with the scout/investigator evidence

### Step 4c: Wait for Codex reviews, the Investigation Workflow, and drift investigators

The 9 Claude agents return first (2-6 min; Drift Scout may take longer on projects with many worktrees). Codex reviews run in background and take longer. The Research Auditor may take the longest — web research has latency — budget 20-40 min. The **Investigation Workflow** (Agent 11) also runs in the background and notifies on completion — budget 10-30 min depending on theme count and width; read its saved brief (`docs/investigations/…`) when it lands. Drift investigators, if dispatched, should run in parallel with remaining Codex reviews.

**How to wait:** Use `run_in_background: true` on the Bash dispatch calls. You get notified when each completes. Then **read the output file with the Read tool** and extract findings yourself. No grep, no sed, no checkpoint scripts — you're an LLM, just read the file.

**If a Codex run seems stuck** (no notification after 15+ min for std/adv, 40+ min for research), check if the process is alive:
```bash
pgrep -f "codex exec" && echo "still running" || echo "exited"
```
If exited, read the file. If still running, let it finish — Codex legitimately runs 20-40 min on complex specs, and research can run longer.

**Codex-down fallback (standing policy — never improvise it per-run).** A tee file ending in a usage-limit/auth error ("You've hit your usage limit", 401) means the lane is DEAD for this run. Do NOT blind-retry (2-strike rule). Instead:
1. **Adversarial substitute:** dispatch ONE Fable-pinned `critic` agent (Agent tool, `subagent_type: critic`, model `fable`) with the spec + the same FOCUS concerns/generated questions the Codex adversarial got. Across 6+ documented Codex-down runs this substitute found the run's deepest criticals.
2. **Elevation substitute:** the Investigation Workflow (Agent 11) carries the elevation lane alone; if a <24h investigation brief on the same themes already exists, reuse it instead of re-launching. Optionally add one web-enabled Claude research lane (general-purpose + WebSearch) as the external cross-check.
3. **Report honestly:** the Final Report's verdict lines say `timed-out/usage-limit — backfilled by <substitute>`; cross-examination (Step 5b) is recorded as unavailable for those lanes.
The same degraded-mode principle applies to a Claude-model/classifier outage: run the lanes on an available model tier rather than zeroing the pipeline, and log the substitution.

Wait for all 12 primary reviewers, the Investigation Workflow (Agent 11), and any second-wave drift investigators to complete before starting Step 5.

### Step 5: Merge & Classify

Collect all 12 primary reports (9 Claude markdown + 3 Codex text/JSON) plus any second-wave drift investigator reports and the Investigation Workflow brief. The Live-Evidence Premise Auditor's LE-N table gets its own report section (like Edge-Case/Security/Obs); its CRITICAL/MAJOR REFUTED-premise rows are auto-applied as prose fixes when in scope. The Research Auditor findings **and the Investigation Workflow brief** are handled separately — they go into the Industry Insights section (see Step 5c) and do NOT feed the defect-classification pipeline below. The Edge-Case Miner, Security Miner, Observability Auditor, and Spec Drift Scout/Investigators are also handled in their own sections (see Step 5c) — CRITICAL/MAJOR Edge-Case rows with `Spec Coverage: MISSING`, CRITICAL/MAJOR Security rows, CRITICAL/MAJOR Observability rows, and CRITICAL/MAJOR drift findings with `update-current-spec` action are auto-applied like other consensus issues when scoped to the target spec, but they don't get cross-examined since they do not have a direct Codex peer in this skill. Classify each **defect** finding from the other 6 reviewers (completeness, codebase, architecture, provider-fit, codex-standard, codex-adversarial):

| Codex severity | Claude severity | Unified |
|---|---|---|
| critical | CRITICAL | **CRITICAL** |
| high | MAJOR | **MAJOR** |
| medium | MAJOR/MINOR | **MINOR** |
| low | MINOR | **MINOR** |

**Consensus detection:**
- **2+ reviewers agree** → high confidence — cross-lane agreement is a severity/confidence BOOST, not just a dedup key
- **Codex-only finding** → likely Claude blind spot, investigate
- **Claude-only finding (all 3 agree, Codex approves)** → could be over-flagging, but 3-agent consensus is strong
- **Claude and Codex disagree** → if the split is a REPO FACT (store boundary, symbol existence, schema shape), it goes to a falsifier (below) that resolves it by reading the seam — only genuine judgment splits go to cross-examination (Step 5b)

### Step 5a: Per-Finding Falsifier Wave (mandatory before the report)

For EVERY CRITICAL/MAJOR finding that survived classification, dispatch a **Finding Falsifier** (`prompts/finding-falsifier.md`) — one per finding, batched when trivially related, all in parallel:
- **Type:** `general-purpose` | **Model:** `sonnet` (escalate an individual falsifier to `opus` only for deep multi-file refutations)
- Each falsifier's ONLY job is to REFUTE its finding: spec already covers it / an existing mechanism neutralizes it / the cited evidence doesn't say that / the failure scenario is unreachable. Verdicts: `REFUTED` / `SURVIVES` / `SURVIVES-BUT-FIX-REJECTED` / `NEEDS-LIVE-EVIDENCE`.
- This wave also owns: **citation verification** (every symbol/file/component a reviewer OR a proposed fix introduces into the spec is grep-confirmed — phantom symbols in applied fixes are a recurring external-reviewer catch), **factual-split resolution** (Claude↔Codex repo-fact disagreements resolved by reading the code, not debate), and the **downgrade guard** — the coordinator may NOT downgrade or fold a CRITICAL as "docs-only" unless a falsifier REFUTED it with evidence; an unrefuted CRITICAL keeps its severity (a past instinct-downgrade cost 2 PRs + 3 deploy storms).
- `REFUTED` findings move to the report's **Resolved** section with the refuting evidence. `NEEDS-LIVE-EVIDENCE` items route to the live-evidence lane's method (or land as explicit open risks). Only surviving findings reach Step 5b/5c and the fix step — this is the false-positive filter that keeps applied fixes trustworthy (the production pattern behind it drives reviewer false-finding rates under ~1%).
- Rough budget: this wave is cheap relative to the reviewer wave (sonnet, one narrow question each). Do not skip it in `focused`/`hotfix` profiles — it is precisely what makes reduced profiles safe.

### Step 5b: Cross-Examination — Claude vs Codex Debate

For any MAJOR+ finding where Claude and Codex disagree, run an iterative debate so the user can see both perspectives and decide.

**What triggers cross-examination:**
- Codex flags something MAJOR+ that all 3 defect-hunting Claude agents (completeness, codebase, architecture) missed or dismissed (the Edge-Case Miner, Security Miner, and Drift lane do not participate in cross-examination — their findings have their own sections)
- Claude agents (2+) flag something MAJOR+ that Codex approved
- Claude and Codex propose **conflicting fixes** for the same issue
- Codex adversarial flags a risk that Claude architecture agent explicitly called safe

**How it works:**

1. **Present the disagreement to the user** in a structured format:

```markdown
### Disagreement #N: <topic>

**Codex (GPT-5.6-sol) says:** <summary of Codex position + severity + confidence>
**Claude says:** <summary of Claude position + which agents>

**Key question:** <the specific architectural/design question at the heart of the disagreement>
```

2. **Prompt Codex with Claude's counter-argument** via Bash (resume the session):

```bash
echo "This is Claude (Opus) following up on your review. Re: your finding about <TOPIC>.

Our architecture auditor disagrees because: <CLAUDE_REASONING>
Our codebase verifier found: <EVIDENCE_FROM_CODEBASE>

Specific question: <TARGETED_QUESTION>

Do you still hold your position? If so, what specific evidence would change your mind?" | codex exec --skip-git-repo-check resume --last 2>/dev/null
```

3. **Evaluate Codex's response.** If Codex:
   - **Concedes** → note as resolved, move on
   - **Doubles down with new evidence** → present both positions to user with your assessment
   - **Raises a point Claude missed** → investigate the new claim, update your position

4. **Present the final positions to the user** and ask them to decide:

```markdown
### Decision needed: <topic>

**Codex position:** <updated position after debate>
**Claude position:** <updated position after debate>
**My recommendation:** <which side you lean toward and why>

Should I apply Codex's recommendation, Claude's recommendation, or something else?
```

**Rules for cross-examination:**
- Max **2 rounds** per disagreement (initial + one follow-up) — don't let it spiral
- Only for MAJOR+ disagreements — MINOR disagreements go to the report as-is
- Always identify yourself as Claude when prompting Codex — it's a peer AI discussion
- If Codex raises a genuinely new concern during debate, add it to the findings
- If both models converge after discussion, note it as "resolved via cross-examination"
- **Never auto-resolve a disagreement without user input** on CRITICAL issues

### Step 5c: Final Report

After cross-examination resolves (or goes to user), compile the full report:

```markdown
## Spec Review — Final Report

### Spec: <filename>
### Profile: <full | focused | hotfix> — dropped lanes: <none | list, each `SKIPPED (<reason>)`>
### Reviewers: Completeness (Opus) + Codebase (Sonnet) + Architecture (Opus) + Provider-Fit (Opus) + Edge-Case Miner (Opus) + Security Miner (Opus) + Observability Auditor (Opus) + Live-Evidence (Opus | SKIPPED no-live-surface) + Spec Drift Scout (Sonnet) + Codex Standard (GPT-5.6-sol) + Codex Adversarial (GPT-5.6-sol) + Codex Industry Research (GPT-5.6-sol, web-enabled) + Investigation Workflow (code-grounded, verified)
### Falsifier wave: <N findings falsified: K survived / M refuted / J needs-live-evidence>
### Codex Standard Verdict: <approve|needs-attention|timed-out>
### Codex Adversarial Verdict: <approve|needs-attention|timed-out>
### Codex Research Verdict: <N elevate suggestions / M cautions / timed-out>
### Investigation Verdict: <N verified elevations / M cautions / brief path / skipped (non-Claude runtime) / timed-out>
### Spec Drift Verdict: <clean|N candidates|N investigators|timed-out>

### Consensus Issues (2+ reviewers)
1. [CRITICAL] <issue> — flagged by: <which reviewers>
   Codex confidence: <0.0-1.0> | File: <path>:<line>
   Recommendation: <specific fix>
...

### Codex-Only Findings (investigate — possible Claude blind spot)
Category: Implementation (from standard) / Risk (from adversarial)
1. [severity] <title>
   Body: <finding body>
   File: <path>:<line_start>-<line_end> | Confidence: <score>
   Recommendation: <recommendation>
...

### Edge Cases (from Edge-Case Miner — semantic boundary enumeration)
Kept in its own section — boundary enumeration is structurally different from
defect-hunting. Output is the EC-N table from `prompts/edge-case-miner.md`,
filtered to omit any `Spec Coverage: EXPLICIT` rows (which shouldn't occur).

| EC-ID | Entity / Operation | Boundary | Spec Coverage | Recommended Resolution | Severity |
|---|---|---|---|---|---|
| EC-1 | … | … | MISSING / IMPLICIT | <one-line spec-text addition> | CRITICAL / MAJOR / MINOR |

CRITICAL/MAJOR rows with `Spec Coverage: MISSING` are auto-applied to the spec
in Step 9 (same path as other consensus issues). MINOR rows are reported but
not auto-applied. IMPLICIT rows trigger a one-line spec clarification — make
the implication explicit.

### Security Findings (from Security Miner — project-policy audit)
Kept in its own section — security policy violations are project-specific
and structurally different from generic defect-hunting. Output is the Sec-N
table from `prompts/security-miner.md`. Every row cites a source policy
(`docs/security-policy.md`, `CLAUDE.md`/`AGENTS.md`, or — if the project has
them — `docs/PRODUCT-RULES.md` / `docs/PLATFORM-INVARIANTS.md`).

| Sec-ID | Category | Spec Section | Violation | Severity | Recommended Resolution |
|---|---|---|---|---|---|
| Sec-1 | <1-8> | §X.Y | <policy-violation description> | CRITICAL / MAJOR / MINOR | <spec-text fix> |

CRITICAL/MAJOR Security rows are auto-applied to the spec in Step 9 (same
path as Edge Cases and other consensus issues). MINOR rows are reported but
not auto-applied. If a CRITICAL row touches a surface outside the spec's
scope (e.g. spec is about feature X but security finding is about platform
primitive Y), file a separate GitHub issue rather than expanding scope —
hand the rationale to the user as part of the Final Report.

### Observability & Traceability Findings (from Observability Auditor)
Kept in its own section — a spec's production telemetry plan is structurally
different from defect-hunting. Output is the Obs-N table from
`prompts/observability-auditor.md`. Each row names the checklist category (1-12)
or the project's own observability convention it maps to.

| Obs-ID | Category | Spec Section | Gap | Severity | Recommended Resolution |
|---|---|---|---|---|---|
| Obs-1 | <1-12> | §X.Y | <what the spec is silent on / gets wrong> | CRITICAL / MAJOR / MINOR | <one-line behavioral spec-text fix> |

CRITICAL/MAJOR Observability rows are auto-applied to the spec in Step 9 (same
path as Edge Cases and Security) — but as a **one-line behavioral statement in
prose** (e.g. "the run's terminal status is persisted to the run store, not
inferred from the dispatch ack"), NEVER as a pasted Obs-N table. MINOR rows are
reported, not auto-applied. A CRITICAL row that touches a surface outside the
spec's scope (e.g. the project has no correlation-id primitive at all) → file a
separate issue rather than expanding scope.

### Live-Evidence Premise Audit (from the Live-Evidence Auditor)
Kept in its own section — falsified live-state premises are structurally
different from prose defect-hunting. Output is the LE-N table from
`prompts/live-evidence-auditor.md`, plus the budget-traceability table and the
bake-feasibility verdict.

| LE-ID | Premise (spec §) | Check run | Result | Verdict | Severity |
|---|---|---|---|---|---|
| LE-1 | … | <exact command/query> | <observed> | HOLDS / REFUTED / UNVERIFIABLE | CRITICAL / MAJOR / MINOR |

CRITICAL/MAJOR REFUTED rows are auto-applied to the spec in Step 9 as prose
fixes (correct the premise and whatever design rested on it). UNVERIFIABLE
rows are listed as explicit open risks — never silently dropped. A
`bake-feasibility: THEATRE` verdict is always at least MAJOR.

### Spec Drift Findings (from Spec Drift Scout + optional investigators)
Kept in its own section — this lane checks whether the target spec is drifting
from recently pushed changes, dirty/in-progress worktrees, sibling specs,
architecture changes, feature work, test plans, and review artifacts across the
same local project scope.

**Scope scanned:** <N worktrees/repos scanned; fetched refs or local-only; skipped roots>

| Drift ID | Severity | Evidence | Impact | Recommended Action | Decision |
|---|---|---|---|---|---|
| DRIFT-1 | CRITICAL / MAJOR / MINOR | <worktree/spec/file/commit> | <what goes stale/conflicts> | update-current-spec / update-other-spec / combine-specs / move-section / split-new-spec / create-missing-spec / mark-intentional / no-action | applied / user-decision-needed / follow-up |

CRITICAL/MAJOR drift findings with `update-current-spec` are auto-applied when
the change is unambiguous and inside the target spec's scope. Findings that
touch sibling specs, other active worktrees, spec consolidation, moving sections,
or creating a new spec require explicit user decision or a follow-up issue —
do not silently edit another worktree. `mark-intentional` requires user
confirmation and should become project memory if accepted.

### Claude-Only Findings
1. [severity] <source agent> — <description>
...

### Cross-Examined Disagreements
1. [severity] <topic>
   Claude position: <position>
   Codex position: <position>
   Resolution: <user decision / converged / escalated>
...

### Both Codex Reviews Agree (high confidence — different prompts, same conclusion)
1. [severity] <standard finding> + <adversarial finding> — same file/concern
...

### Provider-Fit / Build-vs-Adopt (from Provider-Fit Auditor)
Its CRITICAL/MAJOR *defect* findings (hand-building what a class owns; a wrongful-adopt that
flattens a boundary / duplicates a live subsystem / routes regulated data upstream of
redaction) are classified with the other defects above and auto-applied as prose fixes when
in scope. Surface its explicit **build-vs-adopt call** separately here as a decision surface —
it is not severity-ranked against defects:

- Workload access pattern: <on-demand / persistent-workspace / batch / stream / …>
- [ADOPT <capability-class>] — <why the class owns it; the thin adapter seam that survives> · Verified: <investigation lane / yes-no>
- [BUILD / KEEP-OWNED] — <which tripwire disqualified adoption: boundary-flattening / live-subsystem-duplication / regulated-data-upstream / buys-nothing> ; scope any vendor to <the surface your stack physically cannot reach>
- [GATE] — substrate swap must land as a gated spike with a measured cost bake + adapter seam

### Industry Insights (elevation, not defects) — Codex Research Auditor + Investigation Workflow
Kept in its own section on purpose — elevation suggestions are NOT severity-ranked against defects. Present as a separate decision surface. **Two independent lanes feed it:** the Codex Industry Research Auditor (Agent 9 — external-only, single-model) and the Investigation Workflow (Agent 11 — code-grounded, adversarially verified in code). Merge them per theme:
- Where **both lanes agree** on an ELEVATE/CAUTION → mark `lane: both` = high confidence.
- Where only the **investigation lane's *verified* evidence** supports a point → keep it (it cleared the in-code verify partition).
- Where a Codex ELEVATE/CAUTION is **unverified** by the investigation lane → flag it `(unverified)` and leave the call to the user; never auto-apply it.
- The investigation brief lives at `docs/investigations/…` — cite it as a source for the points it grounds.

**Theme: <spec theme>**
- [ELEVATE] <OSS library or industry pattern> — <repo URL or blog URL> — `lane: codex | investigation | both`
  Why it fits: <one line> | Evidence: <file:line or live URL> | Refactor suggestion: <concrete change>
- [CAUTION] <spec claim vs. established practice> — <authoritative URL> — `lane: codex | investigation | both`
  What the spec says: <quote> | What the source says: <quote> | Verified: yes/no | Your call: adopt / reject / flag

**Theme: <next spec theme>**
...

### Resolved (non-issues after cross-checking)
- <finding> — resolved because <reason>
...

### Changes Applied
1. <what was changed and why>
...
```

**Apply fixes — design defects only, in prose.** Apply CRITICAL and MAJOR consensus issues by **fixing the actual design problem in the spec's own prose** (correct the mechanism, the boundary, the auth rule, etc.). That is the only thing that gets written into the spec.

**Never inject review scaffolding into the spec file.** Edge-case (EC-N), Security (Sec-N), Observability (Obs-N), and Drift (DRIFT-N) findings, traceability matrices, and "lanes" stay in the **review report** — they are NOT auto-applied as new tables/sections/checklists in the spec. When an EC/Sec/Obs/Drift finding reveals a genuine design defect, fix the design in prose (e.g. "deletes are idempotent" or "terminal status is persisted, not inferred from the ack" as a one-line behavioral statement) — do not paste the finding's table row into the spec. Present every EC/Sec/Obs/Drift/Industry finding to the user in the report and let them decide what, if anything, changes. Industry Insights and CAUTION items are never auto-applied. Out-of-scope findings → file a separate issue, don't expand the spec.

### Step 6: Alignment Investigation (OPTIONAL — off by default)

The core review ends at Step 5c. Alignment investigation is an **optional deep add-on, not part of the default linear flow** — it adds 15-30 min checking strategic drift between decisions and reality. **Do NOT run it by default and do NOT gate the review on it.** Skip straight to Step 9 (Commit) unless the user explicitly asked for alignment investigation (e.g. "also check alignment", or the trigger included it).

Even when requested, skip if: the spec is trivial (<50 lines), no prior specs exist in `docs/specs/`, or no session decisions were mined in Step 2b.

If the user explicitly wants it and it's not skippable, the Alignment Investigator (agent #12) runs as follows:

This step is intentionally narrower than the Spec Drift Scout. Step 4 checks
other worktrees/specs/recent changes for parallel drift. Step 6 checks whether
the target spec's own key claims still match selected code reality after the
review synthesis.

1. Read the synthesis report from Step 5c
2. Read the design decisions dossier from Step 3
3. Check for existing acknowledged-divergence notes in project memory (if your
   setup keeps them), otherwise skip:
   ```bash
   ls ~/.claude/projects/*/memory/*intentional*.md 2>/dev/null || true
   ```
4. **Build a focused prompt with INLINE content.** Codex wastes its entire budget reading codebase files if you tell it to "explore." Instead:
   - **Inline the spec content** directly in the prompt (or the key sections)
   - **Inline the synthesis summary** from Step 5c
   - **List specific files to check** (from the codebase verifier's findings) — don't say "explore the codebase"
   - Include acknowledged divergences as "known intentional — do not re-flag"
   - Keep the prompt under ~50 lines. Plain language, no XML blocks, no JSON templates.
5. Dispatch via `codex exec` with `run_in_background: true` (no `&`):
   ```bash
   TASK_TAG="alignment-$$"
   cd <PROJECT_ROOT> && echo '' | codex exec --skip-git-repo-check \
     -m gpt-5.6-sol \
     --config model_reasoning_effort="high" \
     --sandbox read-only \
     --full-auto \
     "Check if the following spec claims match reality in the codebase. <INLINE SPEC KEY CLAIMS>. Check these specific files: <LIST 5-10 FILES FROM CODEBASE VERIFIER>. For each claim that doesn't match, state: what the spec says, what the code does, which file:line, and severity. Do NOT read files beyond the ones listed." \
     2>&1 | tee /tmp/alignment-${TASK_TAG}.txt
   ```

**CRITICAL: Do NOT tell Codex to "explore the codebase" or "investigate drift."** That causes it to read every file it can find until budget exhaustion with zero synthesis. Give it specific claims to verify against specific files.

When notified of completion, read the output file with Read tool.

### Step 7: Present Alignment Findings

When the investigation completes, read the output file and extract findings yourself.
3. Filter out hypotheses matching known acknowledged divergences from memory
4. Present ALL hypotheses to user in single-pass format:

> **Misalignment detected:** [dimension]
> **What Codex found:** [evidence with file:line]
> **What was expected:** [from spec/decisions]
> **The gap:** [divergence description]
> **Confidence:** [high/medium/low]
> **Your call:** intentional / problem / investigate later

5. If user requests deeper investigation on any finding ("dig deeper"), escalate to adaptive interview:
   - Capture the Codex thread ID from the dispatch output
   - Feed user context via `resume <THREAD_ID>`
   - Max 5 resume rounds
6. Collect all user decisions

### Step 8: Apply Alignment Fixes

1. Append alignment findings to the Step 5c Final Report as a new section:

```markdown
### Alignment Findings
**Model:** gpt-5.6-sol at high | **Mode:** single-pass [or adaptive]

#### Confirmed Misalignments
- [severity] <description> — Evidence: <files/lines>. Action: <fix>

#### Acknowledged Divergences
- <description> — User confirmed intentional. Reason: <context>

#### Open Questions
- <description> — Flagged for future investigation
```

2. Apply spec fixes for any findings marked "problem" with Critical/Major severity (same fix pattern as Step 5c)
3. For each acknowledged divergence, save a memory note (if your setup keeps project memory) following the schema in the spec

### Step 9: Commit

```bash
git add <spec-file>
git commit -m "docs(<scope>): spec review fixes — <N> issues from the multi-lane pipeline + alignment investigation"
```

### Step 10: Visualize (optional)

After fixes are applied and committed, offer to produce an interactive HTML dashboard of the spec via the `spec-visualization` skill.

**When to offer:**
- Spec status is Approved / Wave-N-ready (not Draft)
- Spec is non-trivial (>200 lines) AND has waves OR a clear architectural model
- User is at a desktop (visualization opens in a browser)

**When to skip:**
- Spec is still Draft / pre-review
- Bug-fix or refactor spec with no architectural surface
- User is in a headless / CI / no-display environment

**How to invoke:**

```
Invoke the Skill tool with skill=spec-visualization. Pass the spec path
plus any sibling .review*.md / *-decisions.md files. The skill handles
data extraction, template render, and Chrome open.
```

The skill emits `<spec-path>.viz.html` next to the spec. The file is fully reproducible from the spec, so commit is optional — offer to commit it on the same review-fixes commit only if the user wants it tracked.

This step is the "vision fitness check" — a single dashboard view of the spec's architecture, pipeline, rollout, review history, decisions, and open gates. It surfaces structural problems (missing waves, no clear data boundaries, pipeline gaps) faster than re-reading the markdown.

---

## Quick Reference

| Step | Who | What | Parallel? |
|------|-----|------|-----------|
| 1 | Coordinator | Read spec, confirm target | — |
| 2a | Coordinator | Write "why" context block (inline, no compaction) | — |
| 2b | Coordinator | Generate session-decisions JSON (skippable) | — |
| 2c | **Agent (opus)** | **Context Dossier Miner — ticket/ADR-bodies/prior-sessions/memory/ledger/flows/open-PRs → ground-truth dossier + generated review questions** | Parallel with 3 |
| 2d | Coordinator | Mechanical pre-filter (merge-base pin, symbol greps, schema lookups, parity tests, open-PR list) | — |
| 2e | Coordinator | Pick + log the review profile (full / focused / hotfix); non-droppable domain lanes | — |
| 3 | Agent (haiku) | Decisions JSON → design decisions dossier | — |
| 4 | **12 Reviewers + Investigation Workflow** | Completeness + Codebase + Architecture + **Provider-Fit** + Edge-Case Miner + Security Miner + **Observability Auditor** + **Live-Evidence Premise Auditor (gated)** + Spec Drift Scout + Codex Standard + Codex Adversarial + Codex Industry Research + **Investigation Workflow (elevation grounding)** | **ALL PARALLEL** |
| 4b | Coordinator + optional agents | Progressive drift investigation from Scout candidates | Parallel when needed |
| 4c | Coordinator | Wait for Codex reviews (Codex-down → Fable-critic substitute), the Investigation Workflow, and drift investigators | — |
| 5 | Coordinator | Merge 12 primary reports plus drift investigations, classify findings | — |
| 5a | **Agents (sonnet)** | **Per-Finding Falsifier wave — refute every CRITICAL/MAJOR; citation verification; factual-split resolution; downgrade guard** | **ALL PARALLEL** |
| 5b | Coordinator + Codex | Cross-examine MAJOR+ judgment disagreements (Claude vs Codex debate) | Sequential |
| 5c | Coordinator + User | Final report, user decides on contested issues | — |
| 6 | Coordinator | Alignment investigation — OPTIONAL, off by default, only if user asks | — |
| 7 | Coordinator + User | Present alignment findings (single-pass) — only if 6 ran | — |
| 8 | Coordinator | Append alignment findings to report, apply fixes — only if 6 ran | — |
| 9 | Coordinator | Apply approved fixes, commit | — |
| **10** | **Coordinator (Skill)** | **Visualize spec via `spec-visualization` — interactive HTML dashboard for vision fitness check (optional)** | **—** |

## Agent Summary

> Numbering: the **12 primary reviewers** are agents 1–9 **+ Provider-Fit (3b) + Observability Auditor (5b) + Live-Evidence (5c)** (the `Nx` suffix groups a reviewer with its sibling — 3b with Architecture #3, 5b/5c with Security Miner #5, 6b with Drift Scout #6). Agents **11–12** are the non-reviewer lanes (Investigation Workflow, Alignment Investigator), so **no agent bears the number 10 by design** — it is not a gap. Agent 0b (Context Dossier Miner) and agent 13 (Finding Falsifiers) are the pre- and post-wave stages.

| # | Agent | Prompt File | Type | Model | Focus |
|---|-------|------------|------|-------|-------|
| 0 | Design Decisions Extractor | `prompts/design-decisions-extractor.md` | general-purpose | haiku | JSONL → dossier |
| 0b | **Context Dossier Miner** | `prompts/context-dossier-miner.md` | general-purpose | opus | **Pre-wave. Ticket body+comments+blockers, cited-ADR/doc BODIES (citation-inversion, zero-call-site primitives, numbered-artifact collisions), prior-session decisions via Session-Id trailers, project memory + known-error/RCA ledger + fix-cluster attribution, flow registry, sibling specs + open PRs → ground-truth dossier + 8-15 generated lane-tagged review questions injected into every reviewer** |
| 1 | Completeness Reviewer | `prompts/completeness-reviewer.md` | general-purpose | opus | Dossier × spec cross-check |
| 2 | Codebase Verifier | `prompts/codebase-verifier.md` | Explore | sonnet | File refs, duplicates, stale code |
| 3 | Architecture Auditor | `prompts/architecture-auditor.md` | general-purpose | opus | Fit, simplicity, maintenance, **deep-module fit** (invokes the `improve-codebase-architecture` + `codebase-design` rubric by reading their SKILL.md: deletion test, shallow-vs-deep, testability-through-the-interface) **+ delete-legacy/one-architecture gate (CRITICAL if the spec keeps the replaced path alongside the new one)** |
| 3b | **Provider-Fit Auditor** | `prompts/provider-fit-auditor.md` | general-purpose | opus | **First-wave. Provider ⋈ Technical-Architecture Alignment: ownership-inversion, access-pattern↔provider-class match, "nobody hand-builds this" as a field survey per use-case, build-vs-buy gradient, the BUILD-is-correct counter-check (wrongful-adopt = flatten boundary / duplicate live subsystem / regulated-data-upstream = CRITICAL), gate-don't-cutover, + the inherited-premise audit (PF-7: fires on pre-existing architecture the spec extends — fix-cluster ≥3, LOC ratio, invented vocabulary, unmeasured premise numbers, unwired vendor primitives). Balanced both ways — never an "always buy" bias. Feeds the Step 5 defect pipeline with Architecture.** |
| 4 | **Edge-Case Miner** | `prompts/edge-case-miner.md` | general-purpose | opus | **Semantic boundary enumeration: cardinality / lifecycle / tenancy / encoding / time / concurrency / permission / resource / schema-evolution / forbidden-but-valid** |
| 5 | **Security Miner** | `prompts/security-miner.md` | general-purpose | opus | **Project-policy security mining: reads `docs/security-policy.md` + `CLAUDE.md`/`AGENTS.md` and audits against your project's stated rules + portable categories (authN/authZ, secret storage, tenant isolation, injection, data boundaries, privilege escalation, allowlist gaps, output sanitization)** |
| 5b | **Observability & Traceability Auditor** | `prompts/observability-auditor.md` | general-purpose | opus | **First-wave. Ships-its-own-telemetry audit: named structured events + a request-threading correlation id, W3C `traceparent` trace context, release/version stamping (onset-vs-deploy), an authoritative terminal status for async work (not a dispatch/`202` ack), alarm-visible metric granularity, cardinality + PII/PHI discipline, a stable PII-free error fingerprint, observable fail-open branches, and a nameable log/telemetry destination. Own report section (like Edge-Case/Security), not cross-examined.** |
| 5c | **Live-Evidence Premise Auditor** | `prompts/live-evidence-auditor.md` | general-purpose | opus | **First-wave, gated to specs touching a live surface. Extracts load-bearing premises and falsifies each against LIVE evidence: deployed flag/config values, live schema/signatures/rows (provenance, duplicate keys, dedup dry-runs, row-size × page-size × channel-cap arithmetic), upstream-trigger liveness (a dead pipeline = bake theatre), DNS/infra reads, budget traceability (every number → a measurement or a named constant). Read-only, every verdict cites the exact command + observed value.** |
| 6 | **Spec Drift Scout** | `prompts/spec-drift-scout.md` | general-purpose | sonnet | **Cross-worktree/project-scope drift: recent pushed refs, dirty worktrees, sibling specs, architecture changes, feature overlap, missing spec updates** |
| 6b | **Spec Drift Investigator** | `prompts/spec-drift-investigator.md` | general-purpose | opus | **Second-wave deep dive on one drift candidate: update current/other spec, combine, move, split, create missing spec, or mark intentional** |
| 7 | **Codex Adversarial** | `prompts/codex-adversarial-reviewer.md` | **codex exec (web)** | **GPT-5.6-sol** | **Attack surface, risks — cross-referenced against public CVEs/post-mortems** |
| 8 | **Codex Standard** | `prompts/codex-standard-reviewer.md` | **codex exec (web)** | **GPT-5.6-sol** | **Completeness, feasibility — API/library claims verified against primary sources** |
| 9 | **Codex Industry Research** | `prompts/codex-research-auditor.md` | **codex exec (web)** | **GPT-5.6-sol** | **Elevation: OSS libraries, big-company patterns, production gotchas with URL citations** |
| 11 | **Investigation Workflow** | `investigation` skill (`DEEP-WORKFLOW.md`) | **dynamic Workflow** | **multi-agent** | **Elevation grounding: spec themes framed against THIS codebase, fanned out across sources, adversarially verified in code → industry-standard + best-in-class elevation evidence (Claude Code-only)** |
| 12 | **Alignment Investigator** | (coordinator-composed prompt) | **codex exec** | **GPT-5.6-sol** | **Decision-reality drift** |
| 13 | **Finding Falsifiers** (one per CRITICAL/MAJOR) | `prompts/finding-falsifier.md` | general-purpose | sonnet | **Post-wave disprove-step: refute each finding against code/spec/evidence; verify every citation a reviewer or fix introduces; resolve Claude↔Codex repo-fact splits by reading the seam; guard severity downgrades (an unrefuted CRITICAL keeps its severity)** |

## Process Gates (bind the coordinator, not just the reviewers)

- **Review before build.** A net-new tracked spec passes /spec-review BEFORE its build workflow dispatches. Post-build adversarial validate lanes are NOT a substitute for design-stage review — the documented cost of skipping was a concurrency defect that lived in the spec prose and surfaced only at build.
- **No build dispatch past an unresolved sequencing drift finding.** If the drift lane produced a CRITICAL/MAJOR finding with a `sequence-after <PR/spec>` action, the coordinator REFUSES any build dispatch until it is resolved or explicitly overridden by the user — a review that reports the collision and then dispatches against the doomed base has already happened.
- **Grill precedes review.** If the spec's core premise was never interrogated (`grilling`/`grill-with-docs` or equivalent), run that FIRST — a full pipeline spent polishing a premise the grill then reverses is the most expensive possible ordering. spec-review verifies a written spec; it cannot fix a spec authored from a misread ask.
- **Right-sizing is a named profile (Step 2e), never a silent judgment call** — and the report always states the profile + dropped lanes.

## When NOT to Use

- Trivial specs (<50 lines AND low blast-radius, single feature) — overkill. But **line-count is not the risk axis, blast-radius is**: a small spec touching a core reducer/shared seam still gets the full pipeline. Even a skipped spec gets one cheap grounding-verification of its core scope claim.
- Specs not discussed in a session — no session decisions to mine (the review still works, it just skips the dossier cross-check; the Context Dossier Miner still runs)
- Pure documentation changes — use Codex review directly via Bash

**Flags:**
- `--skip-alignment` in trigger phrase — skips alignment investigation (Steps 6-8)
