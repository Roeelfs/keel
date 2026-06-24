# Investigating an unfamiliar codebase

Most of keel is about *building* a change: spec it, review it with a panel, test
it end-to-end, ship it without collisions. But before any of that, you often have
to do the harder thing first — **understand a codebase you didn't write.** Map its
structure, find where the intent lives, root-cause why something breaks, and have
that understanding survive past the current session.

keel does not ship a single `investigate` button. It ships the *primitives*, and
this page is the playbook for assembling them. The throughline is the same one
behind the spec pipeline — **claims are backed by evidence (`path:line`, a log
line, a git fact), not by what the code looks like it does.**

## The shape of an investigation

```
  UNDERSTAND ──────────────► MAP ──────────────► CRITIQUE ──────► REMEMBER
  parallel recon            structure +          what the         durable,
  (explore × N)             root cause           map missed       cross-session
                            (tracer/debugger/    (critic)         (claude-sessions,
                             architect)                            in-flight registry,
                                                                   flows.json)
```

You rarely run these in a clean line — you loop. But naming the phases tells you
which agent to reach for.

## Phase 1 — UNDERSTAND: fan out read-only recon

The atomic unit is the [`explore`](../.claude/agents/explore.md) agent: a Haiku,
**read-only** (Read/Grep/Glob/Bash) search specialist. Its contract is a
*conclusion*, not a file dump — it leads with the answer, then cites `path:line`
for the few files that matter, names the naming/structure convention it observed,
and lists the gaps it searched but couldn't find (so you know the search was real).

Drop into an unknown repo and dispatch several at once, one per subsystem:

```
explore: where does HTTP request handling enter the system, and how is auth applied?
explore: how is the database accessed — ORM, raw SQL, a repository layer? where do migrations live?
explore: where is configuration loaded, and what are the env vars / config files?
```

Because `explore` is cheap and read-only, a fan-out sweep builds a structured map
of an unfamiliar codebase *without burning the orchestrator's context window on raw
file contents*. Each one returns the local convention it observed, so you also
learn how the repo wants you to navigate it.

> **Tip:** `explore` is read-only but web-enabled — when recon hits an unfamiliar
> third-party library or framework, it can look the docs up itself instead of
> guessing from memory. Keep the web for what the repo *can't* answer; most
> questions are settled by reading the code.

## Phase 2 — MAP: root cause and design archaeology

Once you know *where* things are, the deep-analysis agents tell you *how* and
*why* — each read-only, each requiring evidence:

- **[`tracer`](../.claude/agents/tracer.md)** — competing-hypothesis causal
  tracing for the case where you have **no reproducer and no ground truth** (the
  normal state on an unfamiliar repo). It separates observation from
  interpretation, generates 2+ hypotheses across *deliberately different frames*
  (code-path / config / measurement-artifact / orchestration / architecture-
  mismatch), collects evidence for *and against* each, ranks by an evidence-strength
  hierarchy (logs and git-history above naming-proximity guesses), runs an explicit
  disconfirmation round, and ends by naming the single cheapest probe that collapses
  the uncertainty. Its whole purpose is to stop you marrying a favorite theory in
  code you don't understand.
- **[`debugger`](../.claude/agents/debugger.md)** — when there *is* a failing test
  or red build: reproduce, read the evidence literally, form competing hypotheses,
  bisect by commit/layer/input, confirm the cause, then fix the cause not the
  symptom. On a new codebase a red build is often the fastest way to learn how a
  subsystem actually works.
- **[`architect`](../.claude/agents/architect.md)** — design archaeology. Its
  first move is "map the real constraints first: read the relevant code and
  configs," then it names the load-bearing seams and explains *why* the system is
  shaped the way it is. Web-enabled, so it can benchmark an unfamiliar design
  against ecosystem norms.
- **[`security-reviewer`](../.claude/agents/security-reviewer.md)** — doubles as an
  attack-surface map. An injection + authn/authz + secrets + isolation sweep is one
  of the fastest ways to chart the trust boundaries, input handling, and auth
  surfaces of a system you didn't write. It audits against the project's own
  `docs/security-policy.md` first (when present), so it learns the repo's rules
  before falling back to portable categories.

## Phase 3 — CRITIQUE: pressure-test your emerging model

