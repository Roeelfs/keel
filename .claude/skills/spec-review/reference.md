# Spec Review — Reference (moved detail)

Sibling of `SKILL.md`, holding verbatim material the coordinator does not need
on every run: the incident that motivates the "no compaction" append-as-you-go
rule, the optional (off-by-default) alignment-investigation steps, and the
optional post-review visualization step. `SKILL.md` links here with a one-line
pointer at each extraction point; this file exists to keep those lines
grep-able rather than deleted, not as a separate document to read start-to-end.

## Why "no compaction" means append-as-you-go (incident rationale)

> **"No compaction" describes this skill's MECHANISM, not the session it runs in.** The
> pipeline does not orchestrate a compact-and-resume; it does not stop the harness from
> AUTO-compacting underneath it, which is routine on a full run — one measured run
> dropped ~448k tokens mid-wave, between the lanes returning and the report being
> written. Consequence, and the reason the report file above is not optional: **a lane's
> findings that exist only in conversation context are lost at the next compaction.**
> Append each lane's findings to the report file as its notification arrives, and
> assemble the Final Report by reading that file back — never from memory of the wave.

## Steps 6-8: Alignment Investigation (optional, off by default)

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
5. Dispatch via the wrapper with `run_in_background: true` (no `&`):
   ```bash
   S=/tmp/alignment-$$; mkdir -p "$S"
   cat > "$S/alignment.md" <<'PROMPT'
Check if the following spec claims match reality in the codebase. <INLINE SPEC KEY CLAIMS>. Check these specific files: <LIST 5-10 FILES FROM CODEBASE VERIFIER>. For each claim that doesn't match, state: what the spec says, what the code does, which file:line, and severity. Do NOT read files beyond the ones listed.
PROMPT
   CODEX_SERVICE_TIER=fast \
     ~/.claude/scripts/codex-dispatch.sh verify "$S/alignment.md" "$S/alignment.out.md" <PROJECT_ROOT>
   ```
   No `CODEX_NETWORK` — this lane checks the local codebase and needs no internet.

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
**Model:** gpt-6.1-sol at high | **Mode:** single-pass [or adaptive]

#### Confirmed Misalignments
- [severity] <description> — Evidence: <files/lines>. Action: <fix>

#### Acknowledged Divergences
- <description> — User confirmed intentional. Reason: <context>

