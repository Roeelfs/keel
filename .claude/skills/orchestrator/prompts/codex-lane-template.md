# Codex bounded-phase lane template

Use one fresh task for one phase of **define → build → verify-release**.

```text
NAME: <lane-name>
PURPOSE: <one-line outcome>
PHASE: <define|build|verify-release>
MODE: <checklist|moderate|critical>

Worktree: <repo>/<lane-name>-impl/ (nested inside the workspace; never /tmp)
Branch/head: <branch and SHA>
Spec/design: <path>
Proof-obligation ledger: <path>
Selected project-test context: <section names / flow keys>
Owned paths: <explicit paths>
Do not touch: <other-lane paths>
Accepted build task group: <exact tasks; required for BUILD>

The lifecycle is define → build → verify-release. This fresh bounded task owns only PHASE.

DEFINE: make scope, acceptance criteria, mode, and the proof-obligation ledger durable. The root author writes the moderate plan. At most one fresh Terra-medium critical coverage reviewer; Sol only for a named security/irreversible/trust-boundary dispute.

BUILD: implement only the exact accepted task group from durable artifacts, run targeted changed-seam checks, and record changed seams. Do not absorb adjacent discovered work or repeatedly run the project gate; defer nonblocking discoveries with an owner.

VERIFY-RELEASE: group deterministic commands into one targeted pass and dispatch one fresh Terra-low native procedural worker with `fork_turns:"none"`; include the project gate last and exactly once. A changed SHA may earn one fresh correction-pass worker. The phase root interprets results and updates the ledger; it never owns the worker's exec/write_stdin session. Reuse existing tests. FAIL is an owned defect; BLOCKED is an external prerequisite preventing the next accepted action; DEFERRED is owned backlog. A runtime claim needs real-boundary evidence when project law requires it.

Hard rules:
- Never merge, deploy, or mutate production unless this mission includes the project's explicit authorization.
- Never sleep or poll CI/deploy. External wait/readiness failure gets one blocker/resume artifact and ends the task.
- A spawned child owned by the accepted task group is internal work, not an external wait. Give it an explicit lease; consume its terminal result before final, or interrupt it once on lease expiry and continue from its durable handoff.
- Never start a third identical failing command.
- Review protocol is finite: one broad pass, one consolidation/falsification, one changed-seam closure. No restart/follow-up loop without a changed artifact.
- Commit with project conventions and verify the declared artifact exists outside /tmp.

Return: phase, branch HEAD, artifact paths, proof-obligation ledger status, commands run, changed seams, last verified fact, and blocker/resume key.
```

The three modes are `checklist`, `moderate`, and `critical`. Keep the proof-obligation ledger as the cross-phase handoff; do not paste whole prior transcripts.
