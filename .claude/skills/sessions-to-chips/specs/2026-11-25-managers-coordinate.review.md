## Spec Review — Final Report

### Spec: 2026-11-25-managers-coordinate.md
### Profile: standard (tier standard) — runtime path: harness-local manager role load (keel `sessions-to-chips` scripts: `coordinate.py`, `role_brief.py`, `work_state_store.py`; no deployed service) — dropped lanes: architecture-auditor, provider-fit-auditor, observability-auditor, spec-drift-scout, critic-hotfix, codex-standard, codex-adversarial, codex-research, fable-frontier-judge (each `SKIPPED (gate: not in tier standard (profile standard))`); adr-auditor, legal-auditor, cutover-architect, runtime-wiring, security-miner, live-evidence-auditor, performance-architect, operator-plane-architect, dependency-currency, system1-elevation, critic-adversarial, critic-frontier (each `SKIPPED (gate: <reason in the manifest below>)`)
### Lane plan: tier standard (profile standard) — planned 4 lanes (2 Codex), ran 4 (2 Codex); advisory budget: max 11 lanes / 2 Codex, token ceiling 22000000, falsifier scope critical. Manifest files: <scratchpad>
- spend: 6415874 tokens (Claude 5918884, Codex 496990) = 0.292x the 22000000 ceiling
- completeness-reviewer: tier standard default set
- codebase-verifier: tier standard default set
- edge-case-miner: tier standard default set
- codex-frontier: tier standard default set

### Lane manifest
| Lane | Status | Agent / model |
|---|---|---|
| completeness-reviewer | run | general-purpose / opus |
| codebase-verifier | run | codex-dispatch / gpt-6-sol |
| edge-case-miner | run | general-purpose / opus |
| codex-frontier | run | codex-dispatch / gpt-6-astra |
| architecture-auditor | SKIPPED (gate: not in tier standard (profile standard)) | - |
| adr-auditor | SKIPPED (gate: adrTouched not fired (keel has no docs/adr change in this spec)) | - |
| legal-auditor | SKIPPED (gate: cynap-only lane, repo keel is not a cynap repo) | - |
| cutover-architect | SKIPPED (gate: cutover not fired (additive: new optional manifest key, new ledger file, new brief block; the deleted events.jsonl clause is prose with no code reader)) | - |
| runtime-wiring | SKIPPED (gate: runtimeWiring not fired (no env var, secret, flag or deployed function)) | - |
| provider-fit-auditor | SKIPPED (gate: not in tier standard (profile standard)) | - |
| security-miner | SKIPPED (gate: security not fired (no credential, table or authz surface; local files under ~/.claude only)) | - |
| observability-auditor | SKIPPED (gate: not in tier standard (profile standard)) | - |
| live-evidence-auditor | SKIPPED (gate: liveSurface/externalShape not fired (harness-only local tooling (keel skill scripts); no live system runtime; reads only local manifests, session index and its own ledger, all instantiable in unit tests)) | - |
| performance-architect | SKIPPED (gate: liveSurface not fired (harness-only local tooling (keel skill scripts); no live system runtime)) | - |
| operator-plane-architect | SKIPPED (gate: cynap-only lane, repo keel is not a cynap repo) | - |
| dependency-currency | SKIPPED (gate: dependencyChange not fired (stdlib Python only, no package change)) | - |
| system1-elevation | SKIPPED (gate: decisionSurface not fired (ownership decisions stay with managers and founder; the script only derives thread state from rows)) | - |
| spec-drift-scout | SKIPPED (gate: not in tier standard (profile standard)) | - |
| critic-hotfix | SKIPPED (gate: not in tier standard (profile standard)) | - |
| codex-standard | SKIPPED (gate: not in tier standard (profile standard)) | - |
| codex-adversarial | SKIPPED (gate: not in tier standard (profile standard)) | - |
| codex-research | SKIPPED (gate: not in tier standard (profile standard)) | - |
| fable-frontier-judge | SKIPPED (gate: not in tier standard (profile standard)) | - |
| critic-adversarial | SKIPPED (gate: codex-adversarial produced its artifact) | - |
| critic-frontier | SKIPPED (gate: codex-frontier produced its artifact) | - |
| Investigation Workflow | SKIPPED (gate: no investigation Workflow ran for this standard-tier run) | - |

