# LEARNINGS — spec-review

This is the skill's running memory. Read it at task start; append a dated bullet
per non-trivial finding at task end. Prune vague entries and promote recurring
ones (≥3 occurrences) into SKILL.md.

Keep entries specific (cite the bug class + the evidence pattern that caught it),
but **portable** — describe the reusable lesson, not a one-off codebase detail.
Soft cap ~100 lines.

The entries below are the portable patterns distilled from many runs of this
pipeline across different stacks (web apps, payment systems, mobile apps, infra
migrations, data pipelines). They are starting wisdom, not project-specific.

---

## What Worked

### Pre-injecting adversarial focus concerns
- **Before dispatching Codex Adversarial, scan the spec for 3-6 specific risk concerns and inject them into the prompt's focus block.** Across many runs this reliably produces an ~85%+ confirm rate with grounded, URL-cited findings — versus generic output when no concerns are injected. Derive the concerns from the spec's own risk vocabulary (the things it claims are safe, the third-party APIs it leans on, the money/auth/data paths it touches). When a fix re-routes a flow onto a path the new hardening doesn't cover, the spec's "it's now protected" acceptance claim is the first thing to attack.

### Two/three-model convergence on a primary-source URL = ship without debate
- **When two Codex agents with different prompts (or Codex + an internal Claude lane) independently cite the SAME authoritative URL for the same finding, that is the strongest consensus signal in the pipeline — apply the fix without cross-examination.** Recurs constantly (Postgres constraint docs, Stripe capture docs, AWS Lambda lifecycle docs, RFC constraints, vendor SDK references). Likewise, zero Claude↔Codex disagreement across all 9 lanes → ship all CRITICAL/MAJOR fixes without a debate round.

### Web-enabled Codex catches third-party-API drift that training-data review can't
- **When a spec invokes a third-party API/SDK/format with enumerated values, transport assumptions, or a version-gated surface, web-enabled Codex (Standard or Adversarial) catches spec-vs-docs mismatches by reading the actual primary docs.** Claude reviewers tend to accept the spec's stated values on faith. This cuts both ways: sometimes the spec is wrong, sometimes the spec's *pessimistic* assumption is stale (a documented `http://` that actually 301s to HTTPS). Pre-inject "verify the API transport/enum/limit against live docs" whenever a spec names a brand-new or not-yet-GA API.

### Verify "current state" claims against the real source, not prose
- **A reviewer citing a doc line (CLAUDE.md / a README / an architecture doc) as proof that a dependency or file exists is a false-positive smell — confirm against the package manifest + lockfile, the actual file, or `git` truth.** Docs go stale. Same for migration numbers, ADR numbers, and "the next free number is N": always `ls` the directory or check `origin/main`, never trust a hardcoded number in the spec.

### `general-purpose` beats `Explore` for the codebase verifier in long sessions
- **The `Explore`-class agent intermittently refuses to use tools ("I need permission…", a compaction artifact).** If it does, re-dispatch as `general-purpose` with an explicit "EXECUTE THE TOOLS. Do not ask, do not summarize, do not refuse." lead sentence and 8-12 inlined exact commands. Produces complete, file:line-cited verification. If a verifier false-stops but ≥2 other lanes already cite the same file:line evidence, synthesize from cross-coverage rather than re-dispatching.

### Coordinator fills "NOT VERIFIED" gaps directly
- **When the codebase verifier returns "NOT VERIFIED" entries for non-blocked claims, fill the gaps with one Bash call rather than re-dispatching** — re-dispatch costs more than the verification itself. For repos with submodules, the verifier must run the submodule-status check AND a file-find inside the submodule BEFORE asserting a referenced file is missing or present.

