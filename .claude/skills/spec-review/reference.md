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

