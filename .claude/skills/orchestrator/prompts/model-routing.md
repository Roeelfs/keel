# Model & effort routing

Per-lane recommendations to minimize token cost. The state-miner emits `recommended_model` + `recommended_effort` per lane into the program state file (`~/.claude/orchestrator/programs/<slug>.state.md`); the orchestrator surfaces them in the survey and in lane missions.

## Models

**Claude:** Fable 5 (`claude-fable-5`, alias `fable`) is the highest-capability final/security gate; Opus 5 (`claude-opus-5`, alias `opus`) starts complex agentic coding and architecture; Sonnet 5 is the routine-development tier; Haiku 4.5 is the high-volume mining tier.

> Keep Fable + Opus in the deep-review panel for model diversity even though the vendor now documents Fable as the most capable widely released model.

**Codex:** Sol is the frontier judgement tier; Terra is the everyday implementation/review tier; Luna is the high-volume mining/procedure tier; Spark is trivial/mechanical only. Native `spawn_agent` exposes all four tiers. Machine defaults are Luna-low for children; every Terra or Sol child is an explicit role choice.

## Effort

**Claude** — per-turn keyword in the lane's mission or wake prompt: `(none)` / `think` / `think hard` / `think harder` / `ultrathink`.

**Codex** — session-level reasoning level (selectable mid-session via Codex menu): `Low` / `Medium` (default) / `High` / `Extra high`. Map approximately: Low↔standard, Medium↔think, High↔think hard, Extra high↔think harder.

## Matrix

| Lane purpose | Claude | Codex | Effort |
|---|---|---|---|
| Define: spec + moderate proof ledger | Sonnet | gpt-5.6-terra | think / Medium |
| Define: one critical coverage review | Sonnet | gpt-5.6-terra | think / Medium |
| Define: unresolved security/irreversible dispute | Opus + Codex | gpt-5.6-sol | think harder / Extra high |
| Build: implementation + targeted tests | Sonnet | gpt-5.6-terra | think / Medium |
| Verify-release: finite execution | Sonnet | gpt-5.6-terra | think / Medium |
| Procedural worker: deterministic command pass | Haiku | gpt-5.6-luna | standard / Low |
| Verify-release: failure-cluster diagnosis | Sonnet | gpt-5.6-terra | think / Medium |
| Bug fix < 200 LOC | Sonnet | gpt-5.6-terra | think / Medium |
| Trivial < 50 LOC, docs | Haiku | gpt-5.6-luna | standard / Low |
| Mining / surveys / parsing | Haiku | gpt-5.6-luna | standard / Low |
| Soak observation | Haiku | gpt-5.6-luna | standard / Low |
| Soak ESCALATE investigation | Sonnet | gpt-5.6-terra | think / Medium |
| PR comment review | Sonnet | gpt-5.6-terra | think / Medium |
| Refactor (no API change) | Sonnet | gpt-5.6-terra | think / Medium |
| Refactor (API change) | Sonnet | gpt-5.6-terra | think / Medium |
| Hard RCA / critical-path debugging | Opus | gpt-5.6-sol | think harder / Extra high |
| Security review | Fable 5 + Opus 5 | gpt-5.6-sol | think harder / Extra high |
| Irreversible architecture decision | Opus | gpt-5.6-sol | think hard / High |
| Migration writing | Sonnet | gpt-5.6-terra | think / Medium |
| Migration risk review | Sonnet | gpt-5.6-terra | think / Medium |
| Self-managed interactive | Sonnet | gpt-5.6-terra | think / Medium |
| Wake-driven soak watcher | Haiku | gpt-5.6-terra | standard / Low |
| Orchestrator (Claude) | Opus | n/a | think / Medium |
| Orchestrator (long-lived Codex root) | n/a | gpt-5.6-terra | Medium |

## Subagent dispatch

| Role | Claude `Agent` | Codex `spawn_agent` |
|---|---|---|
| State miner | Haiku | gpt-5.6-luna (low) |
| Topical reviewers | Sonnet | gpt-5.6-terra (medium) |
| Boundary / security / adversarial | Fable 5 + Opus 5 | gpt-5.6-sol (xhigh) |
| Coverage verifier | n/a | gpt-5.6-terra (medium) |
| Failure diagnostician | Sonnet | gpt-5.6-terra (medium) |
| Failure-cluster diagnostician | Sonnet | gpt-5.6-terra (medium) |
| Procedural worker | Haiku | gpt-5.6-luna (low) |
| Doc writer / file search | Haiku | gpt-5.6-luna (low) |

## Rules

1. Subagents default to the cheap tier. State miner is always cheap-tier, even from a flagship orchestrator.
2. Effort costs tokens; only apply where the matrix says.
3. Respect a lane's `model_override` in the program state file — never silently reclassify it.
4. An idle lane costs nothing; don't retire one to "save tokens."
5. Cross-runtime second-opinion (flagship Claude + flagship Codex paired) is the one rational flagship double-up — different bug classes.
6. Deep-review bucket (security review, adversarial review, final-gate critique) is split **Fable 5 + Opus 5** — model diversity beats a single-model monoculture; never route all deep-review lanes to one model.
7. **Ad-hoc delegation defaults to `sonnet`.** Research / investigation / mining / exploration / execution dispatches route to `sonnet` or `haiku`; **`opus` requires a one-line justification in the dispatch**; `fable` (or `gpt-5.6-sol` on the Codex side) is reserved for the hardest verify / judge / adversarial reasoning. The Fable-pinned NAMED agents (critic, security-reviewer) stay Fable by design. A permissive default silently becomes an opus default — measured: 189 dispatches went opus 59 / sonnet ~80 / haiku 2.
8. **Bounded Codex children do not inherit the whole parent by default.** Give them a self-contained mission and `fork_turns: "none"` or the smallest positive slice that carries the evidence. Use `"all"` only when the whole conversation is genuinely load-bearing; full-history forks also inherit the parent's model and effort.
9. **The long-lived Codex orchestrator root is Terra-medium.** Context accumulation is the root's dominant multiplier; do not pay frontier weight on coordination, waiting, integration, or routine execution.
10. **Sol is a fresh bounded escalation, not a phase-spanning root.** Use it for irreversible architecture, security/trust boundaries, hard RCA, or final adversarial judgment. Return one decision artifact to the Terra root, then stop the Sol lane.
11. **Existing implementation is resume work, not a new lifecycle.** Honor same-SHA evidence; do not spend a new review/test wave proving unchanged code.
12. **A user stop instruction overrides every review manifest and proof gate.** Interrupt, preserve, hand off. No final test or closure pass is earned.
