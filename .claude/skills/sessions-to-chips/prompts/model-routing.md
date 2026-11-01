# Model & effort routing

Per-lane recommendations to minimize token cost. The state-miner emits `recommended_model` + `recommended_effort` per lane into the program state file (`~/.claude/orchestrator/programs/<slug>.state.md`); the manager surfaces them in the survey and in lane missions.

## Models

**Claude:** Opus 5.5 (alias `opus`) is the Claude ceiling (founder, 2026-10-24: "decrease the use of fable in general. max should be opus 5.5"): architecture, hard RCA, security and final gates; Fable is retired as a dispatch tier and the dispatch hook denies it; Sonnet 5.5 (alias `sonnet`) is the manager and mechanical tier (verification, grading, topical review, diagnosis); Haiku 5.5 (alias `haiku`) is the high-volume mining tier.

**Authorship (founder, 2026-11-01):** specs and ALL implementation are written only by an Opus 5.5 lane or a Codex lane, with implementation run through Codex wherever a lane qualifies; managers run on Sonnet and write neither. The role table, the violation definition and its artifact check are owned by `../references/manager-contract.md` §Model policy; the rows below only carry the parameters.

> Model diversity in the deep-review panel now comes from runtimes: Opus 5.5 beside Codex astra/sol.

**Codex:** model + effort per class is single-sourced in `~/.claude/scripts/codex-headroom.sh` — its case statement is **the one route table** ("THIS CASE STATEMENT IS THE ONE ROUTE TABLE: it owns model AND effort per class"). Ask it with `--route <class>` (echoes `<model> <effort>`), or dispatch directly with `codex-dispatch.sh <class> <promptfile> <outfile> [workdir]`. Never hardcode a `gpt-6-*` id or an effort level in this repo outside that script — the roster and the per-class effort can both change underneath a hardcoded copy. Native children default to Sol-medium for review/implementation and Luna-low for mining/procedure; Astra-high and Sol-high are explicit bounded escalations. The classes it accepts (any of these names routes the same way):

| Class (any of) | Resolves to | Purpose |
|---|---|---|
| `frontier`, `astra`, `final-gate`, `architecture`, `hard-rca`, `adjudication`, `security`, `judge` | Astra · high | bounded architecture, security, hard RCA and final adjudication; retain the final spec gate beside Sol and the finite manifest |
| `falsifier`, `adversarial`, `verify`, `sol` | Sol · high | bounded adversarial review, falsification and verification judgment |
| `review`, `research`, `synthesis`, `standard` | Sol · medium | everyday coding, review, research, synthesis (replaces the retired Terra) |
| `mining`, `census`, `extract`, `locate`, `existence`, `trivial`, `mechanical`, `luna` | Luna · low | mechanical mining/census/extraction/procedure (replaces Terra-low) |

## Effort

**Claude** — per-turn keyword in the lane's mission or wake prompt: `(none)` / `think` / `think hard` / `think harder` / `ultrathink`.

**Codex** — session-level reasoning level (selectable mid-session via Codex menu): `Low` / `Medium` (default) / `High` / `Extra high`. Map approximately: Low↔standard, Medium↔think, High↔think hard, Extra high↔think harder. The gate itself only ever returns `low` / `medium` / `high` (no distinct "extra high" rung) — see the Models table above for what each class resolves to.

## Matrix

The Codex column names the **class** to pass to `codex-headroom.sh --route <class>` — the script resolves it to a model + effort; do not look up or restate that resolution here.

| Lane purpose | Claude | Claude effort | Codex class |
|---|---|---|---|
| Define: spec + moderate proof ledger | Opus | think | standard |
| Define: one critical coverage review | Sonnet | think | standard |
| Define: unresolved security/irreversible dispute | Opus + Codex | think harder | security |
| Build: implementation + targeted tests | Opus (Codex first) | think | standard |
| Verify-release: finite execution | Sonnet | think | standard |
| Procedural worker: deterministic command pass | Haiku | (none) | mining |
| Verify-release: failure-cluster diagnosis | Sonnet | think | standard |
| Bug fix < 200 LOC | Opus (Codex first) | think | standard |
| Trivial < 50 LOC, docs | Opus (Codex first) | (none) | mining |
| Mining / surveys / parsing | Haiku | (none) | mining |
| Soak observation | Haiku | (none) | mining |
| Soak ESCALATE investigation | Sonnet | think | standard |
| PR comment review (fixes go to the implementer) | Sonnet | think | standard |
| Refactor (no API change) | Opus (Codex first) | think | standard |
| Refactor (API change) | Opus (Codex first) | think | standard |
| Hard RCA / critical-path debugging | Opus | think harder | hard-rca |
| Security review | Opus 5.5 + Codex astra | think harder | security |
| Irreversible architecture decision | Opus | think hard | architecture |
| Migration writing | Opus (Codex first) | think | standard |
| Migration risk review | Sonnet | think | standard |
| Self-managed interactive (writes specs or code) | Opus | think | standard |
| Wake-driven soak watcher | Haiku | (none) | mining |
| Manager (Claude `[Manager]` session; writes no spec or code) | Sonnet | medium | n/a |
| Manager (long-lived Codex root) | n/a | n/a | standard |

