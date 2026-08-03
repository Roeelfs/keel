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

## Invocation

```bash
codex exec --skip-git-repo-check --ignore-rules \
  -m gpt-5.6-sol -c model_reasoning_effort=high \
  -s <sandbox-tier> -o <outfile> - < <promptfile>
```

- **Prompt via stdin from a FILE** (`- < <promptfile>`). Passing it as an inline quoted
  argument is a known failure mode — escaping breaks and the lane receives a mangled task.
- **`--ignore-rules`** stops the lane spending its run loading instruction files.
  *It is not an authentication fix* — a 401 from a globally-configured MCP server in the
  Codex config is independent of it, and no flag makes a quota wall go away.
- **`-o <outfile>`**, and read a **slice** of the outfile afterward. Never let the lane's
  full output land in the caller's context.
- Launch with the Bash tool's `run_in_background: true`. No trailing `&`.
- Sandbox tier is the caller's choice: `read-only` for review/research, wider only when
  the lane must write, and only inside a worktree it owns.

## Grading — run this before counting the lane

```bash
wc -l <outfile>
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
