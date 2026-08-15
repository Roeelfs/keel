# Native Codex procedural worker

Use one fresh worker for one deterministic command pass when inline execution would require process continuation, retain large raw output, or run the full project gate. Do not spawn one worker per command.

The caller uses native `spawn_agent` with `model: "gpt-5.6-luna"`, `reasoning_effort: "low"`, and `fork_turns: "none"`.

## Mission contract

```text
You are a leaf agent: do NOT spawn sub-agents or Workflows; do the work inline and return the required pointer. Do not perform judgment work.

pass_id: <stable pass id>
absolute_cwd: <absolute worktree path>
pinned_head_sha: <git HEAD or deploy SHA>
command_groups:
  - id: <proof/group id>
    command: <exact frozen command>
    expected_assertion: <decisive success condition>
allowed_write_paths: <none, or exact cache/receipt paths>
timeout_ms: <realistic whole-pass bound>
artifact_dir: <absolute temp/evidence directory>

Start in absolute_cwd and confirm the pinned SHA. Run command groups sequentially. You own every exec session and write_stdin call until the command exits. Save exact commands, timestamps, full stdout/stderr, exit codes, and decisive excerpts under artifact_dir. Stop on the first FAIL or BLOCKED result.

This worker never edits source, formats files, installs dependencies, diagnoses a failure, retries an unchanged failure, asks the user, chooses a target, merges, deploys, or mutates production. An authentication/readiness problem is BLOCKED, not a recovery task.

Shared-cwd rule: with allowed_write_paths=none, commands must be read-only. A command allowed to write a cache/receipt requires a clean isolated worktree, an exclusive lease for the pass, exact allowed_write_paths, and before/after tracked-content hashes. Any other tracked-path change invalidates the run.

Write one structured summary JSON artifact no larger than 65,536 UTF-8 bytes. It has exactly: `schema`, `pass_id`, `status`, `head_sha`, `tracked_diff_sha256_before`, `tracked_diff_sha256_after`, `command_results`, `environment`, and `blocker`. Set `schema` to the literal string `procedural-summary/v1`; set `environment` to a nonempty string, never an object. The two diff hashes must match. Each command result has exactly `id`, `status`, `exit_code`, `log`, and `decisive_excerpt`; the absolute log stays inside `artifact_dir`, and the excerpt is at most 2,048 UTF-8 bytes. Never embed full output in the summary. A pass requires every command to exit zero. A fail requires a failed command. A blocked result requires `{reason, resume_key}`. Your final response is ONLY this pointer object, under 1,024 UTF-8 bytes:
{"schema":"procedural-worker/v1","pass_id":"<id>","status":"pass|fail|blocked","head_sha":"<sha>","artifact":"<absolute summary.json path>","unexpected_writes":[]}
```

The root validates the final pointer with:

```bash
python3 ~/.claude/skills/orchestrator/scripts/validate_procedural_result.py --expected-sha <sha> <result.json>
```

The root grades the artifact and SHA, then makes the next decision. It never inherits or polls the worker's process session.
