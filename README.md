<h1 align="center">keel</h1>

<p align="center">
  <em>A disciplined harness for AI coding agents.</em><br>
  Multi-model spec review, parallel-agent coordination, and the rules that keep them honest.
</p>

<p align="center">
  <a href="#quickstart">Quickstart</a> ·
  <a href="#whats-in-here">Components</a> ·
  <a href="#the-three-ideas">The ideas</a> ·
  <a href="#requirements">Requirements</a> ·
  <a href="LICENSE">MIT</a>
</p>

---

A keel is the structural backbone of a ship — the spine that lets it carry sail
without capsizing. This repo is that spine for AI-assisted engineering: a small,
opinionated harness that turns "the model wrote some code" into "the change was
specified, reviewed by several independent models, tested end-to-end, and shipped
without two agents clobbering each other."

It's the **generalized, sanitized core of the harness I use to do my day-to-day
engineering** on [Cynap](https://cynap.ai). Everything Cynap-specific has been
stripped and replaced with fill-in-the-blank templates, so you can drop it into any
repo. No business logic, no secrets — just the machinery and the discipline.

> **Philosophy in one line:** an AI agent will confidently produce plausible,
> wrong, or quietly-colliding work unless the *harness* makes that hard. keel is
> the harness — the structure lives outside the model, in skills, hooks, rules, and
> a tiny coordination layer.

## The three ideas

Most of keel is in service of three convictions.

### 1. One model reviewing its own work is a blind spot. Use a panel.

The headline skill, [`spec-review`](.claude/skills/spec-review/), runs **nine
independent reviewers in parallel** against a spec — six Claude agents
(completeness, codebase grounding, architecture, an edge-case *boundary miner*, a
security miner that audits against *your* policy, and a cross-worktree drift scout)
plus three [Codex](https://openai.com/codex/) GPT-class reviewers (standard,
adversarial, and a web-enabled industry-research auditor that cites real OSS and
post-mortems). Each gets a tight prompt and one job.

The coordinator then does the part everyone skips: when Claude and Codex
**disagree** on something that matters, it stages an actual cross-examination —
feeds each model the other's argument, up to two rounds — and brings the
disagreement to *you* with both positions instead of silently picking one. Findings
go in a report; only genuine design defects get written back into the spec prose.
It never pastes its own review scaffolding into your spec.

It also mines the *session that produced the spec* — the decisions, the rejected
alternatives, the corrections you made along the way — so reviewers judge the spec
against your **intent**, not just its prose. That mining is done by
[`claude-sessions`](.claude/skills/claude-sessions/), a 700-line transcript reader
that ships with keel.

### 2. "Done" means verified, not asserted — so prove it end-to-end.

[`spec-test-plan`](.claude/skills/spec-test-plan/) and
[`spec-test-execute`](.claude/skills/spec-test-execute/) are the QA pair. Their
spine is **real staging verification**: deploy, run the feature the way a customer
would, read the actual logs, confirm the customer-facing output. Unit and
integration tests only where they're cheap and catch a real regression — no
smoke-test theatre. The executor marks each test PASS/FAIL/SKIP/BLOCKED, fans out
parallel diagnostician agents on failures, escalates genuinely-stuck tests, and
loops until the plan is green or honestly blocked.

This only works if the harness knows how to run *your* tests, so both skills read a
single `docs/testing-config.md` (templated here) with your staging URLs, deploy
command, test accounts, and the exact log line that means "it worked."

### 3. Parallel agents need lanes, or they crash into each other.

Running several agent sessions at once — one per worktree — is a force multiplier
right up until two of them edit the same file or eight of them launch a full test
build simultaneously and melt your machine. keel's
[`tooling/workflow/`](tooling/workflow/) is a ~650-line coordination layer that
prevents both:

- **Path ownership.** Before an agent touches code it runs `workflow claim-scope
  '<glob>'`. The claim is checked — under a real `flock` — against every other live
  session's claims, with **glob-overlap detection**, and *refused* if they'd
  collide. State is shared across all worktrees of a repo via `--git-common-dir`, so
  the lanes are global, not per-checkout.
- **An in-flight registry** injected into every session's context at start: a joined
  view of every worktree → branch → open PR → issue, and how stale each branch's
  base is — so a new agent continues existing work instead of opening a third branch
  for the same ticket.
- **A machine-global heavy-op lock** (`with-heavy-lock` + the `serialize-heavy-ops`
  hook) so tests/builds/installs **queue and run locally one at a time** instead of
  all firing at once.
- **Lifecycle + a reaper** so state from a crashed session gets cleaned up.

## What's in here

```
keel/
├── .claude/
│   ├── skills/
│   │   ├── spec-review/         # 9-reviewer multi-model spec verification
│   │   ├── spec-test-plan/      # E2E-first test planning from a spec
│   │   ├── spec-test-execute/   # tier-by-tier execution + failure triage
│   │   └── claude-sessions/     # live-session survey + decision-mining (Python)
│   ├── agents/                  # 10 generic sub-agents the skills dispatch
│   │   #   architect · critic · executor · explore · planner
│   │   #   security-reviewer · verifier · code-reviewer · debugger · git-master
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
a [`CLAUDE.md` template](templates/CLAUDE.md.template) that encodes the engineering
discipline an agent should never have to be reminded of twice — verify before
claiming done, delete the code path you replace (leave *one* architecture behind),
no speculative abstraction, conventional commits with a required scope, branch off
fresh trunk. Fill in the `{{PLACEHOLDERS}}` and it becomes your repo's law. See
[`examples/filled-in/`](examples/filled-in/) for a populated version.

## Quickstart

```bash
git clone https://github.com/Roeelfs/keel.git
cd /path/to/your/project
/path/to/keel/install.sh .          # copies .claude/ + tooling/, never overwrites
```

Then fill in `CLAUDE.md`, `docs/security-policy.md`, and `docs/testing-config.md`,
review `.claude/settings.json`, restart Claude Code, and run the `spec-review` skill
on a spec. Full walkthrough in **[QUICKSTART.md](QUICKSTART.md)**.

## Requirements

- **[Claude Code](https://claude.com/claude-code)** — the primary runtime for the skills, hooks, and agents.
- **`git`, `jq`, `bash`, `python3`** — the workflow tooling and session miner.
- **`flock`** — for the locks (`brew install flock` on macOS; preinstalled on most Linux).
- **Optional: [Codex CLI](https://openai.com/codex/)** — enables the 3 multi-model Codex lanes in `spec-review`. Without it, the review runs Claude-only and still works.
- **Optional: [GitHub CLI](https://cli.github.com/) (`gh`)** — lets the in-flight registry show open PRs.

keel is designed for Claude Code but the skills follow the open
[agent-skill standard](https://agentskills.io), so they're portable to other
CLIs that support it.

## Standing on the shoulders of

keel is the original engineering — the spec-review pipeline, the QA skills, the
path-ownership/coordination layer, and the session miner are my own work. It's
meant to sit *alongside* excellent open-source skills I use and recommend, which it
deliberately does **not** republish:

- **[Matt Pocock's skills](https://github.com/mattpocock/skills)** — `grilling`
  (relentless plan stress-testing), the engineering-skills set (triage, to-prd,
  to-issues, domain-modeling, codebase-design), `handoff`, and
  `improve-codebase-architecture`. keel pairs naturally with these.
- **[superpowers](https://github.com/obra/superpowers)** — the spec-driven
  workflow convention that shaped how I think about specs.
- **omc / generic sub-agents** — keel ships its own clean-room sub-agent
  definitions; any compatible agent set works.

## License

[MIT](LICENSE) — use it, fork it, make it yours.

---

<p align="center">
  Built by <strong>Roee Alfasi</strong> ·
  <a href="https://github.com/Roeelfs">GitHub</a> ·
  <a href="https://cynap.ai">cynap.ai</a>
</p>
