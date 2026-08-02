# keel — Agent Instructions

Canonical instructions file for this repo (Codex/Gemini read this; `CLAUDE.md` is a
symlink here — one contract, two filenames; see `docs/instructions-files.md`).

## Communication

Write for an experienced software engineer with a tired brain. **Low cognitive load is
the goal — not low word count.** No unnecessary jargon, no long-winded breakdowns, no
walls of prose. Lead with the answer, then the why; one idea per sentence. Be short
because the writing is DENSE, not because it is clipped: cut filler, preamble and
hedging, but keep the articles and full sentences that let a line parse on the first
read. Telegraphic fragments save tokens and cost comprehension — the wrong trade.

*(Stated here, not only in an operator's global layer, because Codex and Gemini read
this file and never see that layer. Not a duplicate — do not prune it as one.)*

## What this repo is

The public, canonical skills repo. Machines consume it via symlinks from their skill
roots into this clone — an edit here is live everywhere on next skill invocation, no
install step.

## Contracts

- **A dispatched lane is graded by its ARTIFACT, not its envelope** (global CLAUDE.md
  §Workflow). A skill that dispatches lanes states, in the lane prompt, the objective
  artifact the caller will check — a completion envelope reading `success` over an
  empty artifact is a dead lane. Applies to Codex lanes too: `codex exec` can exit 0
  having answered a different question.
- **This repo has no CI and no PR gate** — 1 PR in its lifetime, 0 GitHub Actions runs,
  `.github/workflows/` absent; commits land direct to `master`. Do not propose
  CI-shaped guards here; a `gh pr merge` hook would have no call sites. Merge/CI
  friction observed in *product* repos belongs in those repos' own layer.
- **Never drive the human's focused browser tab.** Chrome automation is cross-project,
  so it lives here: `tooling/chrome.sh` is canonical, consumed by symlink from
  `~/.claude/scripts/chrome.sh` (machine-level — `install.sh` copies only
  `tooling/workflow` and `tooling/sandbox`, so it is never duplicated per repo). Each
  session owns ONE tab, keyed by `$CLAUDE_SESSION_ID` and targeted by id, so `open` /
  `js` / `content` / `url` never move focus and parallel sessions never collide;
  `tab show` is the only command that focuses. Driving "the active tab" instead makes
  the agent and the human fight over one tab — the agent navigates away from what the
  human is reading, and the human switching tabs silently re-points the agent at the
  wrong page. Both directions corrupt work, so a stale owned tab re-opens a fresh one
  and NEVER falls back to the active tab. Run `chrome.sh check` before diagnosing
  "Chrome not working" by hand.
- **Public and marker-free.** No secrets, customer names, project-private facts, or
  machine-specific paths in skills or seeds. Operator-private craft goes to the
  machine's `~/.claude/skills-overlay/<skill>/LEARNINGS.md`; machine/project facts go
  to project memory (`docs/skill-memory.md` owns the routing).
- **Committed `LEARNINGS.md` files are curated seeds** — they grow ONLY via
  de-identified promotion (an `/improve-harness` PR), never by hand-appending at task
  end.
- **One skill, one directory** under `.claude/skills/<name>/` with a `SKILL.md`;
  scripts live in the skill's `scripts/`; no cross-skill runtime coupling.
- **Agents follow the same split as skills.** `.claude/agents/` holds only
  vendor-neutral engineering-craft roles — no customer names, project file paths,
  credentials, or platform-branded agents (they go machine-wide via symlink, so a
  leak surfaces in every repo). A project's own agents live in that project's
  repo-local `.claude/agents/`, extending the craft roles, never here.
- **Skills load at invocation time** (edits apply to running sessions on next use);
  instructions files load at session start. Say which class a change is when
  claiming "applied".
- **Dispatched lane prompts must declare leaf-agent scope** — any prompt a skill
  hands to a subagent/Workflow lane includes: "You are a leaf agent: do NOT spawn
  sub-agents or Workflows; do the work inline and return."
- **Dispatched agents return a condensed summary, not a transcript** — target
  1,000–2,000 tokens of conclusions; never raw tool output or file bodies (the
  caller re-reads them on every subsequent turn). Carve-out: ground-truth
  identifiers — exact error text, `file:line` anchors, commit SHAs, ticket IDs,
  command strings — are quoted VERBATIM, never compressed away to hit the target.
