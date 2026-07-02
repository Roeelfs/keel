<h1 align="center">keel</h1>

<p align="center">
  <em>An evidence-first harness for AI coding agents.</em><br>
  Nothing ships on baked-in knowledge — findings, specs, bug diagnoses, and the
  harness itself get grounded in outside evidence by dynamic multi-agent workflows.
</p>

<p align="center">
  <a href="#quickstart">Quickstart</a> ·
  <a href="#the-principle-never-act-from-baked-in-knowledge">The principle</a> ·
  <a href="#the-four-grounding-loops">The four loops</a> ·
  <a href="#the-skill-map">Skill map</a> ·
  <a href="#requirements">Requirements</a> ·
  <a href="LICENSE">MIT</a>
</p>

---

A keel is the structural backbone of a ship — the spine that lets it carry sail
without capsizing. This repo is that spine for AI-assisted engineering: a complete,
opinionated development harness for coding agents — skills, sub-agents, hooks,
rules, and a small coordination layer — that turns "the model wrote some code" into
"the change was grounded in real evidence, reviewed by a panel of independent
models, verified against real logs, and shipped without two agents clobbering each
other."

No business logic, no secrets, no ties to any particular product — just the
machinery and the discipline, with `{{PLACEHOLDER}}` templates where your project's
specifics go.

## The principle: never act from baked-in knowledge

Coding agents are good. That is exactly the problem: a capable model produces
*convincing* output whether or not it is current, correct, or what the rest of the
industry actually does. Its trained knowledge is a cache with no expiry header —
an API remembered confidently from two majors ago, an "industry standard" that was
one blog post, a root cause that pattern-matches instead of tracing.

keel is built on one ruling conviction:

> **Architectural gains come from high-end dynamic workflows in which the agent
> actively seeks out independent places to ground its work** — vendor docs and
> changelogs, what real providers and competitors ship, the industry standard, and
> your own logs, database, CI, and git history — **before it commits to a finding,
> a spec, a root cause, or a change to its own harness.**

Grounding here is not "do a web search first." It is structural: a framed fan-out
of focused agents across angles × sources, **adversarial cross-verification** (a
separate pass tries to *refute* every load-bearing claim, and refuted claims are
partitioned out in code before synthesis), one live source per claim, and a clear
rule for which evidence surface is authoritative — a third-party question is
answered by the vendor's docs; a question about *your own* runtime is answered by
your own logs and codebase, never the web.

## The four grounding loops

Everything an agent produces falls into one of four artifacts, and each has a
dedicated grounding loop.

### 1. Findings — [`investigation`](.claude/skills/investigation/)

The grounding engine the other loops build on. Before an unfamiliar or
external-facing task, it launches a dynamic multi-agent Workflow: **frame** the
task against *this* codebase (parallel readers, every claim cited `file:line`),
**research** one agent per question against primary sources (official docs,
changelogs, the source repo, GitHub code search — not the top SEO hit),
**cross-verify** adversarially, then synthesize a short grounded brief with an
explicit *industry standard* and *elevation (best-in-class)* section — what the
field actually does, and what the best version of this looks like. Briefs land in
`docs/investigations/` with a freshness header, so grounding compounds instead of
evaporating. Escalation path: the `deep-research`-class skills when you need a
fully-cited standalone report.

### 2. Specs — [`spec-review`](.claude/skills/spec-review/)

