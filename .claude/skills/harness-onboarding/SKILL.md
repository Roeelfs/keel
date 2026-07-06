---
name: harness-onboarding
description: Onboard a machine or new user onto keel — survey the current machine state (skill roots, runtimes, repos, instructions files, memory), decide machine-wide vs repo-local scope, PROPOSE the integration plan (symlinks, canonical-clone wiring, AGENTS.md↔CLAUDE.md links, overlay + memory setup), then apply it with a backup. Triggers — "onboard this machine", "set up keel", "integrate keel with my system", "re-onboard", "harness drift check", "why isn't my skill update showing up everywhere".
---

# Harness Onboarding

Integrate keel with a machine the way it should end up: **one canonical clone, every
consumer a symlink** — so a skill edit propagates everywhere instantly and there is
nothing to re-install, ever. This skill *surveys before it proposes and proposes
before it mutates*: the machine's current state decides the plan, not a fixed script.

Relationship to [`install.sh`](../../../install.sh): the installer **copies** keel
into one target repo (right for teams/CI vendoring a snapshot). This skill does the
**machine-wide integration** the installer deliberately doesn't: global skill roots,
cross-runtime surfaces, the private overlay, instructions-file links, and the upkeep
loop. On a personal machine, symlink integration is the default; per-repo copies are
the exception (and a drift hazard — see Phase 2).

## When to use / when not

- **Use** on a fresh machine, when a new user adopts keel, or as a periodic
  *re-onboard* when skill updates don't seem to propagate (drift check).
- **Not** for the weekly improvement ritual — that's `improve-harness` (this skill
  establishes the shape; that one evolves it). Not for installing into a single
  shared team repo — that's `install.sh`.

## Skill Memory (LEARNINGS.md)

**Before starting:** read `LEARNINGS.md` in this skill directory, and the private
overlay if present — `~/.claude/skills-overlay/harness-onboarding/LEARNINGS.md`.

**Before ending — route each learning by scope; NEVER hand-append to this repo's
committed `LEARNINGS.md` (a read-only curated seed):** operator-private craft → the
overlay (create if absent); machine/project-specific facts → that machine's project
memory; universal craft → note it for `/improve-harness` to promote (de-identified)
into the seed via PR. Full routing: [`docs/skill-memory.md`](../../../docs/skill-memory.md).

---

## Phase 1 — Survey the machine (read-only)

Build the state table before touching anything. Enumerate **every** surface:

- **The canonical clone.** Where is the skills repo cloned (e.g. `~/code/keel`)? Is
  it a git clone tracking its remote (`git -C <clone> status -sb`), or an unpacked
  snapshot (no remote = no update path)?
