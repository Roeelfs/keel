---
license: MIT
name: spec-review
description: Multi-model spec verification pipeline run as Workflow scripts off the main loop. Mines the spec's context lineage into a dossier + generated review questions, runs 13 parallel reviewers (9 Claude including provider-fit, edge-case, security, observability, live-evidence premise auditor and cross-worktree drift scout + 4 Codex: standard, adversarial, industry research, and the Astra frontier judgment that runs in every profile) plus the investigation skill's Workflow for elevation, then a falsifier wave on every CRITICAL/MAJOR before one synthesized report; the main loop reads the report and fixes only real design defects in the spec prose. Never injects review scaffolding into the spec.
---

# Spec Review

**Trigger:** "review this spec", "verify the spec", "run spec review", "gap analysis".

The review wave runs in three Workflow stages of one script, `scripts/spec-review.workflow.js` (prepare, review, synthesize), plus one Bash wrapper that runs the Codex lanes. The main loop launches them, reads `report.md`, applies the spec-prose fixes and commits: about 12 turns, not ~90. Lane data (agent types, models, gates, question tags) lives only in that script's `MANIFEST`; lane briefs live only in `prompts/`; the report shape lives only in `report-template.md`.

**Opt-in.** This skill instruction IS the user's opt-in to the Workflow tool: when the skill fires, call Workflow as written below. The "fewer than 10 agents" figure is a guideline, not a cap.

**Skill memory.** The script hands the LEARNINGS paths to lanes and synthesis (committed `LEARNINGS.md`, plus the private overlay `~/.claude/skills-overlay/spec-review/LEARNINGS.md` if it exists); the main loop does not read them. Before ending, route each learning by scope: operator-private craft to the overlay, project facts to the project's `.claude/memory/`, universal craft to `/improve-harness`. Never append to the committed `LEARNINGS.md`. Routing: [`docs/skill-memory.md`](../../../docs/skill-memory.md).

> **Findings, not procedures.** The review fixes real design defects in the spec's *prose* and must NEVER put its scaffolding (EC/Sec/Obs/DRIFT tables, matrices, lane lists) into the spec. Those live in the report. For `full` and `focused` the report ships as `<spec-without-.md>.review.md`, committed with the spec; `hotfix` keeps it in the run dir. Downstream consumers must degrade gracefully when it is absent.

## Flow

**Step 1. Frame (main loop, one turn).** Confirm the spec (`ls -lt docs/specs/*.md | head -5` if not given) and read it. Decide, from the spec and the conversation:
- **Why block**, 5-10 lines: Goal, Trigger, Target outcome, Scope boundaries (ruled-out items).
- **Profile** (logged, never silent): `full` (default for any spec doc), `focused` (surgical single-seam change), `hotfix` (prod down, minutes matter). Blast radius is the risk axis, not line count: a small spec on a core reducer is `full`.
- **Gates**, each `{run: boolean, reason: string}` (the reason is printed in the report either way): `liveSurface` (touches an existing runtime path, deployed config/flag, prod data or wired provider), `security` (adds a credential, table or authz surface), `cutover` (rewrites, replaces, migrates or cuts over an existing capability, adds a plane/profile/twin, or edits one representation of a contract that has others), `runtimeWiring` (adds a runtime-read env var/secret/flag/URL, a deployed function, or moves such a read into shared code). Domain gates are non-droppable in every profile.
- **`sid`**: `$CLAUDE_SESSION_ID`; on a RESUMED session with an empty transcript, the prior session's id from `Session-Id` trailers on commits touching the spec. From a Codex session pass `runtime: "codex"` and the rollout id.
- **`runDir`**: a fresh absolute directory in the scratchpad, e.g. `<scratchpad>/spec-review-<timestamp>`.

**Step 2. Prepare (Workflow, one call).** The Workflow tool only accepts a `scriptPath` the session can read (cwd, an added dir, or the scratchpad) and refuses the installed skill dir, so first `cp <skill-dir>/scripts/spec-review.workflow.js <runDir>/../spec-review.workflow.js`, then `Workflow({scriptPath: "<that copy>", args: {stage: "prepare", ...}})`. Reuse the same copy for every stage; never paste the script inline (~8k output tokens per stage). It mines decisions, runs the dossier miner and decisions extractor once, and writes filled prompt copies and Codex prompt files into the run dir; it fails on any unfilled placeholder. Returns paths only.

