# Codex Standard Review (file-review mode)

Reviews a SPEC FILE for completeness, correctness, and feasibility. Dispatch through `codex-dispatch.sh` (below), never `companion review` — that reviews git diffs, not files.

## How to dispatch

Use Bash with `run_in_background: true` (no trailing `&`). You'll be notified when it completes.

```bash
S=/tmp/spec-review-$$; mkdir -p "$S"
cat > "$S/codex-spec-std.md" <<'PROMPT'
Review the spec file at <RELATIVE_SPEC_PATH> for completeness, correctness, and feasibility. Check types, defaults, flows, edge cases, failure modes, migrations, rollback paths, integration points, stale code, and scope realism. If docs/PLATFORM-INVARIANTS.md exists, check compliance. You have web access — if the spec cites an API, library, or standard, verify it against the authoritative source and cite the URL. Also verify the vendor/framework semantics beneath any behavior the spec assumes it inherits for free (framework default matchers and exclusions, env allowlist scrubbing across process forks, API response fields the server generates versus accepts, name-reservation windows on delete). For each issue found, state: severity, which spec section, the problem, and a fix. Material issues only.
PROMPT
CODEX_NETWORK=1 CODEX_SERVICE_TIER=fast \
  ~/.claude/scripts/codex-dispatch.sh verify "$S/codex-spec-std.md" "$S/codex-spec-std.out.md" <PROJECT_ROOT>
```

**Why the wrapper and never a raw `codex exec`.** It resolves the REAL node + `codex.js` instead of
the `codex` PATH shim — a shim resolves its runtime through `$HOME`/`.tool-versions` and exits
rc=126/127 from any directory pinning a different node, which is how a whole lane wave dies at once
with nothing in the outfile. It also strips ~30% of the billed input, asks `codex-headroom.sh` for
the model (class **`verify`** here), mounts `<PROJECT_ROOT>` **read-only** — reads and git work, the
sandbox denies writes — grants shell network for the web cross-referencing, and preserves the lane
log at `"$S/codex-spec-std.out.md.log"` so a dead lane can be graded. The prompt goes in via a heredoc file,
never as an inline quoted argument.

## Rules

- `run_in_background: true` on the Bash tool — you get notified when Codex finishes. **Do NOT add `&` to the command** — that makes the Bash tool return immediately and you lose the notification.
- `--sandbox workspace-write` + `sandbox_workspace_write.network_access=true` + fast service tier — shell network is available so Codex can verify API/library/standard references against primary sources. Relative spec path.
- **No JSON templates, no output format examples, no markers in the prompt.** Codex echoes the prompt — any template becomes fake output.

## Reading results

When you get the background completion notification, read `/tmp/codex-spec-std-*.txt` with the Read tool. Parse whatever Codex produced. No grep, no sed. You're an LLM — just read it.

**Leaf-agent scope:** you are a leaf agent — do NOT spawn sub-agents or Workflows; do the work inline and return.
