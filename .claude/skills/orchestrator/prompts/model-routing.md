# Model & effort routing

Per-lane recommendations to minimize token cost. The state-miner emits `recommended_model` + `recommended_effort` per lane into the program state file (`~/.claude/orchestrator/programs/<slug>.state.md`); the orchestrator surfaces them in the survey and in lane missions.

## Models

**Claude:** Fable 5 (`claude-fable-5`, alias `fable`) is the highest-capability final/security gate; Opus 5 (`claude-opus-5`, alias `opus`) starts complex agentic coding and architecture; Sonnet 5 is the routine-development tier; Haiku 4.5 is the high-volume mining tier.

> Keep Fable + Opus in the deep-review panel for model diversity even though the vendor now documents Fable as the most capable widely released model.

**Codex:** Sol is the frontier judgement tier; Terra is the everyday implementation/review tier; Luna is the headless high-volume mining tier; Spark is headless trivial/mechanical only. Native `spawn_agent` currently exposes Sol and Terra overrides, so native mining uses Terra low even when the headless dispatcher can use Luna/Spark.

## Effort

**Claude** — per-turn keyword in the lane's mission or wake prompt: `(none)` / `think` / `think hard` / `think harder` / `ultrathink`.

**Codex** — session-level reasoning level (selectable mid-session via Codex menu): `Low` / `Medium` (default) / `High` / `Extra high`. Map approximately: Low↔standard, Medium↔think, High↔think hard, Extra high↔think harder.

## Matrix

| Lane purpose | Claude | Codex | Effort |
|---|---|---|---|
| Spec authoring (step 2) | Opus | gpt-5.6-sol | think hard / High |
| /spec-review (steps 3, 6) | Opus + Codex | gpt-5.6-sol | think harder / Extra high |
| /spec-test-plan (step 4) | Sonnet | gpt-5.6-terra | think / Medium |
| Step 4b spec patches | Sonnet | gpt-5.6-terra | think / Medium |
| Implementation plan (step 5) | Opus | gpt-5.6-sol | think hard / High |
| Plan review (step 6) | Opus + Codex | gpt-5.6-sol | think harder / Extra high |
| Implementation (step 7) | Sonnet | gpt-5.6-terra | think / Medium |
| spec-test-execute (step 8) | Sonnet | gpt-5.6-terra | think / Medium |
| Bug fix < 200 LOC | Sonnet | gpt-5.6-terra | think / Medium |
| Trivial < 50 LOC, docs | Haiku | gpt-5.6-terra | standard / Low |
| Mining / surveys / parsing | Haiku | gpt-5.6-terra | standard / Low |
| Soak observation | Haiku | gpt-5.6-terra | standard / Low |
| Soak ESCALATE investigation | Opus | gpt-5.6-sol | think hard / High |
| PR comment review | Sonnet | gpt-5.6-terra | think / Medium |
| Refactor (no API change) | Sonnet | gpt-5.6-terra | think / Medium |
| Refactor (API change) | Opus | gpt-5.6-sol | think hard / High |
| Critical-path debugging | Opus | gpt-5.6-sol | think harder / Extra high |
| Security review | Fable 5 + Opus 5 | gpt-5.6-sol | think harder / Extra high |
| Migration writing | Sonnet | gpt-5.6-terra | think / Medium |
| Migration risk review | Opus | gpt-5.6-sol | think hard / High |
| Self-managed interactive | Sonnet | gpt-5.6-terra | (user drives) |
| Wake-driven soak watcher | Haiku | gpt-5.6-terra | standard / Low |
| Orchestrator | Opus | gpt-5.6-sol | think / Medium |

## Subagent dispatch

| Role | Claude `Agent` | Codex `spawn_agent` |
|---|---|---|
| State miner | Haiku | gpt-5.6-terra (low) |
| Topical reviewers | Sonnet | gpt-5.6-terra (medium) |
| Boundary / security / adversarial | Fable 5 + Opus 5 | gpt-5.6-sol |
| Coverage verifier | n/a | gpt-5.6-sol |
| Failure diagnostician | Sonnet | gpt-5.6-terra (medium) |
| Codex rescue | n/a | gpt-5.6-sol |
| Doc writer / file search | Haiku | gpt-5.6-terra (low) |

## Rules

1. Subagents default to the cheap tier. State miner is always cheap-tier, even from a flagship orchestrator.
2. Effort costs tokens; only apply where the matrix says.
3. Respect a lane's `model_override` in the program state file — never silently reclassify it.
4. An idle lane costs nothing; don't retire one to "save tokens."
5. Cross-runtime second-opinion (flagship Claude + flagship Codex paired) is the one rational flagship double-up — different bug classes.
6. Deep-review bucket (security review, adversarial review, final-gate critique) is split **Fable 5 + Opus 5** — model diversity beats a single-model monoculture; never route all deep-review lanes to one model.
7. **Ad-hoc delegation defaults to `sonnet`.** Research / investigation / mining / exploration / execution dispatches route to `sonnet` or `haiku`; **`opus` requires a one-line justification in the dispatch**; `fable` (or `gpt-5.6-sol` on the Codex side) is reserved for the hardest verify / judge / adversarial reasoning. The Fable-pinned NAMED agents (critic, security-reviewer) stay Fable by design. A permissive default silently becomes an opus default — measured: 189 dispatches went opus 59 / sonnet ~80 / haiku 2.
8. **Bounded Codex children do not inherit the whole parent by default.** Give them a self-contained mission and `fork_turns: "none"` or the smallest positive slice that carries the evidence. Use `"all"` only when the whole conversation is genuinely load-bearing; full-history forks also inherit the parent's model and effort.