#### Open Questions
- <description> — Flagged for future investigation
```

2. Apply spec fixes for any findings marked "problem" with Critical/Major severity (same fix pattern as Step 5c)
3. For each acknowledged divergence, save a memory note (if your setup keeps project memory) following the schema in the spec

## Step 10: Visualize (optional)

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

## Cutover-structure lane (3c) — why it's distinct from the delete-legacy gate

This is the coexistence the delete-legacy gate above cannot see: that gate asks whether the OLD path is deleted; this lane asks how many copies the NEW path ships (the agent's own `Why_This_Matters` carries the incident).


## Runtime-wiring lane — consumer-side reachability

**Fires** when the spec introduces a new env var, secret, credential ARN, feature flag, or downstream URL that deployed runtime code will READ — or adds a new deployed function, or moves code that reads one into a module shared by several functions. Gated but non-droppable across profiles; record `SKIPPED (no new runtime dependency)` otherwise.

**Dispatch** the project's IaC/wiring agent in the same wave if the repo defines one (an agent in `.claude/agents/` whose description claims env/IAM/secret wiring); else `general-purpose` with this brief.

**Job — consumer-side, never stack-side.** For each new name, enumerate every deployed entry point whose call graph can EXECUTE the read (bundle presence is not reachability — bundlers include shared modules everywhere), and return the consumer list the spec's infra section must wire: env key + permission grant on each function's ACTUAL execution role, plus the same-change standing gate that pins it.

**Why a separate lane.** Measured 2026-09-21→29: one shared-code secret read was wired into 1 of the 4 functions that execute it; every conversational bot failed for 8 days. Every other lane missed it because no line in the diff was wrong — the defect was an ABSENT line in a stack file the change never touched. A stack-side review cannot see an absence; only a walk from the consumer can.

Rows classify with the defects in Step 5 (like 3c), no Codex peer. Wired into fewer functions than execute it = **CRITICAL**.

## Why This Exists — full 10-point rationale (moved detail)

A spec written in a long session accumulates blind spots. This skill breaks that with:
1. **Session decision-mining** — recovers the design decisions, rejected alternatives, and user corrections from the session so reviewers judge against intent, not just the prose. Runs as a direct agent dispatch — **no compaction, no hooks, no resume dance.**

> **"No compaction" describes this skill's MECHANISM, not the session it runs in** — auto-compaction still happens mid-wave. Append each lane's findings to the report file as its notification arrives and assemble the Final Report by reading that file back, never from memory of the wave. Incident rationale: see [`reference.md`](reference.md#why-no-compaction-means-append-as-you-go-incident-rationale).
2. **11 parallel reviewers** — each with a focused prompt and one job
3. **Multi-model** — Claude (Opus/Sonnet) + 3x Codex GPT-6-sol (standard + adversarial + industry research)
4. **Web-enabled research** — all Codex agents run with network access so findings are grounded in real public implementations, CVEs, post-mortems, and RFCs — not just training-data recall
5. **Semantic boundary mining** — the edge-case miner enumerates entity/state/value boundaries the spec is silent on (cardinality, lifecycle, tenancy, encoding, time, concurrency, permission, resource, schema-evolution, forbidden-but-syntactically-valid)
6. **Project-policy security mining** — the security miner reads `docs/security-policy.md` (filled by the user from `templates/security-policy.example.md`) plus the project root `CLAUDE.md`/`AGENTS.md`, and audits the spec against your project's stated rules plus portable security categories (authN/authZ, secret/credential storage, tenant/org isolation, input validation & injection, data-boundary separation, privilege escalation, allowlist/denylist gaps, output sanitization). Cites the project's own policy in every finding — no inventing rules
7. **Cross-worktree drift scouting** — the spec drift scout checks recently pushed changes, dirty worktrees, architecture changes, sibling specs, and in-progress parallel work across the same project scope, then dispatches narrow follow-up investigators only when material drift is found
8. **Code-grounded industry elevation** — the **investigation skill** runs as a dynamic Workflow over the spec's core themes: it frames them against THIS codebase first (every claim cites a real `file:line`), fans out across primary sources, adversarially cross-verifies each load-bearing claim *in code* (refuted/unchecked claims are partitioned out before synthesis), and returns a verified industry-standard + best-in-class elevation brief. This **deepens the elevation lane** — it is the evidence-and-industry backbone that the Codex Industry Research Auditor's single-model external scan gets cross-checked against, so an ELEVATE suggestion two independent lanes agree on lands at high confidence, and an unverified one is flagged as such
9. **Provider-fit auditing** — the **Provider-Fit Auditor** runs the **Provider ⋈ Technical-Architecture Alignment** check: does the spec hand-build an architecture a provider/platform-class already owns (an access-pattern↔class mismatch that ships as compensating glue — tomorrow's incident), *or* adopt a vendor where keeping it owned is the honest answer (adoption would flatten a data/compliance boundary, duplicate a live owned subsystem, or route regulated data upstream of redaction)? Balanced both ways — it flags hand-building-what-a-class-owns AND adopting-what-should-stay-owned, so the "should we build this at all?" question is answered *before* the design ships. And it fires on **inherited** architecture too (PF-7): when the spec extends an existing vendor-adjacent subsystem, it audits whether that subsystem exists only to *accommodate a provider mismatch* — tripwires: fix-cluster history ≥3, management-to-workload LOC ratio, invented vocabulary absent from the vendor's docs, premise numbers that trace to constants/models instead of measurements/invoices, and the vendor's canonical primitive defined with zero call sites
10. **Observability & traceability auditing** — the **Observability & Traceability Auditor** audits whether the spec ships its own telemetry: named structured events with a request-threading correlation id + a release/version stamp, an **authoritative terminal status** for async work (never inferred from a dispatch/`202` ack), metrics emitted at a granularity their alarms can actually see, a stable PII-free error fingerprint, observable fail-open branches, and a nameable log/telemetry destination. Its premise: a change that ships without its instrumentation is a future RCA run blind — the false-positive, wrong-source, and "we can't tell what failed" incidents all trace back to a spec that never said how the thing would be seen. Distinct lane from the security miner (policy) and edge-case miner (semantic boundaries)

## Step 4b — Progressive Drift Investigation (moved detail)

### Step 4b: Progressive Drift Investigation

**Script-driven.** The `post-review` gate (`scripts/stage.py`) does this: when the scout's envelope carries `drift_investigations`, `run_dir.py drift-briefs` materializes one investigator brief per candidate (capped at 5; the rest are logged as a user decision) and the `review2` Workflow stage runs them as `spec-drift-investigator` lanes before the coverage check. At the spend stop (below) the investigators are not launched. The trigger conditions and result handling below are the policy those lanes and the synthesis follow.

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

## Step 5b — Cross-Examination Debate Protocol (moved detail)

### Step 5b: Cross-Examination — Claude vs Codex Debate

For any MAJOR+ finding where Claude and Codex disagree, run an iterative debate so the user can see both perspectives and decide.

**What triggers cross-examination:**
- Codex flags something MAJOR+ that all 3 defect-hunting Claude agents (completeness, codebase, architecture) missed or dismissed (the Edge-Case Miner, Security Miner, and Drift lane do not participate in cross-examination — their findings have their own sections)
- Claude agents (2+) flag something MAJOR+ that Codex approved
- Claude and Codex propose **conflicting fixes** for the same issue
- Codex adversarial flags a risk that Claude architecture agent explicitly called safe
- **Codex Frontier (Astra) rules `redesign`, or names a wrong decision that no Claude lane flagged** — always cross-examined, never silently downgraded

**How it works:**

1. **Present the disagreement to the user** in a structured format:

```markdown
### Disagreement #N: <topic>

