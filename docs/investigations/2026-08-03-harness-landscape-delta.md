# Harness landscape delta — what shipped, what to adopt

> Grounded 2026-08-03 against sources current as of 2026-07-31; supersede on re-investigation of this slug.
> Method: 8-lane external survey → per-item adversarial falsifier wave → verdicts enforced in code
> (25 agents, 59 raw capabilities → 20 after dedupe → 16 verified → 15 survived, 1 refuted).

## TL;DR

**Nothing in the vendor landscape forces a change. One thing in our own harness does.**

`--full-auto` is a **removed flag kept as a compatibility trap** in codex-cli 0.145.0 — the vendor's own
words. It silently overrides whatever `--sandbox` was passed. It appears **12 times across this harness**,
including 10 in this public repo, in three distinct failure directions. Every other finding is small.

`github/gh-stack`: **skip.** Real, official, good — and a machine for the one thing our law forbids.

## Problem frame

Surveyed for adoptable capability across: gh-stack + stacked-PR tooling, the Claude Code CLI delta since
2.1.220, the Anthropic/OpenAI model lineups, codex-cli, newest GitHub agent stacks, TLDR/HN pulse,
published agent-design guidance, and GitHub platform features. Constraints that decided most verdicts:
never-slice, delete-legacy, one-architecture, keel-stays-public, and context economy (every added
plugin/MCP/skill is taxed on the fixed per-turn preamble across every turn).

## The finding: `--full-auto` is a compatibility trap

Verified independently at the binary level, sanity-controlled (`skip-git-repo-check` → 2 hits, so the
probe is valid — a bare `readlink -f $(which codex)` resolves to an asdf shim where every probe returns
0 and reads as "the feature doesn't exist").

From the real Mach-O binary:

```
removed_full_auto  REMOVED_FULL_AUTO  Legacy compatibility trap for the removed `--full-auto` flag
warning: `--full-auto` is deprecated; use `--sandbox workspace-write` instead.
```

`codex exec --help` no longer lists it at all (0 hits; control flag → 1 hit). Upstream sets
`SandboxMode::WorkspaceWrite` unconditionally when the flag is present, discarding `--sandbox`.
Live control run, both directions:

| invocation | reported sandbox |
|---|---|
| `--sandbox read-only --full-auto` | `workspace-write [workdir, /tmp, $TMPDIR]` |
| `--sandbox read-only` | `read-only` |

### Three failure directions

**A. Declared read-only, actually workspace-write — containment breach.**
The dispatch script prints `sandbox=read-only` to stderr while the process runs with write access.
Silent-wrong-success: exit 0, plausible banner, wrong containment, invisible to any failure-keyed check.

- `~/.claude/skills/codex/codex-dispatch.sh:417` *(machine-only)*
- `~/.claude/skills/codex/LEARNINGS.md:33` *(machine-only)*
- `.claude/skills/spec-test-plan/SKILL.md:98`
- `.claude/skills/spec-review/SKILL.md:547`
- `.claude/skills/spec-test-plan/prompts/codex-coverage-verifier.md:21,48`

**B. Declared danger-full-access, silently downgraded to workspace-write.**
The opposite direction — the rescue lane is *more* restricted than intended, so a rescue needing to write
outside the workspace fails for a reason nobody would look for.

- `.claude/skills/spec-test-execute/SKILL.md:279`
- `.claude/skills/spec-test-execute/prompts/codex-rescue-stuck.md:80`

**C. Redundant alongside an explicit `workspace-write`.**
Same mode either way, so no mode change. **UNVERIFIED:** whether the override also resets the adjacent
`--config sandbox_workspace_write.network_access=true`. If it does, three review prompts that tell the
model "You have web access" are lying to it. Worth a control run once Codex quota returns.

- `.claude/skills/spec-review/prompts/codex-adversarial-reviewer.md:16`
- `.claude/skills/spec-review/prompts/codex-standard-reviewer.md:16`
- `.claude/skills/spec-review/prompts/codex-research-auditor.md:18`

Fix is one token per site. Removing it is behavior-changing by design: lanes that were quietly writing
will now fail loudly.

## gh-stack — skip, on evidence

`github/gh-stack` is genuinely official (github org, public preview 2026-07-30, MIT, requires `gh` ≥2.0,
compatible with 2.96.0). Quality is not the question; purpose is.

The evidence that settles it is our own merge history, not an opinion about the tool:

- **cynap-monorepo-next**: 2,139 merged PRs; the 100 most recent sampled via
  `gh pr list --state merged --limit 100 --json baseRefName` returned **100/100 based on `main`**.
  Zero PR-on-PR chains. Not "few" — none.
- **keel**: no PR gate exists. 1 PR in the repo's lifetime, 0 Actions runs, direct-to-master.

It does **not** land in the runtime/money-path carve-out. That carve-out is for fixes confirmable only by
live traffic, where each ship **bakes before the next**. gh-stack optimizes keeping many branches open,
rebased, and reviewable *in parallel*. Same shape (a sequence), different motivating problem — treating
them as equivalent would smuggle general slicing in under the carve-out's name.

