# Codex lane contract

The single owner of how this repo's skills dispatch to the second runtime. Four skills
call `codex exec` (`spec-review`, `spec-test-plan`, `spec-test-execute`, `orchestrator`);
they state only their sandbox tier and link here. Change the contract in one place.

## Why a lane needs grading, not just an exit code

A Codex lane can exit **0** having answered a different question, or having produced
nothing at all. Measured 2026-08-02/03: **18 of 52 rollouts** terminated on
`You've hit your usage limit… try again at <date>` while the process exited normally.
In the same window **20 of 52 completed with full content** — so a failing lane is not
evidence the runtime is down, and "Codex is broken" is a conclusion that needs its own
proof. An ungraded lane is counted as a reviewer that never reviewed.

## Invocation — always the wrapper, never a bare `codex`

```bash
S=/tmp/<lane>-$$; mkdir -p "$S"
cat > "$S/task.md" <<'PROMPT'
<the task; repo-relative paths are fine>
PROMPT
CODEX_NETWORK=1 CODEX_SERVICE_TIER=fast \
  ~/.claude/scripts/codex-dispatch.sh <class> "$S/task.md" "$S/task.out.md" <PROJECT_ROOT>
```

- **`codex` on `PATH` is an asdf/rbenv SHIM, and a shim is not a runtime.** It resolves node
  through `$HOME` and the nearest `.tool-versions`, so it exits **rc=126/127** from any
  directory pinning a version that lacks the CLI — a whole lane wave dies at once with empty
  outfiles and no error in the artifact. The wrapper resolves the real `node` + `codex.js`
  directly. This is the single reason the invocation is not a bare `codex exec`.
- **`<class>`** picks the model through `codex-headroom.sh`, which is also the capacity gate:
  `frontier` → astra (the final-gate judgment) · `falsifier|verify|judge|security` → sol ·
  `review|research|synthesis` → terra · `mining|census|trivial` → luna. Never hardcode a model;
  never invent a class to get a better one — the class IS the model decision.
- **The cap level decides dispatch-or-refuse, and nothing else** (2026-09-06). Every class answers
  its ideal model at every level below 99%; at 99% the gate refuses outright and the caller routes
  to Claude. There is no middle band: the gate used to degrade a tier or two as the window filled,
  which meant `review`/`research` silently became `luna` above 90% used — output a review lane
  cannot act on, arriving with a healthy-looking verdict. What guards the window instead is the
  refuse threshold plus the **fan-out cap of 5** (8 concurrent dispatches once took a window from
  24% to 100% in under eight minutes — the shape that saturates a cap is lane COUNT, not per-lane
  model choice). Pace is still measured and logged in `analytics/codex-dispatch.jsonl`; it no
  longer routes.
- **The repo is READ-ONLY to the lane.** Measured on codex 0.153.4: with cwd in a scratch dir
  the lane reads any path and runs git in the repo, while a write there returns `Operation not
  permitted`. Writes go to its scratch dir. Do **not** "fix" a path problem by pointing `-C` at
  the repo — under `workspace-write` the working root *is* the writable root.
- **Repo-relative paths resolve.** The wrapper prepends a `REPO:` header with the absolute root
  and symlinks it as `repo`. Without that the lane sits in an empty temp dir and reports it
  cannot see the repo (2026-09-06: two lanes died exactly this way).
- **Prompt via a heredoc FILE**, never an inline quoted argument — escaping breaks and the lane
  receives a mangled task. The wrapper handles stdin and `-o` itself.
- **`CODEX_NETWORK=1`** for a lane that must reach the web (CVEs, RFCs, vendor docs); omit it
  otherwise. **`CODEX_SERVICE_TIER=fast`** for a lane a caller is actively waiting on.
- **Read a *slice* of the outfile** afterward. Never let a lane's full output land in the
  caller's context. The lane log is preserved at `<outfile>.log` — that is the grading input.
- Launch with the Bash tool's `run_in_background: true`. **No trailing `&` and no `nohup`** —
  the harness reaps the process group and the lane dies with its EXIT trap unfired.
- `--ignore-rules` (passed by the wrapper) stops the lane spending its run loading instruction
  files. *It is not an authentication fix* — a 401 from a globally-configured MCP server in the
  Codex config is independent of it, and no flag makes a quota wall go away.
- **One raw exception: `codex exec resume --last`.** The wrapper always opens a fresh thread, so
  a follow-up/debate turn calls the CLI directly — and must export
  `CODEX_HOME="$HOME/.codex-lean"`, because that is the profile the lane ran under. Resuming
  from the default profile finds the wrong thread or none, which reads as a silent concession.

## Grading — run this before counting the lane

```bash
wc -l <outfile>
grep -ciE "hit your usage limit|try again at" <outfile>.log     # the wrapper's preserved log
grep -ciE 'severity|critical|high|medium' <outfile>      # for a review lane
grep -ciE "hit your usage limit|try again at" <outfile>  # quota wall
```

Classify into one of three states — **`BLOCKED-ON-QUOTA` is distinct from failed**, and
conflating them produces the wrong next action:

| State | Signal | Next action |
|---|---|---|
| **DEAD** | under ~50 lines, or zero severity hits on a review lane, or the outfile is the prompt echoed back | Substitute the lane (a Claude reviewer) and say so in the report |
| **BLOCKED-ON-QUOTA** | the usage-limit string; parse the reset date out of it | Do **not** retry. Record the reset time, check it **once**, then batch-redispatch every lane blocked by the same wall |
| **REAL** | substantive content that answers the question asked | Count it |

**A lane that returns in under 60 seconds is dead by definition** — a spec review cannot
complete that fast. Check wall-clock before content.

On a shared-cause mass failure (N lanes dying together on one limit), check the reset
condition **once** and re-dispatch as a batch. Never per-lane, never blind — that is the
blind-retry loop the standing rules already forbid.

## What this contract does NOT claim

Codex is a **separate billing pool**, not an unlimited one, and it has its own weekly
window. Under-use leaves capacity on the table; assuming infinite capacity produces the
mass-death cluster above. Offload only work that is self-contained (needs no conversation
history), delivers a **document**, and is read-only or confined to one worktree. Anything
needing harness state — session ids, chips, the worktree registry, MCP servers — stays on
the primary runtime, because a Codex lane starts cold.
