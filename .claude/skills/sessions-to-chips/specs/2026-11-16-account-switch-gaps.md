# Account-switch gaps in Resume / mine

An account switch on 2026-11-16 hit nine gaps in Mode 2. Four of them hide work: the mine finished
"complete" while a program, unpushed-looking work, a scheduled wake and a CI binding were all
misjudged or missed. The other five only cost retries. This spec fixes the four at their owners in
the scripts (tier 1), then fixes the five in SKILL.md, CATCHUP_MESSAGE.md and one plan field (tier 2).

Every rule below has ONE owner. Where a rule has two copies today, the spec names the copy it
deletes.

## Files

| File | Change |
| --- | --- |
| `scripts/program_family.py` | Owns "which session is a program root". Gains `program_candidates()`; `root_manager()` gains a `roots` argument. |
| `scripts/mine_all.py` | Builds candidate programs next to manager programs and passes `--here` to the sweep. |
| `scripts/mine_report.py` | Candidate handoff and route steps, a route gate, sweep rows matched by session id, the trust kit, `ruling_recipients`. |
| `scripts/child_ledger.py` | Uses `pf.root_manager`; its private `manager_of` is deleted. |
| `scripts/handoff_sweep.py` | Owns "state left pointing at the other account": the content-based landed test, stranded schedules, stranded PR bindings. Its private `owning_manager` is deleted. |
| `prompts/worktree-sweep.md` | Calls `handoff_sweep.py --repo` instead of hand-running `git log` / `git cherry`. |
| `SKILL.md`, `CATCHUP_MESSAGE.md` | Tier 2 wording. |
| `scripts/test_mine_all.py`, new `scripts/test_handoff_sweep.py`, new `scripts/fixtures/handoff_sweep/` | Tests below. |

`work_state_sources.py` also calls `pf.root_manager`. It keeps the default `roots=()`, so its
behaviour does not change.

## Tier 1 — the gaps that hide work

### 1. A program without a `[Manager]` title is invisible

**What happened.** A session titled like an ordinary task ran a full program: six merged PRs,
twelve child sessions, many decisions. Programs are known only by manifest or a `[Manager]` title
(`program_family.families`, `is_manager`). So the session became one row in
`children-unmanaged-none.json`, its twelve children joined the unmanaged pile, and it got no handoff.

**Owner.** `program_family.py`. It already owns program identity (`families`, `root_manager`). Two
more copies of "walk up to the owning manager" exist and are deleted here:
`child_ledger.main.manager_of` (lines 82-90) and `handoff_sweep.owning_manager` (lines 52-62).

**Change.**

- New `program_candidates(rows, since_ms, routed) -> {sid: facts}`. A session is a candidate when
  all of these hold:
  - its title does not start with `[Manager]`;
  - it has no `[Manager]` ancestor (`root_manager(sid, rows)` is `None`);
  - it is not already a manifest's manager instance;
  - its session id is not in `routed`;
  - it shows program activity in the window: **at least one child session** whose
    `spawnedFrom.sessionId` is this session and whose `lastActivityAt >= since_ms`, **or at least
    two PRs** in its own `prs[]`.

  Decisions are not a signal. The store has no field for them, and a transcript scan here would
  make the deterministic step slow. One child or two PRs already catches the observed case
  (twelve children). A plain task session with one PR stays unmanaged.
- `root_manager(sid, rows, roots=frozenset())` stops at a `[Manager]` title **or** at a session id
  in `roots`. `child_ledger.py` and `handoff_sweep.py` call it with the candidate set, so a
  candidate's children land in `children-<candidate-slug>-<sid8>.json` under the candidate's
  session id, never in the unmanaged ledger. Both scripts compute the set themselves with
  `pf.load_store` + `pf.program_candidates`, so they stay runnable standalone.
- `mine_all.mine` appends each candidate to `programs` with `kind: "candidate"`,
  `slug: "<program_key(title)>-<sid8>"` (the suffix means it never collides with a real program),
  `managers: [manager_facts(row, chain)]` (the candidate is its own single instance),
  `moved: True`, `relay_to: None`. Manager programs get `kind: "manager"`. Everything downstream
  (digests, handoff miner, reconcilers) then treats the candidate like a moved program.
- **Routing.** A new append-only record, `~/.claude/sessions-to-chips/candidate-routes.jsonl`, one
  line per routed candidate:
  `{"session": "local_<uuid>", "route": "absorb" | "promote" | "leave", "program": "<slug>" | null, "at": "<ISO>", "by": "founder"}`.
  It is the one owner of routes. `mine_all` reads it and passes the routed ids to
  `program_candidates`. A route is permanent for that session id.
