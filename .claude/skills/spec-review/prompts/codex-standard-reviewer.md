# Codex Standard Review (file-review mode)

Reviews a SPEC FILE for completeness, correctness, and feasibility. Always use raw `codex exec`, never `companion review` (that reviews git diffs, not files).

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
  "Review the spec file at <RELATIVE_SPEC_PATH> for completeness, correctness, and feasibility. Check types, defaults, flows, edge cases, failure modes, migrations, rollback paths, integration points, stale code, and scope realism. If docs/PLATFORM-INVARIANTS.md exists, check compliance. You have web access — if the spec cites an API, library, or standard, verify it against the authoritative source and cite the URL. For each issue found, state: severity, which spec section, the problem, and a fix. Material issues only." \
  2>&1 | tee /tmp/codex-spec-std-$$.txt
```

## Rules

- `echo '' |` — prevents stdin hang
- `run_in_background: true` on the Bash tool — you get notified when Codex finishes. **Do NOT add `&` to the command** — that makes the Bash tool return immediately and you lose the notification.
- `2>&1 | tee FILE` — captures output to file AND stdout
- `--sandbox workspace-write` + `sandbox_workspace_write.network_access=true` + fast service tier — shell network is available so Codex can verify API/library/standard references against primary sources. Relative spec path.
- **No JSON templates, no output format examples, no markers in the prompt.** Codex echoes the prompt — any template becomes fake output.

## Reading results

When you get the background completion notification, read `/tmp/codex-spec-std-*.txt` with the Read tool. Parse whatever Codex produced. No grep, no sed. You're an LLM — just read it.

**Leaf-agent scope:** you are a leaf agent — do NOT spawn sub-agents or Workflows; do the work inline and return.
