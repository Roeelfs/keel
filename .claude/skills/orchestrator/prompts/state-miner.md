# State miner — compact cross-runtime prompt

Use a cheap mining tier to turn Claude and Codex session surveys into one project-scoped state update. The orchestrator reads the summary, not raw JSONL.

## Inputs

Provide:

1. Claude project-filtered survey JSON;
2. Codex project-filtered survey JSON;
3. previous `<program>.state.md`;
4. current branches/PRs and relevant tracker blockers;
5. manifest membership.

Process both runtime pools and only lanes owned/adopted by the program.

## Lifecycle model

The canonical lifecycle is `define → build → verify-release`.

- `define`: spec/design, review convergence, and the `checklist` / `moderate` / `critical` **proof-obligation ledger**.
- `build`: source changes, focused tests, targeted checks, changed-seam list.
- `verify-release`: finite proof execution, project gate once, PR/release/post-merge evidence.

Infer the phase from durable artifacts and branch activity:

- spec/design or test-plan creation without source edits → `define`;
- source edits and targeted test commands → `build`;
- spec-test-execute, terminal ledger statuses, project gate, PR, or keyed deployed proof → `verify-release`.

Do not infer numeric micro-steps. Do not require a no-op commit between artifacts. A material planner finding may patch the spec; absence of such a patch is normal.

## Output

```markdown
### Active lanes (N)

**<lane>** — runtime: <claude|codex|both>; phase: <define|build|verify-release>; mode: <checklist|moderate|critical|unknown>; status: <ACTIVE|WARM|IDLE>; model/effort: <actual>
- Artifact: <durable path/branch/PR>
- Ledger: <path and terminal/total count>
- Changed seam / now doing: <one line>
- Last verified fact: <SHA, command result, PR state, or deployed proof key>
- Risk: <only a real collision, blocker, repeated signature, or missing artifact>

### Cross-session
- Open PRs: <program-owned only>
- WIP: <count>
- Collisions/blockers: <facts>

### Next moves
- <3-5 artifact-anchored actions>

### State-file update
# <program> — state (run <ISO timestamp>)
| lane | phase | mode | status | head | artifact | ledger | last verified fact |
|---|---|---|---|---|---|---|---|
| <lane> | <phase> | <mode> | <status> | <sha> | <path> | <x/y terminal> | <fact> |

## AT-WAKE
1. <single next action>
Blocked on: <gate/dependency or nothing>
```

## Mining rules

- Branch HEAD and named artifacts outrank chat prose and JSONL silence.
- Skip unchanged lanes when the previous state matches their latest event; report the skip count.
- Force a fresh mine when a branch/PR/artifact contradicts the cache or the cache is older than 30 minutes.
- Preserve explicit model overrides.
- Flag a phase-spanning marathon when one task crosses `define`, `build`, and `verify-release`; recommend a fresh bounded handoff.
- Flag a non-terminal obligation without a blocker/deferred owner.
- Flag repeated review/follow-up activation without a changed artifact or final result.
- A deployed proof key is `{obligation, deploy SHA, environment, command/journey}`.

Output Markdown only, with no preamble.