**Codex (GPT-6-sol) says:** <summary of Codex position + severity + confidence>
**Claude says:** <summary of Claude position + which agents>

**Key question:** <the specific architectural/design question at the heart of the disagreement>
```

2. **Prompt Codex with Claude's counter-argument** via Bash (resume the session):

```bash
echo "This is Claude (Opus) following up on your review. Re: your finding about <TOPIC>.

Our architecture auditor disagrees because: <CLAUDE_REASONING>
Our codebase verifier found: <EVIDENCE_FROM_CODEBASE>

Specific question: <TARGETED_QUESTION>

Do you still hold your position? If so, what specific evidence would change your mind?" \
  | CODEX_HOME="$HOME/.codex-lean" codex exec --skip-git-repo-check resume --last 2>/dev/null
```

**`CODEX_HOME` is load-bearing here, and this is the one lane that stays raw.** The wrapper has no
resume mode — it always opens a fresh thread — so this follow-up calls the CLI directly. But the
lanes it is resuming ran under the wrapper's lean profile, so a resume from the default profile
finds the wrong thread or none at all and reads as "Codex declined to answer". If the CLI cannot be
reached here at all (shim rc=126/127), skip the debate and record it as unavailable in the report
rather than treating silence as a concession.

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

## Tiers, lane plan, per-repo lanes and budgets

Spec review is mandatory; only its depth varies (founder 2026-10-25). `lanes.json` is the one owner of
lane data: `profiles`, `tiers` (tier -> profile + `budget`), `gates`, `lanes`, `support`. A lane runs
when its `profiles` list holds the tier's profile OR its domain gate fired OR the `lanePlan` adds it.

| tier | profile | default lanes (plus every gate-fired lane) | falsifier |
|---|---|---|---|
| critical | `full` | the full 13-lane set (incl. legal, provider-fit, observability, drift, 3 extra Codex) | every CRITICAL, plus each MAJOR only one lane raised (`uncorroborated`) |
| standard | `standard` | completeness, codebase-verifier, edge-case, codex-frontier | CRITICAL only |
| light | `light` | codebase-verifier, edge-case, codex-frontier (plus completeness when `frame.runtimePath` is set); refused if any gate fired | off |
| hotfix | `hotfix` | codebase-verifier, architecture, critic-hotfix, codex-frontier | every CRITICAL/MAJOR (`all`) |

Findings outside the falsifier scope still appear in the report (verdict word SURVIVES with a
"not falsified at tier" note naming why: corroborated by a second lane, outside the tier scope or ceiling stop); only the falsifier dispatch is narrowed (`run_dir.py` `FALSIFIER_MODES`). `uncorroborated` is decided per merged unit after the merge: a MAJOR unit whose members come from two or more distinct lanes skips the falsifier; any unit with a CRITICAL member is always falsified.
Only the critical tier adds `fable-frontier-judge`, a final-gate judge on `fable` (Fable 5.1 today; re-probe the alias when 5.2 exists) that runs beside the Astra judge, never instead of it, and whose dispatch first line `ROLE: fable-frontier-judge` is the marker the harness model gate allows.
`floor` lanes (codex-frontier, codebase-verifier) are non-droppable, as is any lane whose gate fired. A lane's `gate`
may be a list (live-evidence-auditor: `liveSurface` or `externalShape`); any one fired runs it. A `keepFrom` lane
(completeness-reviewer, `keepFrom: standard`) cannot be dropped, disabled or retuned out of its profiles at that tier
and above, nor at `light` when `runtimePath` is set: a "reduced round" never loses the consumer census (P4).

**lanePlan** (main loop, Step 1): `{tier, add, drop, reasons}`, validated by `run_dir.py plan`
(unknown label, drop at critical, drop of a floor/gate-fired/`keepFrom` lane, light with a gate fired,
a `pathFloors` hit below critical with no naming reason, missing reason: all errors). Reasons print in the report's `### Lane plan` block either way.

