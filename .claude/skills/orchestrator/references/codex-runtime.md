# Codex CLI runtime variance

This skill is symlinked into both `~/.claude/skills/` and `~/.codex/skills/`. Detect the host runtime first:

- **Claude Code** — `$CLAUDE_SESSION_ID` is set; the `Skill`, `Agent`, `Workflow`, `ScheduleWakeup`, `Monitor`, and `AskUserQuestion` tools and the `/loop` command exist.
- **Codex CLI** — none of the above. Sessions live at `~/.codex/sessions/<YYYY>/<MM>/<DD>/*.jsonl`; subagents come from `spawn_agent`; there is no harness-managed loop.

When hosted by Codex, the following replace the CORE's verbs. Everything else in the CORE — program files, membership, collision protocol, lane grading, pre-flight verification — applies unchanged.

- **State mining** — `claude-sessions` is unregistered as a Skill **but its script is still callable**. Run BOTH miners every turn and union them in the state-miner prompt:
  `python3 ~/.claude/skills/claude-sessions/sessions.py survey --filter <project> --json`
  `python3 ~/.claude/skills/codex-sessions/scripts/sessions.py survey --filter <project> --days 2 --json`
  A program routinely splits across runtimes (spec authored in Codex, reviewed in Claude). Skipping the Claude pool because "I'm in Codex" was a real audit miss.
- **Subagent dispatch** — no `Agent`/`Skill` tools. Use `spawn_agent` only for an allowed bounded role and give it the compact phase contract, exact artifact paths, and selected evidence slice. Do not paste whole skill files or accumulated history. Luna-low is the native default for mining, file search, and deterministic procedure; explicitly select Terra-medium for implementation, topical review, and diagnosis. Sol is a bounded named security/irreversible/trust-boundary escalation.
- **Procedural worker** — when a fixed command group would require process continuation, retain large output, or run the full gate, use one fresh Luna-low child for that targeted/correction pass. Call `spawn_agent` with `fork_turns: "none"`, `model: "gpt-5.6-luna"`, and `reasoning_effort: "low"`; use `prompts/procedural-worker.md` as the result/lease contract. At most one is active per worktree. Start with one realistically sized `wait_agent`; re-wait only after consuming a distinct unrelated mailbox update, never to poll unchanged target state. The root never calls `write_stdin` on the child's process. The child owns exec continuation and returns one validated pointer artifact.
- **Shared cwd** — native children have no cwd parameter, so the mission names an absolute cwd and pinned SHA. Read-only commands may use a shared cwd while the root leaves it unchanged. Receipt/cache writes require a clean isolated worktree, an exclusive pass lease, exact `allowed_write_paths`, and before/after tracked-content hashes. Any unexpected tracked-path delta blocks acceptance.
- **Boundary** — the root keeps small bounded read-only probes, judgment, edits, auth/target selection, and all production mutations. Source-mutating format/install/migration commands stay in build. A procedural worker never diagnoses, retries an unchanged failure, asks the user, or selects/mutates production.
- **`wait_agent` polling — poll at the work's latency, not below it.** The minimum accepted is
  `timeout_ms: 10000` (a smaller value is rejected outright: `"timeout_ms must be at least 10000"`),
  but the minimum is not the right value. For web-research-backed or falsifier fan-outs, poll at
  **`timeout_ms: 60000` or higher**. Measured 2026-08-02 across the local rollouts: **24 of 37
  `wait_agent` calls timed out (65% dead round-trips)** at 20,000–30,000 ms, worst case **14
  identical polls in one session**. Each dead poll is a full turn that reads the whole context
  again, so under-polling costs far more than waiting.
- **Continuation** — no `ScheduleWakeup`, no `/loop`. Use the single-paste bounded-phase directive in `prompts/loop-directive.md` §Codex variant. End after the current `define`, `build`, or `verify-release` artifact; a later fresh task resumes from branch HEAD and the proof-obligation ledger.
- **Human surfacing** — no `AskUserQuestion`/`PushNotification`. Contested claims and pre-authorization asks go in the reply text as an explicit numbered decision, and the turn ends there.
- **Sandbox writes** — Codex defaults to `sandbox_mode = "workspace-write"`, which silently blocks writes to sibling worktrees and `~/.codex`. Run with `--add-dir <lane-worktree>` per lane, or set `danger-full-access` in `~/.codex/config.toml`. Otherwise workers fall back to `/tmp` and the work vanishes.
- **Worktree placement** — workers cannot write to sibling paths outside the sandbox root, so lane prompts MUST use the nested pattern `<repo>/<lane>-impl/`. In a past audit every sibling-path lane bounced through `/tmp`; every nested one stayed clean.
- **Session-Id trailer** — `$CLAUDE_SESSION_ID` does not exist. Skip the trailer, or install a `prepare-commit-msg` hook that recovers the SID by matching the lane's cwd against the first record's `payload.cwd` in `~/.codex/sessions/<YYYY>/<MM>/<DD>/rollout-*.jsonl`. Never paste the Claude-only heredoc warning blindly.
- **PURPOSE hints** — no `sessions.py list` derivation. The spawning prompt itself declares `NAME: <name>` and `PURPOSE: <one-liner>` on its first lines so the next miner pass recovers them.
- **Spawning a Codex lane** — use `prompts/codex-lane-template.md` as the single-paste mission; it carries the nested-worktree, no-`/tmp`, and orchestrator-owns-the-merge constraints inline.
- **Compact survivability** — no `/compact` command and no SessionStart hook. Write `<slug>.state.md` after every significant routing decision, and re-read it before the next routing claim whenever a context-summary banner appears.