### Falsifier wave: 4 dispatched over 4 CRITICAL/MAJOR — 0 REFUTED, 4 SURVIVES.
Falsifier scope at this tier is critical (CRITICAL only). The three CRITICAL units F-3, F-4 and F-7 were falsified (F-4 was also checked member-by-member: AST-1, CB-4, COMP-4, EC-12 each SURVIVES). Every other CRITICAL/MAJOR id below carries SURVIVES with a "not falsified at tier standard" note.
### Codex Standard Verdict: SKIPPED (gate: not in tier standard (profile standard))
### Codex Adversarial Verdict: SKIPPED (gate: not in tier standard (profile standard))
### Codex Research Verdict: SKIPPED (gate: not in tier standard (profile standard))
### Codex Frontier (Astra) Verdict: redesign — redesign the ticket handover, then ship the peer view and durable asks
### Investigation Verdict: skipped (no investigation Workflow ran; no brief)
### Spec Drift Verdict: SKIPPED (gate: not in tier standard (profile standard)). Worktree drift noted by the dossier and codebase-verifier: the committed baseline is `8cef7ef656d064c274cbfba9b6af3b18afdd1e30` (fetched `origin/master` merge base), `3e28513` is spec-only, and the implementation (`validate_owns`, `coordinate.py`, `test_coordinate.py`) appeared as worktree changes and landed locally as `346685a` during review. It establishes neither shipped behavior nor a bake revision (AST-12).