One model reviewing its own plan is a blind spot, so specs face a **panel of ten
independent reviewers in parallel**: seven Claude lanes (completeness, codebase
grounding, architecture, a provider-fit auditor that runs build-vs-adopt both ways
— including on the *inherited* architecture a spec extends, an edge-case boundary
miner, a security miner that audits against *your* policy, and a cross-worktree
drift scout) plus three web-enabled [Codex](https://openai.com/codex/) GPT-class
lanes (standard, adversarial, and an industry-research auditor that cites real OSS
and post-mortems). The elevation lane is grounded by the `investigation` Workflow —
verified, code-anchored industry evidence, not the model's recollection of it.

When Claude and Codex **disagree** on something that matters, the coordinator
stages an actual cross-examination — each model gets the other's argument, up to
two rounds — and brings the disagreement to *you* with both positions instead of
silently picking one. It also mines the session that *produced* the spec (via
[`claude-sessions`](.claude/skills/claude-sessions/)) so reviewers judge the spec
against your intent, not just its prose. Only genuine design defects get written
back; it never pastes review scaffolding into your spec.

### 3. Bugs — [`root-cause-analysis`](.claude/skills/root-cause-analysis/)

An RCA is where ungrounded reasoning is most expensive, so the skill makes every
step evidential: read the **terminal signal** (logs, run status, the store's
actual state) before theorizing; pin **onset vs. change timeline** — a change
shipped after onset is mechanically exonerated; no fix without a **red-capable
feedback loop** that proves the cause. Before hand-building a fix architecture, a
**provider ⋈ architecture alignment gate** field-surveys how 3+ real providers
serve the same use-case (grounded via `investigation`, never asserted from memory)
and demands that every number justifying the incumbent design traces to a
**measurement or an invoice** — not a timeout constant remembered as one.

Then the loop that makes errors non-recurring — the **no-error-occurs-twice
principle**: every RCA is checked against and written back to a **known-error
ledger** keyed on a stable fingerprint, so the next agent inherits the finding
instead of re-deriving it. A regression is recognized as a regression, with the
prior fix as its starting point. Diagnosis mechanics live in
[`diagnosing-bugs`](.claude/skills/diagnosing-bugs/); fix placement follows
[`improve-codebase-architecture`](.claude/skills/improve-codebase-architecture/)
so the fix deepens the codebase rather than bolting on a compensating layer.

### 4. The harness itself — [`improve-harness`](.claude/skills/improve-harness/)

The harness is not exempt from its own rule. A periodic ritual mines your recent
sessions for **recurring friction loops** (the same operation retried three times,
repeated identical errors, a merge blocked over and over), audits every
instructions file for stale or contradictory rules, and researches current
versions of every plugin, CLI, and model pin against live sources. The key
correlation: for every mined lesson, *should an existing rule have prevented it?*
Strengthen the rule — or better, **promote it to a hook** that mechanically blocks
the wrong move, because a rule the model must remember is weaker than a guard the
harness enforces. That is "no error occurs twice" applied to the agent's own
behavior, not just the codebase's.

## The whole system lives in the harness

The grounding loops only close if the harness can *reach* every surface of your
system — so keel bakes them all in as configuration, per repo:

- **Local verification and CI/CD** — [`docs/testing-config.md`](templates/testing-config.example.md)
  (templated) tells the test skills your verify gate, deploy command, staging
  URLs, test accounts, and the exact log line that means "it worked."
  [`spec-test-plan`](.claude/skills/spec-test-plan/) and
  [`spec-test-execute`](.claude/skills/spec-test-execute/) use it to run
  verification whose spine is **real staging**: deploy, exercise the feature the
  way a customer would, read the actual logs, confirm the customer-facing output —
  not smoke-test theatre. Failures fan out to parallel diagnostician agents.
- **Logs and database** — the rules files name the authoritative surfaces
  (which log group, which store holds terminal status), and the RCA skill refuses
  to theorize until they've been read. "It should work" is answered by the log
  line, not the diff.
- **Behavioral knowledge** — [`flows`](.claude/skills/flows/) maintains
  `testing/flows.json`, a committed registry of the non-code-documented end-to-end
  behaviors discovered across spec-test cycles, so they accumulate instead of
  being re-learned each session.
- **Rules as one canonical contract** — one `AGENTS.md`/`CLAUDE.md` per repo, the
  other filename a symlink or thin pointer, per
  [docs/instructions-files.md](docs/instructions-files.md). Contracts live in
  instructions files, procedures in skills, facts in memory — and the
  `improve-harness` audit keeps that routing true over time.
- **Memory, routed by scope** — [docs/skill-memory.md](docs/skill-memory.md)
  splits what a skill learns three ways: universal craft into the skill's
  committed seed (promote-only, via PR), operator-private craft into
  `~/.claude/skills-overlay/`, and **project-specific facts into that project's
  `.claude/memory/`** — which is what lets one harness serve many repos on the
  same machine without cross-contamination.
- **Multi-repo, one canonical clone** —
  [`harness-onboarding`](.claude/skills/harness-onboarding/) surveys a machine
  (skill roots, runtimes, repos, instructions files, memory), then wires
  everything as **symlinks to a single canonical keel clone**, so a skill edit
  propagates to every repo instantly and there is nothing to re-install, ever.

## Parallel agents need lanes

Running several agent sessions at once — one per worktree — is a force multiplier
right up until two of them edit the same file, or eight of them launch full test
builds simultaneously and melt your machine.
[`tooling/workflow/`](tooling/workflow/) is a ~650-line coordination layer that
prevents both:

- **Path ownership.** Before touching code an agent runs `workflow claim-scope
  '<glob>'`. Claims are checked — under a real `flock` — against every live
  session, with glob-overlap detection, and *refused* on collision. State is
  shared across all worktrees of a repo via `--git-common-dir`.
- **An in-flight registry** injected into every session's context at start: a
  joined view of every worktree → branch → open PR → issue, and how stale each
  branch's base is — so a new agent continues existing work instead of opening a
  third branch for the same ticket.
- **A machine-global heavy-op lock** (`with-heavy-lock` + the
  `serialize-heavy-ops` hook) so tests/builds/installs queue and run one at a
  time.
- **Lifecycle + a reaper** so state from a crashed session gets cleaned up.

The [`orchestrator`](.claude/skills/orchestrator/) skill sits on top for 3+
parallel sessions; [`claude-sessions`](.claude/skills/claude-sessions/) and
[`codex-sessions`](.claude/skills/codex-sessions/) survey what every session is
doing and mine transcripts for the decisions downstream reviews need.

## The skill map

The harness covers the full development lifecycle. Roughly in the order work
flows (`/ask-matt` is the built-in router when you forget):

| Stage | Skills |
|---|---|
| **Ground** | `investigation` — evidence before action, for everything below |
| **Shape the idea** | `grilling` / `grill-with-docs` / `grill-me` · `prototype` · `domain-modeling` · `to-prd` · `to-issues` · `triage` |
| **Build** | `implement` · `tdd` · `codebase-design` · `resolving-merge-conflicts` |
| **Review** | `spec-review` · `standards-spec-review` · `spec-visualization` |
| **Test & verify** | `spec-test-plan` · `spec-test-execute` · `flows` |
| **Diagnose** | `diagnosing-bugs` · `root-cause-analysis` |
| **Codebase health** | `improve-codebase-architecture` |
| **Parallel sessions** | `orchestrator` · `claude-sessions` · `codex-sessions` · `sessions-to-chips` · `handoff` |
| **Harness upkeep** | `improve-harness` · `harness-onboarding` · `writing-great-skills` · `free-resources` |
| **Utilities** | `work-report` · `design-taste-frontend` · `caveman` · `ask-matt` · `setup-matt-pocock-skills` |

## What's in here

```
keel/
├── .claude/
│   ├── skills/                  # 36 skills — the full lifecycle above
│   ├── agents/                  # focused sub-agents the skills dispatch:
│   │   #   architect · code-reviewer · critic · debugger · executor
│   │   #   explore · refactorer · scientist · security-reviewer
│   │   #   sql-specialist · tracer
│   ├── hooks/                   # session lifecycle, id capture, worktree warn,
│   │   #                          heavy-op serializer, crashed-session reaper
│   └── settings.example.json    # model routing, permissions, hook wiring
├── tooling/
│   ├── workflow/                # path-ownership CLI + in-flight registry
│   └── sandbox/with-heavy-lock  # machine-global heavy-op lock
├── templates/                   # CLAUDE.md / AGENTS.md / security-policy / testing-config
├── examples/filled-in/          # the templates populated for a sample project
├── docs/                        # one short essay per subsystem
├── install.sh                   # drop keel into a target repo (never clobbers)
└── QUICKSTART.md
```

### The rules that keep agents honest

Skills and hooks are the machinery; the **rules file** is the contract. keel ships
a [`CLAUDE.md` template](templates/CLAUDE.md.template) encoding the engineering
discipline an agent should never have to be told twice — verify before claiming
done, delete the code path you replace (leave *one* architecture behind), no
speculative abstraction, conventional commits with a required scope, branch off
fresh trunk. Fill in the `{{PLACEHOLDERS}}` and it becomes your repo's law. The
full discipline is written up in [docs/philosophy.md](docs/philosophy.md); see
[`examples/filled-in/`](examples/filled-in/) for a populated version.

## Quickstart

Two ways in, by scope:

**One repo** — copy the harness in:

```bash
git clone https://github.com/Roeelfs/keel.git ~/keel
cd /path/to/your/project
~/keel/install.sh .                 # copies .claude/ + tooling/, never overwrites
```

Then fill in `CLAUDE.md`, `docs/security-policy.md`, and `docs/testing-config.md`,
review `.claude/settings.json`, restart your agent CLI, and run `spec-review` on a
spec. Full walkthrough in **[QUICKSTART.md](QUICKSTART.md)**.

**Whole machine, many repos** — let the harness onboard itself:

> Run the harness-onboarding skill

It surveys your machine's current state, proposes an integration plan (one
canonical clone, symlinked everywhere; `AGENTS.md`↔`CLAUDE.md` wiring; overlay +
memory setup), and applies it with a backup — so every repo shares one live copy
of the skills.