**Per-repo override** `<project root>/.claude/spec-review.lanes.json`, merged over `lanes.json` and
validated by the same `validate_manifest`; both file paths are logged in the plan and the report:

```json
{"lanes": {"add": [{"label": "pii-check", "kind": "claude", "agentType": "general-purpose", "model": "sonnet",
                    "prompt": null, "brief": "...{{SPEC_PATH}} ... {{PROJECT_ROOT}}", "profiles": ["full"], "gate": null,
                    "idPrefix": "PII", "tags": []}],
           "disable": ["codex-research"],
           "retune": {"edge-case-miner": {"model": "sonnet", "profiles": ["full", "standard"]}}},
 "tiers": {"standard": {"budget": {"maxLanes": 9}}}}
```

Added lanes are `kind: claude` with an inline brief. Retunable fields: `model`, `profiles`, `codexClass`.
Floor, gate, `keepFrom` and substitute lanes cannot be disabled.

**Budget dials**: `maxLanes`, `maxCodexLanes` (advisory: the plan warns and the report prints planned vs ran),
`falsifier` (`all|uncorroborated|critical|off`) and `tokenCeiling`, which is calibrated and ENFORCED.

**Token ceilings.** Calibrated at about 0.7x the measured means (64.6M critical, 32.3M standard):
critical 45,000,000, standard 22,000,000, light 2,000,000, hotfix 3,000,000. Spend is Claude lane tokens
(`lane_spend.py`: input + cache + output per `ROLE:` lane, counting only agents whose prompt names this run dir)
plus the `tokens used` of this run's Codex dispatches. Every gate in `stage.py` re-measures it into
`<run>/lane-spend.json` (the per-lane spend log of every run; `report-check` writes the final one
automatically). At 1.0x of the ceiling the gate prints `SPEND WARNING` (also in the report's Lane plan block).
At 1.5x it prints `SPEND STOP`: no NEW optional work is launched, and the report names what ran and what did not
(`stoppedLanes` in `lane-spend.json`). Never dropped by the stop: the mandatory review itself, tier-floor
(`floor`) lanes, fired-gate lanes, codebase-verifier, the Astra frontier judge (and its critic), the coverage
repair of a floor or fired-gate lane, and the falsification of every CRITICAL unit. Droppable at the stop: the
second-wave drift investigators, the coverage repair of other lanes, the critic substitute for a dead
adversarial lane, and the falsification of MAJOR units. Wave 1 (the reviewer lanes) is one concurrent fan-out
launched before any spend is known, so the stop governs only the later waves; no lane is demoted by it. A lane
already running cannot be stopped either: one lane can cross 1.5x on its own, and the synthesis report still runs
(the review is mandatory). At the stop its brief is lean: envelopes, merged units, verdicts and lane files only.

**Quota stop and dead-agent cap.** The first session/weekly limit message in any of this run's Claude
agents (a synthetic `rate_limit` assistant message, `quota_hits` in `lane_spend.py`) or a Codex lane graded QUOTA
sets a sticky `quotaStopped` in `state.json` and `lane-spend.json`; `post-review`, `synth-prep`, `falsify-prep` and
`falsify-check` then refuse (exit 1, `quotaStopped:true`, one `QUOTA STOP` line) and launch nothing, so a limit is
never followed by relaunches (the audit's wf_d570cfb2 re-ran 17 lanes into the wall: 43M tokens). Lanes that
already wrote envelopes stay; the rest are listed `not run: quota`. `quota-clear [--after <ISO>]` resumes after the
reset. `lanes.json` `agentTurnCaps` (synthesis-writer 40, context-dossier-miner 80, from the audit's successful
agents: synthesis-writer p95 33, max 42, n=48; dossier-miner p95 67, max 84, n=42) are stated in the agent brief; an
agent with no result is DEAD, retried once, then the stage fails (the workflow's `withDeadRetry`).

## Why gate

A pre-flight check that runs BEFORE `prepare`, so no review token is spent on a spec that should not be
built as written. One Opus 5.5 lane (`why-gate` in `lanes.json` `support`, brief `prompts/why-gate.md`, no fan-out)
answers seven questions: (1) what real trigger or evidence makes this needed now; (2) can the playground (ADR-0036:
customer config, flows, MCP) or an existing primitive already do it; (3) the smallest version that delivers the
outcome and its explicit OUT list; (4) does the scope exceed that version, and why each extra item; (5) size in
days, and above 5 the hard dependency that forbids a smaller first ship; (6) the cheapest proof it works and what
would make us delete it; (7) which exit criterion of the parent map this advances and what remains
toward the destination after it ships. Its envelope (`<runDir>/why-gate.json`): `verdict` PROCEED | SIMPLIFY | WRONG-ROUTE,
`answers` q1..q7 (one line each), `whyRecord` (about 10 lines, PROCEED only).

Commands (main loop): `stage.py why-gate --run --spec --root --ticket [--docs-only <reason>]` writes the filled
prompt and prints the Workflow `{stage:"why"}` args; after the lane, `stage.py why-gate --run --check` validates the
envelope and records the outcome in `inputs/why-gate.json`. PROCEED writes `inputs/why-record.md` and appends the
record to `inputs/context.md`, so the dossier miners and every lane see it. SIMPLIFY or WRONG-ROUTE exit 1 with
`hardStop` and `required`: grill the founder with a recommended answer BEFORE any review lane runs, revise, rerun
`why-gate` (a rerun clears the stale envelope). `stage.py prepare` refuses (hardStop `why-gate`) unless the record
is `pass` or `skipped`; a `--prior` re-review needs no new gate.

Skips: tier `hotfix`, and a docs-only spec (`--docs-only` with the reason; a docs-only spec that specifies a
money, security, tenancy or credential change still gets the tier floor, only the Why gate is skipped). The skip
reason is printed once. Spend: the lane's prompt starts `ROLE: why-gate` and names the run dir, so `lane_spend.py`
lists it in `lane-spend.json` and counts it in the tier's `tokenCeiling` accounting; the ceilings are unchanged.

## Run costs (what this skill spends)

The measured study found Claude lanes carry 99.6% of spec-review tokens and cache reads dominate, so
cost follows turns x context. The levers, all in this skill: no LLM agent runs a command (every Bash step is a
`stage.py` gate the main loop runs); the dossier and decisions miners and the Codex envelope extraction run on
Codex (`verify` / `luna` / `luna`), with the Claude lane as the fallback only when the Codex lane is DEAD,
BLOCKED-ON-QUOTA or fails validation (graded by artifact); a re-review reuses the prior dossier and re-runs only
the lanes its depth mode selects; the falsifier skips corroborated MAJOR; ceilings are enforced.

**Re-review depth (R1, one mechanism)** (`stage.py prepare --prior <old run dir>`): copies the prior dossier,
questions and decisions and diffs the spec by markdown section (`inputs/spec.delta.diff`, `inputs/delta.md`). The
mode is measured, not chosen: **fix-verify** when the edit is 150 changed lines or fewer (`FIX_VERIFY_MAX_LINES`) and
no gate fired that the prior plan did not have; **delta** otherwise. Both RE-RUN a `floor` lane, a lane with no
usable prior result, and a lane that raised a finding `mark-applied` recorded as applied (verify the fix). Delta
also re-runs fired-gate lanes and lanes whose prior findings name a changed section heading or `section N`;
fix-verify re-runs a gate lane only if its gate is newly fired. Every other lane is CARRIED: prior envelope and
findings copied minus REFUTED and applied findings, listed as "carried forward". Re-run briefs get the delta block.
Merge and falsifier waves run over carried + new findings. No new dossier in either mode; a prior run without
`inputs/spec.snapshot.md` cannot seed a re-review: run a full review. No spec is ever skipped by this ladder.
`report-check` archives every run dir it passes (`stage.py` `archive_run`: `$SPEC_REVIEW_ARCHIVE/<spec stem>/<run name>`,
default base `~/.claude/spec-review/runs`) and prints it as `archivePath`; `mark-applied` updates the archived
`merged.json` too, so the archive is a complete `--prior` seed after the session's scratchpad is gone.

**Tier rules (R2-R4)**, enforced by `run_dir.py plan` from `frame.json` (`repo`, `harnessOnly`, `floorDomain`):
`critical` is refused unless the repo is in `lanes.json` `cynapRepos`, the spec is not tooling/harness-only, and a
floor domain exists (security or cutover gate fired, the cutover being shared-store, prod-traffic or credential-bearing, legalSurface fired in a cynap repo, or `floorDomain` named);
otherwise run `standard`, where every fired gate still adds its lane. Lanes marked `cynapOnly` (legal-auditor,
operator-plane-architect) are skipped, with that reason, in any other repo.

**Path-derived floor (R5, P6).** The floor check was one-directional: a fired gate or `floorDomain` could raise the
tier, but nothing read the spec's own paths. `plan --spec` now extracts every path the spec names (URLs excluded)
and matches it against `lanes.json` `pathFloors`, a small table of generic classes (auth-session, billing-ledger,
migrations, infra-stack, credentials-kms, shared-reader; each a `class` and a regex). A hit refuses `standard` and
`light` unless `frame.pathFloorReasons.<class>` is a reason that contains one of the hit paths (e.g. "reads
`src/auth/flags.ts` for a label only; no auth decision changes"). A harness-only spec is exempt (it tops out at
standard by R2), as is `hotfix`. Retune the table in `lanes.json`; keep classes generic.

**Gate evidence (founder 2026-10-27).** `run_dir.py plan` rejects a fired gate whose reason quotes no path, file:line, backticked token or snake_case/camelCase identifier (`gate_evidence_errors`). liveSurface fires only for a changed, named runtime behavior of a live system (narrowed below); cutover only for a removed/replaced owner with a stated switch-over step. Tier follows the changed surface: "docs only" is never a downgrade for a money, security, tenancy, credential or shared-infrastructure spec (a docs PR specifying a money migration stays on the floor), and a shared reader/writer used by every Lambda or process/sandbox-killing code stays critical (two replayed escapes: a docs-only money spec and a shared process-tree killer).

**Gated ADR and dependency lanes (founder 2026-11-04).** `adr-auditor` and `dependency-currency` were always-on (critical+standard, dependency-currency also hotfix) and were among the costliest non-falsifier lanes (adr 95M, dependency 134M tokens over 36 reviews; critical reviews averaged 48.5M vs the 45M ceiling). Each now runs at any tier only when its gate fires: `adrTouched` (the spec adds, changes or supersedes an Accepted ADR or platform invariant, or edits a `docs/adr/` file) and `dependencyChange` (the spec adds, upgrades, removes or pins a package, vendor, SDK or runtime version). An unfired gate skips the lane with `gate: <name> not fired` in the plan; a fired gate makes the lane non-droppable and forbids `light`. The ADR hard stop is unchanged once the lane is planned (`founder_approval_needed` without `founder_approval_marker_present`, or a missing envelope, stops the review), so firing `adrTouched` is the main loop's duty whenever an ADR or invariant moves. The dependency lane checks installed vs latest versions, CVE/GHSA advisories joined to CISA KEV with reachability, changelogs since the installed version, current vendor docs via Context7, and workarounds a newer version removes. Falsifier policy and ceilings are unchanged.

**Narrowed liveSurface gate (founder 2026-11-04).** In the product repo merging a PR is a prod deploy, so "changes a deployed artifact AND names it" was true of nearly every spec: liveSurface fired in 40 of 40 recent plans, and its two lanes (`live-evidence-auditor`, 163M tokens; `performance-architect`) ran on every review. The gate now fires only when the spec changes RUNTIME BEHAVIOR of a live system: request handlers, dispatch or queues, webhooks, billing or money paths, auth or credentials, data migrations or schema on live stores, deployed infrastructure wiring, or a model/LLM boundary. It does not fire for a spec that only changes tooling, the harness, skills, docs, CI config, dev scripts, lint rules, or config that has no live runtime consumer, even though merging it deploys something. The evidence rule is unchanged: a fired liveSurface reason must quote the runtime surface (a path, file:line or identifier), or `run_dir.py plan` rejects it. Lane membership, ceilings, falsifier policy and the other gates are unchanged.

**externalShape gate (P2, 2026-11-09).** The dominant escape class was a spec asserting the shape of something
unit tests cannot instantiate, then a fixture encoding the same invented value, so green tests defended the bug.
The gate fires when the spec asserts a shape, behavior, limit or lifecycle of: a vendor response or event body, a
cloud audit/log/query dialect, a managed-runtime lifecycle (init/freeze/thaw), a serverless or remote DB client
versus the embedded one used in tests, a KMS/IAM decision, a real production head or fixture, or an LLM following
an instruction. When fired, live-evidence-auditor runs at every tier and cannot be dropped, `light` is refused (any
fired gate forces `standard`+), and the spec must attach a CAPTURED real sample or a printed probe (command +
date). spec-test-plan builds the fixture from that sample, never an invented value; an instruction-following
assumption needs an eval row, not prose.

## Closure: carried obligations and proof per tier

A review finding is closed by the build, not by the report (P1). `### Carried obligations` in the report is a table
`| ID | Obligation | Proof | Owner | Close-by |` with one row per surviving CRITICAL/MAJOR finding from ANY lane
(EC/Sec/Obs/LE and every F-N unit; a row may list several ids) and per interaction/UX acceptance line the spec
states (`UX-N`). Proof names a test, probe, drive or bake. `validate_review_report.py` refuses a missing id, a
table with no Proof column and an empty or "TBD"/"owed" proof. The build PR body reproduces the table with each
row's receipt; the PR's spec-axis review (standards-spec-review) fails it on an unproven row.

| tier | proof owed before merge | after deploy |
|---|---|---|
| light | the targeted test | - |
| standard, runtime or portal behavior (the Profile line states `runtime path: <path>`; the validator then requires the row) | one named PRE-MERGE DRIVE row: portal, a preview with real auth; backend, a staging/test-org probe of the changed seam; interaction UI, a browser scenario | - |
| critical | the PRE-MERGE DRIVE row | a POST-DEPLOY BAKE row |

Drive, bake and any owed proof carry an owner and a close-by date (YYYY-MM-DD); the validator refuses one without,
and a `(tier critical)` report without both rows (P3). A proof owed with no named closing step is refused. A proof
later closed with a different result than the PR claimed is logged as an escape (LEARNINGS escape ledger).

**Fix receipt (P4).** A fix PR with no spec still carries three lines: `Invariant restored:` what is true again;
`Siblings swept:` the command that enumerated every consumer, mirrored copy and entry point, and its count;
`Found by:` the alarm, user report, review or probe that surfaced it.

**Applied flag.** Each merged unit in `merged.json` carries `applied` (null until the fixing step records it with
`stage.py mark-applied --ids F-1,F-3 [--status false]`), so value per token is measured, not guessed. The merge
covers every CRITICAL/MAJOR id at every tier; the tier's falsifier scope sets only each unit's `falsify` flag. (A
light run with the merge scoped to the falsifier wrote zero units over 25 findings, so every id was refused.)

**Lane cost rules.** Every review lane's run contract asks for ranged reads, batched independent reads, live
commands only when no file gives the value, and each deliverable written once. At `light` it also caps a lane at
`LANE_FINDING_CAP` (12) findings, overriding a brief's minimum row count. The synthesis brief forbids reading this
skill's scripts and multi-file `cat`s. Measured cause (spec-review-state-page-v2, light): a 53-row edge-case miner
whose tool calls each stalled ~600s on an unreachable PreToolUse hook, past the 5-minute subagent cache, so its last
8 turns re-created 173k-225k of context each.

## Follow-on census, unknowns and decisions

Why: in a backtest of mission chains (spec, fix, next spec, next fix), most unplanned follow-on missions were
knowable before build, and about half had no data or contract dependency on the mission before them, yet they ran
one after another. Four report tables move that discovery to review time and turn it into parallel work.

- **Follow-on dispositions (F1).** completeness-reviewer section H, a premortem: "this spec merged 30 days ago and
  more missions were needed; name them." High recall, filtered by evidence (a candidate with no spec line, file:line,
  PR or ledger row is dropped). Seeded classes: every deployed host running the new path; refusal paths a bake can
  match; the same defect class fixed elsewhere; release and version mechanics; recovery after a half-applied attempt;
  each drive or bake leg reachable on its fixture. Dispositions: `IN`, `PARALLEL-TICKET`, `PROBE`, `DEFER -> <target>`
  with a trigger, `OUT`. The join/defer rule decides `DEFER`: a need the spec's own goal (or its map's exit criteria)
  cannot pass without is never deferred. Required where completeness runs; `no candidates: <classes checked>` is the
  empty receipt.
- **Unknowns (F3).** Every claim nothing has proven: an uncaptured external sample, a deployed limit, a read-only
  dry run per seam on real target bytes (per seam, because the first failure masks the next), fixture readiness for
  each drive or bake leg, and for a performance goal a full-path per-hop trace before any fix. Each row is a
  read-only, time-boxed probe ticket with a document deliverable. **At most 3 probes per spec** by default:
  merge probes that share a seam, and go over only with a `probe cap override: <reason>` line under the table
  (the validator refuses a 4th row without it). Probes route to the cheapest lane class: Codex `luna` document
  lanes first, `sonnet` or `haiku` when Codex is unavailable, never `opus`; an uncapped probe wave on the top
  model is the one way this section can cost more than the late missions it saves. All probes dispatch in one message; at
  `standard`/`critical` a build ticket on a probed seam is blocked by its probe, at `light` the probe is advisory.
  Results amend the spec once (`--prior`, fix-verify).
- **Founder decisions owed (F7).** Every open default, ruling, signature and ADR status change the ships need, each
  with a recommended answer, grilled in one round before the spec merges, so a spec merges once.
- **Ship plan (F4).** The spec's `## Ships` table (`ship | scope items | files and contracts | blockedBy | dependency`)
  is checked by `scripts/ship_plan.py`: a serial edge is never typed `none`, a typed dependency has an edge, a ship
  holding both sides of a repo split rule (for example schema-before-caller) is refused, the after side must be
  blocked by the before side, and every numbered scope item maps to a ship or a `DEFER` row with a tracker id.
  Split rules are per repo (`<root>/.claude/split-rules.json`); they plan splits repo law already forces, never new
  slicing. Tickets and `blockedBy` edges are created from this table; `none` ships dispatch concurrently. The check
  is a separate script because every `stage.py` command is scoped to a run directory and the plan is checked on the
  spec before a run exists.
- **Sibling contract agreement (F5).** spec-drift-scout question 7: specs under one map that share a contract get
  a `contract agreement` table; a disagreement is MAJOR, `amend-both` or `sequence-after`.

`validate_review_report.py` refuses a candidate with no evidence or disposition, a `PARALLEL-TICKET`/`DEFER` with no
tracker id (the synthesizer writes `to-file`; `--final` before the commit refuses it), a `DEFER` with no trigger, a
`PROBE` with no Unknowns row, an unknown with no probe, time-box or blocked ship, and a decision with no recommended
answer.

**Measurement: discovered missions per map.** Not a gate. When a map closes, count the child tickets added after
charting and label each with the chain taxonomy: knowable at spec, knowable with a spike, genuinely new, scope cut
or deferred, end goal undefined, serial but parallelizable, split too early, gate-driven. Each `State as of` map
comment reports the running count (`discovered: N since charting`). It is the data any future appetite or reference-class rule would need; no stop rule uses it until
that data exists.