## Start parameters

| Start | Call | Model / effort |
|---|---|---|
| Manager | `start_session` (`use_worktree: true`, `context: "fresh"`) | `model: "sonnet"`, `effort: "medium"` |
| Spec or implementation child the human steers | `start_session` | `model: "opus"`, `effort: "medium"` (more only with a stated reason) |
| Unattended spec or implementation lane, Codex (default for implementation) | `spawn-lane.sh --runtime codex --class standard --cwd <worktree>`, or `codex-dispatch.sh <class> …` for a spec document; both ask `~/.claude/scripts/codex-headroom.sh` | the gate's `--route <class>` |
| Unattended spec or implementation lane, Claude (Codex does not fit) | `spawn-lane.sh --model opus` | opus, medium |
| Mechanical lane or child (mining, census, verification, grading) | `start_session`, `spawn-lane.sh` or `Agent` | `sonnet`/`haiku`, Codex `mining` |

Grade every lane by its artifact, never its exit code: the spec file or commits exist, answer the mission, and name an opus or Codex author.

## Subagent dispatch

| Role | Claude `Agent` | Codex `spawn_agent` class |
|---|---|---|
| State miner | Haiku | mining |
| Topical reviewers | Sonnet | standard |
| Boundary / security / adversarial | Opus 5.5 + Codex astra | security |
| Coverage verifier | n/a | standard |
| Failure diagnostician | Sonnet | standard |
| Failure-cluster diagnostician | Sonnet | standard |
| Procedural worker | Haiku | mining |
| Doc writer / file search | Haiku (notes and summaries only; a repo doc change is a diff) | mining |

## Rules

1. Subagents default to the cheap tier. State miner is always cheap-tier, even from a flagship manager.
2. Effort costs tokens; only apply where the matrix says.
3. Respect a lane's `model_override` in the program state file — never silently reclassify it.
4. An idle lane costs nothing; don't retire one to "save tokens."
5. Cross-runtime second-opinion (flagship Claude + flagship Codex paired) is the one rational flagship double-up — different bug classes.
6. Deep-review bucket (security review, adversarial review, final-gate critique) is split **Opus 5.5 (Claude) + Codex astra/sol** — model diversity beats a single-model monoculture; never route all deep-review lanes to one model.
7. **Ad-hoc mechanical delegation defaults to `sonnet`.** Research / investigation / mining / exploration / verification dispatches route to `sonnet` or `haiku`; **`opus` there requires a one-line justification in the dispatch**. Spec and implementation lanes are the exception by policy: always `opus` or Codex, and the policy is their justification; Codex's `adjudication`/`security` class (Astra at high effort) is reserved for the hardest verify / judge / adversarial reasoning, with `opus` as the Claude side. The NAMED deep agents (critic, security-reviewer, verifier) are pinned to opus. A permissive default silently becomes an opus default — measured: 189 dispatches went opus 59 / sonnet ~80 / haiku 2.
8. **Bounded Codex children do not inherit the whole parent by default.** Give them a self-contained mission and `fork_turns: "none"` or the smallest positive slice that carries the evidence. Use `"all"` only when the whole conversation is genuinely load-bearing; full-history forks also inherit the parent's model and effort.
9. **The long-lived Codex manager root is Sol-medium.** Context accumulation is the root's dominant multiplier; do not pay frontier weight on coordination, waiting, integration, or routine execution.
10. **Judgment uses a fresh bounded escalation, not a phase-spanning root.** Use Astra classes `architecture`, `security`, `hard-rca`, and `adjudication` for the hardest decisions; use Sol-high `falsifier`/`adversarial` for routine falsification. Return one decision artifact to the Sol-medium root, then stop the judgment lane.
    **The bound is the SHAPE, not the frequency** — one question, fresh context, one document, stop. In that shape judgment lanes are used freely within the accepted finite review manifest; outside it, never. Cost is `turns × context_size × model_weight`; a root maximizes the first two, so frontier weight on a root multiplies the worst case, while a bounded lane pays it once. Roots are **few but individually heavy** — measured 2026-08-21, one session spawned 30 subagent threads and another produced 81 rollout files, against a median root of 1. *(An earlier version of this rule cited "59% root sessions, 37 roots in 7h"; that counted rollout FILES as sessions and is retracted — a session owns one root file plus one file per subagent thread.)* The split that gets missed is inside *research*: **research-as-retrieval is Sol-medium, research-as-judgment is Sol-high for falsification, with Astra for architecture/security/hard RCA/adjudication** — "what does the vendor document?" vs "which reading is right, and what would falsify each?". Mission contract: `prompts/sol-judgment-lane.md`.
11. **Existing implementation is resume work, not a new lifecycle.** Honor same-SHA evidence; do not spend a new review/test wave proving unchanged code.
12. **Completion and terminal stop are distinct.** "Stop reviewing and finish" freezes scope and returns to the declared build group; explicit stop-now ends every descendant with no more tools.