**Step 3. Review wave (one turn, parallel calls).** In ONE message: (a) `Bash` with `run_in_background: true` running the returned `codexCommand` (`scripts/run-codex-lanes.sh <runDir> <profile>`; it starts the Codex dispatches in parallel, waits internally, exits once with a status line per lane; never wrap it in `&`/nohup, never launch it from a Workflow agent); (b) `Workflow` with `stage: "review"` (Claude lanes, drift second wave, question coverage); (c) for `full` on Claude Code, the investigation skill on the spec's 3-6 core themes (premise: "Ground the industry standard + best-in-class elevation for these spec themes, framed against THIS codebase: `<themes>`. Spec: `<path>`. Return verified evidence, each claim code-anchored or carrying a live source URL"), which writes `docs/investigations/YYYY-MM-DD-<slug>.md`. Do not poll; each completion notification is the signal.

**Step 4. Synthesize (Workflow, one call, after ALL of: the Codex wrapper, the review stage, the investigation).** `stage: "synthesize"`, plus `investigationBrief` (path or omit) and `reviewPath`. It extracts Codex envelopes, substitutes a Fable `critic` for a dead adversarial or Astra lane, runs the falsifier wave on EVERY CRITICAL/MAJOR, and has one agent write `<runDir>/report.md`, then fails the run unless: the falsifier line matches the real counts, every CRITICAL/MAJOR envelope id is in the report with a verdict, every lane is listed as run or `SKIPPED (gate: <reason>)`, the Astra lane (or its critic) produced a result, and `validate_review_report.py` passes. A stage error names what to fix; fix it and relaunch that stage (same `runDir`).

**Step 5. Read, decide, fix (main loop).** Read `report.md` (it is the only findings text the main loop ever reads). If `hardStop` is true, stop: the ADR auditor found an Accepted ADR/invariant changed without a founder-approval marker. For genuine Claude-vs-Codex judgment splits see [`reference.md`](reference.md#step-5b--cross-examination-debate-protocol-moved-detail).

**Step 5c. Fix policy.** Apply CRITICAL and MAJOR defects that SURVIVED the falsifier wave by fixing the actual design problem in the spec's own prose (the mechanism, the boundary, the auth rule), as a one-line behavioral statement. Never paste a finding's table row, an EC/Sec/Obs/DRIFT id, a matrix or a lane list into the spec. Present every EC/Sec/Obs/Drift/Industry finding to the user; Industry Insights and CAUTION items are never auto-applied. Out-of-scope findings go to a separate issue. An unrefuted CRITICAL is never downgraded by instinct.

**Step 9. Commit.** `git add <spec> <spec>.review.md`, then `git commit -F <msgfile> --trailer "Session-Id: $CLAUDE_SESSION_ID"` with a message like `docs(<scope>): spec review fixes, <N> issues from the multi-lane pipeline`. Optional follow-ups: alignment investigation and visualization, both in [`reference.md`](reference.md) (off by default).

## Args contract

| stage | args (all stages also take `runDir`, `skillDir`, `spec`, `profile`, `gates`) |
|---|---|
| prepare | `root` (absolute repo root), `sid`, `runtime` (default `claude`), `contextBlock` (the why block) |
| review | none extra |
| synthesize | `investigationBrief?`, `reviewPath?` (absolute `.review.md` path), `wiringAgentType?` |

`skillDir` is this skill's absolute directory; pass the same `gates`/`profile`/`spec`/`runDir` to every stage (the lane plan is recomputed from them). Every stage returns only `{paths, counts, gateLog}`; never findings text.

## Process gates

- **Review before build.** A net-new tracked spec passes spec-review BEFORE its build dispatches.
- **No build dispatch past an unresolved sequencing drift finding** (`sequence-after <PR/spec>` is a refusal until resolved or overridden by the user).
- **Grill precedes review** when the spec's premise was never interrogated.

## When NOT to use

- Trivial specs (<50 lines AND low blast radius, single feature). Even then, run one cheap grounding check of the core scope claim.
- Pure documentation changes: use Codex review directly.
- Flag `--skip-alignment` skips the optional alignment investigation.
