# Merge, post-merge proof, and retire

The project's merge/prod gate is authoritative. Never infer authorization from a verification plan.

## Before PR or merge

The `verify-release` task confirms:

- every proof obligation is terminal (`PASS`, justified `SKIP`/`BLOCKED`, or `DEFERRED` with owner);
- the project gate ran exactly once when required;
- the changed branch artifact exists and is pushed;
- owned failures remain `FAIL` with a normalized signature and owner rather than becoming false external blockers or another retry loop;
- the PR states its mode (`checklist`, `moderate`, or `critical`) and links the proof-obligation ledger.

Grade the evidence in the ledger. Do not infer execution from a green build or a long test plan.

## Merge handling

Use the repository's documented merge mechanism and approval rule. A lane may only perform a merge when the project explicitly permits autonomous merge for that change class; otherwise stop at the ready PR with current checks and evidence.

Resolve dependencies and scope collisions before merge. Re-run only evidence invalidated by a changed SHA; do not restart the full lifecycle.

## Post-merge proof

Post-merge work contains only proof obligations whose claim depends on merged/deployed state. Key each run by:

`{obligation, deploy SHA, environment, command/journey, test identity, human-step kit, terminal assertion}`

This line is the bake obligation key set's one owner: `scripts/work_state.py bake-body` reads it to write each bake ticket's body, and `test_work_state.py` pins the two equal. A merged ship's bake is its own map ticket (`work_state.py` BAKE_OWED, manager contract §The deploy seam).

Run the smallest project-authorized proof against the **changed runtime seam**. Record the assertion, logs/state evidence, and safe test identity. **never rerun local suites** after merge merely because a merge happened.

If deploy completion or another external system is not ready, write one resumable blocker/wake artifact and stop. Do not sleep or poll. A later fresh task resumes by the key above and confirms the deploy SHA per `manager-contract.md` §Spawning a headless lane, *Verify the substrate BEFORE dispatch* — that bullet is the canonical statement; this line is its resume-path pointer.

## Retire gate

A lane retires only when:

1. its declared artifact is present and pushed;
2. every obligation is terminal or has a deferred owner;
3. required post-merge changed-seam proof is recorded against the correct deploy SHA and environment;
4. deferred work and soak observation have tracked owners;
5. the final summary names shipped artifacts, evidence, blockers, and the next resumable action;
6. its consolidation block is recorded in the program state file: worktree `OK` or reasoned, cited commits
   `CONFIRMED` ([consolidation.md](consolidation.md) §Before a chip changes hands).

A completion envelope, an unexecuted plan, or a stale environment does not satisfy this gate.
