# Codex lane prompt — template

Single-paste prompt for spawning a Codex CLI lane session. Applies the discipline from `references/codex-runtime.md` (Codex variance) and `references/merge-and-retire.md` (merge gate) — branch protection + orchestrator-owned merge + no `/tmp/` source-of-truth.

Replace the `<...>` placeholders before pasting.

---

```
NAME: <lane-name>
PURPOSE: <one-line goal — "ship X spec", "implement Y", etc>

cwd: <repo>/<lane-name>-impl/      # NESTED inside the workspace, NOT sibling under ~/code/
                                   # Sibling paths fall outside the Codex sandbox writable root
                                   # and force fallback to /private/tmp/ which loses work.

Setup:
  cd <repo> && git worktree add <lane-name>-impl -b <branch-name> origin/main

Goal: <2-3 sentences describing scope — read spec at docs/specs/<X>.md first>

Hard constraints:
  - DO NOT run `gh pr merge`. The orchestrator owns the merge gate.
    After `git push`, run `gh pr checks <N>` and quote the statusCheckRollup back to the operator.
  - If dependency setup is needed and the lane hits DNS/registry isolation under `workspace-write`,
    run the dependency step through whatever network-enabled dispatch path your harness provides
    (a Codex dispatcher with network on, or `--add-dir`/`danger-full-access` per your config).
    Registry/DNS isolation is an environment constraint, not a reason to abandon the task.
  - DO NOT use /tmp/ or /private/tmp/ for any source-of-truth files. Patches, drafts, work-in-progress
    all live in the lane worktree (<repo>/<lane-name>-impl/).
  - DO NOT touch paths owned by other lanes — see DO-NOT-TOUCH list below.
  - Before spawning reviewers, declare a finite review protocol and stop condition. Run one broad
    primary wave, consolidate and falsify material findings once, then run one narrow closure pass
    over changed seams. Named finite skill stages are allowed; never repeat a completed broad stage.
    Another broad cycle requires explicit user authorization and a fresh task. Backlog non-blocking
    or cosmetic residue instead of keeping reviewers alive with follow-ups or interrupt/restart loops.
  - Put this block in every native Codex review activation's message. Declare all finite slots before
    the first spawn and reuse the identical protocol_id, artifact_paths, and manifest throughout:
      [review-protocol:v1]
      protocol_id=<stable task-scoped id>
      stage=primary|investigator|falsifier|security|closure
      artifact_paths=<comma-separated explicit files relative to cwd>
      manifest=primary:<slot>,falsifier:<slot>,closure:<slot>
      manifest_slot=<unique slot launched by this call>

DO-NOT-TOUCH:
  - <other-lane-1 paths>
  - <other-lane-2 paths>

Test-spec gate (binding decision — see orchestrator skill for rubric):
  feature / multi-component / customer-facing / data-integrity → RUN both spec-test-plan AND spec-test-execute
  single-file / no-behavior-change → SKIP both
  Once decided, follow it. spec-test-execute is mandatory when gate RAN — write PASS/FAIL/SKIP/BLOCKED
  markers to the plan file before merge. test-runner passing ≠ tier marker.

Verify before push:
  Run your project's verify gate (the command your project documents — lint + typecheck/compile +
  tests + any migration/schema check). The .git/hooks/pre-push hook runs it automatically.

Commit discipline:
  - conventional commits with scope: type(scope): description
  - Session-Id trailer is auto-injected by .git/hooks/prepare-commit-msg (no manual heredoc needed)
  - DO NOT skip hooks (--no-verify) without surfacing why

Self-paced lifecycle:
  spec → review → fixes → test-spec gate → impl-plan → plan-review → implementation →
  spec-test-execute (if gate RAN) → merge gate → push branch → poll CI → REPORT TO OPERATOR (do not merge)

STOP and surface to operator only on:
  (1) input genuinely needed
  (2) hard blocker after 2 fix attempts
  (3) scope creep beyond agreed PR
  Do NOT stop for stylistic decisions or "should I commit?" — proceed with project conventions.
```

---

## What's specifically DIFFERENT from the Claude lane template

| Concern | Claude Code lane | Codex lane |
|---|---|---|
| Worktree placement | sibling `~/code/<lane>/` is fine | MUST be nested `<repo>/<lane>-impl/` |
| Continuation cadence | `/loop 10m` (harness) | self-paced, embedded stop conditions |
| Subagent dispatch | `Agent` tool → Haiku/Sonnet | `spawn_agent` on a cheap Codex tier (verify one exists; flagship is `gpt-5.6-sol`), prose-instruct workers |
| Skill invocation | `Skill` tool fires `spec-test-execute`, etc. | paste canonical guidance into worker prompt — no skill dispatch |
| Session-Id trailer | UNQUOTED heredoc with `$CLAUDE_SESSION_ID` | `prepare-commit-msg` hook recovers SID from `~/.codex/sessions/` |
| Merge action | session can self-merge after CI CLEAN | orchestrator merges (lane has unreliable CI visibility under sandbox) |
| Network access | full | a network-enabled dispatch path defaults write tasks to network-on; raw interactive `workspace-write` lanes may still lack registry/DNS access |

## When to deviate

The "lane doesn't merge" rule is firm under Codex. The "nested worktree" rule is firm under Codex (technical sandbox constraint). Other rules are scoped — adapt for the project.
