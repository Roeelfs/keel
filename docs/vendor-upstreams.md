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
- Last adopted upstream commit: `c55ee46073ed923f86ce59a5eb3b6d895095d1b7`
- Reviewed / adopted: 2026-09-27

### Adopted (his latest is canonical)

Engineering + productivity flow, all at the reviewed commit: `ask-matt`, `codebase-design`,
`diagnosing-bugs`, `domain-modeling`, `grill-me`, `grilling`, `grill-with-docs`, `handoff`,
`implement`, `improve-codebase-architecture`, `prototype`, `resolving-merge-conflicts`,
`setup-matt-pocock-skills`, `tdd`, `to-spec`, `to-tickets`, `triage`, `wayfinder`,
`writing-for-agents`, plus `teach`, `git-guardrails-claude-code`,
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
| `writing-for-agents` | safety-scoped Negation guardrail; one-level pointers from `SKILL.md`; preserve `disable-model-invocation: true` across rename | keel security posture, reliable reference loading, and existing user-invoked entry |
| `implement` | `/review` (not `/code-review`) | keel review command |
| `prototype` | `disable-model-invocation: true` | prototyping is explicitly user-invoked in keel |
| `wayfinder` | `/research` ticket → `/investigation` subagent | keel's research flow is `investigation` |
| `ask-matt` | router refs mapped to keel's set (`/review`, `/investigation`); UI/UX redesign on-ramp routed to `design-taste-frontend` / the `ui-ux-pro-max` plugin | keel installs those, not upstream `code-review`/`research`; the ui-craft stack was removed 2026-09-06 as unused |
| `setup-matt-pocock-skills` | added first-class **Linear** tracker option + `issue-tracker-linear.md` seed (Linear MCP + Wayfinding ops); default-posture stays generic | Linear support is a public-useful addition; the per-repo default is configured, not hard-coded |
| `triage` | `AGENT-BRIEF.md` "GitHub issue or PR" → tracker-neutral wording | tracker-abstracted |
| `grill-with-docs`, `implement`, `improve-codebase-architecture`, `to-spec`, `to-tickets`, `triage`, `wayfinder` | omit `disable-model-invocation: true` | preserve existing model-invoked reach used by composed engineering flows |
| `ask-matt` | omit router entries for uninstalled `to-questionnaire` and `wait-what`; describe investigation as adversarially cross-verified | route only to installed flows, with the actual investigation contract |
| all | `license: MIT` metadata | retain existing vendored license metadata |
| all | strip `agents/openai.yaml` | Claude-first, marker-free |

Apart from blanket license metadata, everything not in this table is upstream verbatim (`codebase-design`, `diagnosing-bugs`,
`improve-codebase-architecture`, `handoff`, `grill-me`, `grilling`, `grill-with-docs`, and
the remaining adopted skills).

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

## 2026-09-27 adoption receipt

Refreshed the existing 24-skill catalog only, from immutable upstream
`c55ee46073ed923f86ce59a5eb3b6d895095d1b7`, using old adopted upstream
`e9fcdf95b402d360f90f1db8d776d5dd450f9234` as the three-way base.
`writing-great-skills` is now `writing-for-agents`; its obsolete `GLOSSARY.md`
was removed and upstream `SKILL-MECHANICS.md` added. `wizard` now comes from
`skills/engineering`, rather than `skills/in-progress`.

The merge identified conflicts in 10 files: `ask-matt/SKILL.md`,
`resolving-merge-conflicts/SKILL.md`, `setup-matt-pocock-skills/SKILL.md`,
`tdd/SKILL.md`, `to-spec/SKILL.md`, `to-tickets/SKILL.md`,
`triage/AGENT-BRIEF.md`, `triage/SKILL.md`, `wayfinder/SKILL.md`, and renamed
`writing-for-agents/SKILL.md`. Resolutions adopted upstream wording and new
reference files while retaining the deltas above. Upstream's `codebase-design`
reference now covers the former local TDD seam hook without an extra delta.

Upstream-relative receipt: every `SKILL.md` retains MIT metadata; additional
differences are confined to `ask-matt/SKILL.md`, `domain-modeling/ADR-FORMAT.md`,
model-invocation metadata for the seven composed-flow entries listed above,
`resolving-merge-conflicts/SKILL.md`, `setup-matt-pocock-skills/SKILL.md` and
its local-only `issue-tracker-linear.md`, `tdd/SKILL.md` and `mocking.md`,
`triage/AGENT-BRIEF.md`, `wayfinder/SKILL.md`, and
`writing-for-agents/SKILL.md`. All other adopted support files match upstream.
No upstream interface stubs or new catalog entries were adopted.

## Update procedure (resync to a newer upstream)

1. Fetch upstream; pin its immutable commit and retain the old adopted commit.
2. Stage each adopted skill outside the live source tree. Resolve moved/renamed
   skill directories against both immutable trees; strip `agents/`.