- **Skill roots — all of them.** For each root, classify every entry as
  `symlink→clone` / `real-copy` / `absent`:
  - `~/.claude/skills/` (Claude Code, user-global);
  - `~/.agents/skills/` and any other agents.md-ecosystem roots (`~/.codex/…`) —
    cross-runtime surfaces are the ones everyone forgets;
  - per-repo `.claude/skills/` across the user's code root (`for d in <code-root>/*/;
    do ls $d/.claude/skills 2>/dev/null; done`).
  - **Completeness, not just classification.** For each machine-wide root, which keel
    skills are MISSING: `comm -23 <(ls <clone>/.claude/skills | sort) <(ls <root> |
    sort)`. A hand-wired root silently omits every skill added since it was last
    touched — that is how a skill (e.g. `root-cause-analysis`) becomes invisible to a
    whole runtime like Codex. `~/.codex/skills/` is Codex's discovery root; its
    `.system/` built-ins are runtime-owned — never touch them.
- **Agent roots — same split as skills.** For each `~/.claude/agents/` and per-repo
  `.claude/agents/`, classify every entry `symlink→clone` / `real-copy` / `absent`
  **and** generic-craft vs project-specific: does its prompt name a specific
  project's stack, files, credentials, domain, or a vendor-branded platform? A
  project-specific agent living in (or symlinked from) the canonical clone is
  machine-wide contamination — it surfaces in every repo and leaks project-private
  facts into a public repo. Flag every one.
- **Overlay + seeds.** Does `~/.claude/skills-overlay/` exist? Which skills have
  overlay `LEARNINGS.md` files?
- **Instructions files.** The global `~/.claude/CLAUDE.md`; per repo: does it have
  `CLAUDE.md`, `AGENTS.md`, both, or neither — and if both, are they linked
  (symlink/pointer) or **divergent** (diff them)?
- **Memory.** `~/.claude/projects/*/memory/` per project; which repos keep memory
  in-repo (`.claude/memory/`) vs harness-side; index sizes.
- **Harness versioning.** Is `~/.claude` itself a git repo with a private remote?
- **Package managers in play.** Plugin marketplaces, `npx skills` locks, or older
  installers that left **copies** — these are the drift sources to retire.

Output: one table — surface × state × verdict (`ok` / `stale-copy` / `divergent` /
`absent`). Nothing is mutated in this phase.

## Phase 2 — Decide scope (the placement model)

| What | Placement | Why |
|---|---|---|
| Engineering-craft skills (the keel set) | **Machine-wide**: `<root>/<skill> → clone` symlink in *every* skill root (Claude Code + cross-runtime) | one edit/`git pull` propagates everywhere; skills load at invocation time so updates are instant |
| Repo-specific skills (deploy runbooks, project scripts) | **Repo-local** `.claude/skills/` in that repo only | they version with the code they operate |
| Engineering-craft agents (`.claude/agents/` — the keel crew: verifier, debugger, deployment-engineer…) | **Machine-wide**: symlinked into every agents root, same as the skill set | vendor-neutral roles load in every repo; a project *extends* them, never edits them |
| Project-specific agents (a clinical eval-judge, a platform-branded deploy agent, an app's login gotchas/credentials) | **Repo-local** `.claude/agents/` in that project only | they name that project's stack/files/creds — in the clone they go machine-wide AND leak project-private facts into a public, marker-free repo |
| Private learnings | `~/.claude/skills-overlay/<skill>/LEARNINGS.md` | the committed seed is read-only; private craft never enters the public repo |
| Project facts/status | that repo's `.claude/memory/` (in-repo, optionally symlinked from the harness projects dir) — keep PHI/secrets machine-local | memory versions with the project; sensitive facts stay off any remote |
| Personal cross-repo rules | `~/.claude/CLAUDE.md` (harness repo) | user-global contract |
| Repo law | one canonical `AGENTS.md`/`CLAUDE.md` + pointer/symlink — [`docs/instructions-files.md`](../../../docs/instructions-files.md) | one contract, however many filenames |

The anti-pattern this phase exists to prevent: a **repo-local or root-local COPY of a
machine-wide skill**. A copy shadows the canonical one (repo-local wins in Claude
Code) and silently drifts — the "why is this machine still doing the old thing"
class. Copies are only correct when a team deliberately vendors a pinned snapshot
into a shared repo (`install.sh`'s job), and then that repo owns updating it.

The second anti-pattern, the one this skill now guards explicitly: **authoring a
project's agents or facts INTO the canonical clone.** Onboarding *must* survey the
project's scope — its stack, workflow (Linear/git/CI), deploy target, login quirks,
credentials — to embed the work-pipeline harness. But that knowledge is
project-private and the clone is public and marker-free, so it lands in the *project
repo*, never the clone: a project-scoped `CLAUDE.md`/`AGENTS.md`, project-local
`.claude/agents/` and per-skill context, and project memory (`.claude/memory/`) for
secrets/PHI. Never a customer name, project file path, credential, or vendor-branded
role in the clone. When a generic-craft agent needs project specifics, the project
*extends* it repo-locally — it does not edit the machine-wide one. (This is the class
that put a clinical eval-judge and a Vercel-branded deploy agent into keel and made
them machine-wide — the failure this row exists to prevent.)

**Cross-runtime memory is already one store — verify, don't symlink.** Curated project
memory lives at `~/.claude/projects/<slug>/memory/` (`MEMORY.md` + one `*.md` per fact),
and both Claude Code and Codex address it by the *same* cwd-slug — so there is nothing to
symlink; they converge by convention. What onboarding checks: (1) Codex's
`~/.codex/AGENTS.md` has the per-project block that **reads the whole store** (index →
topic files, not just `MEMORY.md`) and **writes durable facts back** into it in the same
format; (2) memory stays machine-local (PHI/secrets never in keel or a remote). Codex's
native `memories_1.sqlite` is a separate auto-cache — leave it. Full model:
[`docs/cross-runtime-memory.md`](../../../docs/cross-runtime-memory.md).

## Phase 3 — Propose (dry-run plan; nothing mutates yet)

Emit the full plan as a table — every mutation listed, then **stop for confirmation**:

- `absent` → create symlink.
- `symlink→clone` → no-op (verify target resolves).
- `real-copy`, byte-identical to the clone → replace with symlink (backed up first).
- `real-copy`, **divergent** → NEVER blind-overwrite. Diff it; classify each delta:
  an improvement → propose merging back into the skills repo (PR); private/operator
  content → move to the overlay; garbage → confirm before dropping. Only after the
  deltas have homes does the copy become a symlink.
- Skills that aren't keel's (other vendors, personal) → untouched, listed as such.
- Per repo with both instructions files divergent → propose the canonical+pointer
  consolidation (which file is canonical follows where that repo's agents run).
- `~/.claude` not versioned → propose `git init` + private remote (and NEVER weaken
  an existing `.gitignore` to commit more).

Each row carries a risk note. Anything destructive names its backup.

## Phase 4 — Apply, verify

1. **Backup first**: lean tar of every root/dir about to change (skill roots, any
   diverged copies, instructions files being consolidated).
2. Apply symlinks + links per the confirmed plan. For the machine-wide skill roots,
   run `tooling/wire-skills.sh` from the clone — it symlinks every keel skill into
   every runtime root (Claude Code, Codex, agents.md), adds only what's missing,
   prunes its own stale links, and leaves real copies + runtime built-ins untouched.
   Then activate the sync hook once: `git config core.hooksPath .githooks` — so a
   future `git pull` that adds a skill re-wires every runtime automatically, no
   re-onboard needed (see [`docs/cross-runtime-skills.md`](../../../docs/cross-runtime-skills.md)).
   Also ensure Codex's `~/.codex/AGENTS.md` carries the shared-memory per-project block
   (read the whole `~/.claude/projects/<slug>/memory/` store, not just the index, and
   write durable facts back into it) — template + rationale in
   [`docs/cross-runtime-memory.md`](../../../docs/cross-runtime-memory.md).
3. **Verify mechanically**: every new symlink resolves (`find <root> -type l
   ! -exec test -e {} \; -print` → empty); no `real-copy` entries remain for
   machine-wide skills; invoke one skill end-to-end to confirm loading; re-run the
   Phase 1 sweep and show the before→after table.
4. If `~/.claude` is versioned: commit the integration as one change.

## Phase 5 — Record + hand off the upkeep loop

- Write the machine's integration state into memory (which roots are wired, where
  the clone lives, what was deliberately left as a copy and why).
- Point the user at the maintenance cadence: updates arrive by `git pull` in the
  clone (or automatically, since working-tree symlinks track edits instantly);
  `improve-harness` is the periodic ritual that evolves the harness and audits the
  instructions files; learnings route per `docs/skill-memory.md`.

The end-state test, one line: **edit a skill in the clone, and every runtime, every
repo, and every session on the machine sees it on the next invocation — with zero
install steps in between.**
