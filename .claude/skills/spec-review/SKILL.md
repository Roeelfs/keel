---
license: MIT
name: spec-review
description: Multi-model spec verification pipeline run as Workflow scripts off the main loop. Mines the spec's context lineage into a dossier + generated review questions, runs 13 parallel reviewers (7 Claude including provider-fit, edge-case, security, observability, live-evidence premise auditor and cross-worktree drift scout + 6 Codex: codebase verifier, architecture auditor, standard, adversarial, industry research, and the Astra frontier judgment that runs in every profile) plus gated supplements (ADR, legal, cutover, runtime wiring, latency/performance, operator plane, System 1 elevation, dependency currency: installed vs latest versions, CVE/KEV advisories, changelogs and current vendor docs) and the investigation skill's Workflow for elevation, then a tier-scaled falsifier wave (every CRITICAL/MAJOR at critical, CRITICAL only at standard, none at light) before one synthesized report; the main loop reads the report and fixes only real design defects in the spec prose. Never injects review scaffolding into the spec.
---

# Spec Review

**Trigger:** "review this spec", "verify the spec", "run spec review", "gap analysis".

The review wave runs in three Workflow stages of one script, `scripts/spec-review.workflow.js` (prepare, review, synthesize), plus one Bash wrapper that runs the Codex lanes. The main loop launches them, reads `report.md`, applies the spec-prose fixes and commits: about 12 turns, not ~90. Lane data (agent types, models, gates, tiers, budgets) lives only in `lanes.json` (plus the optional per-repo `<root>/.claude/spec-review.lanes.json`, merged and validated by `run_dir.py plan`); lane briefs live only in `prompts/`; the report shape lives only in `report-template.md`.

**Mandatory, depth tiered by risk.** Every spec is reviewed before build; only the depth varies. This skill instruction IS the user's opt-in to the Workflow tool: call it as written below.

**Skill memory.** The script hands the LEARNINGS paths to lanes and synthesis (committed `LEARNINGS.md`, plus the private overlay `~/.claude/skills-overlay/spec-review/LEARNINGS.md` if it exists); the main loop does not read them. Before ending, route each learning by scope: operator-private craft to the overlay, project facts to the project's `.claude/memory/`, universal craft to `/improve-harness`. Never append to the committed `LEARNINGS.md`. Routing: [`docs/skill-memory.md`](../../../docs/skill-memory.md).

> **Findings, not procedures.** The review fixes real design defects in the spec's *prose* and must NEVER put its scaffolding (EC/Sec/Obs/DRIFT tables, matrices, lane lists) into the spec. Those live in the report. For `critical`, `standard` and `light` the report ships as `<spec-without-.md>.review.md`, committed with the spec; `hotfix` keeps it in the run dir. Downstream consumers must degrade gracefully when it is absent.

## Flow

