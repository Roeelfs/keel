# Model & effort routing

Per-lane recommendations to minimize token cost. State-miner emits `recommended_model` + `recommended_effort` per session in `last-state.json`; orchestrator surfaces in survey + lane spawn prompts.

## Models

**Claude:** Fable 5 (`claude-fable-5`, alias `fable` — top reasoning tier) → Opus 4.8 (1.0×) → Sonnet 5 (~0.2×) → Haiku 4.5 (~0.04×)
**Codex:** gpt-5.6-sol (1.0×) → gpt-5.4 (~0.3×) → gpt-5.4-mini (~0.05×)

## Effort

**Claude** — per-turn keyword in mailbox `message`: `(none)` / `think` / `think hard` / `think harder` / `ultrathink`.

**Codex** — session-level reasoning level (selectable mid-session via Codex menu): `Low` / `Medium` (default) / `High` / `Extra high`. Map approximately: Low↔standard, Medium↔think, High↔think hard, Extra high↔think harder.

## Matrix

| Lane purpose | Claude | Codex | Effort |
|---|---|---|---|
| Spec authoring (step 2) | Opus | gpt-5.4 | think hard / High |
| /spec-review (steps 3, 6) | Opus + Codex | gpt-5.6-sol | think harder / Extra high |
| /spec-test-plan (step 4) | Sonnet | gpt-5.4 | think / Medium |
| Step 4b spec patches | Sonnet | gpt-5.4 | think / Medium |
| Implementation plan (step 5) | Opus | gpt-5.4 | think hard / High |
| Plan review (step 6) | Opus + Codex | gpt-5.6-sol | think harder / Extra high |
| Implementation (step 7) | Sonnet | gpt-5.4 | standard / Low |
| spec-test-execute (step 8) | Sonnet | gpt-5.4 | standard / Low |
| Bug fix < 200 LOC | Sonnet | gpt-5.4 | standard / Low |
| Trivial < 50 LOC, docs | Haiku | gpt-5.4-mini | standard / Low |
| Mining / surveys / parsing | Haiku | gpt-5.4-mini | standard / Low |
| Soak observation | Haiku | gpt-5.4-mini | standard / Low |
| Soak ESCALATE investigation | Opus | gpt-5.6-sol | think hard / High |
| PR comment review | Sonnet | gpt-5.4 | think / Medium |
| Refactor (no API change) | Sonnet | gpt-5.4 | think / Medium |
| Refactor (API change) | Opus | gpt-5.4 | think hard / High |
| Critical-path debugging | Opus | gpt-5.6-sol | think harder / Extra high |
| Security review | Fable 5 + Opus 4.8 | gpt-5.6-sol | think harder / Extra high |
| Migration writing | Sonnet | gpt-5.4 | think / Medium |
| Migration risk review | Opus | gpt-5.6-sol | think hard / High |
| Self-managed interactive | Sonnet | gpt-5.4 | (user drives) |
| Mailbox-mode soak watcher | Haiku | gpt-5.4-mini | standard / Low |
| Orchestrator | Opus | gpt-5.6-sol | think / Medium |

## Subagent dispatch

| Role | Claude `Agent` | Codex `spawn_agent` |
|---|---|---|
| State miner | Haiku | gpt-5.4-mini |
| Topical reviewers | Sonnet | gpt-5.4 |
| Boundary / security / adversarial | Fable 5 + Opus 4.8 | gpt-5.6-sol |
| Coverage verifier | n/a | gpt-5.4-mini |
| Failure diagnostician | Sonnet | gpt-5.4 |
| Codex rescue | n/a | gpt-5.6-sol |
| Doc writer / file search | Haiku | gpt-5.4-mini |

## Rules

1. Subagents default to the cheap tier. State miner is always cheap-tier, even from a flagship orchestrator.
2. Effort costs tokens; only apply where the matrix says.
3. Respect `model_override` in `last-state.json[<sid>]`.
4. Mailbox-idle is free; don't retire to "save tokens."
5. Cross-runtime second-opinion (flagship Claude + flagship Codex paired) is the one rational flagship double-up — different bug classes.
6. Deep-review bucket (security review, adversarial review, final-gate critique) is split **Fable 5 + Opus 4.8** — model diversity beats a single-model monoculture; never route all deep-review lanes to one model.
