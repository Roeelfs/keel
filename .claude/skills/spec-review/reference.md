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
**Model:** gpt-6-sol at high | **Mode:** single-pass [or adaptive]

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
