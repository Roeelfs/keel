# Codex Adversarial Review (file-review mode)

Adversarial review of a SPEC FILE. Always use raw `codex exec`, never `companion adversarial-review` (that reviews git diffs, not files).

## How to dispatch

Use Bash with `run_in_background: true` (no trailing `&`). You'll be notified when it completes.

```bash
cd <PROJECT_ROOT> && echo '' | codex exec --skip-git-repo-check \
  -m gpt-5.5 \
  --config model_reasoning_effort="high" \
  --config service_tier="fast" \
  --sandbox workspace-write \
  --config sandbox_workspace_write.network_access=true \
  --full-auto \
  "Adversarial review of the spec at <RELATIVE_SPEC_PATH>. Find material risks: attack surface, data safety, rollback hazards, race conditions, degraded dependencies, observability gaps, architectural fit, over-engineering. If docs/PLATFORM-INVARIANTS.md exists, check compliance. You have web access — when relevant, verify risk hypotheses against published CVEs, incident post-mortems, or RFC constraints and cite the URL. <FOCUS_TEXT_FROM_COORDINATOR> For each issue: severity, spec section, the problem, a concrete failure scenario, and a fix. No style feedback." \
  2>&1 | tee /tmp/codex-spec-adv-$$.txt
```

## Rules

- `echo '' |` — prevents stdin hang
- `run_in_background: true` on the Bash tool — **no trailing `&`**
- `2>&1 | tee FILE` — captures output
- `--sandbox workspace-write` + `sandbox_workspace_write.network_access=true` + fast service tier — shell network is available so Codex can cross-reference risk hypotheses against CVEs, post-mortems, and RFCs. Relative spec path.
- **No JSON templates, no output format examples, no markers in the prompt.**

## Reading results

When you get the background completion notification, read the output file with Read tool. Parse whatever Codex produced.

## Focus text

The coordinator adds 3-6 specific concerns from scanning the spec.
