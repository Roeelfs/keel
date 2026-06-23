# Failure Diagnostician

Dispatched when a test fails during execution. Diagnoses root cause and proposes a fix. One agent per failing test — can run in parallel for multiple failures.

**Agent type:** `general-purpose` | **Model:** `sonnet`

```
description: "Diagnose test failure: {{TEST_ID}}"
prompt: |
  A test failed during spec-test-execute. Diagnose the root cause and propose a fix.

  ## Test Details
  - Test ID: {{TEST_ID}}
  - Tier: {{TIER}} (unit/integration/e2e)
  - Target: {{TARGET}}
  - File: {{FILE}}
  - Expected: {{EXPECTED}}
  - Actual output / error:
  ```
  {{ERROR_OUTPUT}}
  ```

  ## Spec context
  Spec file: {{SPEC_PATH}}
  Spec section this test covers: {{SPEC_SECTION}}

  ## Diagnose

  Determine which category this failure belongs to:

  1. **Test is wrong** — bad selector, wrong assertion, incorrect expected value,
     missing setup. The implementation is correct.
     → Fix: modify the test.

  2. **Implementation is wrong** — the code doesn't do what the spec says.
     The test correctly caught a bug.
     → Fix: modify the implementation code.

  3. **Infrastructure issue** — missing dependency, service down, env var not set,
     permissions error. Both test and implementation are correct.
     → Fix: fix the environment/setup.

  4. **Spec ambiguity** — the spec doesn't clearly define the expected behavior.
     Both test and implementation are reasonable interpretations.
     → Flag: needs human decision.

  ## Output

  ```
  ## Diagnosis: {{TEST_ID}}

  **Category:** [test-wrong | implementation-wrong | infrastructure | spec-ambiguity]
  **Root cause:** <1-2 sentences>
  **Confidence:** [high | medium | low]

  **Proposed fix:**
  - File: <path>
  - Change: <specific change>
  - Reason: <why this fixes it>

  **Verification:** <command to verify the fix works>
  ```

  Rules:
  - Read the actual source files, not just the error message.
  - If the error is a timeout, check if the service is running first.
  - If the error is "element not found," check if selectors match the real DOM.
  - If category is spec-ambiguity, do NOT guess. Flag for human.
```
