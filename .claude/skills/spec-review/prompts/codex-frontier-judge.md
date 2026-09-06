# Codex Frontier Judgment (Astra — file-review mode)

The HIGHER judgment rung, run on EVERY spec review beside the sol lanes (never instead of them; founder directive 2026-09-06). Sol attacks and verifies; Astra rules. One lane per review — its cost against the weekly Codex cap is unpublished, so it is never fanned out.

## How to dispatch

Use Bash with `run_in_background: true` (no trailing `&`). You'll be notified when it completes. Ask the gate for the model first — it answers `gpt-6-astra` for class `frontier` and `CLAUDE` only at the refuse threshold (then substitute one Fable-pinned `critic`, and say so in the report):

```bash
MODEL=$(~/.claude/scripts/codex-headroom.sh --model frontier)
cd <PROJECT_ROOT> && echo '' | codex exec --skip-git-repo-check \
  -m "$MODEL" \
  --config model_reasoning_effort="high" \
  --config service_tier="fast" \
  --sandbox workspace-write \
  --config sandbox_workspace_write.network_access=true \
  "Frontier judgment of the spec at <RELATIVE_SPEC_PATH>. You are the final reviewer, not another defect hunter: rule on whether this is the RIGHT thing to build and whether the design is sound. Read the spec, its cited ADRs and invariants, and the code it touches. Deliver: (1) the one decision in this spec most likely to be wrong, with the evidence from the codebase that makes you think so; (2) the three highest-leverage risks the specialist lanes are likely to miss because each is scoped narrowly — cross-cutting, second-order, or economic; (3) what a best-in-class team would do differently, concretely, for THIS codebase; (4) a verdict: approve / approve-with-changes / redesign, with the changes named. Every claim cites file:line or a URL. Concerns to weigh: <FOCUS TEXT>." \
  2>&1 | tee /tmp/codex-spec-frontier-$$.txt
```

## Rules

- `echo '' |` — prevents stdin hang; `run_in_background: true` — **no trailing `&`**; `2>&1 | tee FILE` — captures output.
- Never `model_reasoning_effort="ultra"` — on astra that is *task delegation*, not a quality dial.
- Same sandbox + network flags as the other Codex lanes; relative spec path.
- **No JSON templates, no output format examples, no markers in the prompt.**
- Grade this lane by its ARTIFACT before counting it (`docs/codex-lane-contract.md`): a file ending in a usage-limit/auth error is DEAD → the Fable `critic` substitute, reported as `timed-out/usage-limit — backfilled by critic (fable)`.

## Reading results

Read the output file with the Read tool. The verdict line feeds `### Codex Frontier (Astra) Verdict:`; its (1)–(3) enter Step 5 classification like any reviewer's findings and are cross-examined in Step 5b when they disagree with the Claude lanes.

## Focus text

The coordinator adds the same 3-6 concerns given to the adversarial lane, plus the spec's stated non-goals (Astra is asked whether they are the right non-goals).

**Leaf-agent scope:** you are a leaf agent — do NOT spawn sub-agents or Workflows; do the work inline and return.
