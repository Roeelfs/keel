# Codex Adversarial Review (file-review mode)

Adversarial review of a SPEC FILE. Always use raw `codex exec`, never `companion adversarial-review` (that reviews git diffs, not files).

## How to dispatch

Use Bash with `run_in_background: true` (no trailing `&`). You'll be notified when it completes.

```bash
cd <PROJECT_ROOT> && echo '' | codex exec --skip-git-repo-check \
  -m gpt-5.6-sol \
  --config model_reasoning_effort="high" \
  --config service_tier="fast" \
  --sandbox workspace-write \
  --config sandbox_workspace_write.network_access=true \
  --full-auto \
  "Adversarial review of the spec at <RELATIVE_SPEC_PATH>. Find material risks: attack surface, data safety, rollback hazards, race conditions, degraded dependencies, observability gaps, architectural fit, over-engineering. If docs/PLATFORM-INVARIANTS.md exists, check compliance. You have web access — when relevant, verify risk hypotheses against published CVEs, incident post-mortems, or RFC constraints and cite the URL. Audit the vendor semantics UNDER the spec's remedies, not just its features: for every remedy or guard that leans on a vendor/framework behavior, verify that behavior against the primary docs (deletion/recovery-window name reservation, middleware/matcher default exclusions, permission-flag child propagation, server-generated-vs-client-supplied secrets). For any guard that cross-checks a provider ECHO, ask where the echo originates — request-derived means the comparison is job===job dead code; raw means format mismatch fires 100% false. <FOCUS_TEXT_FROM_COORDINATOR> For each issue: severity, spec section, the problem, a concrete failure scenario, and a fix. No style feedback." \
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

**Leaf-agent scope:** you are a leaf agent — do NOT spawn sub-agents or Workflows; do the work inline and return.
