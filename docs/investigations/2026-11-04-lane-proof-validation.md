# Lane proof validation — 2026-11-04

Implemented ranks 1 and 4 and section 4 of `2026-11-04-karpathy-graph-engineering.md`.

`--proof <command> <args...>` consumes the remaining argv; launcher options precede it.
The launcher executes argv directly in the resolved lane worktree after the runtime exits,
including unsuccessful runtime exits. No reset or worktree removal occurs. Proof exit 0
passes, 75 records `deferred` and returns 75, and other proof failures return 4.
Receipts append under flock to `lane-proofs.jsonl` beside `lane-parents.jsonl`, independent
of whether the optional parent session or ticket was supplied. Receipt failure is fatal.
The own-files advisory compares named argv file paths with the committed lane diff;
it cannot discover tests or dependencies imported indirectly by the named command.
Heavy proof argv must use the project's heavy-lock wrapper. The proof inherits the
headless-lane marker, and a deferred result never counts as a failure or clears failures.

`PROOF_FAILED` is advisory after three failures on a ticket since its last pass, including
in the state page's `--context` brief. Only a pass clears the counter.

Claude `--help` was run: it lists `--max-budget-usd` but hides `--max-turns`.
The installed CLI registers `--max-turns <turns>` with `hideHelp()` and describes it as
an early exit after the specified number of agentic turns in print mode. No real lane
was used to probe it. Both cap options pass through on Claude; Codex refuses them with
exit 2 rather than silently ignoring them.

## Tests

Every `test_*.py` in the sessions-to-chips scripts directory was run as its own Python
process with `RENDER_STATE_NO_OPEN=1`. Twelve of fourteen files passed. Two files each
had one environment failure:

- `test_spawn_lane_runtime.py`: `test_both_runtimes_record_a_full_lane_row` requires a
  nonempty real `ps` start time.
- `test_work_state.py`: `test_offset_reader_ignores_legacy_rows` requires the same.

The sandbox rejects `ps -o pid= -p $$` with `operation not permitted: ps`. Loading
`work_state_store.py` from the original HEAD and calling `pid_start(os.getpid())`
also returned `''`. These two tests remain unverified in an environment permitting `ps`.
One existing rendering test was skipped. An initial single-process unittest discovery
run additionally suffered cross-module test-environment pollution; isolated file runs
are the authoritative full-suite results.

After final changes, targeted reruns passed:

- `test_lane_proof.py`: 11 tests, mocked Claude and Codex. Covers pass, fail, deferred,
  absent proof, nonimplementation proof, own worktree, retained salvage, own-file
  advisory, runtime failure receipts, and Claude cap argv / Codex refusal. Mutation
  controls cover omitted proof, false success, false deferred pass, missing own-file
  flag, and a pass not clearing the counter.
- `test_state_story.py`: 16 tests, including actual `--context` output after three
  failed rows and after a passing row.
- `test_work_state.py ProofFlagTests`: 2 tests, including a mutated threshold.
- The separate requested `python3 ~/.claude/scripts/test_spawn_lane.py`: 13 tests passed.
- `bash -n bin/spawn-lane.sh` and `git diff --check` passed.

No heavy command, real lane, push, PR, or remote mutation was run. Live-runtime proof
execution is intentionally unproven. These are invocation-time skill/script changes;
existing callers that supply none of the new options retain their launch behavior.
