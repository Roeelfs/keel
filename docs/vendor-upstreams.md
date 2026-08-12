# Vendored skill upstreams

## Policy: track the canonical latest, layer only approved deltas

For Matt Pocock's skills, **keel's canonical version IS his latest.** We do not
maintain a divergent fork. On each resync we adopt his current `main` verbatim, then
re-apply a small, **explicitly approved** set of keel-specific deltas — each recorded in
the ledger below with its reason. A delta earns its place only when it encodes a real
keel operational need (a hard-won safety rule, a source-of-truth wiring, a skill-name
mapping); cosmetic divergence is dropped in favour of upstream.

Two standing, blanket deltas apply to every adopted skill:

1. **Strip `agents/openai.yaml`.** keel is Claude-first and marker-free; it mirrors into
   Codex/other runtimes via `tooling/wire-skills.sh`, so upstream's OpenAI interface
   stubs are removed on adoption.
2. **Map skill-name references to keel's set.** Upstream `/research` → keel
   `/investigation`; upstream `/code-review` (the skill) → keel `/review`
   (`standards-spec-review`). See "Not installed" below.

keel stays **public and marker-free**: no customer names, no "our tracker is X" defaults
baked into a seed. Operator/project facts (e.g. which tracker a given repo uses) are
configured per-repo via `/setup-matt-pocock-skills` and recorded in that project's memory,
never here.

## Matt Pocock skills

- Source: <https://github.com/mattpocock/skills>
- Last adopted upstream commit: `e9fcdf95b402d360f90f1db8d776d5dd450f9234`
- Reviewed / adopted: 2026-07-15

### Adopted (his latest is canonical)

Engineering + productivity flow, all at the reviewed commit: `ask-matt`, `codebase-design`,
`diagnosing-bugs`, `domain-modeling`, `grill-me`, `grilling`, `grill-with-docs`, `handoff`,
`implement`, `improve-codebase-architecture`, `prototype`, `resolving-merge-conflicts`,
`setup-matt-pocock-skills`, `tdd`, `to-spec`, `to-tickets`, `triage`, `wayfinder`,
`writing-great-skills`, plus net-new `teach`, `git-guardrails-claude-code`,
`setup-pre-commit`, `wizard`, `setup-ts-deep-modules`.

`wayfinder` and the tracker-coupled skills (`to-spec`/`to-tickets`/`triage`/
`setup-matt-pocock-skills`) were previously held back as GitHub/local-tracker-shaped; they
are now adopted, with Linear added as a **first-class tracker option** (see delta below).

### Approved keel deltas (the ONLY divergence from upstream)

