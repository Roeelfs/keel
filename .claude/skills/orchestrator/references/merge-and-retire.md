# Merge, post-merge proof, and retire

The project's merge/prod gate is authoritative. Never infer authorization from a verification plan.

## Before PR or merge

The `verify-release` task confirms:

- every proof obligation is terminal (`PASS`, justified `SKIP`/`BLOCKED`, or `DEFERRED` with owner);
- the project gate ran exactly once when required;
- the changed branch artifact exists and is pushed;
- unresolved failures have a normalized signature and owner rather than another retry loop;
- the PR states its mode (`checklist`, `moderate`, or `critical`) and links the proof-obligation ledger.

Grade the evidence in the ledger. Do not infer execution from a green build or a long test plan.

## Merge handling

Use the repository's documented merge mechanism and approval rule. A lane may only perform a merge when the project explicitly permits autonomous merge for that change class; otherwise stop at the ready PR with current checks and evidence.

Resolve dependencies and scope collisions before merge. Re-run only evidence invalidated by a changed SHA; do not restart the full lifecycle.

## Post-merge proof

Post-merge work contains only proof obligations whose claim depends on merged/deployed state. Key each run by:

`{obligation, deploy SHA, environment, command/journey}`

Run the smallest project-authorized proof against the **changed runtime seam**. Record the assertion, logs/state evidence, and safe test identity. **never rerun local suites** after merge merely because a merge happened.

If deploy completion or another external system is not ready, write one resumable blocker/wake artifact and stop. Do not sleep or poll. A later fresh task resumes by the key above and first confirms the deploy SHA.

## Retire gate

A lane retires only when:

1. its declared artifact is present and pushed;
2. every obligation is terminal or has a deferred owner;
3. required post-merge changed-seam proof is recorded against the correct deploy SHA and environment;
4. deferred work and soak observation have tracked owners;
5. the final summary names shipped artifacts, evidence, blockers, and the next resumable action.

A completion envelope, an unexecuted plan, or a stale environment does not satisfy this gate.
