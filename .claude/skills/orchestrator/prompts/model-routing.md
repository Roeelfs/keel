# Model & effort routing

Per-lane recommendations to minimize token cost. The state-miner emits `recommended_model` + `recommended_effort` per lane into the program state file (`~/.claude/orchestrator/programs/<slug>.state.md`); the orchestrator surfaces them in the survey and in lane missions.

## Models

**Claude:** Fable 5.1 (alias `fable`) is the highest-capability final/security gate; Opus 5.5 (alias `opus`) starts complex agentic coding and architecture; Sonnet 5 is the routine-development tier; Haiku 4.5 is the high-volume mining tier.

> Keep Fable + Opus in the deep-review panel for model diversity even though the vendor now documents Fable as the most capable widely released model.

**Codex:** model + effort per class is single-sourced in `~/.claude/scripts/codex-headroom.sh` — its case statement is **the one route table** ("THIS CASE STATEMENT IS THE ONE ROUTE TABLE: it owns model AND effort per class"). Ask it with `--route <class>` (echoes `<model> <effort>`), or dispatch directly with `codex-dispatch.sh <class> <promptfile> <outfile> [workdir]`. Never hardcode a `gpt-6-*` id or an effort level in this repo outside that script — the roster and the per-class effort can both change underneath a hardcoded copy. Native children default to Sol-medium for review/implementation and Luna-low for mining/procedure; Sol-high is always an explicit bounded escalation. The classes it accepts (any of these names routes the same way):

| Class (any of) | Resolves to | Purpose |
|---|---|---|
| `frontier`, `astra`, `final-gate` | Astra · high | the ONE final-gate judgment lane per spec review, beside sol, never instead of it |
| `falsifier`, `adversarial`, `verify`, `judge`, `security`, `sol` | Sol · high | adversarial/falsifier judgment, security/trust-boundary, hard RCA, irreversible architecture |
| `review`, `research`, `synthesis`, `standard` | Sol · medium | everyday coding, review, research, synthesis (replaces the retired Terra) |
| `mining`, `census`, `extract`, `locate`, `existence`, `trivial`, `mechanical`, `luna` | Luna · low | mechanical mining/census/extraction/procedure (replaces Terra-low) |

## Effort

**Claude** — per-turn keyword in the lane's mission or wake prompt: `(none)` / `think` / `think hard` / `think harder` / `ultrathink`.

**Codex** — session-level reasoning level (selectable mid-session via Codex menu): `Low` / `Medium` (default) / `High` / `Extra high`. Map approximately: Low↔standard, Medium↔think, High↔think hard, Extra high↔think harder. The gate itself only ever returns `low` / `medium` / `high` (no distinct "extra high" rung) — see the Models table above for what each class resolves to.

## Matrix

The Codex column names the **class** to pass to `codex-headroom.sh --route <class>` — the script resolves it to a model + effort; do not look up or restate that resolution here.

| Lane purpose | Claude | Claude effort | Codex class |
|---|---|---|---|
| Define: spec + moderate proof ledger | Sonnet | think | standard |
| Define: one critical coverage review | Sonnet | think | standard |
| Define: unresolved security/irreversible dispute | Opus + Codex | think harder | security |
| Build: implementation + targeted tests | Sonnet | think | standard |
| Verify-release: finite execution | Sonnet | think | standard |
| Procedural worker: deterministic command pass | Haiku | (none) | mining |
| Verify-release: failure-cluster diagnosis | Sonnet | think | standard |
| Bug fix < 200 LOC | Sonnet | think | standard |
| Trivial < 50 LOC, docs | Haiku | (none) | mining |
| Mining / surveys / parsing | Haiku | (none) | mining |
| Soak observation | Haiku | (none) | mining |
| Soak ESCALATE investigation | Sonnet | think | standard |
| PR comment review | Sonnet | think | standard |
| Refactor (no API change) | Sonnet | think | standard |
| Refactor (API change) | Sonnet | think | standard |
| Hard RCA / critical-path debugging | Opus | think harder | judge |
| Security review | Fable 5.1 + Opus 5.5 | think harder | security |
| Irreversible architecture decision | Opus | think hard | judge |
| Migration writing | Sonnet | think | standard |
| Migration risk review | Sonnet | think | standard |
| Self-managed interactive | Sonnet | think | standard |
| Wake-driven soak watcher | Haiku | (none) | mining |
| Orchestrator (Claude) | Opus | think | n/a |
| Orchestrator (long-lived Codex root) | n/a | n/a | standard |

