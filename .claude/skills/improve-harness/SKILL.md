---
name: improve-harness
description: Periodically mine recent work + harness state into one consolidated improvement plan, grill it, then execute prune → vendor → upgrade → docs → memory and merge across your harness surfaces.
disable-model-invocation: true
---

# Improve Harness

A periodic ritual that turns the last stretch of work into a **better agent harness**. It mines recent sessions for lessons, surveys every harness surface, researches what's gone stale, **consolidates** one sequenced plan, grills it, and converges the harness to a new **canonical** state — then merges that state across all your harness surfaces.

Run it like `/improve-codebase-architecture`: every week or two, or after a burst of heavy work has accumulated lessons and version drift. It is **user-invoked** — it only fires when you type it, because it mutates your live global harness.

## The harness surfaces it touches

Every change lands in exactly one of these — name the target before editing:

- **product repo** — the repo you ship from. `AGENTS.md`/`CLAUDE.md` rule edits land here. Ships as a **PR**; if merging is a prod-deploy-class gate in your project, it needs explicit go-ahead.
- **skills repo** — the repo holding your vendored skills (cloned locally, e.g. `~/code/<your-skills-repo>`); commit + push, installed via `npx skills update -g`.
- **harness repo** — your `~/.claude` (itself a git repo, optionally backed by a private remote): agents, commands, hooks, global `CLAUDE.md`, settings, memory. Commit + push; **never weaken its `.gitignore`**.

## Reversibility first

This ritual mutates your live global harness. **Back up before any mutation** — that is step 4(a), and nothing destructive runs before it. Every step is individually reversible (git revert, lock restore, plugin re-pin).

## Process

### 1. Launch the investigation — parallel dynamic Workflows

Fan the read-only investigation out into **parallel background Workflows** so they run while you do nothing. Run **A and B every time**; add **C on a deeper/~quarterly pass** (the agent-stack landscape moves slowly), and **D whenever the period included a regression cluster, a prod incident, or an unstable-prod stretch** (the production-stability pass). Author them from the templates in [WORKFLOW.md](WORKFLOW.md):

