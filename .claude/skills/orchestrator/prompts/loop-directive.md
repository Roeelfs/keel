# Loop directive — bounded phase continuation

The canonical lifecycle is **define → build → verify-release**. A loop may continue work inside the current fresh bounded phase; it never turns one session into the whole feature lifecycle.

Every lane records one verification mode (`checklist`, `moderate`, or `critical`) and shares the **proof-obligation ledger** through branch artifacts.

## Paste 2

```text
/loop 10m Advance only the current bounded phase named in the mission: define, build, or verify-release. Before each tick, read the program state file and branch HEAD; confirm owned paths and dependencies; read the proof-obligation ledger instead of reconstructing history. The lifecycle is define → build → verify-release. Modes are checklist, moderate, critical. DEFINE ends when scope, acceptance criteria, mode, and proof obligations are durable. BUILD ends when code and targeted changed-seam checks are ready; do not run the project gate in an inner loop. VERIFY-RELEASE runs one targeted pass, at most one changed-seam correction pass after a build fix, and the project gate once. Every obligation ends PASS, justified SKIP/BLOCKED, or DEFERRED with owner. Do not deploy generically, sleep, poll CI/deploy, repeat a review wave, or run a third identical command. External wait/readiness failure: write one blocker/resume artifact, append the last verified fact to the program events file, cancel the loop, and stop. A phase ends by committing/pushing its artifact and handing branch HEAD + ledger + changed seams to a fresh bounded next-phase task.
```

Default cadence is 10 minutes. Use a longer cadence for a slow command. Never shorten it to approximate polling.

## Stop conditions

Cancel on:

1. required human input or production authorization;
2. unresolved readiness/external wait;
3. the second occurrence of the same normalized failure signature;
4. scope outside the mission or another lane's ownership;
5. the current phase artifact is complete.

## Codex variant

Codex has no `/loop`. Append this block to the phase mission:

```text
SELF-PACED BOUNDED PHASE: The lifecycle is define → build → verify-release, but this task owns only <phase>. Mode: <checklist|moderate|critical>. Read the proof-obligation ledger at <path>. Complete the named phase artifact, record the last verified fact, and stop. Do not continue into the next phase, poll external state, repeat review waves, or retry the same failure a third time. Return branch HEAD, artifact path, changed seams, terminal obligations, and blocker/resume key.
```