## Subagent dispatch

| Role | Claude `Agent` | Codex `spawn_agent` class |
|---|---|---|
| State miner | Haiku | mining |
| Topical reviewers | Sonnet | standard |
| Boundary / security / adversarial | Fable 5.1 + Opus 5.5 | security |
| Coverage verifier | n/a | standard |
| Failure diagnostician | Sonnet | standard |
| Failure-cluster diagnostician | Sonnet | standard |
| Procedural worker | Haiku | mining |
| Doc writer / file search | Haiku | mining |

## Rules

1. Subagents default to the cheap tier. State miner is always cheap-tier, even from a flagship orchestrator.
2. Effort costs tokens; only apply where the matrix says.
3. Respect a lane's `model_override` in the program state file — never silently reclassify it.
4. An idle lane costs nothing; don't retire one to "save tokens."
5. Cross-runtime second-opinion (flagship Claude + flagship Codex paired) is the one rational flagship double-up — different bug classes.
6. Deep-review bucket (security review, adversarial review, final-gate critique) is split **Fable 5.1 + Opus 5.5** — model diversity beats a single-model monoculture; never route all deep-review lanes to one model.
7. **Ad-hoc delegation defaults to `sonnet`.** Research / investigation / mining / exploration / execution dispatches route to `sonnet` or `haiku`; **`opus` requires a one-line justification in the dispatch**; `fable` (or Codex's `judge`/`security` class, which the gate resolves to Sol at high effort) is reserved for the hardest verify / judge / adversarial reasoning. The Fable-pinned NAMED agents (critic, security-reviewer) stay Fable by design. A permissive default silently becomes an opus default — measured: 189 dispatches went opus 59 / sonnet ~80 / haiku 2.
8. **Bounded Codex children do not inherit the whole parent by default.** Give them a self-contained mission and `fork_turns: "none"` or the smallest positive slice that carries the evidence. Use `"all"` only when the whole conversation is genuinely load-bearing; full-history forks also inherit the parent's model and effort.
9. **The long-lived Codex orchestrator root is Sol-medium.** Context accumulation is the root's dominant multiplier; do not pay frontier weight on coordination, waiting, integration, or routine execution.
10. **Sol-high is a fresh bounded escalation, not a phase-spanning root.** Use it for irreversible architecture, security/trust boundaries, hard RCA, or final adversarial judgment. Return one decision artifact to the Sol-medium root, then stop the Sol-high lane.
    **The bound is the SHAPE, not the frequency** — one question, fresh context, one document, stop. In that shape Sol-high is used freely; outside it, never. Cost is `turns × context_size × model_weight`; a root maximizes the first two, so frontier weight on a root multiplies the worst case, while a bounded lane pays it once. Roots are **few but individually heavy** — measured 2026-08-21, one session spawned 30 subagent threads and another produced 81 rollout files, against a median root of 1. *(An earlier version of this rule cited "59% root sessions, 37 roots in 7h"; that counted rollout FILES as sessions and is retracted — a session owns one root file plus one file per subagent thread.)* The split that gets missed is inside *research*: **research-as-retrieval is Sol-medium, research-as-judgment is Sol-high** — "what does the vendor document?" vs "which reading is right, and what would falsify each?". Mission contract: `prompts/sol-judgment-lane.md`.
11. **Existing implementation is resume work, not a new lifecycle.** Honor same-SHA evidence; do not spend a new review/test wave proving unchanged code.
12. **Completion and terminal stop are distinct.** "Stop reviewing and finish" freezes scope and returns to the declared build group; explicit stop-now ends every descendant with no more tools.