The mistake on an unfamiliar system is trusting the model you just built.
[`critic`](../.claude/agents/critic.md) (Opus, read-only, web-enabled) is the
completeness gate: its signature move is evaluating what *isn't* there — missing
cases, hidden coupling, unstated assumptions, verification gaps — and verifying
every claim against real source instead of trusting it. Run it over your subsystem
map to surface the holes you were too close to see, and its `WebSearch` reach lets
it check your understanding of an unfamiliar project against how the wider
ecosystem does the same thing.

## Discovering the *real* current state of the code

Two pieces in the spec pipeline are quietly excellent for investigation:

- **The git-hotspot scan** (in the spec-review
  [`codebase-verifier`](../.claude/skills/spec-review/prompts/codebase-verifier.md))
  uses `git log --oneline --since="2 months ago" -- <file> | wc -l` — **10+ commits
  in two months marks a repeat-fix hotspot**, a file that probably needs a redesign
  rather than another patch. Run that heuristic early: churn is where the pain is.
- **The [`spec-drift-scout`](../.claude/skills/spec-review/prompts/spec-drift-scout.md)**
  is a cross-worktree, machine-wide discovery pass: it enumerates worktrees,
  searches for sibling clones with the same origin, and reports parallel work and
  prior intent that already exist locally. On a project that several people (or
  several of your own sessions) are touching, this is how you avoid re-investigating
  what's already in flight.

## Phase 4 — REMEMBER: make investigation compound across sessions

Investigation is wasted if the next session cold-starts. keel's durable-knowledge
layer:

- **[`claude-sessions`](../.claude/skills/claude-sessions/)** (a ~700-line Python
  transcript reader) surveys live sessions — what each one is doing, its open
  todos, the commits it authored (tagged via the `Session-Id` trailer) — and
  `extract-decisions` mines a transcript into structured intent and rejected
  alternatives. A new investigation reads what prior sessions already discovered
  instead of re-deriving it.
- **The in-flight registry**
  ([`inflight-registry.sh`](../tooling/workflow/inflight-registry.sh), a SessionStart
  hook) injects a repo-global worktree → branch → issue → PR table, with a "Behind"
  column for base staleness, into every new session's context. A fresh agent
  immediately *sees* what work is in flight.
- **The `testing/flows.json` behavior registry** is a committed place for the
  non-code-documented end-to-end behaviors you discover while investigating — the
  "this is what actually happens when a user does X" facts. keel's `spec-test`
  skills read this registry when it exists and bootstrap an empty one when it
  doesn't, so those discovered behaviors accumulate across cycles instead of being
  re-learned each session. For the *domain* side of durable knowledge — a
  ubiquitous-language glossary and architecture-decision records — pair it with
  Matt Pocock's `domain-modeling` skill (credited below), which writes those
  artifacts as you go.
- **The `Session-Id` trailer convention** means months later you can answer "which
  session wrote this, and why" by reading the trailer back through `claude-sessions`
  — investigation of the codebase's *own* history.

## Running it in parallel, safely

Fanning out several investigator sessions across subsystems is the force
multiplier — and `tooling/workflow/` is what keeps them from colliding. Even
read-only sweeps benefit from the [in-flight registry](parallel-agents.md) so each
session sees what the others are mapping. When an investigation turns into edits,
`workflow claim-scope` gives each lane an exclusive, glob-overlap-checked claim.
See [parallel-agents.md](parallel-agents.md) for the coordination layer.

## Standing on the shoulders of

keel ships the *agents and coordination* above as its own clean-room work. For the
disciplined **discovery and research skills** that pair naturally with them, it
points you to excellent open source rather than republishing it:

- **[Matt Pocock's skills](https://github.com/mattpocock/skills)** — `domain-modeling`
  (build a ubiquitous-language glossary + ADRs as durable cross-session artifacts),
  `codebase-design` (a precise deep-module vocabulary — Module / Interface / Adapter
  / Depth / seams — for describing an unknown module's shape), `diagnosing-bugs`
  (signal-first hard-bug loop), and `grilling` (a relentless one-question-at-a-time
  interview that explores the codebase to answer its own questions). Pair
  `domain-modeling` with keel's `testing/flows.json` registry: one captures the
  language, the other captures the behaviors.
- **[superpowers](https://github.com/obra/superpowers)** — `deep-research` (fan-out
  web search with adversarial verification and cited synthesis — the external-research
  half of new-project investigation), `systematic-debugging` (root-cause-before-fix),
  and `brainstorming` (surface requirements and intent before touching code).

Add those alongside keel; this page describes how keel's own primitives compose,
and where the borrowed ones plug in. The line is deliberate: keel ships the
mechanics that are mine to ship, and credits the skills that aren't.