- **Workflow A — mine + consolidate.** Session miners over the **past week** of `~/.claude/projects/*/*.jsonl` + `history.jsonl` (extract human turns, corrections, self-flagged mistakes, **and recurring friction loops** — the same operation retried ≥3× to no effect, repeated identical errors, repeated permission denials, a merge attempted-and-blocked over and over), plus surveyors of every harness surface: **GitHub** (merged PRs, **and the *friction* side: PRs that were BLOCKED / took many merge attempts / had high CI re-run counts / were stuck on unresolved review comments** — `gh pr list`, `gh run list`, the `mergeStateStatus`), **your issue tracker** (recent issue comments + status changes), **worktrees** (the in-flight registry; prune candidates), **memory** (`MEMORY.md` + topic-file drift), and a **vendoring + deep-audit** of skills/agents/commands/hooks. → one consolidated, sequenced plan with ranked new lessons + a concrete prune list. **A recurring friction loop is the highest-signal lesson there is** — it is the canonical case for proposing a **harness hook** (a `settings.json` `PreToolUse`/`Stop` guard that mechanically blocks the wrong move) or a standing rule, not just a doc edit. The motivating example: stuck on `gh pr merge` four times before learning "resolve all PR review comments before merging" — that friction should have surfaced itself as a hook proposal, never waited on the human to notice it.
- **Workflow B — latest + models.** Research the latest version of every **GitHub-derived** plugin, marketplace, and skill, the **CLIs** (Claude Code, Codex, `skills`), and a **model-pin audit** of every `model:` against the current flagship IDs. → a version matrix + ready-to-run upgrade plan.
- **Workflow C — agent-stack landscape (periodic).** Live-verify the best/newest GitHub agent stacks — subagent collections, orchestration frameworks, frontier SDKs — and gap-analyze our owned agents against them. → a stay/cherry-pick/adopt recommendation. The standing answer is **own + cherry-pick specific roles, never adopt a stack wholesale** (a competing framework violates one-architecture — the same reason to retire any parallel orchestration layer you've previously rejected — see [GOTCHAS.md](GOTCHAS.md)).
- **Workflow D — production-stability / regression RCA (conditional).** When the period regressed prod — a cluster of incidents, an outage, an unstable stretch — mine the incidents into a robustness program. One agent RCAs **each incident** grounded in its diff + deploy-timestamp-vs-onset; cluster into failure classes + hot-zone files; design a cheap guardrail per class that converts a deploy-only defect into a **local-green failure**; then a **separate skeptic adversarially REFUTES each guardrail** (3 of 5 ship as false-security otherwise); synthesize a prioritized program. → fixes spanning **documentation, CI gates, harness rules, cross-session coordination, the lack-of-research gap, and standing invariants** — north star: **keep production stable**. It operationalizes the load-bearing finding that **local green is structurally blind** to whole defect classes (infra env/IAM wiring, stale config, hardcoded recipients, disagreeing literals, browser CSS, existing-data drift), so the lever is the reflex to add a cheap standing invariant at the un-mockable layer — never "understand the feature better." This is the phase that folds **CI + production stability** into the harness ritual.

All run read-only. **Completion criterion:** every launched Workflow has returned its structured plan; nothing in the harness has been mutated yet.

### 2. Reconcile into one sequenced program

Merge the plans into a single ordered program: **prune → vendor → upgrade → doc-edits → guardrails+hooks → memory**. (When D ran, weave its prioritized robustness program in as the **guardrails** step — CI gates, standing invariants, cross-session tooling, doc-rules — each routed to its surface; drop any guardrail D's adversarial verifier rated `insufficient` unless its refinement is applied.) **Every recurring-friction lesson from Workflow A's friction lane gets a routing decision here: a `settings.json` hook (mechanical block — highest leverage), a standing `CLAUDE.md`/`AGENTS.md` rule (prose guard), or both.** Prefer a hook whenever the wrong move is mechanically detectable at a tool boundary (e.g. a `PreToolUse` guard on `gh pr merge` that refuses while review threads are unresolved) — a rule the model "should remember" is weaker than a hook the harness enforces. Reconcile overlaps — the model audit is authoritative over the audit's coarse "re-point everything" (bump only genuinely-stale IDs); a delete-target needs no model bump. Adopt the recommended defaults for any low-stakes open question; surface only genuine risk-class forks (e.g. a MAJOR plugin bump). **Completion criterion:** one written plan where every item has a target surface and a risk rating, and every cross-workflow overlap is resolved.

### 3. Grill the plan

Run the `/grill-with-docs` skill on the consolidated plan **before mutating anything** — stress-test it against the documented domain language and project rules, and let contradictions surface. `/spec-review` verifies an already-written spec; grilling fixes a plan authored from a misread. **Completion criterion:** the plan survives grilling, with any contradiction either resolved or recorded.

### 4. Execute, in order

Each phase has traps — read [GOTCHAS.md](GOTCHAS.md) before running it.

- **a. Back up** the harness (lean tar of touched dirs + `~/.agents` + the skill-lock; `~/.claude` is itself a git repo). Verify the backup contains the files you're about to delete.
- **b. Prune** dead config — **verify every delete target exists first**, then remove and confirm no dangling references remain.
- **c. Vendor** — fork or sync the skills repo, promote/adapt skills, then **cut the global install over** to the fork (`npx skills add <fork> -g -y -s <name>` per skill). Confirm every lock row points at the fork and **no symlink dangles**.
- **d. Upgrade** — `claude plugin marketplace update` then `claude plugin update` per plugin; CLIs; bump only **genuinely-stale** model pins; prune dangling marketplaces. Plugin updates need a **restart** to apply; flag MAJOR bumps for a **bake** you can't do mid-session.
- **e. Doc-edits + hooks** — apply the rule changes to the product repo's `AGENTS.md` (for the PR) and the global `CLAUDE.md` (harness repo); apply approved **hooks** to `~/.claude/settings.json` (+ a script under `~/.claude/hooks/` if non-trivial) — harness repo. A hook can *block* a tool call, so treat it like a guardrail: dry-run its matcher against a recent transcript before committing, and never weaken `~/.claude`'s `.gitignore` to land a hook script (see [GOTCHAS.md](GOTCHAS.md)).
- **f. Memory + skill-learning promotion** — run the memory-consolidation pass first (keep the index lean), then write the new lesson files. Then **promote skill learnings by scope** (see [`docs/skill-memory.md`](../../../docs/skill-memory.md)): a learning that recurs ≥3× in a skill's private overlay (`~/.claude/skills-overlay/<skill>/LEARNINGS.md`) or across project memories gets **de-identified** and promoted into that skill's public **seed** `LEARNINGS.md` via the skills-repo PR — promotion is the ONLY way the seed grows. Keep secrets / customer / project specifics OUT of the seed (they stay in the overlay or project memory).

**Completion criterion:** every planned item is applied and locally verified; the only outstanding work is the human-gated restart + bake.

### 5. Merge everything, verify clean

Land the work across all your harness surfaces: the product-repo `AGENTS.md` **PR** (if merge-to-main is a prod deploy in your project, do not merge without an explicit go-ahead), the **skills repo** push, and the **harness repo** commit + push. Then verify each repo is clean and local == remote. **Completion criterion:** all surfaces clean, the version matrix reflects the new canonical state, and the only remaining items are the restart + bake handed to the human.
