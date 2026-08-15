# Canonical lifecycle — three bounded phases

Run a feature through **define → build → verify-release**. Each phase is a fresh bounded task that resumes from branch artifacts and a shared **proof-obligation ledger**, not from the whole accumulated conversation.

## Modes

Choose once during `define` and record it in the ledger:

- `checklist`: trivial or no meaningful behavior change.
- `moderate`: default feature work.
- `critical`: auth, money, deletion, migration, isolation, irreversible state, or a named trust boundary.

Mode controls verification depth, not implementation ambition. `moderate` and `critical` use the provisional planner budget (12 unique obligations, 2 customer journeys) with a named override for uncovered risk.

## Existing implementation fast path

When the task begins with implementation, commits, tests, or review artifacts already present, inventory those artifacts once and resume from the first genuinely non-terminal changed seam. Evidence remains valid at the **same SHA**; conversation age and a new task do not invalidate it. Run at most **one changed-seam review** and **one grouped verification pass** for work not already proven. Reuse a same-SHA gate receipt when project law permits.

Never replay define or build merely because orchestration started late, a skill was invoked, or a new root took ownership. Do not review unchanged implementation, regenerate a test plan after code exists, or rerun PASS rows. If the user asks to proceed, complete, finalize, or backlog residue, the next forcing function is the nearest implementation/ship blocker—not another broad review.

## Phase 1 — define

Inputs: issue/goal, relevant project memory and law.

Outputs on the branch:

1. a spec or compact accepted design artifact;
2. one converged spec review when the change is non-trivial;
3. a `checklist`, `moderate`, or `critical` proof-obligation ledger;
4. an implementation plan only when the spec is not executable as written.

The root author creates the ledger; no mandatory child or second adversarial review is attached to normal planning. A material planner finding may patch the spec. Zero material findings need no stub or no-op commit.

Termination: acceptance criteria, scope, owning seams, mode, and proof obligations are explicit; build can proceed without rediscovery.

## Phase 2 — build

Inputs: define artifacts and branch HEAD.

Outputs:

1. product code and focused tests;
2. cheap boundary invariants at unmockable seams;
3. targeted verification while iterating;
4. one architecture/correctness closure appropriate to risk.

Do not run the project-wide gate repeatedly. A verification defect returns here once with its normalized failure signature and affected obligations.

Termination: implementation is complete, targeted checks are green, and the branch identifies the changed seams for verification.

## Phase 3 — verify-release

Inputs: changed SHA, proof-obligation ledger, selected project-test context.

Outputs:

1. one targeted execution pass;
2. at most one changed-seam correction pass after a build fix;
3. **project gate exactly once**;
4. terminal ledger rows: PASS, justified SKIP/BLOCKED, or DEFERRED with a **deferred owner**;
5. PR/release evidence and only the post-merge proof obligations that require merged/deployed substrate.

Readiness failures end with a blocker/resume artifact; they do not start polling. Release remains subject to the project's human/prod gates.

## Fresh bounded handoff

Create one fresh bounded task per phase, not per micro-step and not one marathon task for the whole feature. The handoff is:

- branch/worktree + HEAD;
- spec/design path;
- proof-obligation ledger path and mode;
- changed seams;
- last verified fact and blocker, if any.

This keeps coordination cheap while retaining durable decisions.

## Skip rules

- Trivial/docs-only: `checklist`; combine define and build if safe, then run the exact checklist.
- Small bug with no new surface: compact define note → build → verify-release against the regression seam.
- No deployed substrate: omit deployed-bake rows; never invent staging work.
- Critical work: keep the same three phases, but add one bounded critical coverage/adversarial judgment where risk requires it.
