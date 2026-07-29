# Canonical spec lane — 7 steps + the load-bearing 4→4b edge

Spec-class lanes follow this exact ordered sequence. Every step produces a **committed, file-anchored artifact**; the state-miner infers a lane's step from its most recent commit subject. One feature lives in ONE session through its full lifecycle — do not recommend "exit the spec session, spawn a fresh execute session"; context handoff costs real productivity. Multi-stage specs get one session per stage, each running the full read → plan → implement arc in place.

| # | Skill / action | Input | Output artifact | Commit pattern | Termination signal |
|---|---|---|---|---|---|
| 1 | `superpowers:brainstorming` | issue + memory refs | inline Q&A consensus | none (in-session) | user picks an option |
| 2 | spec authoring (no skill) | brainstorm answers | `docs/specs/active/<date>-<slug>-design.md` | `docs(<scope>): spec — <title>` | spec v0 committed |
| 3 | `/spec-review` | spec + decisions | **revised spec in-place** + insights filed as issues | `docs(<scope>): spec revision post /spec-review — <verdict>` | user "yes apply" + commit |
| 4 | `/spec-test-plan` | revised spec | `<spec>-test-plan.md` (multi-tier, `[ADV]` + `[EC]` tagged) | `test(<scope>): add test plan for <slug>` | plan file committed |
| **4b** | **spec patches from the test plan** | `[ADV]` / `[EC-MISSING]` findings | **revised spec AGAIN** | `docs(<scope>): spec patches for ADV-X + EC-Y from /spec-test-plan` | patch commit, or the stub below |
| 5 | `superpowers:writing-plans` | revised spec + test plan | `<spec>-plan.md` | `docs(<scope>): add implementation plan for <slug>` | plan file committed |
| 6 | `/spec-review` on the PLAN | implementation plan | plan revisions in-place | `docs(<scope>): plan revision post /spec-review` | reviews return + user "go" |
| 7 | `superpowers:executing-plans` | revised plan | code + tests + tier markers | per-task feature commits | all plan tasks checked + the project's verify gate PASS |

**Steps 3 and 6 default to a PAIRED Codex lane**, not an all-Claude panel — model diversity is the standing law for the deep-review bucket, and a Codex review pass bills a separate pool. Run the Claude review and the Codex review on the same artifact, then reconcile.

**The 4→4b edge is non-negotiable.** Adversarial and coverage reviewers routinely surface bugs the spec missed; without 4b the implementation plan inherits them and ships them. If `/spec-test-plan` yields zero patch-worthy findings, the lane still emits a stub commit — `docs(<scope>): no spec patches required from /spec-test-plan — all findings deferred to plan` — so the absence of 4b is recorded, not ambiguous.

**Skip rules (non-spec lanes):**
- Trivial < 50 LOC → skip 1, 3, 4, 4b, 6.
- Pure docs → skip 1, 4, 4b, 5, 6.
- Bug fix < ~200 LOC, no new surface → 2 → 5 → 7 only.

**A lane is "ready to execute" when ALL hold:** spec file exists · at least one `spec revision post /spec-review` commit · test-plan file exists · a step-4b patch commit OR the explicit no-patches stub · implementation plan exists · plan reviewed (`plan revision post /spec-review`, or all plan-review findings closed).

Steps past 7 — merge gate, post-merge chain, retire — live in `references/merge-and-retire.md`.