### Research Auditor's job is elevation, not defect classification
- **Keep ELEVATE/CAUTION findings in their own Industry Insights section — never fold them into CRITICAL/MAJOR.** Mixing dilutes the severity signal. Never auto-apply; present as a decision surface. But DO check: "does any ELEVATE pattern subsume an existing CRITICAL fix?" — a single industry-aligned substitution often replaces 2-3 spec-bug band-aids, and that's cleaner than stacking patches. Pre-suggesting candidate companies in the research prompt (domain-matched: e.g. logistics → Uber/Lyft/DoorDash; payments → Stripe) yields richer, more grounded findings than a generic prompt.
- **An ELEVATE/CAUTION sometimes RESOLVES an open question rather than just adding a "nice to have."** Before treating a research finding as deferrable, check whether it reframes a question the spec left open.

### When the spec proposes to GENERATE what the codebase already AUTHORS
- **If a spec proposes to build a generator/compiler for artifacts the codebase already produces correctly by hand, surface "this already works via authored X" as a decision-fork — don't build a generator that re-derives reviewable artifacts.** Same family: when a spec adds a brand-new model/table, grep for existing `*History`/`*Snapshot`/`*Audit`/`*Log` peers first — peer-pattern reuse beats greenfield invention. Surface as Path A (keep) / Path B (simplify), don't auto-apply.

### "Self-reported inventory runs low" — re-enumerate exhaustively
- **For any "unify/consolidate the scattered X" spec, the self-reported count of call-sites/allowlists/producers is almost always low, and sometimes the enumeration AXIS itself is wrong.** Require a reviewer to grep the FULL set repo-wide and reconcile against the spec's claimed inventory. Different search strategies find different sites (syntactic grep, semantic-flow grep, signal/callback trace) — use several. The canonical inventory belongs in the SPEC (for future contributors), not just the implementation plan.

### Three-document review catches contract-bridge gaps single-doc review misses
- **When reviewing a triple-deliverable (design + test plan + implementation plan), trace every test row back to a creating task AND forward to a verifying section.** Gaps where a state is "assumed" but never created, or a test exists with no implementing task, are invisible to single-doc review. Same for cross-spec contract drift: when spec X claims "Y comes from spec Z," verify Z actually owns Y *compatibly* — not just that Y exists somewhere.

---

## Patterns (promoted — apply on every relevant run)

