# Cross-runtime skills — one clone, every runtime, no drift

keel is consumed by **symlink**: one canonical clone, and each runtime's *global*
skill root holds one symlink per skill pointing back into it. An edit to a skill is
live everywhere on its next invocation. But a symlink only exists once someone makes
it — and that is where drift creeps in.

## The drift this prevents

The runtime roots were originally wired **by hand, per skill**. That silently rots:
the moment a new skill lands in keel (say `root-cause-analysis`), every root that
was wired before it existed simply omits it — the skill is invisible to that whole
runtime, with no error. Codex was missing 27 of 36 skills this way; the agents.md
root was missing 19; even the Claude Code root was missing 7. Nothing was broken —
the roots were just frozen snapshots of "which skills existed the day I wired them."

The fix is structural, not a reminder to re-wire: **a tool that syncs, plus a hook
that runs it.**

## The runtime skill roots

| Runtime | Global skill root | Notes |
|---|---|---|
| Claude Code | `~/.claude/skills/` | also merges per-repo `<repo>/.claude/skills/` when you're in that repo |
| Codex (OpenAI) | `~/.codex/skills/` | its `.system/` holds Codex's own built-ins — **runtime-owned, never touch**. No per-repo skill discovery. |
| agents.md ecosystem | `~/.agents/skills/` | e.g. Gemini and other AGENTS.md-compatible runtimes |

Each root holds `<root>/<skill> → <clone>/.claude/skills/<skill>` symlinks, alongside
any real (non-keel) skill copies the runtime installed itself.

## The tool: `tooling/wire-skills.sh`

Syncs the canonical skill set into every runtime root. **Idempotent and safe** — it
only ever creates symlinks into the source and prunes *its own* dangling
skill-symlinks; it never touches real skill copies, other vendors' skills, or a
runtime's built-ins.

```sh
tooling/wire-skills.sh            # sync keel skills into all detected roots
tooling/wire-skills.sh --dry-run  # show what would change; mutate nothing
```

Runtimes that aren't installed (no home dir) are skipped. Skills load at invocation
time, so a newly-wired skill is available on its next use — no restart.

## Durability: the sync runs itself

`.githooks/post-merge` and `.githooks/post-checkout` run the tool automatically, so a
`git pull` (or branch switch) that adds a skill re-wires every runtime with no manual
step. Activate the hooks once per clone:

```sh
git config core.hooksPath .githooks
```

(This is repo-local git config — not versioned — so each fresh clone sets it once;
the `harness-onboarding` skill does this as part of Phase 4.)

**Drift check**, any time: `tooling/wire-skills.sh --dry-run` — a clean run prints
`+0 / -0` for every root.

## Project-scoped vs global skills

- **Global engineering-craft skills live in keel** → `wire-skills.sh` puts them in
  every runtime root. This is the shared set.
- **Project-specific skills live in `<repo>/.claude/skills/`**, versioned with that
  repo (the same repo-local rule as [agents](../AGENTS.md) and
  [instructions files](instructions-files.md)). **Claude Code discovers them
  natively** when you open that repo — nothing to wire.
- **Codex and the agents.md runtimes have no per-repo skill discovery** — they read
  only their one global root. So a project skill is *not* auto-visible there, and
  that is correct: globalizing it would leak a project-scoped tool into every repo
  (the same failure class as a project-specific agent in the machine-wide crew). Two
  honest options when a project skill is needed under Codex:
  1. **If it's actually general craft, promote it to keel** — then it's wired
     everywhere by design.
  2. **If it's genuinely project-only, opt in explicitly**, accepting that it becomes
     globally visible in that runtime:
     `KEEL_SKILL_ROOTS=~/.codex/skills tooling/wire-skills.sh --src <repo>/.claude/skills`

The rule mirrors the rest of keel: **shared craft is machine-wide; project scope
stays in the project repo.**