- `mine_report.build_plan` adds a phase-2 step `route:<sid8>` per candidate. Its `out` is the routes
  file and its `expect` is `{"jsonl_has": "<full session id>"}`. `check_gate` passes the step only
  when the file has a line for that session. Steps without `expect` keep today's check (file
  exists, is non-empty, and is newer than the plan). The step is OWED, so the run exits 3 and the
  relay does not start until every candidate is routed. A founder kit line per candidate says:
  "`<title>` (`local_<uuid>`) ran as a program: N children, M PRs, handoff `<path>`. Reply `absorb
  <slug>` (recommended when its tickets sit in that program's map), `promote`, or `leave`."
- The receipt's Programs table lists candidates with a `candidate` tag. Its holes line becomes
  `holes = <coverage holes> + <unrouted candidates>`.
- Phase 3: a candidate message has `kind: "candidate"` and `target: null`. At send time the
  dispatcher resolves it from the route. `absorb` means its handoff and child ledger ride the
  absorber's catch-up. `promote` follows the `no-manager-here` path. `leave` sends nothing.

**Deleted.** `child_ledger.main.manager_of`, `handoff_sweep.owning_manager`, and the title match
in `mine_report.build_plan` (`w.get("manager") in titles`, line 79). Sweep rows now carry
`ownerSessionId` and are matched against the program's manager ids.

**Test** (`test_mine_all.py`, the existing two-account `Fixture`):

- `test_unmanaged_root_with_children_is_a_candidate`: a root session titled "Release features"
  with two children and three PRs. The dry run plans `handoff:release-features-<sid8>` and
  `route:<sid8>`; both children are in `children-release-features-<sid8>.json`;
  `children-unmanaged-none.json` does not hold them; the exit code is 3.
- `test_single_pr_root_is_not_a_candidate`: a root with one PR and no children stays in the
  unmanaged ledger, with no route step.
- `test_routed_candidate_is_not_replanned`: after a routes line for the session, the next run plans
  no route step, and `check_gate` passes the earlier route step.
- `test_root_manager_roots_argument`: a unit test that `root_manager` stops at a session in `roots`.

**Acceptance.** Against a recorded store of the incident's shape (fixture), the receipt names the
candidate, holes count it, and the relay is blocked until a routes line exists. On the live machine,
`mine_all.py --dry-run` lists every root session with a child or two PRs in the window. The proof
command is `jq` over the plan: `.phases[1].steps[] | select(.id|startswith("route:"))`.

### 2. The unpushed-work check gives false positives

**What happened.** `handoff_sweep.worktree_findings` (line 85) runs `git log @{u}..`, or
`origin/main..HEAD` when there is no upstream. A commit that was squash-merged is still ahead by
ancestry, so it was reported as unpushed, and a redundant branch was pushed and then deleted.

**Owner.** `handoff_sweep.py`, a new function `landed(cwd) -> {"verdict", "evidence"}`.
`prompts/worktree-sweep.md` currently restates its own version of this test (`git log @{u}..` plus
`git cherry` for branches). That copy is deleted, and the prompt calls the script.

**Change.** The test checks content, not ancestry:

1. Resolve the main ref from `git symbolic-ref refs/remotes/origin/HEAD`. Never hardcode
   `origin/main`: some repos use `master`.
2. Run `git fetch origin <main> --quiet` once per repo common dir per run. On failure the row says
   `main ref stale (fetch failed)` and keeps going.
3. If `git merge-tree --write-tree <main> HEAD` succeeds and prints exactly the tree id of
   `<main>^{tree}`, the branch adds nothing to main. Verdict `LANDED`; the row is dropped from
   findings. This catches squash merges, cherry-picks and later main edits to the same files.
   It needs git 2.38 or newer; the run checks the version once and falls back to step 4 below that.
4. Otherwise run `git cherry <main> HEAD`. Every `+` line is a commit whose patch is not on main.
   Verdict `UNPUSHED <n>` lists only those commits. A merge-tree conflict is never read as landed:
   the verdict stays `UNPUSHED`, with `(conflicts with main)` added.
5. Commits ahead of `@{u}` are still reported as "not on the remote branch" whatever the verdict,
   because a push may be owed even when the content is on main. Such a row is informational,
   not at-risk.

The new `--repo <path>` mode walks `git worktree list --porcelain` of that repo and applies the
same `landed()` to every worktree, so the agent sweep and the script share one test.

**Deleted.** The `ahead = git(... "@{u}.." if upstream else "origin/main..HEAD")` branch (lines
84-91) as the at-risk signal, and the prompt's hand-written `git log @{u}..` / `git cherry` text.

**Test** (new `test_handoff_sweep.py`, hermetic temp repos with a bare `origin`):

- a branch squash-merged onto main gives `LANDED`, and the worktree is not in findings;
- the same after main later edits the same file still gives `LANDED`;
- a branch with one real unmerged commit gives `UNPUSHED 1` and names that commit;
- a branch whose change conflicts with main gives `UNPUSHED` with `(conflicts with main)`;
- a repo whose default branch is `master` resolves the main ref correctly.

**Acceptance.** All five cases pass. On the live machine, no worktree with a MERGED PR for its
branch appears as at-risk in `handoff-sweep.json`; the proof cross-checks that with
`gh pr list --head <branch> --state merged`.

### 6. Scheduled tasks are not swept

**What happened.** A one-shot scheduled task targeted a manager session on the old account. It had
already fired. A recurring one would have messaged a dead session forever, or never fired at all.

**Where the facts live** (read on 2026-11-16):

- The app's registry is per account and org:
  `<store>/<account>/<org>/scheduled-tasks.json`, `{"key": "scheduledTasks", "value": [ ... ]}`.
  Each entry has `id`, `enabled`, `cronExpression` or `fireAt`, `filePath`, `cwd` and
  `notifySessionId`.
- The task prompt is at `filePath`, under `~/.claude/scheduled-tasks/<id>/SKILL.md`. Its body may
  name target sessions as `local_<uuid>`.

**Owner.** `handoff_sweep.py`, new `stranded_schedules(store, here, rows)`. It owns all state left
pointing at the other account, alongside row 7. `mine_all` already runs this script in step 6.

**Change.** For every registry entry with `enabled: true` that is still due (it has
`cronExpression`, or `fireAt` is after now), collect its targets: `notifySessionId` plus every
`local_<uuid>` in its SKILL.md body. Report the entry when either of these holds:

- `registry-elsewhere`: the registry file sits under an account other than `here`. It will not fire
  while that account is signed out.
- `target-elsewhere`: a target session belongs to an account other than `here`, or is archived.

Each row carries `taskId`, `class`, `schedule`, the `targets` (full ids, account and title) and
`ownerSessionId`, which is the program root of the target found by `pf.root_manager` with the
candidate set. `mine_report` routes the row into its program's `SWEEP_ROWS`, so the catch-up
carries it. A row with no owner becomes a founder kit line.

The fix the row prescribes: the owner re-creates the task on this account with the scheduled-task
tool, naming its own full session id, then disables the old task where it can reach it. The sweep
never edits `scheduled-tasks.json`. The app owns that file, and a hand edit races the app's own
writes.

**Deleted.** Nothing. This is a new check, and no other code reads the registry today.

**Test** (`test_handoff_sweep.py` plus `fixtures/handoff_sweep/scheduled-tasks.json`, a
de-identified copy of the real shape with one entry of each kind):

- an enabled cron task whose `notifySessionId` is on the other account gives `target-elsewhere`
  with the right owner;
- a task whose target is named only in the SKILL.md body is found;
- an enabled task in the other account's registry gives `registry-elsewhere`;
- disabled tasks, and one-shots whose `fireAt` has passed, are excluded;
- a task targeting a here-account live session is excluded.

**Acceptance.** All tests pass. On the live machine, `handoff-sweep.json` has a `staleSchedules`
list, and the receipt prints its count. The proof cross-checks it with `jq` over both registries:
enabled entries whose `notifySessionId` row is on the other account.

### 7. PR Auto-fix bindings are not swept

**What happened.** A PR stayed bound, with Auto-fix on, to a session on the old account. Its CI
events went nowhere.

**Where the facts live.** A binding is an entry in the session row's `prs[]`, for example
`{"prNumber", "repo", "state", "branch", "autoFix": true}`. That is the same array
`list_sessions._pr_number` already reads.

**Owner.** `handoff_sweep.py`, new `stranded_bindings(rows, here)`.

**Change.** A PR, keyed by `(repo, prNumber)`, is stranded when all of these hold:

- some row on another account binds it with `autoFix: true`;
- its state is `OPEN`, or it is `MERGED` and the row was active since `--since` (the keep-bound
  rule: the binding is held until main is green past the merge);
- no non-archived row on `here` binds the same PR.

Each row carries `repo`, `pr`, `state`, `branch`, `boundSession` (full id and title) and
`ownerSessionId`. The prescribed action: an `OPEN` PR is bound by the owner (`bind_pr`, then
`set_monitor` with `auto_fix: true`). A `MERGED` PR is bound only until main is green past its
merge, then unbound. The other account's binding cannot be removed from here; it goes dead with
that session, and the row says so. The rows route like row 6.

**Deleted.** Nothing. This is a new check.

**Test** (`test_handoff_sweep.py`, store fixture rows):

- an OPEN PR with `autoFix: true` on an other-account row is stranded;
- the same PR also bound on a here-account row is not stranded;
- a CLOSED PR is excluded, and a MERGED one older than `--since` is excluded;
- a PR with `autoFix` absent or false is excluded.

**Acceptance.** All tests pass. `handoff-sweep.json` has a `strandedBindings` list, the receipt
prints its count, and each row appears in its owner's catch-up `{{SWEEPS}}`.

## Tier 2 — the gaps that cost retries

| # | Gap | Owner | Change |
| --- | --- | --- | --- |
| 3 | Trust is granted per folder, so an approval for the wrong folder did nothing | SKILL.md trust bullet (lines 68-72), and the founder kit string in `mine_report.build_plan` (line 142) | The ask lists every refused session as `title — exact cwd`, and says that trust belongs to that folder: approving another worktree of the same repo does not help. `pending-sends.md` records the cwd beside each refused send. |
| 4 | Short session ids fail in `send_message` | SKILL.md Relay / Converge paragraphs | Plan, relay, `pending-sends.md` and `replies.md` store the full `local_<uuid>`. Short ids appear only in receipt tables, for reading. `messages[].target` is already the full id; the rule covers the files the dispatcher writes by hand. |
| 5 | A ruling cannot reach the live children of a folded or archived manager | `mine_report.build_plan`, new plan field `ruling_recipients`, plus one SKILL.md line | `ruling_recipients` = every live manager here, plus every live (non-archived, present) lineage session on this account of an absorbed or closed program, plus that program's absorber. SKILL.md: "a cross-cutting ruling is sent to `plan.ruling_recipients`; orphan children never load the role, so the ledger alone does not reach them." |
| 8 | A rename right after the catch-up made the manager read its new title as a second manager | SKILL.md Relay, CATCHUP_MESSAGE.md | Rename before sending the catch-up. The catch-up's first line says "Your title is now `<title>`; no other manager holds it." |
| 9 | The one-message budget leaves no room for a late find | SKILL.md send constraints, the CATCHUP_MESSAGE.md header | Each manager may get ONE absorption addendum after its catch-up, only to hand it a program found later in the same round (a row 1 candidate routed `absorb`). Every other follow-up still waits for the reply. |

Tier 2 tests: the plan has `ruling_recipients` for a fixture with a closed program and one live
orphan child (`test_mine_all.py`), and the trust kit string contains `cwd`. The wording rows are
proven by reading the diff, since they carry no behaviour a test can pin.

## Ships

| Ship | Contents | Why one |
| --- | --- | --- |
| 1 | Tier 1 rows 1, 2, 6, 7 and tier 2 rows 3, 4, 5, 8, 9, with tests | Rows 6 and 7 route by `ownerSessionId`, which row 1 introduces. The SKILL.md wording describes plan fields the same change adds. No hard ordering dependency splits it. |

The repo has no CI. The local verify gate is
`python3 -m unittest discover -s .claude/skills/sessions-to-chips/scripts -p 'test_*.py'`
plus `tooling/leak-check.py --staged`. The live proof is one `mine_all.py --dry-run` on the
machine, read against the acceptance lines above. It is owed after the merge, because only real
stores hold the incident's shape.

## Spec-review tier

**Standard.** This is behaviour-bearing tooling: it changes what the mine reports and when the relay
may start. No critical gate fires. It touches no access control, credentials, money or tenancy.
Session titles and ids are operator metadata, not customer data. The spec writes no app-owned
state: schedules and bindings are reported, and the owner fixes them through the app's own tools.
If review moves any row to writing `scheduled-tasks.json` or session rows directly, the tier rises
to critical.

Lanes worth adding at standard: edge-case (candidate thresholds, merge-tree conflicts, fetch
failure) and live-evidence (the registry and `prs[]` shapes, read again on the day of the build).
