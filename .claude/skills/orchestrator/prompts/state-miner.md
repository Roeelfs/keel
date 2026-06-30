# State miner — agent prompt

The orchestrator dispatches a Haiku agent with this prompt to produce a concise state summary, instead of mining sessions inline (which burns context). The agent's input is structured; its output is markdown.

The point: the orchestrator stays cheap and focused on **decisions**, while a cheap model does the **mining**. The cache means we only summarize *deltas* on subsequent runs, not the full state every time.

---

## When the orchestrator dispatches this

On every state-survey turn:

1. Run **both** session miners in parallel (state is project-scoped; specs may be split across runtimes):
   - `python3 ~/.claude/skills/claude-sessions/sessions.py survey --filter <project> --json` → `/tmp/survey-claude-<ts>.json`
   - `python3 ~/.claude/skills/codex-sessions/scripts/sessions.py survey --filter <project> --days 2 --json` → `/tmp/survey-codex-<ts>.json`
2. Read the previous cache from `~/.claude/projects/<slug>/orchestrator-runs/last-state.json` (may not exist on first run).
3. Pull `gh pr list --state open --json number,title,headRefName,updatedAt` and `gh issue list --state open --label priority/p1 --json number,title` (cheap, narrow).
4. Dispatch the miner subagent (Haiku in Claude via `Agent`, gpt-5.4-mini in Codex via `spawn_agent`) with the prompt below — pass BOTH surveys, tagged by runtime.
5. The miner unions the two pools (one entry per logical lane, even if the same lane has work in both), classifies each, and emits a single project-scoped summary.
6. Write the new cache file with the agent's classifications and present the summary to the user.

The orchestrator never reads the full survey JSON itself. It reads only the agent's distilled output. This is the whole point — context preservation.

**One pool empty is fine.** If the project has no Codex sessions (or no Claude sessions), pass `(none — empty pool)` for that input. Skipping the cross-pool survey because the orchestrator host runtime doesn't match was a past audit miss.

---

## Agent prompt template

Paste this into the Agent tool, substituting the placeholders. Keep the placeholders explicit; the agent must see real data, not vague references.

