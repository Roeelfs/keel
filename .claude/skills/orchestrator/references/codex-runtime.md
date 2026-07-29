# Codex CLI runtime variance

This skill is symlinked into both `~/.claude/skills/` and `~/.codex/skills/`. Detect the host runtime first:

- **Claude Code** — `$CLAUDE_SESSION_ID` is set; the `Skill`, `Agent`, `Workflow`, `ScheduleWakeup`, `Monitor`, and `AskUserQuestion` tools and the `/loop` command exist.
- **Codex CLI** — none of the above. Sessions live at `~/.codex/sessions/<YYYY>/<MM>/<DD>/*.jsonl`; subagents come from `spawn_agent`; there is no harness-managed loop.

When hosted by Codex, the following replace the CORE's verbs. Everything else in the CORE — program files, membership, collision protocol, lane grading, pre-flight verification — applies unchanged.

- **State mining** — `claude-sessions` is unregistered as a Skill **but its script is still callable**. Run BOTH miners every turn and union them in the state-miner prompt:
  `python3 ~/.claude/skills/claude-sessions/sessions.py survey --filter <project> --json`
  `python3 ~/.claude/skills/codex-sessions/scripts/sessions.py survey --filter <project> --days 2 --json`
  A program routinely splits across runtimes (spec authored in Codex, reviewed in Claude). Skipping the Claude pool because "I'm in Codex" was a real audit miss.
- **Subagent dispatch** — no `Agent`/`Skill` tools. Use `spawn_agent` for the miner role and prose-instruct workers; you cannot dispatch `/spec-review`, `/spec-test-execute` etc. as skills — paste their canonical guidance into the worker prompt. Verify a cheap Codex tier exists before pinning one; the flagship id is `gpt-5.6-sol`.
- **Continuation** — no `ScheduleWakeup`, no `/loop`. Use the single-paste self-paced directive in `prompts/loop-directive.md` §Codex variant, with explicit stop conditions embedded in the initial prompt. A silent worker is re-triggered by a new `codex exec`, never by a loop.
- **Human surfacing** — no `AskUserQuestion`/`PushNotification`. Contested claims and pre-authorization asks go in the reply text as an explicit numbered decision, and the turn ends there.
- **Sandbox writes** — Codex defaults to `sandbox_mode = "workspace-write"`, which silently blocks writes to sibling worktrees and `~/.codex`. Run with `--add-dir <lane-worktree>` per lane, or set `danger-full-access` in `~/.codex/config.toml`. Otherwise workers fall back to `/tmp` and the work vanishes.
- **Worktree placement** — workers cannot write to sibling paths outside the sandbox root, so lane prompts MUST use the nested pattern `<repo>/<lane>-impl/`. In a past audit every sibling-path lane bounced through `/tmp`; every nested one stayed clean.
- **Session-Id trailer** — `$CLAUDE_SESSION_ID` does not exist. Skip the trailer, or install a `prepare-commit-msg` hook that recovers the SID by matching the lane's cwd against the first record's `payload.cwd` in `~/.codex/sessions/<YYYY>/<MM>/<DD>/rollout-*.jsonl`. Never paste the Claude-only heredoc warning blindly.
- **PURPOSE hints** — no `sessions.py list` derivation. The spawning prompt itself declares `NAME: <name>` and `PURPOSE: <one-liner>` on its first lines so the next miner pass recovers them.
- **Spawning a Codex lane** — use `prompts/codex-lane-template.md` as the single-paste mission; it carries the nested-worktree, no-`/tmp`, and orchestrator-owns-the-merge constraints inline.
- **Compact survivability** — no `/compact` command and no SessionStart hook. Write `<slug>.state.md` after every significant routing decision, and re-read it before the next routing claim whenever a context-summary banner appears.