**Step 1. Frame (main loop, one turn).** Confirm the spec (`ls -lt docs/specs/*.md | head -5` if not given) and read it. Decide, from the spec and the conversation:
- **Why block**, 5-10 lines: Goal, Trigger, Target outcome, Scope boundaries (ruled-out items).
- **Tier** (logged, never silent; blast radius is the risk axis, not line count): `critical` (access/authn/authz/credentials/tenancy/billing/money/personal data/erasure, high-level architecture, deep infrastructure, shared-store migrations, cutovers: profile `full`, ALL gate-fired lanes, frontier judge, falsifier on every CRITICAL/MAJOR), `standard` (every other behavior-bearing spec: completeness, codebase-verifier, edge-case, dependency-currency, one frontier judge, plus gate-fired lanes; falsifier on CRITICAL only), `light` (low-risk local change with NO gate fired: docs/config/copy/UI-only/internal tooling; codebase-verifier, edge-case, one judge, no falsifier), `hotfix` (prod down, minutes matter). Budgets are advisory dials; override file and tier detail: [`reference.md`](reference.md#tiers-lane-plan-per-repo-lanes-and-budgets).
- **Gates**, each `{run: boolean, reason: string}` (the reason is printed in the report either way): `liveSurface` (touches an existing runtime path, deployed config/flag, prod data or wired provider), `security` (adds a credential, table or authz surface), `cutover` (rewrites, replaces, migrates or cuts over an existing capability, adds a plane/profile/twin, or edits one representation of a contract that has others), `runtimeWiring` (adds a runtime-read env var/secret/flag/URL, a deployed function, or moves such a read into shared code), `operatorSurface` (adds or changes a feature, entity, setting or action an operator must reach, query or drive), `legalSurface` (touches personal data, a data recipient or vendor, consent/acceptance/disclosure UX, retention or erasure, billing terms or AI disclosure; the legal lane also runs in every `critical`), `decisionSurface` (hard-codes a decision a fast model could make: routing, classification, matching, thresholds, UI or assistant behaviour, tool/integration choice). The `dependency-currency` lane runs in every tier but `light`, with no gate: installed vs latest versions, open CVE/GHSA advisories joined to CISA KEV with reachability, changelogs since the installed version, current vendor docs via Context7, and workarounds a newer version removes. Domain gates are non-droppable in every tier.
- **`lanePlan`** `{tier, add: [labels], drop: [labels], reasons: {label: why}}`: your lane choice on top of the tier's default set, every add/drop with a reason. `run_dir.py plan` rejects an unknown label, any drop at `critical`, any drop of the frontier or codebase-verifier lane or of a lane whose gate fired, and `light` with any gate fired; reasons print in the report either way. Write `{gates, lanePlan}` to `<runDir>/inputs/frame.json`, then run `python3 <skill-dir>/scripts/run_dir.py plan --run <runDir> --root <root> --input <runDir>/inputs/frame.json` and fix what it rejects. It writes the one resolved manifest and plan every later stage reads.
- **`sid`**: `$CLAUDE_SESSION_ID`; on a RESUMED session with an empty transcript, the prior session's id from `Session-Id` trailers on commits touching the spec. From a Codex session pass `runtime: "codex"` and the rollout id.
- **`runDir`**: a fresh absolute directory in the scratchpad, e.g. `<scratchpad>/spec-review-<timestamp>`.

**Step 2. Prepare (Workflow, one call; after `plan`).** The Workflow tool only accepts a `scriptPath` the session can read (cwd, an added dir, or the scratchpad) and refuses the installed skill dir, so first `cp <skill-dir>/scripts/spec-review.workflow.js <runDir>/../spec-review.workflow.js`, then `Workflow({scriptPath: "<that copy>", args: {stage: "prepare", ...}})`. Reuse the same copy for every stage; never paste the script inline (~8k output tokens per stage). It mines decisions, runs the dossier miner and decisions extractor once, and writes filled prompt copies and Codex prompt files into the run dir; it fails on any unfilled placeholder. Returns paths only.

**Step 3. Review wave (one turn, parallel calls).** In ONE message: (a) `Bash` with `run_in_background: true` running the returned `codexCommand` (`scripts/run-codex-lanes.sh <runDir> <profile>`; it starts the Codex dispatches in parallel, waits internally, exits once with a status line per lane; never wrap it in `&`/nohup, never launch it from a Workflow agent); (b) `Workflow` with `stage: "review"` (Claude lanes, drift second wave, question coverage); (c) for `critical` on Claude Code, the investigation skill on the spec's 3-6 core themes (premise: "Ground the industry standard + best-in-class elevation for these spec themes, framed against THIS codebase: `<themes>`. Spec: `<path>`. Return verified evidence, each claim code-anchored or carrying a live source URL"), which writes `docs/investigations/YYYY-MM-DD-<slug>.md`; when `decisionSurface` runs, one theme is fast-model decision placement. Do not poll; each completion notification is the signal.

**Step 4. Synthesize (Workflow, one call, after ALL of: the Codex wrapper, the review stage, the investigation).** `stage: "synthesize"`, plus `investigationBrief` (path or omit) and `reviewPath`. It extracts Codex envelopes, substitutes an Opus `critic` for a dead adversarial or Astra lane, runs the falsifier wave at the tier's scope (every CRITICAL/MAJOR at `critical`), and has one agent write `<runDir>/report.md`, then fails the run unless: the falsifier line matches the real counts, every CRITICAL/MAJOR envelope id is in the report with a verdict, every lane is listed as run or `SKIPPED (gate: <reason>)`, the Astra lane (or its critic) produced a result, and `validate_review_report.py` passes. A stage error names what to fix; fix it and relaunch that stage (same `runDir`).

**Step 5. Read, decide, fix (main loop).** Read `report.md` (it is the only findings text the main loop ever reads). If `hardStop` is true, stop; `hardStopReasons` says why: `adr` (an Accepted ADR/invariant changed) or `legal` (an in-force legal commitment breached), each without a founder-approval marker, or a gate lane with no usable verdict (relaunch it). If it lists System 1 research hand-offs (`S1-Hn`), send them to the investigation skill in one call before applying any S1 elevation. For genuine Claude-vs-Codex judgment splits see [`reference.md`](reference.md#step-5b--cross-examination-debate-protocol-moved-detail).

**Step 5c. Fix policy.** Apply CRITICAL and MAJOR defects that SURVIVED the falsifier wave by fixing the actual design problem in the spec's own prose (the mechanism, the boundary, the auth rule), as a one-line behavioral statement. Never paste a finding's table row, an EC/Sec/Obs/DRIFT id, a matrix or a lane list into the spec. Present every EC/Sec/Obs/Drift/Industry finding to the user; Industry Insights and CAUTION items are never auto-applied. Out-of-scope findings go to a separate issue. An unrefuted CRITICAL is never downgraded by instinct.

**Step 9. Commit.** `git add <spec> <spec>.review.md`, then `git commit -F <msgfile> --trailer "Session-Id: $CLAUDE_SESSION_ID"` with a message like `docs(<scope>): spec review fixes, <N> issues from the multi-lane pipeline`. Optional follow-ups: alignment investigation and visualization, both in [`reference.md`](reference.md) (off by default).

## Args contract

| stage | args (all stages also take `runDir`, `skillDir`, `spec`; tier, gates and lanes come from the plan) |
|---|---|
| prepare | `root` (absolute repo root), `sid`, `runtime` (default `claude`), `contextBlock` (the why block) |
| review | none extra |
| synthesize | `investigationBrief?`, `reviewPath?` (absolute `.review.md` path), `wiringAgentType?` |

`skillDir` is this skill's absolute directory; pass the same `spec`/`runDir` to every stage (they read `<runDir>/plan.json`). Every stage returns only `{paths, counts, gateLog}`; never findings text.

## Process gates

- **Review before build, no exceptions.** No spec ships to build without a review at or above its tier; skipping is not an option. Lowering the tier is allowed only down to the floor the gates imply: any fired security/legal/cutover/runtimeWiring/liveSurface gate (indeed any gate) forces `standard`-or-`critical` with that lane, never `light`.
- **No build dispatch past an unresolved sequencing drift finding** (`sequence-after <PR/spec>` is a refusal until resolved or overridden by the user).
- **Grill precedes review** when the spec's premise was never interrogated.

## Light and trivial specs

There is no skip path. A trivial spec (<50 lines, low blast radius, no gate fired) takes tier `light`. Pure documentation changes are `light`. Flag `--skip-alignment` skips the optional alignment investigation.
