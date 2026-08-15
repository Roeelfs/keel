---
license: MIT
name: spec-test-execute
description: Use when a compact proof-obligation ledger must be executed. Runs one targeted pass and, when earned, one changed-seam correction pass; it records evidence and returns product defects to build.
---

# Spec Test Execute

Execute a compact test plan as a finite verifier. This skill proves the built artifact; it does not become a second implementation loop, deployment controller, or knowledge-maintenance program.

## Skill memory

Read `LEARNINGS.md` and the private overlay at `~/.claude/skills-overlay/spec-test-execute/LEARNINGS.md` when present. Project test law is authoritative. Route private learning to the overlay and project facts to project memory.

## Load-bearing rules

- **Evidence before PASS.** Run the stated proof and retain the decisive output.
- A PASS needs a **strong assertion** against the intended behavior, not only process exit zero or `200 OK`.
- Every `SKIP` names the unavailable proof and the fallback attempted.
- Every `BLOCKED` names the readiness failure or unresolved failure signature and a resumable next action.
- Reuse **existing tests** before authoring new ones.
- The **project test contract** owns safe identities, environments, deployment rules, commands, and the project gate.
- A runtime behavior claim needs **real-boundary** evidence at the narrowest project-authorized seam.
- Never weaken a test or assertion to make a row green.

## Inputs and context

Read the plan, its referenced spec sections, and only the selected test-config/flow slices recorded by the planner. Do not reload whole large registries unless the plan records why selection was insufficient.

Validate the plan first:

```bash
python3 ~/.claude/skills/spec-test-plan/scripts/validate_plan.py <test-plan.md>
```

Group rows by reusable command/setup so one command can prove several obligations. Keep raw output under `$TMPDIR/spec-test-execute/<run-id>/` and write concise evidence references into the ledger after each command group, not after every assertion.

On native Codex, the phase root does not execute a deterministic pass inline when it would require process continuation, retain large output, or run the full gate. Dispatch **one procedural worker per pass**: one fresh history-free Luna-low worker owns all targeted command groups plus the project gate, writes raw logs outside the conversation, and returns only a compact structured result pointer. The root begins with one realistic wait, validates the pointer and evidence artifact, promotes decisive evidence into the durable ledger, and interprets the result. Do not spawn one worker per command or let the root take over the worker's process. Small bounded read-only probes that immediately inform judgment stay in the root.

If existing artifacts already prove a row at the same SHA, keep it terminal; do not execute it again. If the user says stop review/testing or preserve usage, stop immediately and return the current ledger plus backlog. No readiness probe, current command completion, project gate, or closure pass survives that instruction.

Before execution, query the worktree registry with `git worktree list --porcelain` and inspect only candidate sibling worktrees touching the ledger's test/fixture/helper paths. Reuse visible existing work. Relevant in-flight work that would collide produces a blocker artifact; do not scaffold a duplicate or dispatch a broad infrastructure-audit child.

## 1. Readiness gate

A readiness failure is missing authentication, safe test identity, required live revision, target environment, or another prerequisite that prevents the proof command from reaching the changed seam.

Perform one read-only readiness diagnosis. If unresolved:

1. write a blocker artifact containing the failed check, evidence, safe next action, and resume key;
2. mark the affected rows `BLOCKED` with that artifact;
3. stop the task.

Do not poll, deploy generically, or retry a readiness failure. A project-authorized deploy may be started only when the project test contract explicitly makes it part of this task; an external wait still ends the task with a resumable blocker/wake artifact.

## 2. One targeted pass

Run **one targeted pass** over the command groups, ordered from cheap changed-seam checks to the smallest real-boundary journey. On native Codex this is the procedural worker's pass; include the project gate last. Capture:

- command/journey identity;
- code/deploy SHA when relevant;
- environment and safe identity;
- exit/status class;
- the decisive assertion or diagnostic;
- artifact path or durable evidence URL.

Update rows to `PASS`, `FAIL`, `SKIP`, or `BLOCKED`. The plan is the durable ledger, but grouped evidence updates are preferred over edit-per-row churn.

Run the project gate exactly once, as the final group in the targeted-pass worker when a `project-gate` row exists. Do not rerun it as an inner loop.

## 3. Cluster failures once

A **failure signature** is:

`phase + command-group id + status class + normalized primary diagnostic/root frame`

Normalize by removing volatile timestamps, request IDs, ports, temporary paths, and line numbers. Group all rows sharing a signature.

Allow at most one fresh Terra-medium, read-only diagnostician for the verifier task. Give it all normalized clusters together using `prompts/failure-cluster-diagnostician.md`; it prioritizes the highest-leverage cause and leaves unrelated clusters explicit. It may inspect the relevant code, test, logs, and artifacts. It must not edit product code or tests.

Return a product defect to the `build` phase with the signature, minimal reproduction, affected obligations, and likely owning seam. Do not spawn one agent per failing row. Do not launch a write-capable rescue lane or Sol rescue.

## 4. One correction pass

After the build phase provides a changed SHA, run **one changed-seam correction pass** in one fresh procedural worker over only:

- previously failed obligations whose owning seam changed;
- directly dependent obligations invalidated by that change;
- a real-boundary journey when the changed runtime seam is the proof target.

Do not rerun unrelated rows or the project gate. A second occurrence of the same normalized signature becomes `BLOCKED`; there is no third identical execution.

## 5. Finish

The verifier finishes when every row is terminal:

- `PASS` with evidence;
- justified `SKIP`;
- `BLOCKED` with a blocker/resume artifact; or
- `DEFERRED` with `owner:`.

Report counts, executed command groups, product defects returned to build, changed-seam reruns, real-boundary evidence, and blockers. Optionally propose at most three reusable learning candidates, but apply them only in a separate approved change. Never auto-stage/commit unrelated knowledge, registry, or config files.

## Prohibited expansion

- no repeated tier sweeps or full-suite loops;
- no one-agent-per-row fan-out;
- no sleep or CI/deploy polling;
- no generic staging branch push or implicit production mutation;
- no automatic product fixes inside verification;
- no mandatory flow/config knowledge sync;
- no third identical execution.