### Consensus Issues (2+ reviewers)
1. [F-3] [CRITICAL] Abandonment/takeover liveness is a second, weaker carrier-liveness implementation — flagged by: codebase-verifier, codex-frontier, completeness-reviewer, edge-case-miner. Verdict: SURVIVES (falsified).
   Members: CB-2 (CRITICAL) SURVIVES; COMP-3 (MAJOR) SURVIVES; EC-22 (MAJOR) SURVIVES; AST-5 (MAJOR) SURVIVES.
   File: `scripts/coordinate.py:122-149`, `scripts/work_state.py:186-227`, `scripts/work_state_store.py:705-713`, `references/manager-contract.md:546`, spec:136-144.
   Falsifier evidence: the spec checks one binding only (the contract says the program's bindings), exempts seams from carriers, hardcodes wake/card/founder/bake carriers dead while the engine treats founder as always live and card/wake/bake as leased, and turns a failed `ps` PID probe into "dead". The sandbox's denied `ps` reproduced a live PID read as dead. The spec claims "does not define a new one" yet narrows the rule.
   Recommendation: evaluate abandonment across ALL bindings of the source program (seams included), reuse the engine's liveness (`work_state.py:186` lane PID/start, session liveness, `live_bg`) rather than a second implementation, treat `unknown` and a failed probe as live (fail closed), require a parseable `updated_at` older than 24 h, and resolve the terminal owner first.
2. [F-4] [CRITICAL] Takeover retires the source binding, then only prints `bind --continue`; the ticket is left ownerless — flagged by: codebase-verifier, codex-frontier, completeness-reviewer, edge-case-miner. Verdict: SURVIVES (falsified).
   Members: CB-4 (CRITICAL) SURVIVES; AST-1 (CRITICAL) SURVIVES; COMP-4 (MAJOR) SURVIVES; EC-12 (MAJOR) SURVIVES.
   File: spec:148-153, `scripts/coordinate.py:462-496`, `scripts/work_state_store.py:377`, `scripts/work_state.py:815`.
   Falsifier evidence: `coordinate.py` retires, writes the `taken` row and events, then prints. `bind` refuses a ticket outside the destination map or its children (`work_state_store.py:377`), and `--continue` does not lift that gate. A fresh bind carries no branch, worktree, publication or paths. There is no pending state. The codebase-verifier fixture produced two empty binding lists and a thread marked `taken`.
   Recommendation (Astra): defer the cross-map single-ticket writer until `work_state_store` owns admission, recovery and bake semantics; ship an abandoned-claim report with an executable handover route (the existing whole-program takeover/fold) and a visible `taken-unbound`/pending state. If a transfer is kept, order bind-before-retire in one store operation that validates destination membership, preserves the full binding and writes the ledger row last.
3. [F-7] [CRITICAL] Claim admission and multi-record transfer lack serialized locks, a lock order and crash/retry semantics — flagged by: codebase-verifier, codex-frontier, completeness-reviewer. Verdict: SURVIVES (falsified).
   Members: CB-8 (CRITICAL) SURVIVES; COMP-11 (MAJOR) SURVIVES; AST-6 (MAJOR) SURVIVES.
   File: spec:145-153, `scripts/coordinate.py:68`, `:387`, `scripts/work_state_store.py:430`, `:459`.
   Falsifier evidence: `own()` checks peer holdings outside any lock, then writes, so two concurrent first claims both pass (reproduced in a fixture). `takeover()` retires under the peer lock only, then appends ledger, events and bind as separate steps; a retry after retire hits "no open binding". The falsifier noted the window is small with human-paced managers and suggested MAJOR, but no REFUTED verdict was returned, so CRITICAL stands (downgrade guard).
   Recommendation: take `folds.lock`, then the coordination lock, then manifest locks in sorted slug order; re-read claims under lock; first successful writer wins; retries keep the original `since`; a tie never gives both first place; inject interruption after each write in tests.
4. [F-1] [MAJOR] A self-awarded settle and an unbound ledger identity let a later claimant proceed, or spoof another manifest, before the prior owner releases — flagged by: completeness-reviewer, edge-case-miner. Verdict: SURVIVES (not falsified at tier standard: corroborated by lane edge-case-miner).
   Members: COMP-1 (MAJOR) SURVIVES; EC-15 (MAJOR) SURVIVES.
   File: spec:73, spec:80-83, `references/manager-contract.md:544-546`.
   Recommendation: a self-award stays `proposed` until the counterparty settles/acks or its manifest no longer holds the item; refuse a self-award against an earlier first claim; the writer derives `from` from `--program` and the holding session, and `settle`/`contest`/`reply`/`owner` must name a thread party.
5. [F-2] [MAJOR] Contest-before-settle, ruling/expiry/escalation precedence and the escalation owner are undefined — flagged by: completeness-reviewer, edge-case-miner. Verdict: SURVIVES (not falsified at tier standard: corroborated by lane edge-case-miner).
   Members: COMP-2 (MAJOR) SURVIVES; EC-7 (MAJOR) SURVIVES; EC-8 (MAJOR) SURVIVES.
   File: spec:71-77, spec:83, spec:164.
   Recommendation: any contest by the other party on an open or settled thread makes it `contested`; escalate when contested and both live; one deterministic escalator (the asker); precedence `taken` > `ruled` > `expired` > `escalate` > `contested` > `settled` > `answered` > `open`; reject rows after `ruled`/`taken` except a new thread generation.
6. [F-5] [MAJOR] No release operation for a ceded ticket/branch/worktree/PR binding; ordinary retire requires tracker closure — flagged by: codebase-verifier, completeness-reviewer, edge-case-miner. Verdict: SURVIVES (not falsified at tier standard: corroborated by lanes codebase-verifier and edge-case-miner).
   Members: COMP-5 (MAJOR) SURVIVES; CB-7 (MAJOR) SURVIVES; EC-19 (MAJOR) SURVIVES.
   File: spec:42, spec:127, `scripts/work_state.py:847`, `scripts/coordinate.py:410`.
   Recommendation: name a release verb per item kind (a retire with reason `ceded to <owner>` and an allow predicate), and have the "still holds it: release it" line print that exact runnable command.
7. [F-6] [MAJOR] The messaging path contradicts the operator-present contract and assumes a reachable Claude holder, with no exact recipient or durable recovery — flagged by: codebase-verifier, codex-frontier, completeness-reviewer. Verdict: SURVIVES (not falsified at tier standard: corroborated by lanes codebase-verifier and codex-frontier).
   Members: COMP-6 (MAJOR) SURVIVES; CB-10 (MAJOR) SURVIVES; CB-11 (MAJOR) SURVIVES; AST-7 (MAJOR) SURVIVES.
   File: spec:162-163, spec:175-178, `references/manager-contract.md:545`, `:774-778`, `references/role.md:50`, `scripts/role_brief.py:422`, `scripts/coordinate.py:166`, `references/codex-runtime.md:8`.
   Recommendation: address asks to the terminal program; on an operator-present Claude turn resolve one full `sessionId` (CLI UUID via `cliSessionId`, a short `local_` prefix only on a unique match) and send with `notify_when_idle` from a non-final message; unattended, ambiguous or Codex (null session) recipients get the durable ask on their next load only; expose thread text through a `show` command; make reader errors visible instead of an empty result.
8. [F-9] [MAJOR] Absorbed/folded manifests are invisible to ownership resolution, the claims projection and direct asks — flagged by: codebase-verifier, codex-frontier, completeness-reviewer, edge-case-miner. Verdict: SURVIVES (not falsified at tier standard: corroborated by lanes codebase-verifier, codex-frontier and edge-case-miner).
   Members: COMP-14 (MAJOR) SURVIVES; EC-13 (MAJOR) SURVIVES; CB-5 (MAJOR) SURVIVES; AST-2 (MAJOR) SURVIVES.
   File: spec:94, spec:129-131, `scripts/state_index.py:44`, `scripts/work_state_waiters.py:15`, `scripts/program_family.py:93`, `scripts/coordinate.py:155`.
   Recommendation: project every family member's claims to `program_family.terminal_owner` while keeping the source slug for mutations; resolve `to`/`from` through the terminal owner; `ask --to <absorbed>` refuses and prints the terminal owner. Five absorbed manifests still carried bindings at the 2026-11-25 13:13 UTC census.
9. [F-10] [MAJOR] `coordinate.holdings` duplicates the sidecar reader and drops completeness markers; coverage is not reported per peer and repo — flagged by: codebase-verifier, codex-frontier (both Codex lanes agree). Verdict: SURVIVES (not falsified at tier standard: corroborated by lane codex-frontier).
   Members: CB-1 (MAJOR) SURVIVES; AST-8 (MAJOR) SURVIVES.
   File: `scripts/coordinate.py:233`, `scripts/state_index.py:30`, `:48`, `scripts/role_brief.py:319`.
   Recommendation: reuse `other_sidecars` (delete the second reader); report coverage per peer and repo using `generated_at`, `collapsed` and `holdings_dropped`; show stale evidence with its age and a refresh command; reserve "no overlap" for fresh, complete inputs. Also delete the duplicate advisory path-collision surface already printed by the context brief (COMP-8, MINOR).
10. [F-13] [MAJOR] A persistent overlap re-asks on every wake: threads are not unique per canonical item and claim generation — flagged by: codex-frontier, edge-case-miner. Verdict: SURVIVES (not falsified at tier standard: corroborated by lane codex-frontier).
   Members: EC-5 (MAJOR) SURVIVES; AST-3 (MAJOR) SURVIVES; AST-9 (MAJOR) SURVIVES.
   File: spec:125, `references/role.md:63`.
   Recommendation: one active ownership thread per canonical item and claim generation; an overlap with a non-terminal thread prints that thread's id, state and next command, never a fresh `ask`; `ask` is idempotent on an open (from, to, item); third claimants attach to the same thread.

### Codex-Only Findings (investigate — possible Claude blind spot)
Category: Implementation (codebase-verifier) / Risk (codex-frontier)
1. [F-11] [MAJOR] Pre-publication repo identity has no producer — Verdict: SURVIVES (not falsified at tier standard: outside scope).
   Members: CB-6 (MAJOR) SURVIVES.
   Body: `bind --repo` stores a repo only with `--pr`/`--sha`; `coordinate` emits `branch::<ref>` without a repo and skips those bindings' paths. `publication.repo` was on 0 of 17 Apps bindings. A fixture produced a false branch collision across two repos.
   File: `scripts/work_state_store.py:36`, `scripts/work_state.py:815`, `scripts/coordinate.py:214` | Confidence: fixture-reproduced
   Recommendation: define how bind records or resolves a canonical repo from unambiguous evidence; surface unresolved multi-repo claims as "ask", never as a collision.
2. [F-14] [MAJOR] The extra world read on every role load has no incremental performance budget or bounded-read design — Verdict: SURVIVES (not falsified at tier standard: outside scope).
   Members: AST-4 (MAJOR) SURVIVES; AST-11 (MAJOR) SURVIVES.
   Body: §3 adds a full ledger and manifest read to every role load; a line cap bounds neither bytes nor work. Apps' manifest is already 12,463 B against the 8,192 B budget.
   File: spec:89-100, `scripts/work_state_store.py:26` | Confidence: design judgment
   Recommendation: proposed targets (unmeasured): warm p95 ≤250 ms, 1 s coordination deadline, ≤4 KiB added to the brief; reuse the per-wake read; index open threads by program and ledger offset; cursor-based overflow; degraded output names what is unknown.
3. [F-15] [MAJOR] Bake evidence and the review baseline are not established — Verdict: SURVIVES (not falsified at tier standard: outside scope).
   Members: AST-10 (MAJOR) SURVIVES; AST-12 (MAJOR) SURVIVES.
   Body: the acceptance permits a clarification reply with no ownership change; unattended ask recovery and a two-manager settlement are not required. Baseline is `8cef7ef656d064c274cbfba9b6af3b18afdd1e30`, not the dirty worktree.
   File: spec:214-219 | Confidence: verified presence of `harness` and `a second program` at 13:17 UTC 2026-11-25 on pre-feature role `v5dc80639`
   Recommendation: bake on `harness` and `a second program` (recheck presence at bake time); capture commit, installed path and role hash; record one ownership ask recovered by an unattended recipient without a message, the incumbent's release, both manifests and both final views on the feature ticket.
4. [F-16] [MAJOR] Transfer events reuse `binding-retired`, which other readers interpret differently — Verdict: SURVIVES (not falsified at tier standard: outside scope).
   Members: CB-9 (MAJOR) SURVIVES.
   Body: the renderer puts retired PRs into publication history (a fixture showed a taken-over open PR as historical), fold-migration verification accepts the event as retirement proof, and both events advance role-head/resume freshness (also COMP-10, MINOR).
   File: `scripts/render_state.py:198`, `scripts/work_state_migrate.py:523`, `scripts/role_brief.py:265`, `scripts/mine_all.py:86`
   Recommendation: define a distinct transfer event (or a reason field those readers branch on) and extend `scripts/test_work_state.py:693` and `scripts/test_render_state.py:567` with a transfer case.
5. [F-17] [MAJOR] The role/fold subsystem is a repeatedly corrected hotspot; the slug passed to role load conflates "claims shown" with "manager contacted" — Verdict: SURVIVES (not falsified at tier standard: outside scope).
   Members: CB-3 (MAJOR) SURVIVES.
   Body: corrective commits `b51cb90` (#34), `55cbd25` (#37, a tracker ticket), `ef85abf` (#40) and `e0cc8bd` (#27, a tracker ticket) on the same seam. Two-month counts: 11 for `work_state_store.py`, 19 for `role.md`, 61 for `manager-contract.md`.
   File: `scripts/role_brief.py:444`, `scripts/work_state_sources.py:263`, `references/role.md:60`
   Recommendation: separate the display identity (terminal-owner projection) from the contact identity (verified present holder) in the spec, and add a concurrent two-manager takeover test (Follow-on row 3).

### Edge Cases (from Edge-Case Miner — semantic boundary enumeration)
| EC-ID | Entity / Operation | Boundary | Spec Coverage | Recommended Resolution | Severity |
|---|---|---|---|---|---|
| EC-1 | Peers block overflow (spec:99-100) | `+N more` points at the same bounded command; past-cap rows unreachable while wake 3c says act on every line | MISSING | `peers --all` prints every row; `+N more` names `--all` | MAJOR — SURVIVES (F-12) |
| EC-2 | Truncation precedence | escalations/contests/takeovers can be cut behind advisory path lines | MISSING | fixed order: escalations > threads for me > release > takeover > exact overlaps > path overlaps > peers; escalations and threads never truncated | MAJOR — SURVIVES (F-12) |
| EC-3 | Uncapped sections | Escalate/Takeover/release have no cap or counting rule | MISSING | state each cap or exemption | MINOR |
| EC-4 | 0 peers / 0 overlaps | empty block indistinguishable from degraded load | IMPLICIT | print one line `Other managers (0 live): no overlaps, no threads` | MINOR |
| EC-5 | Overlap with an open thread | re-asks every wake | MISSING | print the thread's id/state/next command; `ask` refuses a duplicate | MAJOR — SURVIVES (F-13) |
| EC-6 | 3+ claimants | pairwise threads, "both" escalation undefined | MISSING | first claim across all holders; escalation names every live holder | MINOR |
| EC-7 | Contest on open thread, no settle | maps to no state, no escalator | MISSING | contested; asker owns the founder question | MAJOR — SURVIVES (F-2) |
| EC-8 | Rows after a terminal row | no precedence among ruled/taken/expired/escalate | MISSING | precedence rule; writer rejects rows after ruled/taken | MAJOR — SURVIVES (F-2) |
| EC-9 | Counterparty absorbed/done/closed | thread open forever | MISSING | re-target terminal owner or close as `folded` | MINOR |
| EC-10 | `question:` threads | escalate on age; reply rules overlap | IMPLICIT | question threads never escalate on age | MINOR |
| EC-11 | Seam moved by takeover | `since` undefined | MISSING | takeover stamps `since` = takeover time | MINOR |
| EC-12 | Takeover side-effect order | ledger says taken, nobody holds | MISSING | ledger row last, after bind; `taken-unbound` line otherwise | MAJOR — SURVIVES (F-4, falsified) |
| EC-13 | Rows to an absorbed slug | invisible to terminal owner | MISSING | resolve through `terminal_owner`; `ask` refuses absorbed `--to` | MAJOR — SURVIVES (F-9) |
| EC-14 | `seam:<name>` identity | not unique across programs | MISSING | `seam:<program>:<name>` or unique at `own` | MINOR |
| EC-15 | Ledger `from`/party validation | spoofed settle mutates another manifest | MISSING | derive `from` from caller; parties-only verbs | MAJOR — SURVIVES (F-1) |
| EC-16 | Item encoding in printed commands | unquoted seam names; unnormalized items | MISSING | `shlex.quote`; normalize ticket/worktree/repo | MINOR |
| EC-17 | First-claim tie; 24 h clock origin | equal timestamps; clock start unspecified | MISSING | tie by slug; clock from latest row | MINOR |
| EC-18 | Duplicate `ask` on retry | second open thread | MISSING | idempotent `ask` (covered by EC-5 fix) | MINOR |
| EC-19 | Release of non-seam items | no writer for ceded bindings | MISSING | settle cede retires via `retire` with reason, or print the exact command | MAJOR — SURVIVES (F-5) |
| EC-20 | Missing/unbounded ledger; manifest cap | first run, full-read growth, 8192 B warn-only cap | MISSING | missing reads empty; bounded window; warn at 85% | MINOR |
| EC-21 | Schema evolution | unknown verbs/kinds from newer writer | MISSING | reader skips with a note; writer refuses | MINOR |
| EC-22 | Seam abandonment without carrier check | working program's seam takeable | IMPLICIT | seam abandoned only when no binding has a live carrier | MAJOR — SURVIVES (F-3, falsified) |
| EC-23 | Takeover replay after half-apply | refuses forever | MISSING | idempotent completion of missing steps | MINOR |
| EC-24 | Open thread to absent-not-abandoned peer | occupies thread cap indefinitely | MISSING | `waiting-on-absent-peer` line | MINOR |
| EC-25 | Fold-family duplicate holders | two lines or arbitrary first claim | MISSING | fold holdings to terminal owner first | MINOR |
| EC-26 | `ruling`/`owner` expressiveness | cannot record split/stack rulings | MISSING | `owner: null` + `text`, optional `scope` | MINOR |
| EC-28 | Line width | caps count lines not bytes | MISSING | 200-char lines; thread text only via `show` | MINOR |

EC-27 (long-lived process) is N/A and omitted.

### Claude-Only Findings
1. [F-8] [MAJOR] completeness-reviewer — Q12: the spec cites no the harness map exit criterion or shipped defect justifying a JOIN, and the feature ticket has no parent, project or relations (Backlog; excluded from the harness map's 53 children), so bake evidence lands on a ticket no map census reads. Verdict: SURVIVES (not falsified at tier standard: outside scope).
   Members: COMP-13 (MAJOR) SURVIVES.
   Recommendation: state the founder-direct ask as the justification and link the feature ticket (Founder decision D-2; Follow-on row 8).
2. [F-12] [MAJOR] edge-case-miner — the overflow pointer repeats the same capped view and truncation has no precedence, hiding escalations behind advisory lines. Verdict: SURVIVES (not falsified at tier standard: outside scope).
   Members: EC-1 (MAJOR) SURVIVES; EC-2 (MAJOR) SURVIVES.
   File: spec:99, `scripts/coordinate.py:293`, `references/role.md:63`.
3. [MINOR] completeness-reviewer — COMP-7 ruling's manifest effect and `expired` on question threads undefined; COMP-8 duplicate advisory path-collision surface; COMP-9 `live_program` prose omits `closed`; COMP-10 takeover events hit live `.events.jsonl` readers (see F-16); COMP-12 acceptance does not name the feature ticket or the founder merge-ask step; COMP-15 `owns` unbounded against the 8192 B warn-only manifest cap.

### Cross-Examined Disagreements
1. [CRITICAL] Severity of the carrier-liveness and ticket-handover defects
   Claude position: MAJOR (COMP-3, EC-22 on liveness; COMP-4, EC-12 on handover).
   Codex position: CRITICAL (CB-2 on liveness; CB-4 and AST-1 on handover).
   Resolution: converged on the repo fact. The falsifier read the seams and returned SURVIVES for F-3 and F-4, and both units keep CRITICAL.
2. [CRITICAL] Severity of F-7 (lock gaps)
   Claude position: MAJOR (COMP-11). Codex position: CRITICAL (CB-8); AST-6 MAJOR.
   Resolution: the falsifier returned SURVIVES and suggested MAJOR given human-paced managers. Without a REFUTED verdict the downgrade guard keeps CRITICAL; the founder may rule on it (D-1 removes most of the multi-record transfer window if accepted).

### Resolved (non-issues after cross-checking)
- None: the falsifier wave returned no REFUTED verdict.

### Changes Applied
1. None by the synthesis stage. The main loop applies spec prose fixes in Step 5c.

### Follow-on dispositions
| # | Candidate | Class | Evidence | Disposition | Tracker | Trigger |
|---|---|---|---|---|---|---|
| 1 | Doorbell fallback for Codex role loads (no session id) and bare CLI-UUID holders: ledger-only, no doorbell | 1 | spec:175; `scripts/role_brief.py:409` | IN | - | - |
| 2 | Matchable log line per refused `own`/`takeover` cause and degraded `peers_block` | 2 | spec:172 names only a by-hand command; takeover refusal reasons unnamed | IN | - | - |
| 3 | Test: two managers run `takeover` on one item concurrently (same defect class as #40 holder ping-pong) | 3 | fold/role seam fixes #27, #34, #40 (dossier); `ef85abf` | PROBE | - | - |
| 4 | Role delivery through the installed master symlink | 4 | `references/role.md` version bump plus `## Changes` line | OUT: already covered by §5's role version bump | - | - |
| 5 | Half-applied takeover (retire ok, bind refused) and crash between ledger row and manifest write | 5 | COMP-4, COMP-11; `scripts/work_state_store.py:377`, `:430` | IN | - | - |
| 6 | Name the second present manager before bake (only 6 of 75 manifests had present holders; Apps was not present) | 6 | dossier 13:13 UTC census; AST-10 names `harness` and `a second program` | PROBE | - | - |
| 7 | Stop-guard enforcement of unanswered threads | other | spec non-goal; Astra keeps it excluded | DEFER | the deferred follow-up ticket | a thread left open >24 h in the first 30 days |
| 8 | the feature ticket map linkage (native child of the harness map or recorded founder-direct) | other | COMP-13; the feature ticket has no parent or relations | PARALLEL-TICKET | done: parent set | - |

### Unknowns
| U-ID | Claim | Why unproven | Probe | Time-box | Blocks ship |
|---|---|---|---|---|---|
| U-1 | Serialized `own` admission and takeover survive concurrent managers and a crash between writes (F-7, Follow-on 3) | only a fixture showed the race; no lock-order design exists yet | test: two processes run `coordinate.py own` and `takeover` on one item against temp stores, with interruption injected after each write; expect exactly one owner and a recoverable pending state | 2h | Ship 1 (the feature ticket keel PR merge) |
| U-2 | Two managers are present at bake time and an unattended recipient recovers an ask on its next normal role load (F-15, Follow-on 6) | presence verified only at 13:17 UTC 2026-11-25, on pre-feature role `v5dc80639` | read-only: recheck the holder-presence predicate for `harness` and `a second program`; record commit, installed path and role hash at bake start | 1h | Ship 1 (the feature ticket keel PR merge) |
| U-3 | The added role-load read stays within an incremental budget (F-14) | the proposed targets (warm p95 ≤250 ms, ≤4 KiB) are not measured | benchmark `role_brief` with and without the coordination block on the live store, a cold index and a long synthetic ledger; also time the Stop guard import under its 2 s budget | 2h | Ship 1 (the feature ticket keel PR merge) |

### Founder decisions owed
| D-ID | Decision | Recommended answer | Blocks |
|---|---|---|---|
| D-1 | Build a cross-map single-ticket takeover writer in this ship, or defer it? | Defer it. Ship ownership declarations, the peer view, durable asks, manifest-verified settlement, and an abandoned-claim report that routes to the existing whole-program takeover/fold with a visible pending state. Put any item transfer in `work_state_store` later. | spec merge |
| D-2 | How is the feature ticket linked for census and bake evidence? | Record it as a founder-direct ticket and link it as a native child of the harness map, so the map census sees the bake evidence. | spec merge |
| D-3 | Does `SendMessage` with `notify_when_idle` from a non-final message satisfy the operator-present transport rule, with ledger-only delivery on unattended, ambiguous or Codex wakes? | Yes. Amend the contract transport section in the same change so only one rule remains. | spec merge |
| D-4 | Who asks the founder on a live-vs-live contest? | The asker of the thread is the single founder liaison; the other side's block reads "escalated by <peer>, awaiting ruling". | spec merge |
| D-5 | Is F-7 CRITICAL or MAJOR? | Keep CRITICAL until the U-1 probe passes; D-1 shrinks the multi-record window. | Ship 1 |

### Carried obligations
| ID | Obligation | Proof | Owner | Close-by |
|---|---|---|---|---|
| F-3, CB-2, COMP-3, EC-22, AST-5 | Abandonment checks every binding of the source program (seams included) through the engine's liveness; `unknown` or a failed PID probe counts as live | test: `test_coordinate.py` takeover refused when another binding has a live carrier, when `ps` fails, and for card/wake/bake/founder carriers | the feature ticket build session | 2026-11-28 |
| F-4, CB-4, AST-1, COMP-4, EC-12 | No ledger `taken` row unless the destination holds the ticket with branch/worktree/publication/paths preserved; otherwise a visible pending state | test: `test_coordinate.py` foreign-map takeover leaves a pending row and the source binding intact; fixture asserts the destination binding carries metadata | the feature ticket build session | 2026-11-28 |
| F-7, CB-8, COMP-11, AST-6 | Serialized claim admission with a fixed lock order and retryable transfer | probe: U-1 concurrent `own`/`takeover` test with interruption after each write | the feature ticket build session | 2026-11-28 |
| F-1, COMP-1, EC-15 | Self-award is proposed until release; writer binds `from` to the caller and parties | test: `test_coordinate.py` self-award against an earlier claim refused; spoofed `--from` refused | - | - |
| F-2, COMP-2, EC-7, EC-8 | One thread state machine with contest-before-settle, precedence and one escalator | test: `test_coordinate.py` table-driven thread-state cases | - | - |
| F-5, COMP-5, CB-7, EC-19 | A runnable release for each ceded item kind | test: `test_coordinate.py` cede of an open ticket binding retires it with reason `ceded to <owner>` | - | - |
| F-6, COMP-6, CB-10, CB-11, AST-7 | Exact recipient on attended turns; durable ledger-only path otherwise; thread text readable | test: `test_role_brief.py` unattended/Codex/ambiguous-holder cases print the ask without a send target | - | - |
| F-8, COMP-13 | the feature ticket linked so bake evidence is in a map census | probe: Linear GraphQL read shows the feature ticket parent or founder-direct label | the feature ticket build session | 2026-11-28 |
| F-9, COMP-14, EC-13, CB-5, AST-2 | Absorbed claims projected to the terminal owner; asks to absorbed slugs redirected | test: `test_coordinate.py` third program sees an absorbed child's binding under its terminal owner | - | - |
| F-10, CB-1, AST-8 | One sidecar reader (`other_sidecars`); per-peer/repo coverage incl. stale, collapsed, dropped | test: `test_coordinate.py` stale and dropped sidecars print "unknown", not "no overlap" | - | - |
| F-11, CB-6 | Canonical repo key for unpublished branches and paths | test: `test_coordinate.py` same branch name in two repos is not a collision | - | - |
| F-12, EC-1, EC-2 | Reachable overflow and fixed truncation precedence | test: `test_coordinate.py` cap+1 rows keep escalations; `peers --all` lists every row | - | - |
| F-13, EC-5, AST-3, AST-9 | One thread per canonical item and generation; idempotent `ask` | test: `test_coordinate.py` repeated wake with an open thread prints no fresh `ask` | - | - |
| F-14, AST-4, AST-11 | Incremental role-load budget measured | probe: U-3 benchmark | the feature ticket build session | 2026-11-28 |
| F-15, AST-10, AST-12 | Bake on present managers at the installed feature revision, including unattended ask recovery and a real settlement | bake: U-2 presence check, then two-manager ask, release and both final views recorded on the feature ticket | the feature ticket build session | 2026-11-30 |
| F-16, CB-9 | Transfer events do not read as publication history or fold-retirement proof | test: extend `test_work_state.py:693` and `test_render_state.py:567` with a transfer case | - | - |
| F-17, CB-3 | Display identity separated from contact identity | test: `test_role_brief.py` load of an absorbed child slug contacts the terminal holder | - | - |
| UX-1 | `coordinate.py peers --program harness` and `--program <second live program>` each list the other as a present manager with its ownership, from the real stores | drive: run both commands on the live stores after install | the feature ticket build session | 2026-11-30 |
| UX-2 | One real question thread: Harness `ask`s a second live manager, sends the doorbell, the second `reply`s or `settle`s, and both role loads show the final state | drive: two-manager exchange, evidence on the feature ticket | the feature ticket build session | 2026-11-30 |
| PRE-MERGE DRIVE | The manager role load with the coordination block (`role_brief.py` + `coordinate.py`) at the installed feature revision | drive: two present managers (`harness` plus one other) run `/manager-role`; capture both blocks, one ask/settle round trip and the resulting manifests | the feature ticket build session | 2026-11-30 |

