# Spec-review report template

The synthesis agent writes `<run-dir>/report.md` to this shape. Section order is fixed; sections with
no content are omitted except the header block, the lane manifest and the falsifier-wave line.
The pipeline checks mechanically (scripts/run_dir.py `check-report` + scripts/validate_review_report.py):
the one canonical `### Falsifier wave:` line with the real counts; every CRITICAL/MAJOR id from any lane
envelope present with a REFUTED/SURVIVES verdict on its line; every lane in the manifest as run or
`SKIPPED (gate: <reason>)`; a Codex Frontier (Astra) or critic-frontier result; no unfilled placeholders;
a `### Carried obligations` section whenever an Obs-/Sec-/LE- CRITICAL/MAJOR survives.

Severity vocabulary: CRITICAL (security, data loss, compliance, rollback safety; block ship) / MAJOR
(correctness, availability, contract break; fix before release) / MINOR (performance, cosmetic, edge
case). Codex words map critical->CRITICAL, high->MAJOR, medium->MAJOR if user-facing else MINOR, low->MINOR.
ELEVATE and CAUTION (research lane) are NOT on this scale; they live in Industry Insights only.

Consensus rules: 2+ lanes agree = high confidence (a severity boost, not just a dedup key); a Codex-only
finding is a possible Claude blind spot; a Claude/Codex split on a REPO FACT is settled by the falsifier
that read the seam, only genuine judgment splits stay under Cross-Examined Disagreements. An unrefuted
CRITICAL keeps its severity (downgrade guard). Never inject EC/Sec/Obs/DRIFT tables into the spec.

```markdown
## Spec Review — Final Report

### Spec: <filename>
### Profile: <full | focused | hotfix> — dropped lanes: <none | list, each `SKIPPED (gate: <reason>)`>
### Lane manifest
(Reproduce the manifest table the pipeline gave you VERBATIM: every lane is `run`, `FAILED`, `DEAD: <status>`, or `SKIPPED (gate: <reason>)`. Add the Investigation Workflow as `run (brief: <path>)` or `SKIPPED (gate: <reason>)`.)
### Falsifier wave: <N> dispatched over <M> CRITICAL/MAJOR — <R> REFUTED, <S> SURVIVES.
### Codex Standard Verdict: <approve|needs-attention|timed-out>
### Codex Adversarial Verdict: <approve|needs-attention|timed-out>
### Codex Research Verdict: <N elevate suggestions / M cautions / timed-out>
### Codex Frontier (Astra) Verdict: <approve|approve-with-changes|redesign|timed-out — backfilled by critic (fable)>
### Investigation Verdict: <N verified elevations / M cautions / brief path / skipped (non-Claude runtime) / timed-out>
### Spec Drift Verdict: <clean|N candidates|N investigators|timed-out>

### Consensus Issues (2+ reviewers)
1. [F-1] [CRITICAL] <issue> — flagged by: <which reviewers>
   Codex confidence: <0.0-1.0> | File: <path>:<line>
   Recommendation: <specific fix>
...

### Codex-Only Findings (investigate — possible Claude blind spot)
Category: Implementation (from standard) / Risk (from adversarial)
1. [F-2] [severity] <title>
   Body: <finding body>
   File: <path>:<line_start>-<line_end> | Confidence: <score>
   Recommendation: <recommendation>
...

Every Consensus/Codex-Only finding carries a stable `F-N` ID (assigned once, at merge time — never renumbered across report revisions), the same way EC-/Sec-/Obs-/LE- rows carry theirs. The falsifier wave (synthesize stage) and the validator (below) refer to findings by these IDs.

### Edge Cases (from Edge-Case Miner — semantic boundary enumeration)
Kept in its own section — boundary enumeration is structurally different from
defect-hunting. Output is the EC-N table from `prompts/edge-case-miner.md`,
filtered to omit any `Spec Coverage: EXPLICIT` rows (which shouldn't occur).

| EC-ID | Entity / Operation | Boundary | Spec Coverage | Recommended Resolution | Severity |
|---|---|---|---|---|---|
| EC-1 | … | … | MISSING / IMPLICIT | <one-line spec-text addition> | CRITICAL / MAJOR / MINOR |

CRITICAL/MAJOR rows with `Spec Coverage: MISSING` are auto-applied to the spec
in the SKILL.md Step 5c fix step (same path as other consensus issues). MINOR rows are reported but
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

CRITICAL/MAJOR Security rows are auto-applied to the spec in the SKILL.md Step 5c fix step (same
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

CRITICAL/MAJOR Observability rows are auto-applied to the spec in the SKILL.md Step 5c fix step (same
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

CRITICAL/MAJOR REFUTED rows are auto-applied to the spec in the SKILL.md Step 5c fix step as prose
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

### Coexistence / Contract-Copy Findings (from Cutover Architect — when dispatched)
Its CRITICAL rows (a contract left at ≥2 hand-maintained representations with no
gate-invoked parity instrument; a new plane/profile/twin with no named shared owner) are
classified with the other defects above and auto-applied as prose fixes when in scope.
Surface the structural plan itself here — it is the spec's architecture section, not a
severity row:

- Verdict: STRUCTURED | COEXISTS | SKIPPED (greenfield)
- Contract × Representation matrix (HRC before → after) with `file:line` per cell
- MIGRATE ledger — what moves into each owner before its copies are deleted
- Probes that print the count after the change — and the spec's acceptance criterion that runs them post-implementation (an INSTRUMENT lands in the mandatory gate in the same change)

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

### Carried obligations
One line per SURVIVING CRITICAL/MAJOR Obs-/Sec-/LE- finding, by ID — these are the
findings that were real, not auto-applied as a spec-prose fix (a live-surface gap the
spec's scope can't absorb, a policy violation routed to a follow-up issue, an
observability gap left for the build to instrument), and so must not silently vanish
when the review closes. Omit the section only when there are none.
- Obs-2 — SURVIVES: <what remains true and why it wasn't fixed here> — tracked as: <follow-up issue / build-time proof obligation>
...
```