| Skill | Delta | Why |
|---|---|---|
| `resolving-merge-conflicts` | step-4 verify-gate wording; step-5 commit-trailer clause; "Project guardrails" section (fetch-before-rebase, contaminated-branch → cherry-pick-clean-commit, squash-to-merge-base) | encodes real keel contamination/rebase incidents that upstream's generic flow omits |
| `domain-modeling` | ADR-FORMAT.md numbering: permanent identities, renumber-lower-cited-on-collision (replaces upstream's `ls | tail`-and-increment) | keel runs many parallel sessions/branches; naive increment collides |
| `tdd` | "Test-runner & iteration conventions" section; mocking.md "Partial module mocks (vitest)" block; `/codebase-design` seam hook; `/review` (not `/code-review`) | vitest worker/segfault + runtime-vs-seam scars; keel review command |
| `writing-great-skills` | safety-scoped Negation guardrail final line (prohibition only for irreversible/security/data-loss boundaries) | keel security posture |
| `implement` | `/review` (not `/code-review`) | keel review command |
| `prototype` | `disable-model-invocation: true` | prototyping is explicitly user-invoked in keel |
| `wayfinder` | `/research` ticket → `/investigation` subagent | keel's research flow is `investigation` |
| `ask-matt` | router refs mapped to keel's set (`/review`, `/investigation`); UI/UX redesign on-ramp linked to `docs/ui-ux-redesign-flow.md` | keel installs those, not upstream `code-review`/`research`; the shared UI stack needs one discoverable flow |
| `setup-matt-pocock-skills` | added first-class **Linear** tracker option + `issue-tracker-linear.md` seed (Linear MCP + Wayfinding ops); default-posture stays generic | Linear support is a public-useful addition; the per-repo default is configured, not hard-coded |
| `triage` | `AGENT-BRIEF.md` "GitHub issue or PR" → tracker-neutral wording | tracker-abstracted |
| all | strip `agents/openai.yaml` | Claude-first, marker-free |

Everything not in this table is upstream verbatim (`codebase-design`, `diagnosing-bugs`,
`improve-codebase-architecture`, `handoff`, `grill-me`, `grilling`, `grill-with-docs`, and
the net-new skills).

### Not installed (would duplicate or collide)

- **`research`** — keel's `investigation` (+ `deep-research`) is a strict superset
  (gated frame→research→brief Workflow, primary-source-first, adversarial cross-verify).
  Installing upstream `research` would be a second, thinner research front door — a
  one-architecture violation. wayfinder/ask-matt route to `/investigation` instead.
- **`code-review`** — its name collides with the built-in `/code-review` command, and
  keel's `standards-spec-review` (`/review`) is already a fork of it. Not installed;
  instead its one genuine improvement — the **Fowler 12-smell baseline** — is cherry-picked
  into `standards-spec-review`'s Standards sub-agent prompt.
- **Deprecated upstream** (`design-an-interface`, `qa`, `request-refactor-plan`,
  `ubiquitous-language`) — skipped; upstream marks them deprecated.
- **Matt-personal / niche net-new** (`scaffold-exercises`, `obsidian-vault`, `edit-article`,
  `migrate-to-shoehorn`, `writing-beats`/`-fragments`/`-shape`) and overlap/experimental
  (`claude-handoff`, `loop-me`, `to-questionnaire`) — not installed this pass; out of scope
  for the engineering harness.

## Update procedure (resync to a newer upstream)

1. Fetch upstream; record the new immutable adopted commit above.
2. `cp -R` each adopted skill from upstream over keel's copy; strip `agents/`.
3. Re-apply every row of the approved-deltas table (they live only here + in git history).
4. Re-check the "Not installed" set — has upstream changed anything that removes the
   collision/duplication reason?
5. Run `tooling/wire-skills.sh`, verify no runtime symlink dangles, commit.

## UI/UX product-redesign stack

This stack is intentionally **one workflow, not a collection of competing taste packs**.
Keel's existing `prototype` skill is the variation harness. UI Craft is the only visual
authoring system. The other skills cover upstream design disciplines or independent
evaluation gates.

| Adopted skill(s) | Source | Adopted commit |
|---|---|---|
| `information-architecture-and-navigation` | <https://github.com/jpoindexter/design-and-ai-skills> | `101dbc940f473699e676424b3f8ece6efcee59f1` |
| `interaction-design` | <https://github.com/rastian/interaction-design-skills> | `57a3eaa8c1830c6b6608550d75466434eeff2344` |
| `service-blueprint`, `conversational-ux`, `usability-test-plan`, `design-critique` | <https://github.com/Owl-Listener/designer-skills> | `20e34c4a587e5eb09fcdf8351fa97b3ad761b31e` |
| `ux-writing` | <https://github.com/content-designer/ux-writing-skill> | `98cacde4ba2dd10ed28df43a8d53eef1e321c539` |
| `ui-craft` and its command/variant skills | <https://github.com/educlopez/ui-craft> | `2ee6e0889a7a6ceb1542fe9e6793b71c697e1c2a` |
| `fixing-accessibility` | <https://github.com/ibelick/ui-skills> | `146fcd0b34fca2d80333b120d67f5009ccf58b28` |
| `web-design-guidelines` | <https://github.com/vercel-labs/agent-skills> | `b8caa260a420a73042e35521de4b5c8baf6446cc` |

Reviewed / adopted: 2026-08-13.

### Approved keel deltas

| Skill | Delta | Why |
|---|---|---|
| UI Craft command/variant skills | remap command-local `references/` paths to the sibling `ui-craft/references/` directory; replace one missing animation-example pointer with a local storyboard instruction | the upstream harness mirrors assume the full package layout; Keel stores one skill per sibling directory |
| `service-blueprint`, `conversational-ux`, `usability-test-plan`, `design-critique` | map descriptions away from companion Owl skills that are not installed and onto the selected Keel stack | keep routing honest without importing Owl's entire catalog |
| `web-design-guidelines` | replace the Claude-specific `WebFetch` assumption with the runtime's available web client | Keel is cross-runtime |
| all | strip `agents/openai.yaml` if an upstream later adds it | Claude-first, marker-free |

Update these skills by re-adopting the immutable source paths at a newer reviewed commit,
then re-applying only the deltas above. The operating sequence and selection rationale live
in [`docs/ui-ux-redesign-flow.md`](ui-ux-redesign-flow.md).