One near-miss checked so it isn't mistaken for a counter-example: `orchestrator/SKILL.md:97` says
*"Stack, don't park — a lane blocked on an unmerged PR branches its worktree off that PR's branch."*
That is a build-on-branch device for a blocked lane, not a PR review chain; the 100/100 result proves
those branches never reach GitHub as stacked PRs.

Also refuse `gh skill install github/gh-stack` — a standing skill whose documented workflow contradicts
clause 1, taxed on the preamble forever.

## Industry standard

| Point | Source |
|---|---|
| Stacked PRs are mainstream for large-team review throughput (Graphite, spr, git-town, Sapling) | github.com/github/gh-stack |
| Vendors are retiring implicit-permission flags in favor of one explicit sandbox axis | codex-cli 0.145.0 binary strings |
| Agent harnesses are converging on OS-native sandboxing for tool execution | code.claude.com/docs sandboxing |
| Context engineering guidance: diverse-not-exhaustive examples; a tool description a human can't disambiguate, an agent can't either | Anthropic, *Effective context engineering for AI agents* (2025-09-29) |

## Elevation

- Treat any flag that *implies* a permission level as a defect surface — declare the axis explicitly and
  let the banner print what the process actually got, not what was requested.
- A worktree is **not** an isolation boundary: linked worktrees share `.git/hooks`, `.git/config`, and
  `refs/stash` with the parent (`git help worktree`, git 2.51.2 — only `refs/bisect`, `refs/worktree`,
  `refs/rewritten` are excepted). A lane's postinstall writes into the *common* `.git`.
- Compression proxies in front of tool output target the right cost (~76% of accumulated context) but
  must be measured in CLI/library mode — registering one as an MCP server adds to the very preamble it
  exists to shrink.

## Tips & gotchas

- **Sanity-control every binary probe.** `readlink -f $(which codex)` → asdf shim → node wrapper → the
  real Mach-O is under `node_modules/@openai/codex-darwin-arm64/vendor/<triple>/bin/codex`. Three layers.
  Without a known-present control string, all three read as "feature absent."
- **GitHub code search missed `--full-auto`** despite it being in the pinned-tag source. Zero hits is not
  absence.
- `gh skill publish --dry-run` cannot lint this repo — it discovers `skills/*/SKILL.md`, not
  `.claude/skills/<name>/SKILL.md`, and has no `--allow-hidden-dirs`. Verified: exit 1, "no skills found."
  (`gh skill list` does work.)
- `network.strictAllowlist` in a repo's `settings.local.json` **has no effect** — user/managed settings
  or `--settings` only.
- Codex hit **100% of its weekly cap** (until 2026-08-09 02:31). Third data point that Plus is binding.

## Recommendations for THIS harness

1. **Delete ` --full-auto` at all 12 sites.** One token each. Direction B sites are the sharpest — they
   fail closed for an invisible reason.
2. **`brew upgrade gh`** 2.96.0 → 2.97.0 — 4 CVEs, two in commands in constant use
   (`gh api` escape-sequence injection, `gh auth status` token leak).
3. **Delete `CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING` from settings** — confirmed no-op under direct-API
   binding; Fable 5 / Sonnet 5 / Opus 4.7+ always use adaptive reasoning. Inherited cruft.
4. **Add the worktree-isolation caveat** to global `CLAUDE.md` §Agent Dispatch. Repo-agnostic.
5. **Zero model-pin edits.** All 12 agent pins and all four aliases confirmed current
   (`opus→claude-opus-5`, `sonnet→claude-sonnet-5`, `haiku→claude-haiku-4-5`, `fable→claude-fable-5`),
   read from the installed binary's own resolution table. `gpt-5.6-sol` current, no successor.
6. **Add no plugin, MCP server, or skill this round.** Every candidate failed to justify preamble cost.
7. **Defer the `sandbox.*` block** to its own change with a bake window — `enabled` is the master switch
   the survey omitted, `credentials` is an object not a boolean, and `strictAllowlist` hard-denies rather
   than prompts, so breakage shows up as silence.

## What to research next

- Does `--full-auto` also reset `sandbox_workspace_write.network_access`? (blocked on Codex quota)
- Does Anthropic's models/overview actually rank Fable 5 above Opus 5? Would resolve the standing
  UNMEASURED clause in global `CLAUDE.md`.
- Does cynap's merge friction actually recur? Decides whether a `gh pr merge` PreToolUse guard is earned.

## Sources

- https://github.com/github/gh-stack
- https://code.claude.com/docs/en/model-config
- https://code.claude.com/docs/en/sandboxing
- https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents (2025-09-29)
- https://github.com/cli/cli/releases/tag/v2.97.0
- Installed binaries: `claude` 2.1.220, `codex` 0.145.0 (Mach-O, strings-probed), `gh` 2.96.0, git 2.51.2
- `~/.claude/skills/codex/codex-dispatch.sh:417`; `.claude/skills/spec-{review,test-plan,test-execute}/`