## Requirements

- **[Claude Code](https://claude.com/claude-code)** — the primary runtime for the skills, hooks, and agents.
- **`git`, `jq`, `bash`, `python3`** — the workflow tooling and session miners.
- **`flock`** — for the locks (`brew install flock` on macOS; preinstalled on most Linux).
- **Optional: [Codex CLI](https://openai.com/codex/)** — enables the 3 multi-model Codex lanes in `spec-review`. Without it, the review runs Claude-only and still works.
- **Optional: [GitHub CLI](https://cli.github.com/) (`gh`)** — lets the in-flight registry show open PRs.

keel is designed for Claude Code but the skills follow the open
[agent-skill standard](https://agentskills.io), so they're portable to other
CLIs that support it.

## Standing on the shoulders of

The spec-review pipeline, the investigation and RCA loops, the QA skills, the
harness-improvement ritual, the coordination layer, and the session miners are
original work. Part of the engineering skill line is vendored — sanitized and
adapted, with gratitude — from excellent open source:

- **[Matt Pocock's skills](https://github.com/mattpocock/skills)** — the
  idea→ship engineering flow (`grilling`, `domain-modeling`, `codebase-design`,
  `diagnosing-bugs`, `triage`, `to-prd`, `to-issues`, `implement`, `prototype`,
  `handoff`, `improve-codebase-architecture`, `writing-great-skills`). Run
  `/setup-matt-pocock-skills` once to configure them; `/ask-matt` routes between
  them.
- **[superpowers](https://github.com/obra/superpowers)** — the spec-driven
  workflow convention that shaped the spec pipeline, and the `deep-research` /
  `systematic-debugging` / `brainstorming` axis keel's grounding loops
  deliberately compose with.

## License

[MIT](LICENSE) — use it, fork it, make it yours.

---

<p align="center">
  Built by <strong>Roee Alfasi</strong> ·
  <a href="https://github.com/Roeelfs">GitHub</a>
</p>