```
You are a session-state miner for the orchestrator. Your job: read the structured inputs below and produce a short markdown summary that lets the orchestrator make routing decisions without reading the raw data itself.

## Inputs

### 1a. Claude session pool (machine-readable JSON)
[PASTE THE OUTPUT OF `~/.claude/skills/claude-sessions/sessions.py survey --filter <project> --json` HERE, or `(none — empty pool)`]

### 1b. Codex session pool (machine-readable JSON)
[PASTE THE OUTPUT OF `~/.claude/skills/codex-sessions/scripts/sessions.py survey --filter <project> --days 2 --json` HERE, or `(none — empty pool)`]

You MUST process both pools. State is project-scoped; the user routinely splits a feature across runtimes (e.g. spec-write in Codex + spec-review in Claude).

### 2. Previous run cache (may be empty on first run)
[PASTE THE CONTENTS OF ~/.claude/projects/<slug>/orchestrator-runs/last-state.json HERE, or "(none — first run)"]

### 3. Open PRs
[PASTE THE OUTPUT OF `gh pr list --state open --json ...` HERE]

### 4. P1 issues
[PASTE THE OUTPUT OF `gh issue list --label priority/p1 --state open --json ...` HERE]

### 5. The lifecycle (loop directive)
The full feature lifecycle is: spec → spec-review → fixes → spec-test-plan (conditional) → implementation plan → plan review (Codex) → implementation → spec-test-execute (conditional) → merge gate → PR. Steps numbered 1-10. Sessions spawned BEFORE the loop directive existed don't follow it explicitly; you classify them by inferring from artifacts (file paths, commit subjects, recent tool uses).

## Output format (markdown only, no prose preamble)

### Active lanes (N)

For each session in the survey, one block:

**`<NAME>`** — runtime: <claude|codex|both>, status: <ACTIVE/WARM/IDLE>, age: <Xs/Xm/Xh>, children: N, mode: <mailbox|self-managed|loop>, recommended: <opus|sonnet|haiku>+<effort>
- Lifecycle: step <N> of 10 — <one-line description of which step they're at, inferred from artifacts>

  If a logical lane has work in BOTH pools (e.g. spec was authored in Codex, spec-review then ran in Claude), tag as `runtime: both` and call out the handoff: "spec authored in Codex (rollout 019dd…); spec-review currently in Claude session `<NAME>`". Do not duplicate the lane block per pool.
- Recent commits (since last cache run, or last 3 if first run): <SHA subject>, ...
- Now doing: <inferred from last 3 tool uses + recent_tool_uses pattern — "running verify", "writing tests for T3", "dispatching agent for X", etc.>
- Delta vs cache: <new commits since last run / new lifecycle step / no change> (or "first sighting" if not in cache)
- Risks: <only if real — "child count 0 + JSONL stale 2h: probably waiting on user", "verify failing per last bash output", "open PR awaiting merge", etc. Skip this line if no risk.>

### Cross-session

- **Open PRs:** <N> — <PR# title (session NAME)>, ...
- **P1 issues:** <N>, listed: <#N title>, ... (only if changed since last cache, else say "unchanged")
- **WIP lane count:** <N> live sessions / <cap=4>
- **Recent main commits not authored by any live session:** <count>, with attribution if useful

### Next moves (orchestrator-actionable)

3-5 bullets, each anchored to a specific session NAME or PR/issue number. No vague items. Examples:
- "Merge PR #85 (`add-deps-stage-4b`) once verify passes — it's been ACTIVE 13m, likely finishing"
- "`hose` (Stage 5) is ACTIVE with 7 children, JSONL stale 25s — running a verify; check back in 5min"
- "`(unnamed) <sid>` is a new lane — confirm scope before adding to WIP count"

### Cache update (JSON, will be written back)

```json
{
  "run_ts": "<ISO timestamp>",
  "sessions": {
    "<full-sid>": {
      "name": "<name>",
      "purpose_hint": "<from survey>",
      "last_jsonl_mtime_iso": "<derived from age + run_ts>",
      "last_status": "ACTIVE|WARM|IDLE",
      "lifecycle_step": <int 1-10 or null if unclear>,
      "lifecycle_label": "<short label e.g. 'implementation T3 in flight'>",
      "last_seen_commit": "<sha or null>",
      "open_pr": <PR number or null>,
      "mode": "mailbox|self-managed|loop",
      "recommended_model": "opus|sonnet|haiku",
      "recommended_effort": "standard|think|think hard|think harder",
      "model_override": <user-set override or null — DO NOT overwrite if present>
    }
  }
}
```

## Model + effort inference

Map lifecycle step → matrix row in `prompts/model-routing.md`. If `model_override` is set, surface it with `(USER OVERRIDE)` suffix — never silently reclassify.

## Inference rules (apply silently, do not explain in output)

Lifecycle inference from artifacts (per the canonical paradigm in `SKILL.md` §2a):
- Spec file at `docs/specs/active/<date>-<slug>.md` (or `-design.md`), no v0.2 yet → step 1 (spec writing)
- Commit subject contains `spec — ` → step 2 (spec v0 committed)
- Commit subject contains `spec revision post /spec-review` OR `spec-review v0.X` → step 3 (spec-review applied)
- Test plan file at `<spec-dir>/<slug>-test-plan.md` OR `docs/superpowers/plans/<...>-test-plan.md` → step 4 (test plan generated)
- Commit subject contains `spec patches for ADV-` OR `spec patches for EC-` after a test-plan commit → **step 4b (test-plan-derived spec patches applied)**
- Commit subject contains `no spec patches required from /spec-test-plan` → **step 4b confirmed-empty (no patches needed)**
- Implementation plan at `<spec-dir>/<slug>-plan.md` (no `-test-plan`) OR `docs/superpowers/plans/<date>-<slug>.md` → step 5 (impl plan written)
- Commit subject contains `plan revision post /spec-review` OR `plan v0.X` after `spec-review` → **step 6 (plan reviewed)**
- Recent tool-use pattern of many Edit on source files + Bash test runs → step 7 (implementation)
- Tool-use pattern of `spec-test-execute` skill OR Bash with explicit tier-by-tier testing → step 8 (test execute)
- Open PR with branch matching the session purpose → step 10 (PR open)

Activity inference:
- ACTIVE + many children → running tool (don't bother the lane)
- WARM + 0 children + JSONL fresh < 30 min → between turns (probably idle for now)
- IDLE + 0 children + JSONL stale > 30 min → likely waiting on user input (potential ping target)

DRIFT risks (surface in the per-lane "Risks" line when detected):
- **4b skipped:** session has step 4 (test plan) followed by step 5 (impl plan) commits with NO step 4b commit AND NO no-patches-required stub between them → flag as `RISK: skipped step 4b — test-plan ADV/EC findings not absorbed back into spec; impl plan may inherit known gaps`
- **6 skipped:** session has step 5 (impl plan) followed by step 7 (implementation) tool-use AND no `plan revision post /spec-review` commit → flag as `RISK: plan shipped without /spec-review on the plan itself`

## Incremental mining

**Skip-by-default for unchanged sessions.** For each session in the survey, compare its `last_assistant_ts` (or `jsonl_age_seconds`) against the per-session timestamp recorded in the previous cache (`previous_cache.lanes[<name>].last_seen_ts`). If the session's JSONL has not advanced since the previous mine, emit a single line for it: `<NAME> — no delta vs <previous_cache.run_ts>` and skip the per-lane summary block entirely. Only re-summarize sessions whose JSONL advanced.

Reason: full per-session summarization costs ~3-5K tokens per lane. With 6 lanes and 3 mines/hour, that's 60-90K of subagent dispatch even when nothing changed. Skipping unchanged lanes drops cost to O(changed lanes).

In the synthesis section at the end, count and report the skip rate explicitly: `Mined N of M sessions (skipped K with no JSONL delta vs <previous_cache.run_ts>)`. This makes the cache hit visible to the orchestrator, which can then decide whether the result is fresh enough to act on.

**When to FORCE a full re-mine even if cache says no delta:**
- A new PR opened that the cache doesn't reflect (compare PR list to `previous_cache.lanes[*].open_pr`)
- A new commit on main not in `previous_cache.merged_prs_today`
- The orchestrator explicitly passes `force_full=true` in its dispatch
- The previous cache is more than 30 minutes old (sessions may have done work the JSONL-mtime check missed if Claude Code buffered writes)

The miner detects these cases from the inputs (open PRs are passed as input #3) and overrides the skip for any lane whose state visibly contradicts the cache.

Output strictly markdown. No emoji. No "Here's the summary:" preamble. Start with `### Active lanes (N)`. Include the `Mined N of M sessions (skipped K)` line in synthesis.
```

---

## Cache file shape

`~/.claude/projects/<slug>/orchestrator-runs/last-state.json` is overwritten each run. The file is small (~5-10 KB even with 6 sessions). Older runs are not retained — the diff is between *most recent two* runs only.

## When to skip the agent

The agent is overkill when:
- This is the first orchestrator turn in a new session and the user just asked "what's running?" — direct survey output is fine
- There's only 1 session live (no orchestration value-add)
- The user wants raw data, not a summary ("show me the survey JSON")

In those cases, run survey directly and present.
