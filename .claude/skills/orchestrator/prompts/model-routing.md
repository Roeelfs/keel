# Model & effort routing

Per-lane recommendations to minimize token cost. The state-miner emits `recommended_model` + `recommended_effort` per lane into the program state file (`~/.claude/orchestrator/programs/<slug>.state.md`); the orchestrator surfaces them in the survey and in lane missions.

## Models

**Claude:** Fable 5 (`claude-fable-5`, alias `fable`) + Opus 5 (`claude-opus-5`, alias `opus`) — the two top reasoning tiers → Sonnet 5 (~0.2×) → Haiku 4.5 (~0.04×)

> Opus 5 released 2026-07-24, superseding Opus 4.8. Its cost weight and its standing relative to Fable 5 are **unmeasured here** — the deep-review bucket stays split across both (see 6 below) rather than being re-ranked on a guess.
**Codex:** `gpt-5.6-sol` — the only id named by standing law, so the Codex column below is uniform. Cheaper Codex tiers exist per release; **verify one exists before pinning it**, and never pin a dated id that the installed CLI does not know.

## Effort

**Claude** — per-turn keyword in the lane's mission or wake prompt: `(none)` / `think` / `think hard` / `think harder` / `ultrathink`.

**Codex** — session-level reasoning level (selectable mid-session via Codex menu): `Low` / `Medium` (default) / `High` / `Extra high`. Map approximately: Low↔standard, Medium↔think, High↔think hard, Extra high↔think harder.

## Matrix

| Lane purpose | Claude | Codex | Effort |
|---|---|---|---|
| Spec authoring (step 2) | Opus | gpt-5.6-sol | think hard / High |
| /spec-review (steps 3, 6) | Opus + Codex | gpt-5.6-sol | think harder / Extra high |
| /spec-test-plan (step 4) | Sonnet | gpt-5.6-sol | think / Medium |
| Step 4b spec patches | Sonnet | gpt-5.6-sol | think / Medium |
| Implementation plan (step 5) | Opus | gpt-5.6-sol | think hard / High |
| Plan review (step 6) | Opus + Codex | gpt-5.6-sol | think harder / Extra high |
| Implementation (step 7) | Sonnet | gpt-5.6-sol | standard / Low |
| spec-test-execute (step 8) | Sonnet | gpt-5.6-sol | standard / Low |
| Bug fix < 200 LOC | Sonnet | gpt-5.6-sol | standard / Low |
| Trivial < 50 LOC, docs | Haiku | gpt-5.6-sol | standard / Low |
| Mining / surveys / parsing | Haiku | gpt-5.6-sol | standard / Low |
| Soak observation | Haiku | gpt-5.6-sol | standard / Low |
| Soak ESCALATE investigation | Opus | gpt-5.6-sol | think hard / High |
| PR comment review | Sonnet | gpt-5.6-sol | think / Medium |
| Refactor (no API change) | Sonnet | gpt-5.6-sol | think / Medium |
| Refactor (API change) | Opus | gpt-5.6-sol | think hard / High |
| Critical-path debugging | Opus | gpt-5.6-sol | think harder / Extra high |
| Security review | Fable 5 + Opus 5 | gpt-5.6-sol | think harder / Extra high |
| Migration writing | Sonnet | gpt-5.6-sol | think / Medium |
| Migration risk review | Opus | gpt-5.6-sol | think hard / High |
| Self-managed interactive | Sonnet | gpt-5.6-sol | (user drives) |
| Wake-driven soak watcher | Haiku | gpt-5.6-sol | standard / Low |
| Orchestrator | Opus | gpt-5.6-sol | think / Medium |

## Subagent dispatch

| Role | Claude `Agent` | Codex `spawn_agent` |
|---|---|---|
| State miner | Haiku | gpt-5.6-sol |
| Topical reviewers | Sonnet | gpt-5.6-sol |
| Boundary / security / adversarial | Fable 5 + Opus 5 | gpt-5.6-sol |
| Coverage verifier | n/a | gpt-5.6-sol |
| Failure diagnostician | Sonnet | gpt-5.6-sol |
| Codex rescue | n/a | gpt-5.6-sol |
| Doc writer / file search | Haiku | gpt-5.6-sol |

## Rules

1. Subagents default to the cheap tier. State miner is always cheap-tier, even from a flagship orchestrator.
2. Effort costs tokens; only apply where the matrix says.
3. Respect a lane's `model_override` in the program state file — never silently reclassify it.
4. An idle lane costs nothing; don't retire one to "save tokens."
5. Cross-runtime second-opinion (flagship Claude + flagship Codex paired) is the one rational flagship double-up — different bug classes.
6. Deep-review bucket (security review, adversarial review, final-gate critique) is split **Fable 5 + Opus 5** — model diversity beats a single-model monoculture; never route all deep-review lanes to one model.
7. **Ad-hoc delegation defaults to `sonnet`.** Research / investigation / mining / exploration / execution dispatches route to `sonnet` or `haiku`; **`opus` requires a one-line justification in the dispatch**; `fable` (or `gpt-5.6-sol` on the Codex side) is reserved for the hardest verify / judge / adversarial reasoning. The Fable-pinned NAMED agents (critic, security-reviewer) stay Fable by design. A permissive default silently becomes an opus default — measured: 189 dispatches went opus 59 / sonnet ~80 / haiku 2.