- **`ORDER BY` driving selection/pagination/locking must end in a UNIQUE column.** A timestamp or status is not a total order; ties straddling a page boundary or under `FOR UPDATE SKIP LOCKED` cause silent dup/skip/inconsistent picks. Append a unique tiebreaker (e.g. `, id ASC`).
- **Any "auto-paginate / client-side pagination over a capped API" spec:** verify the SERVER's `ORDER BY` has a unique tiebreaker, and demand a regression for many rows sharing one sort-key value.
- **Any "wire tests into CI / add a gate" spec:** the reviewer must RUN the proposed command — a task runner with no matching script exits 0 silently and ships a green-but-empty no-op. Fail-on-zero-tests assertion required.
- **When a refactor says "delete re-check Y, the outer gate X covers it":** verify Y isn't enforcing a FINER granularity (sub-tool / row-scope / fail-closed-on-uninstrumented) than X can see. Removing it is often a privilege-escalation regression.
- **When a spec CUTS a database for a flat-file / JSON store as "simplification":** demand the one durability property the DB gave for free — atomic write (temp + fsync + rename) + a concurrent-writer story.
- **When a new data source drops a field the deterministic logic keys on:** "reuse the rules unchanged" is almost always false — trace EVERY consumer of the dropped field (renderer AND predicate/classifier), not just the obvious one.
- **Concurrency invariants (locks, conditional updates, partial unique constraints) must be tested on the PRODUCTION database engine.** Some constraints/locks are silent no-ops on a lighter dev/test DB — tests pass, prod fires. Require the prod engine + a transaction-aware test harness, or add a programmatic guard alongside the DB constraint.
- **Any spec proposing time-bound retention on a table referenced by other long-lived rows** must specify both a nullable FK AND an inline non-PII snapshot copy — otherwise purge leaves dangling references.
- **A "freshness / last-updated / watermark" field inside a hashed or versioned definition is a category error** — separate the static freshness CONFIG (hashable) from the runtime VALUE (computed per request, never hashed).
- **A new privileged function/RPC/endpoint over a multi-tenant store** must: (a) take a tenant/org-scope parameter, (b) have its predicate actually match the liveness/contract it cites, (c) explicitly revoke execute from anonymous/public + grant only to the intended role, (d) carry a per-call row cap + dry-run mode for any bulk delete/sweep.
- **A privileged or operator-only tool must be gated by an explicit ceiling/exemption, NOT folded into the ordinary permission map** — adding it to the normal map makes it callable by any holder of that permission. Verify the gate is the ceiling, not the generic role map.
- **Verify the LIVE signature of a function before proposing `CREATE OR REPLACE` / a wrapper** — resolve it from the latest baseline + the actual caller's argument list, not the historical migration that first created it. A re-baseline makes old line numbers and signatures stale; overloading on arity ships a dead overload beside the live one.
- **Assert new migrations land in the directory the apply workflow actually scans** — a migration authored under a frozen/legacy path ships inert. Grep the apply workflow's path filter.
- **When a spec cites a policy/config knob as load-bearing,** verify it is (a) live-valued (not null/default), (b) actually READ on the code path the spec changes, and (c) for a NEW knob, enumerate every plumbing site (schema default → mapper → consumer → flag-schema `properties` not `required`).
- **When a concurrency-safety argument rests on "operation X blocks until state Y":** read the call. An `await` of a real result blocks; a fire-and-forget event-invoke does not — safety must then come from a level/readiness check, not call ordering.
- **`JSON.stringify(rows)` is a misleading equality test for SDK row shapes** — non-enumerable named properties get skipped, making dual-access rows look positional-only. Demand explicit per-property assertions (`row.x`, `row['x']`, `row[0]`, `Array.isArray(row)`, `Object.keys(row)`) before trusting a row-shape verdict.

---

## Drift-lane discipline (hard rules — over-reach is destructive here)

- **Drift scout + investigators are READ-ONLY.** A "recommend closing/merging a PR" or "create an issue" finding is a user-decision row, NEVER auto-executed. Never spawn a sub-agent that closes/merges/comments on PRs or creates issues.
- **Before acting on ANY drift-scout deletion/regression claim, verify with a REAL diff** — `git diff --stat base...branch`, `git merge-tree base branch` for conflict truth, and for `CREATE OR REPLACE` migrations check whether the branch forked before/after the migration it might overwrite + diff the function bodies. A stale branch missing a symbol does NOT mean the branch deletes it (a merge never deletes files the branch didn't touch). Acting on an unverified deletion claim can destroy a legitimate, mergeable change. Honesty-over-compliance: if the authorized action's premise is disproven mid-task, STOP and correct the record.
- **For any spec adding a "every registered X ∈ allowlist Y" parity invariant, check OPEN PRs that ADD to that registry** — an in-flight addition silently breaks the new invariant.

---

## When a reviewer's "over-engineered" framing should be dropped

- **When one reviewer proposes a scope-reduction alternative but the user has domain knowledge ruling it out, the "over-engineered" framing evaporates** — don't take it on face value without a valid alternative. The remaining criticals become reasonable spec-quality fixes, not complexity objections.

---

## Operational notes

- **After applying partial-resolution edits, ALWAYS run one scoped Codex verification pass** ("verify these N fixes are now resolved, nothing else") — cheap (<5 min, scoped tokens) and catches stale text references the broad pass missed. Don't assume edits are complete because they were intended to be.
- **When no session decisions can be mined** (spec authored directly, or JSONL aged out), build a proxy dossier from the spec's own Scope / Acceptance-Criteria / Open-Questions sections and give it to the Completeness reviewer. Detect this case by counting real user messages after filtering; if <5, skip extraction and use the spec text. Skip the optional Alignment Investigation in that case.

---

## Open Questions

- (none yet — append uncertainties here as runs surface them)
</content>
