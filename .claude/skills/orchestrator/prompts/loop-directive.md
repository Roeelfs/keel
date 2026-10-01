# Loop directive — bounded phase continuation

The canonical lifecycle is **define → build → verify-release**. A loop may continue work inside the current fresh bounded phase; it never turns one session into the whole feature lifecycle.

Every lane records one verification mode (`checklist`, `moderate`, or `critical`) and shares the **proof-obligation ledger** through branch artifacts.

## Default continuation

Complete the current bounded phase and return its artifact. Do not add `/loop`, a heartbeat, cron, or scheduled wake as a continuation mechanism. Scheduling is available only when the user explicitly requests a schedule with a finish condition. On Codex, explicitly requested autonomous goal execution uses the native goal contract in `../references/codex-runtime.md`; an external gate ends its reachable frontier.

## Stop conditions

Stop the phase (and cancel any explicitly requested schedule) on:

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
