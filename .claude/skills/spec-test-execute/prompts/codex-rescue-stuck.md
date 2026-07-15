# Codex Rescue for Stuck Tests

When a test has failed 2+ times with the same error and the Claude diagnostician couldn't fix it, delegate to Codex for a fresh perspective with write access.

**Execution:** Bash only, managed `codex-dispatch task` primary with raw `codex exec` fallback. **NEVER use the Skill tool** (`disable-model-invocation: true`).

## Why managed `task` dispatch (not `review`) is correct here

Unlike `review` and `adversarial-review` — which feed Codex `git status && git diff` and are wrong for file reviews — managed `task` dispatch takes a task prompt with write-mode sandbox access. That matches what fixing a failing test needs: read the test, read the error, modify the implementation or the test, rerun, verify.

The anti-pattern to avoid: using `review` to "review the failing test" — that would review the git diff, not the test's actual failure. Use `task` here, not `review`.

## When to dispatch

- Test has failed 2 consecutive times with the same root cause
- Claude failure-diagnostician categorized it as `implementation-wrong` but the fix didn't work
- OR diagnostician returned `low` confidence
- OR the same error signature has appeared 3× (the auto-BLOCK threshold from SKILL.md rule 7)

## Primary: managed dispatcher task

```bash
TASK_TAG="rescue-{{TEST_ID}}-$$"
cd <PROJECT_ROOT> && codex-dispatch task --network on --fast -- \
  "$(cat <<'PROMPT'
Fix the failing test {{TEST_ID}} in {{FILE}}.

<task>
Test {{TEST_ID}} has failed {{FAIL_COUNT}} times. Previous fix attempts haven't worked.

Error output:
{{ERROR_OUTPUT}}

Previous diagnosis: {{DIAGNOSIS_SUMMARY}}
Previous fix attempted: {{FIX_ATTEMPTED}}

The spec requirement this test covers (from {{SPEC_PATH}}, section {{SPEC_SECTION}}):
{{SPEC_REQUIREMENT}}

Fix the root cause — either in the test or in the implementation. Run the test after fixing to verify.
</task>

<verification_loop>
After applying the fix, run the test command and verify it passes.
If it still fails, investigate deeper — don't just retry the same approach.
</verification_loop>

<action_safety>
Only modify files directly related to this test failure.
Do not refactor surrounding code or fix unrelated issues.
Do not weaken assertions. Do not delete the test. Do not mock the dependency that's the actual subject of the test.
</action_safety>
PROMPT
)" > /tmp/codex-${TASK_TAG}.txt 2>&1
```

**Dispatch via Bash tool with `run_in_background: true`** — rescue runs can take 10+ min, foreground Bash times out at 10 min max.

## Budget + checkpoint

- **20 min hard budget** (rescue writes files, longer than reads)
- **T+15 min**: check if rescue is still running AND has produced useful output:
  ```bash
  ps -ef | grep "codex-dispatch task.*{{TEST_ID}}" | grep -v grep
  tail -50 /tmp/codex-${TASK_TAG}.txt
  ```
- If the process is hung (no tail growth over 2 consecutive checks), cancel it, run the dispatcher's `reconcile` command, and use the fallback below
- If the rescue finishes with a clear success/failure verdict, record and proceed

## Fallback: raw `codex exec` with `danger-full-access`

If the managed dispatcher crashes before Codex starts, dispatch directly via `codex exec`:

```bash
TASK_TAG="rescue-fallback-{{TEST_ID}}-$$"
cd <PROJECT_ROOT> && echo '' | codex exec --skip-git-repo-check \
  -m gpt-5.6-sol \
  --config model_reasoning_effort="high" \
  --config service_tier="fast" \
  --sandbox danger-full-access \
  --full-auto \
  "$(cat <<'PROMPT'
<task>
Fix failing test {{TEST_ID}} in {{FILE}}.

Error:
{{ERROR_OUTPUT}}

Spec: {{SPEC_PATH}} section {{SPEC_SECTION}}
Requirement: {{SPEC_REQUIREMENT}}

Claude diagnostician tried: {{DIAGNOSIS_SUMMARY}}
Claude fix attempted: {{FIX_ATTEMPTED}}

Fix the root cause — either the test or the implementation. Do NOT weaken assertions. Do NOT delete the test. Do NOT mock the dependency the test is verifying.
</task>

<action_safety>
Only modify files directly related to this test failure.
No unrelated refactors, renames, or reformats.
</action_safety>

<verification_loop>
After each fix attempt, run the test command and check the result.
If it still fails, investigate deeper — don't retry the same approach.
Max 3 fix attempts before marking blocked.
</verification_loop>

<output_contract>
Emit progress at these checkpoints using this exact envelope:
===CODEX_RESCUE_STATUS===
{"phase": "diagnosis" | "fix-applied" | "test-passed" | "test-failed" | "blocked", "summary": "...", "files_modified": ["..."], "next_action": "..."}
===CODEX_RESCUE_END===

Emit one status block on initial diagnosis, one per fix attempt, and one final block with phase "test-passed" or "blocked".
</output_contract>
PROMPT
)" 2>&1 | tee /tmp/codex-${TASK_TAG}.txt
```

**Key differences from file-review dispatches:**
- `--sandbox danger-full-access` — Codex needs to modify files and may need dependency/network setup
- Progress marker is `CODEX_RESCUE_STATUS` (not `CODEX_FINDINGS_BEGIN`) — rescue emits multiple status blocks as it iterates
- 20-min budget, not 15

Coordinator can grep for the latest status:
```bash
grep -A 3 CODEX_RESCUE_STATUS /tmp/codex-${TASK_TAG}.txt | tail -20
```

## Output handling

Codex rescue concludes in one of three ways:

1. **Test passes** → phase `test-passed`. Mark test FIXED in the plan, note "fixed by Codex rescue".
2. **Identified deeper issue, couldn't fix in budget** → phase `blocked`. Escalate to BLOCKED with Codex's analysis in the diagnostics.
3. **Failed to fix** (max attempts reached, or both primary + fallback crashed) → mark BLOCKED with both Claude and Codex diagnoses for human review.

If the rescue modifies files but doesn't verify the test passes, treat it as partial and re-run the test yourself as the coordinator before marking FIXED. Never trust a rescue's self-report without independent verification.
