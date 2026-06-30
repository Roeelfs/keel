---
name: review
description: Review the changes since a fixed point (commit, branch, tag, or merge-base) along two axes — Standards (does the code follow this repo's documented coding standards?) and Spec (does the code match what the originating issue/PRD asked for?). Runs both reviews in parallel sub-agents and reports them side by side. Use when the user wants to review a branch, a PR, work-in-progress changes, or asks to "review since X".
---

Two-axis review of the diff between `HEAD` and a fixed point the user supplies:

- **Standards** — does the code conform to this repo's documented coding standards?
- **Spec** — does the code faithfully implement the originating issue / PRD / spec?

Both axes run as **parallel sub-agents** so they don't pollute each other's context, then this skill aggregates their findings.

Spec context lives in your issue tracker (e.g. Linear, Jira, GitHub Issues), fetched via that tracker's MCP or CLI if one is available. If the tracker exposes an MCP `get_issue`-style tool, use it to pull the issue and its description; otherwise fetch the issue however the repo documents.

## Process

### 1. Pin the fixed point

Whatever the user said is the fixed point — a commit SHA, branch name, tag, `main`, `HEAD~5`, etc. If they didn't specify one, default to `origin/main`.

Run `git fetch origin` first so the fixed point is current — a stale ref manufactures false diffs and phantom contamination (the squash-against-stale-base failure class).

Capture the diff command once: `git diff <fixed-point>...HEAD` (three-dot, so the comparison is against the merge-base). Also note the list of commits via `git log <fixed-point>..HEAD --oneline`.

Before going further, confirm the fixed point resolves (`git rev-parse <fixed-point>`) and the diff is non-empty. A bad ref or empty diff should fail here — not inside two parallel sub-agents.

### 2. Identify the spec source

Look for the originating spec, in this order:

1. Issue-tracker refs in the branch name, commit messages, or PR body (e.g. `PROJ-123`, `Fixes PROJ-123`, `Part of PROJ-123`, or `#123`) — fetch the issue + its description from your issue tracker.
2. A path the user passed as an argument.
3. A spec/ADR file under a spec, ADR, or roadmap directory (e.g. `docs/specs/`, `docs/adr/`, `docs/roadmap/`) matching the branch name or feature.
4. If nothing is found, ask the user where the spec is. If they say there isn't one, the **Spec** sub-agent will skip and report "no spec available".

### 3. Identify the standards sources

A repo typically documents its standards in agent/contributor instruction files (e.g. `CLAUDE.md`/`AGENTS.md` at the root — often the same file, symlinked), plus your project's standards docs (if present), any `CONTEXT.md`, and ADRs under an ADR directory (e.g. `docs/adr/`). Look for whichever of these exist in this repo and pass them to the Standards sub-agent. If the repo has a conventional `CODING_STANDARDS.md` or `CONTRIBUTING.md`, include those too; otherwise use whatever standards files are present.

### 4. Spawn both sub-agents in parallel

Send a single message with two `Agent` tool calls. Use the `general-purpose` subagent for both.

**Standards sub-agent prompt** — include:

- The full diff command and commit list.
- The list of standards-source files you found in step 3.
- The brief: "Report — per file/hunk where relevant — every place the diff violates a documented standard. Cite the standard (file + the rule). Distinguish hard violations from judgement calls. Skip anything tooling enforces. Under 400 words."

**Spec sub-agent prompt** — include:

- The diff command and commit list.
- The path or fetched contents of the spec.
- The brief: "Report: (a) requirements the spec asked for that are missing or partial; (b) behaviour in the diff that wasn't asked for (scope creep); (c) requirements that look implemented but where the implementation looks wrong. Quote the spec line for each finding. Under 400 words."

If the spec is missing, skip the Spec sub-agent and note this in the final report.

### 5. Aggregate

Present the two reports under `## Standards` and `## Spec` headings, verbatim or lightly cleaned. Do **not** merge or rerank findings — the two axes are deliberately separate (see _Why two axes_).

End with a one-line summary: total findings per axis, and the worst issue _within each axis_ (if any). Don't pick a single winner across axes — that's the reranking the separation exists to prevent.

## Why two axes

A change can pass one axis and fail the other:

- Code that follows every standard but implements the wrong thing → **Standards pass, Spec fail.**
- Code that does exactly what the issue asked but breaks the project's conventions → **Spec pass, Standards fail.**

Reporting them separately stops one axis from masking the other.