3. Three-way merge each file with old upstream as base, current local content as
   ours, and new upstream as theirs. Preserve local-only files; remove obsolete
   upstream files only after checking for local modifications.
4. Resolve conflicts by intent. Capture the full old-to-local delta, reconcile
   it with the approved table, and record any retained missing ledger rows.
5. Compare the staged result against new upstream and record every remaining
   delta. Check metadata, references, and conflict markers before replacing the
   adopted directories. Preserve unrelated dirty skills.
6. Re-check the "Not installed" set for changed collision/duplication reasons;
   do not bulk-install new entries.
7. Update provenance, run `tooling/wire-skills.sh`, verify runtime links, commit.

## Other publicly sourced skills

### Marketing skills

- Source: <https://github.com/coreyhaines31/marketingskills>
- Adopted upstream commit: `5b2c0007766c6a1cf1d53fd8fc73e979e0821022`
- License: MIT, copyright Corey Haines (2025); each adopted skill carries the upstream
  `LICENSE` notice.
- Adopted only the already-installed `copywriting` (2.0.2), `copy-editing` (2.0.0),
  and `content-strategy` (2.1.1) skills, including their complete `references/` and
  `evals/` directories. Also carried the three Sanity/Contentful/Strapi integration
  guides referenced by `headless-cms.md` into that skill's `references/integrations/`
  and made those links skill-relative. No other catalog entries were added.
- Historical comparison: the old `copy-editing` and `content-strategy` files match
  upstream history at `4874fe8979134ff428ee2e564b8b20c5855515c3` and
  `51146da746ab2a877b6161b00585994616e3ba0a`. `copywriting` was based on upstream
  v1.1.0 (`f5badfe416acbdb464804f79c42e171ee8ae81d5`) with broader activation phrases
  and stronger anti-fabrication wording; current upstream now contains those changes,
  so no local copywriting delta remains. The only packaging adaptation is bringing
  three repo-level integration guides into the skill and making their links portable.
  The refresh adds upstream's `checklist.md` and `content-distribution.md` references.
- Upstream's cross-skill mentions (`cro`, `emails`, `popups`, `offers`, `social`,
  `launch`, and related marketing skills) remain descriptive references; this refresh
  deliberately does not add those catalog entries.

### Langfuse skill

- Source: <https://github.com/langfuse/skills>
- Adopted upstream commit: `104acd9aa7b1f431066cd9fe4b0b431a0188e642`
- License: MIT, copyright Langfuse GmbH (2026); the adopted skill carries the upstream
  `LICENSE` notice.
- Adopted the already-installed `langfuse` skill and complete `references/` directory.
  The prior `sdk-upgrade.md` was an unmodified older upstream reference and is no longer
  part of the current skill; current upstream adds dataset, prompt-engineering, eval
  setup, and v4 migration references. Fixed one upstream sibling-reference link in
  `references/instrumentation.md` to point to the adjacent `cli.md`. No new catalog
  entries were added.
- Historical comparison: the old `SKILL.md` exactly matches upstream commit
  `d48c5b8b434dc34550053699e8403c23f231446d`; old supporting references match upstream
  history and contain no local-only adaptations. Packaging fixes the instrumentation
  reference to its sibling CLI guide so the installed skill has no broken relative link.

### 2026-09-27 bounded source-adoption disposition (item V)

1. **Current state:** the four installed copies lived as real directories under
   `~/.codex/skills/`; none had a Keel canonical copy. Metadata showed the marketing
   skills at 1.1.0/1.3.0/1.1.0, and the Langfuse copy had no version field. Adopted
   immutable upstream commits above.
2. **Premise:** each installed skill maps to a public upstream path. Current versions
   provide newer references and guidance; both repositories are MIT licensed. Adopt the
   current versions, with only historical generic copywriting edits preserved (now
   already present upstream).
3. **Layer:** these are public reusable skills, so Keel is their canonical source;
   the three runtime skill roots now resolve to the same Keel source.
4. **Enforcement:** `tooling/wire-skills.sh` is the existing one-way projection into
   Claude/Codex/Agents roots. The old real copies were archived before projection;
   all four skills now resolve into Keel in each root.
5. **Preservation:** the supplied backup was readable and contained all four old
   directories. Historical file comparison found no machine paths, customer facts, or
   local-only Langfuse/marketing references; full upstream reference/eval directories
   and notices were carried. Three integration guides were relocated from the upstream
   repo-level directory to keep the skill self-contained, and fixed one Langfuse
   sibling link. The two small copywriting edits were absorbed upstream; the old
   unreferenced Langfuse upgrade note was upstream content, not a local delta.

Packaging also trims upstream trailing whitespace in copywriting/copy-frameworks.md
and langfuse/cli.md so the canonical diff check remains clean.
