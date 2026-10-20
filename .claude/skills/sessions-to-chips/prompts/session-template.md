# Interactive bounded-phase session template

Use one interactive task for one phase of **define → build → verify-release**. The continuation contract is in `prompts/loop-directive.md`; it does not start a schedule.

## Paste 1

```text
You are starting a fresh bounded <define|build|verify-release> task.

Program state: ~/.claude/orchestrator/programs/<slug>.state.md
Goal: <one-line outcome>
Issue: <tracker ref>
Worktree/branch/head: <paths and SHA>
Verification mode: <checklist|moderate|critical>
Spec/design: <path or none>
Proof-obligation ledger: <path or to be created in define>
Selected project-test context: <section names / flow keys>

Owned paths:
- <path>

Do not touch:
- <sibling-owned path>

The program lifecycle is define → build → verify-release. This task owns only <phase>.

Phase artifact:
- define: accepted scope/spec + proof-obligation ledger
- build: implementation + targeted checks + changed-seam list
- verify-release: terminal ledger + one project gate result + release/blocker evidence

Constraints:
- Read durable artifacts, not prior transcripts.
- Commit with project conventions and a real session/lane identifier.
- Do not merge/deploy/prod-mutate without the project's explicit authorization.
- Do not poll CI/deploy or repeat a third identical failure.
- External wait/readiness failure ends with one blocker/resume artifact.
- Final reply: phase, branch HEAD, artifacts, obligations, checks, changed seams, last verified fact, blocker/resume key.

After accepting this mission, complete the bounded phase under its continuation contract.
```

## Paste 2

Use `prompts/loop-directive.md` §Default continuation (or §Codex variant). Do not add a schedule unless the user explicitly requests one.

## Filling guide

- `checklist`: trivial/no meaningful behavior change.
- `moderate`: normal feature default; compact proof plan.
- `critical`: auth, money, deletion, migration, isolation, irreversible state, or named trust boundary.
- Register concrete owned paths in the program manifest before starting.
- The next phase receives branch HEAD, artifact paths, proof-obligation ledger, changed seams, and last verified fact—not the accumulated chat.
