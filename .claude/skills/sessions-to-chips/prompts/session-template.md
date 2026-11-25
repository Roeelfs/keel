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
- Model policy (manager contract §Model policy): a define or build task runs on opus (or is a Codex lane); verify-release execution may run on sonnet. Managers run on sonnet and never write this task's spec or code themselves.
- Read durable artifacts, not prior transcripts.
- Commit with project conventions and a real session/lane identifier.
- Do not merge/deploy/prod-mutate without the project's explicit authorization.
- Do not poll CI/deploy or repeat a third identical failure.
- An unknown is a research lane you dispatch now (headless or Codex, tracked background Bash), never a stop; a blocker you cannot clear is named with its owner.
- Keep ~/.claude/sessions-to-chips/relay/<slug>/child-notes.md current every turn: done, decisions, paths, then Next, Blocked by, Research, Run.
- Final reply: phase, branch HEAD, artifacts, obligations, checks, changed seams, last verified fact, then four labelled fields: Next (how to proceed), Blocked by (exact blocker + owner, or none), Research (lanes dispatched for the unknowns, and when/how each reports back, or none), Run (ready-to-run commands, each in its own fenced block, plus the instructions that finish this task).

After accepting this mission, complete the bounded phase under its continuation contract.
```

## Paste 2

Use `prompts/loop-directive.md` §Default continuation (or §Codex variant). Do not add a schedule unless the user explicitly requests one.

## Filling guide

- Start it with `start_session`: `model: "opus"`, `effort: "medium"` for define/build; `sonnet` for a mechanical verify-release pass (`prompts/model-routing.md` §Start parameters).

- `checklist`: trivial/no meaningful behavior change.
- `moderate`: normal feature default; compact proof plan.
- `critical`: auth, money, deletion, migration, isolation, irreversible state, or named trust boundary.
- Register concrete owned paths in the program manifest before starting.
- The next phase receives branch HEAD, artifact paths, proof-obligation ledger, changed seams, and last verified fact—not the accumulated chat.
