# Account-switch gaps in Resume / mine

An account switch on 2026-11-16 hit nine gaps in Mode 2. Four of them hide work: the mine finished
"complete" while a program, unpushed-looking work, a scheduled wake and a CI binding were all
misjudged or missed. The other five only cost retries. This spec fixes the four at their owners in
the scripts (tier 1), then fixes the five in SKILL.md, CATCHUP_MESSAGE.md and one plan field (tier 2).
Row 10, added by the founder the same day, makes every manager keep the head of its global state
file current, so the next session (any worktree, any account) starts from the right date and owner.

Every rule below has ONE owner. Where a rule has two copies today, the spec names the copy it
deletes.

## Files

| File | Change |
| --- | --- |
| `scripts/program_family.py` | Owns "which session is a program root" and the program slug. Gains `program_candidates()`, `load_routes()`, `program_slug()`; `root_manager()` gains a `roots` argument. |
| `scripts/mine_all.py` | Computes the candidate set once, writes `<work>/candidates.json`, builds candidate programs through the manager-program path, and passes `--roots` and `--here` to the scripts it runs. |
| `scripts/mine_report.py` | Candidate handoff and route steps, the route gate, the `--route` writer verb, sweep rows matched by session id, the trust kit, `ruling_recipients`. |
| `scripts/child_ledger.py` | Uses `pf.root_manager` and `pf.program_slug`; its private `manager_of` and `slug` are deleted. |
| `scripts/handoff_sweep.py` | Owns "state left pointing at the other account": the content-based landed test, stranded schedules, stranded PR bindings. Its private `owning_manager` is deleted. |
| `scripts/coverage_audit.py`, `scripts/wrapup_roster.py`, `scripts/hygiene_candidates.py` | Their `[Manager]`-title family walks go through `pf.root_manager(..., roots)` (details in row 1). |
| `prompts/worktree-sweep.md` | Calls `handoff_sweep.py --repo` instead of hand-running `git log` / `git cherry`. |
| `SKILL.md`, `CATCHUP_MESSAGE.md` | Tier 2 wording. |
| `scripts/state_view.py` | Row 10: owns the state-file head (`read_head`). Loses the `## VIEW` `updated_at` key. `done` and `decisions` rows need a `date`. |
| `scripts/render_state.py`, `scripts/state_brief.py` | Row 10: read the head through `sv.read_head`; staleness and "Narrative updated" use the head's `updated_at`; the log-shape problem rows. |
| `scripts/role_brief.py` | Row 10: a health line when the head is missing, unparseable, older than the newest event, or names another session. |
| `references/role.md`, `references/manager-contract.md` | Row 10: the head rule, rewrite-in-place for `## AT-WAKE`, dated lines, the absolute child-notes path. |
| `scripts/test_mine_all.py`, new `scripts/test_handoff_sweep.py`, new `scripts/fixtures/handoff_sweep/`, `scripts/test_render_state.py`, `scripts/test_role_brief.py` | Tests below. |
| Outside this repo: the Stop guard `~/.claude/scripts/manager_arm_guard.py` and its test | Row 10: the head check. It lives in the operator's private harness, not here; see row 10 §Ownership. |

`work_state_sources.py` also calls `pf.root_manager`. It keeps the default `roots=()`, so its
behaviour does not change.

## Tier 1 — the gaps that hide work

### 1. A program without a `[Manager]` title is invisible

**What happened.** A session titled like an ordinary task ran a full program: six merged PRs,
twelve child sessions, many decisions. Programs are known only by manifest or a `[Manager]` title
(`program_family.families`, `is_manager`). So the session became one row in
`children-unmanaged-none.json`, its twelve children joined the unmanaged pile, and it got no handoff.

**Owner.** `program_family.py`. It already owns program identity (`families`, `root_manager`). Other
copies of "walk up (or down) to the owning manager" exist today and are removed or rerouted here:

| Copy | Today | After |
| --- | --- | --- |
| `child_ledger.main.manager_of` (lines 82-90) | walks up from the parent to a `[Manager]` title | deleted; `pf.root_manager(parent, rows, roots)` |
| `handoff_sweep.owning_manager` (lines 52-62) | walks up to a `[Manager]` title, returns the title | deleted; `pf.root_manager(..., roots)`, returns a session id |
| `mine_report.build_plan` title match (line 79) | matches sweep rows by `w.get("manager") in titles` | deleted; matched by `ownerSessionId` |
| `coverage_audit.py` Test B (lines 76-82) | walks descendants only from `[Manager]` titles | also walks from every session in `roots` |
| `wrapup_roster.has_manager_ancestor` (lines 95-102) | counts a session as managed only under a `[Manager]` title | deleted; managed means `pf.root_manager(sid, rows, roots)` is not `None` |
| `hygiene_candidates.descendants` (line 58) | stops the downward walk at a `[Manager]` prefix | also stops at a session in `roots` |

The three scripts `mine_all` runs (`child_ledger`, `handoff_sweep`, `coverage_audit`) take the set
from `--roots <work>/candidates.json`. The two that run outside a mine (`wrapup_roster`,
`hygiene_candidates`) call `pf.program_candidates` themselves over their own window. The rule has
one owner either way; only the caller differs. A script run standalone with no `--roots` and no own
call uses `roots=()`, which is today's behaviour.

**Change.**

- New `program_candidates(rows, since_ms, routes, self_cli=None) -> {sid: facts}`, where `rows` is
  the FULL store (`pf.load_store`, no window). A session is a candidate when all of these hold:
  - its title does not start with `[Manager]`, and it is not a manifest's manager instance;
  - it is itself active in the window: its own `lastActivityAt >= since_ms`;
  - it is a root: its `spawnedFrom.sessionId` is absent or names a session not in the store. A
    session whose parent is in the store is that parent's family (a manager's child, or another
    candidate's descendant), so a candidate's descendants are never candidates themselves;
  - its `cliSessionId` is not `self_cli` (the session running the mine, from `CLAUDE_SESSION_ID`,
    never routes itself);
  - its routes entry, if any, is not `leave`;
  - it shows program activity: **at least one child session** whose `spawnedFrom.sessionId` is this
    session and whose `lastActivityAt >= since_ms`, **or at least two PRs** in its own `prs[]`.

  On the live store (1807 rows, 2026-11-16) the rule without the own-activity and root clauses
  gives 357 candidates, 350 of them on old PRs alone. With both clauses it gives single digits.
  Decisions are not a signal: the store has no field for them, and a transcript scan would make the
  deterministic step slow. PRs carry no timestamp, so the own-activity clause is the window for
  the PR test. An archived root that was active in the window is still a candidate: its children
  may be live.
- **Routes** feed lineage, not just the candidate list. `pf.load_routes()` reads the routes file
  (below) and `root_manager` resolves through it:
  - an unrouted candidate, or one routed `promote`, stays a root under its own session id;
  - one routed `absorb <slug>` maps to that program's manager ids, so its later children land in
    the absorber's ledger, run after run;
  - one routed `leave` is dropped; its children go to the unmanaged ledger.

  `roots` is therefore `{sid: owner_sid}`: the candidate maps to itself, an absorbed one to the
  absorber's current manager here (or its newest instance when none is here).
- `root_manager(sid, rows, roots={})` stops at a `[Manager]` title **or** at a session id in
  `roots`, returning `roots[sid]` for the latter. It starts at `sid` itself, so `child_ledger`
  calls it with the row's parent (today's `manager_of` starts at the parent) and skips candidate
  rows as well as `[Manager]` rows, so a candidate is never ledgered as its own child.
- **Computed once.** `mine_all` computes the set at the window floor (`now - window_days`), never
  at `since_iso`: `since_iso` is derived from program checkpoints, and candidates are programs, so
  computing it there would be circular and would drop a candidate whose children were active
  between `floor` and `since`. It writes `<work>/candidates.json` (`{sid: {owner, route, slug,
  children, prs}}`) and passes `--roots` to every script it runs.
- **One slug.** `pf.program_slug(title) = program_key(title).replace(" ", "-")`. `child_ledger.slug`
  is deleted; every ledger file name and plan slug uses `program_slug`. Ledger readers glob
  `children-*.json`, so manager ledger names may change without breaking them. A candidate's slug
  is `<program_slug(title)>-<sid8>` (the suffix means it never collides with a real program); its
  ledger is `children-<program_slug(title)>-<sid8>.json`, the existing naming.
- `mine_all.mine` builds each unrouted or promoted candidate through the same code path as a
  manager program, so every field downstream reads exists. Candidate values:

  | Field | Candidate value |
  | --- | --- |
  | `kind` | `"candidate"` (manager programs get `"manager"`) |
  | `slug` | `<program_slug(title)>-<sid8>` |
  | `key` | `program_key(title)` |
  | `managers` | `[manager_facts(row, chain)]` (the candidate is its own single instance) |
  | `lineage` | the candidate plus its descendants, as for a manager family |
  | `live` | `pf.session_present` over that lineage |
  | `checkpoint`, `checkpoint_src`, `checkpoint_sid` | `checkpoint_for([candidate], here, floor)`; a candidate on another account gets the window floor, as a moved program does |
  | `moved` | `True` when the candidate's account is not `here`, else `False` |
  | `absorbed_by` | `None` |
  | `relay_to` | `None` |
  | `conflict` | `False` |
  | `fold` | `state_fold(slug, programs_dir, lineage_last, {})` |

  An absorbed candidate is not a program; its lineage rides the absorber's program through `roots`.
- **Routing.** A new append-only record, `~/.claude/sessions-to-chips/candidate-routes.jsonl`, one
  line per routed candidate:
  `{"session": "local_<uuid>", "route": "absorb" | "promote" | "leave", "program": "<slug>" | null, "at": "<ISO>", "by": "founder"}`.
  `program_family` owns its path and the reader (`load_routes`). Its one writer is
  `mine_report.py --route <full sid> absorb <slug> | promote | leave`, run by the dispatcher on the
  founder's reply. The writer rejects a session id that is not a candidate in the latest plan, an
  `absorb` slug that is not a program in that plan, and a second route for the same session. A
  route is permanent for that session id. Nobody hand-appends the file.
- `mine_report.build_plan` adds a phase-2 step `route:<sid8>` per unrouted candidate. Its `out` is
  the routes file and its `expect` is `{"jsonl_has": "<full session id>"}`. `check_gate` passes the
  step only when the file has a line for that session. Steps without `expect` keep today's check
  (file exists, is non-empty, and is newer than the plan). The step is OWED, so the run exits 3 and
  the relay does not start until every candidate is routed. A founder kit line per candidate says:
  "`<title>` (`local_<uuid>`) ran as a program: N children, M PRs, handoff `<path>`. Reply `absorb
  <slug>` (recommended when its tickets sit in that program's map), `promote`, or `leave`."
- The receipt's Programs table lists candidates with a `candidate` tag. Its holes line becomes
  `holes = <coverage holes> + <unrouted candidates>`.
- Phase 3: a candidate message has `kind: "candidate"` and `target: null`. At send time the
  dispatcher resolves it from the route. `absorb` means its handoff and child ledger ride the
  absorber's catch-up. `promote` follows the `no-manager-here` path. `leave` sends nothing.

**Deleted.** The six copies in the table above, and `child_ledger.slug`. Sweep rows now carry
`ownerSessionId` and are matched against the program's manager ids (or the candidate's id).

**Test** (`test_mine_all.py`, the existing two-account `Fixture`):

- `test_unmanaged_root_with_children_is_a_candidate`: a root session titled "Release features:
  phase 2" (the colon pins the slug rule) with two children and three PRs, active in the window.
  The dry run plans `handoff:release-features-<sid8>` and `route:<sid8>`; both children are in
  `children-release-features-<sid8>.json`; `children-unmanaged-none.json` does not hold them; the
  candidate is not in its own ledger; the exit code is 3.
- `test_single_pr_root_is_not_a_candidate`: a root with one PR and no children stays in the
  unmanaged ledger, with no route step.
- `test_old_root_with_prs_is_not_a_candidate`: a root with two PRs whose own `lastActivityAt` is
  before the floor is not a candidate.
- `test_nested_session_is_not_a_candidate`: a child of a candidate, with its own child and two
  PRs, is not a candidate and is ledgered under the root candidate.
- `test_self_is_not_a_candidate`: the row whose `cliSessionId` equals `CLAUDE_SESSION_ID` is
  excluded.
- `test_routed_candidate_is_not_replanned`: after `--route <sid> promote`, the next run plans no
  route step, `check_gate` passes the earlier route step, and the candidate's children still land
  in its ledger.
- `test_absorbed_candidate_child_reaches_absorber`: after `--route <sid> absorb <slug>`, a new
  child of the candidate lands in the absorber's ledger, not the unmanaged one.
- `test_route_writer_rejects_unknown`: `--route` refuses a non-candidate id and an unknown slug.
- `test_root_manager_roots_argument`: a unit test that `root_manager` stops at a session in `roots`
  and returns its mapped owner.
- `test_candidate_program_fields`: a candidate program carries every field in the table above, and
  `render_receipt` and `build_plan` run on it without a `KeyError`.

**Acceptance.** Against a recorded store of the incident's shape (fixture), the receipt names the
candidate, holes count it, and the relay is blocked until a routes line exists. On the live machine,
`mine_all.py --dry-run` lists every root session active in the window with a child or two PRs, and
no nested or self session. The proof command is `jq` over the plan:
`.phases[1].steps[] | select(.id|startswith("route:"))`, cross-checked against `<work>/candidates.json`.

### 2. The unpushed-work check gives false positives

**What happened.** `handoff_sweep.worktree_findings` (line 85) runs `git log @{u}..`, or
`origin/main..HEAD` when there is no upstream. A commit that was squash-merged is still ahead by
ancestry, so it was reported as unpushed, and a redundant branch was pushed and then deleted.

**Owner.** `handoff_sweep.py`, a new function `landed(repo, ref) -> {"verdict", "evidence"}`.
`prompts/worktree-sweep.md` currently restates its own version of this test (`git log @{u}..` for
worktrees, `git cherry origin/main <branch>` for branches with no worktree). That copy is deleted,
and the prompt calls the script, which covers both.

**Change.** The test checks content, not ancestry:

1. **Main ref.** Read `git symbolic-ref refs/remotes/origin/HEAD`; if unset, try `origin/main`,
   then `origin/master`. With none of them, the verdict is `UNKNOWN (no main ref)`: never
   `LANDED`, and the row stays in findings. Strip the ref to the short branch name (`master`) for
   the fetch.
2. **Fetch.** Run `git fetch origin <branch> --quiet` once per repo common dir per run. On failure
   the row says `main ref stale (fetch failed)` and keeps going. This writes only remote-tracking
   refs; the script's "Read-only" docstring changes to say so.
3. **Merged PR.** If a `prs[]` entry on any store row has this branch, state `MERGED` on a live
   `gh pr view` re-check, and `ref` equals the PR's merged head (`headRefOid`), the verdict is
   `LANDED (PR #n merged)`. This catches the case merge-tree cannot: main later edited the same
   lines. Commits after the merged head fall through to step 4.
4. **Merge-tree.** If `git merge-tree --write-tree <main> <ref>` succeeds and prints exactly the
   tree id of `<main>^{tree}`, the branch adds nothing to main: verdict `LANDED`. This catches
   squash merges and cherry-picks, and later main edits in other hunks. It needs git 2.38 or
   newer; the run checks the version once and falls back to step 5 below that.
5. **Cherry.** Otherwise run `git cherry <main> <ref>`. Every `+` line is a commit whose patch is
   not on main. Verdict `UNPUSHED <n>` lists only those commits. A merge-tree conflict is never
   read as landed: the verdict stays `UNPUSHED <n>`, with `(conflicts with main)` added. So a
   squash-merged branch whose PR is not in the store, after main edited the same lines, still
   reads `UNPUSHED <n> (conflicts with main)` and stays at-risk. That is the one false positive
   left, and it fails toward keeping work.
6. Commits ahead of `@{u}` are still reported as "not on the remote branch" whatever the verdict,
   because a push may be owed even when the content is on main. Such a row is informational,
   not at-risk.

`LANDED` removes only the unpushed-commits issue. The row stays when it also has untracked files,
modified tracked files, or GUTTED state. Today only `??` lines and the deletion count are read
(`handoff_sweep.py:82-94`), though the docstring promises "uncommitted files"; the row gains a
`modified:` issue for tracked files with changes.

The new `--repo <path>` mode walks `git worktree list --porcelain` AND `git for-each-ref
refs/heads` of that repo: every worktree's `HEAD`, plus every local branch with no worktree whose
upstream is missing or gone and whose last commit is newer than the checkpoint. `main`/`master`
themselves are skipped. The agent sweep and the script share one test.

**Ownership.** `handoff_sweep` walks ancestry over the FULL store (`pf.load_store`); the `--since`
window applies only to which findings are reported. Today `load_sessions` filters rows first
(`handoff_sweep.py:42-49`), so a child of a quiet manager gets no owner and its row is dropped. A
worktree or branch row with no owner after the full walk becomes a founder kit line.

**Deleted.** The `ahead = git(... "@{u}.." if upstream else "origin/main..HEAD")` branch (lines
84-91) as the at-risk signal, the windowed `load_sessions` as the ancestry source, and the prompt's
hand-written `git log @{u}..` / `git cherry` text.

**Test** (new `test_handoff_sweep.py`, hermetic temp repos with a bare `origin`):

- a branch squash-merged onto main gives `LANDED`, and the worktree is not in findings;
- the same after main later edits a different hunk of the same file still gives `LANDED`;
- squash-merged, then main edits the SAME line, with a MERGED PR fixture for the branch whose
  `headRefOid` is the branch head, gives `LANDED (PR #n merged)`; the same with no PR fixture gives
  `UNPUSHED 2 (conflicts with main)`;
- a branch with one real unmerged commit gives `UNPUSHED 1` and names that commit;
- a `LANDED` worktree with an untracked file stays in findings with only the `untracked:` issue;
  one with a modified tracked file gets a `modified:` issue;
- a repo whose default branch is `master` resolves the main ref and fetches `master`;
- a repo with `origin/main` but no `origin/HEAD` resolves `origin/main`; a repo with no remote
  gives `UNKNOWN (no main ref)` and stays in findings;
- `--repo` reports a local branch with no worktree and no upstream that carries an unmerged commit;
- a worktree whose session's manager has been quiet since `--since` still gets that manager as
  `ownerSessionId`.

**Acceptance.** All cases pass. On the live machine, no worktree whose `HEAD` equals the merged
head SHA of a MERGED PR for its branch appears as at-risk in `handoff-sweep.json`; the proof
cross-checks that with `gh pr list --head <branch> --state merged --json number,headRefOid`. A
branch with commits after its PR merged is correctly at-risk and is not a regression.

### 6. Scheduled tasks are not swept

**What happened.** A one-shot scheduled task targeted a manager session on the old account. It had
already fired. A recurring one would have messaged a dead session forever, or never fired at all.

**Where the facts live** (read on 2026-11-16, four registries):

- The app's registry is per account and org: `<store>/<account>/<org>/scheduled-tasks.json`, a
  top-level object `{"scheduledTasks": [ ... ], "recordedSkips": {...}, ...}` with two more boolean
  bookkeeping keys. Read `.scheduledTasks[]` and ignore the rest.
- Each entry has `id`, `enabled`, `cronExpression` or `fireAt`, `filePath`, `cwd`, and optionally
  `notifySessionId`, `lastRunAt`, `lastScheduledFor`, `displayName`, `permissionMode`. `fireAt` is
  epoch milliseconds (null or absent on cron entries). `notifySessionId` is absent on some entries.
- The task prompt is at `filePath`, under `~/.claude/scheduled-tasks/<id>/SKILL.md`. Its body names
  target sessions in several forms: `local_<uuid>`, a bare UUID, or a short `local_<8 hex>`.

**Owner.** `handoff_sweep.py`, new `stranded_schedules(store, here, rows)`, where `rows` is the full
store. It owns all state left pointing at the other account, alongside row 7. `mine_all` already
runs this script in step 6.

**Change.** For every registry entry with `enabled: true`, classify its timing: due (it has
`cronExpression`, or `fireAt > now_ms`), or `missed` (`fireAt <= now_ms` and `lastRunAt` is null,
which happens when it came due while its account was signed out). A one-shot that has run is
excluded. Collect its targets: `notifySessionId` plus every id in its SKILL.md body, matched as
`local_<uuid>`, as a bare UUID (resolved against `sessionId` and `cliSessionId`), or as a short
`local_<8 hex>` resolved by prefix. An id that resolves to nothing is kept on the row as
`unresolved`, never dropped. Report the entry when any of these holds:

- `registry-elsewhere`: the registry file sits under an account other than `here`. It will not fire
  while that account is signed out.
- `target-elsewhere`: a target session belongs to an account other than `here`, or is archived.
- `missed`: as above, whatever the account.
- `no-target`: due, with no `notifySessionId` and no id in the body.

A row is suppressed when the here-account registry already holds an enabled, due task with the same
`filePath`, or one naming the row's owner session. That is the sign the owner already re-created
it; without the check, the old task (which cannot be disabled from here) would be reported and
re-created on every mine.

Each row carries `taskId`, `class`, `schedule`, `fireAt` as ISO, the `targets` (full ids, account
and title, plus `unresolved`) and `ownerSessionId`, which is the program root of the target found
by `pf.root_manager` with `roots`. `mine_report` routes the row into its program's `SWEEP_ROWS`, so
the catch-up carries it. A row with no owner becomes a founder kit line.

The fix the row prescribes: the owner re-creates the task on this account with the scheduled-task
tool, naming its own full session id, then disables the old task where it can reach it. A `missed`
row also asks the owner whether the missed wake's work is still owed. The sweep never edits
`scheduled-tasks.json`. The app owns that file, and a hand edit races the app's own writes.

**Deleted.** Nothing. This is a new check, and no other code reads the registry today.

**Test** (`test_handoff_sweep.py` plus `fixtures/handoff_sweep/scheduled-tasks.json`, copied from a
real registry file and de-identified, keeping every top-level key and entry field):

- the reader iterates `.scheduledTasks[]` of the real shape;
- an enabled cron task whose `notifySessionId` is on the other account gives `target-elsewhere`
  with the right owner;
- a task whose target is named only in the SKILL.md body, as a bare UUID or a short `local_<8 hex>`,
  is found; an id that matches nothing appears as `unresolved`;
- an enabled task in the other account's registry gives `registry-elsewhere`;
- an enabled one-shot with `fireAt` in the past and `lastRunAt` null gives `missed`;
- disabled tasks, and one-shots that have run, are excluded;
- a task targeting a here-account live session is excluded;
- a row is suppressed once the here registry holds an enabled task with the same `filePath`;
- an entry with no `notifySessionId` and no id in its body gives `no-target`.

**Acceptance.** All tests pass. On the live machine, `handoff-sweep.json` has a `staleSchedules`
list, and the receipt prints its count. The proof cross-checks it with `jq` over every registry:
`.scheduledTasks[] | select(.enabled)` whose `notifySessionId` row is on the other account. Live
data on 2026-11-16 holds one enabled task, so this check exercises one row unless more exist on
build day; the fixture carries the rest.

### 7. PR Auto-fix bindings are not swept

**What happened.** A PR stayed bound, with Auto-fix on, to a session on the old account. Its CI
events went nowhere.

**Where the facts live.** A binding is an entry in the session row's `prs[]`, the array
`list_sessions._pr_number` already reads. Its keys (census of rows changed since 2026-10-01):
`autoFix, baseRef, branch, dismissed, host, own, prNumber, provider, repo, state, url`. Hundreds
of entries carry `autoFix: true` with `dismissed: true`; those are not live bindings. `repo` appears
in more than one letter case for the same repository. `state` is written when the session last saw
the PR and goes stale.

**Owner.** `handoff_sweep.py`, new `stranded_bindings(rows, here, since_ms)`, where `rows` is the
full store.

**Change.** A binding is **live** when `autoFix` is `true` and `dismissed` is not `true`. A PR is
keyed by `(repo.lower(), prNumber)`. It is stranded when all of these hold:

- some row on another account holds a live binding to it;
- its state, re-checked with `gh pr view <n> --repo <repo> --json state` (only the few candidates
  that pass the other clauses are re-checked), is `OPEN`, or is `MERGED` while the binding row was
  active since `--since` (the keep-bound rule: the binding is held until main is green past the
  merge). If `gh` fails, the stored state is used and the row says `state unverified`;
- no non-archived row on `here`, in the full store whatever its activity, holds a live binding to
  the same key.

Only the other-account binding row's activity is windowed, and only for `MERGED`.

Each row carries `repo`, `pr`, `state` (live) and `storedState` when they differ, `branch`,
`boundSession` (full id and title) and `ownerSessionId`. The prescribed action: an `OPEN` PR is bound
by the owner (`bind_pr`, then `set_monitor` with `auto_fix: true`). A `MERGED` PR is bound only until
main is green past its merge, then unbound. The other account's binding cannot be removed from
here; it goes dead with that session, and the row says so. The rows route like row 6.

**Deleted.** Nothing. This is a new check.

**Test** (`test_handoff_sweep.py`, store fixture rows, `gh` stubbed):

- an OPEN PR with a live binding on an other-account row is stranded;
- the same PR also live-bound on a here-account row is not stranded, including when that here row
  is older than `--since`, and when its `repo` differs only in case;
- a here-row entry with `autoFix` absent does not count as a here binding;
- a binding with `dismissed: true` is excluded;
- a CLOSED PR is excluded, and a MERGED one whose binding row is older than `--since` is excluded;
- a PR stored as `OPEN` that `gh` reports `CLOSED` is excluded; one stored `OPEN` that `gh` reports
  `MERGED` follows the MERGED rule;
- a PR with `autoFix` absent or false is excluded.

**Acceptance.** All tests pass. `handoff-sweep.json` has a `strandedBindings` list, the receipt
prints its count, and each row appears in its owner's catch-up `{{SWEEPS}}`.

## Tier 2 — the gaps that cost retries

| # | Gap | Owner | Change |
| --- | --- | --- | --- |
| 3 | Trust is granted per folder, so an approval for the wrong folder did nothing | SKILL.md trust bullet (lines 68-72), and the founder kit string in `mine_report.build_plan` (line 142) | The ask lists every refused session as `title — exact cwd`, and says that trust belongs to that folder: approving another worktree of the same repo does not help. `pending-sends.md` records the cwd beside each refused send. |
| 4 | Short session ids fail in `send_message` | SKILL.md Relay / Converge paragraphs | Plan, relay, `pending-sends.md` and `replies.md` store the full `local_<uuid>`. Short ids appear only in receipt tables, for reading. `messages[].target` is already the full id; the rule covers the files the dispatcher writes by hand. |
| 5 | A ruling cannot reach the live children of a folded or archived manager | `mine_report.build_plan`, new plan field `ruling_recipients`, plus one SKILL.md line | `ruling_recipients` = every live manager here, plus every present (non-archived) lineage session on this account of any program with no live manager here, plus each absorbed program's absorber. ("Closed" programs have no present session by definition, so they add nothing.) SKILL.md: "a cross-cutting ruling is sent to `plan.ruling_recipients`; orphan children never load the role, so the ledger alone does not reach them." |
| 8 | A rename right after the catch-up made the manager read its new title as a second manager | SKILL.md Relay, CATCHUP_MESSAGE.md | Rename before sending the catch-up. The catch-up's first line says "Your title is now `<title>`; no other manager holds it." |
| 9 | The one-message budget leaves no room for a late find | SKILL.md send constraints, the CATCHUP_MESSAGE.md header | Each manager may get ONE absorption addendum after its catch-up, only to hand it a program found later in the same round (a row 1 candidate routed `absorb`). Every other follow-up still waits for the reply. |

Tier 2 tests: the plan's `ruling_recipients` for a fixture with a live program whose managers are
all archived, no absorber, and one present child on this account includes that child; an absorbed
program adds its absorber (`test_mine_all.py`). The trust kit string contains `cwd`. The wording
rows are proven by reading the diff, since they carry no behaviour a test can pin.

## Row 10 — every manager keeps its global state file's head current (founder, 2026-11-16)

The founder added this row on 2026-11-16 ("fix as proposed everything"). It is recorded as a dated
ruling in the operator's private rulings ledger.

**What happened.** A manager is global. Its state lives in
`~/.claude/orchestrator/programs/<slug>.state.md`, never in a worktree, because the next session
(another worktree, another account) starts with nothing else. Managers appended below and left the
head stale, so the next session read the wrong date and the wrong owner. File mtimes were all
2026-11-16, so mtime hid it. Measured on four live programs, re-checked for this spec on 2026-11-16:

| Program | Head before | Lines | Re-check |
| --- | --- | --- | --- |
| A | line 1 `updated_at: 2026-10-27T14:35:00Z`, names a session from that date | 3427 | Confirmed in the archived copy the manager moved to `A.notes/` when it rewrote the file today (now 1047 lines). |
| B | `# … state (updated_at 2026-10-26T19:22:11Z)` | 1948 | Confirmed in `B.notes/` (now 445 lines). |
| C | title line ends `manager local_<8 hex> …, updated 2026-11-03` | 2519 | Confirmed in `C.notes/` (now 644 lines, still 7 `## AT-WAKE` blocks). The archived `## VIEW` said `"updated_at": "2026-11-16T11:00:00Z"` while the head said 11-03: two "updated" facts in one file that disagree. |
| D | `# [Manager] … state (updated 2026-10-26T22:11:26Z)` | 2049 | Still stale today: 2049 lines, 263 `## AT-WAKE` blocks. |

The three managers that rewrote their files today wrote three different head formats. Without one
format, no check can read the head.

A to D are examples, not the fleet. On 2026-11-16, 15 state files had changed in the last 7 days, and
at least two more non-DONE ones carried a stale or dateless head over a log-shaped body (one 1321
lines with 80 AT-WAKE blocks, one 3648 lines with 538). Every manifest read that day had no `status`
key, so all of them count as non-DONE. The fleet this row must fix is defined by the census command:

```
find ~/.claude/orchestrator/programs -maxdepth 1 -name '*.state.md' -mtime -7
```

minus the programs whose manifest `status` is `done` or whose last `## AT-WAKE` says `Status: DONE`.
`render_state.py --program <slug> --context` names each one's head and log-shape defects.

**Owner.** `state_view.py`, new `read_head(text, now, problems) -> (head, reason)`. `head` is
`{updated_at, writer, account, since}` or `None`; `reason` is `ok`, `missing` (line 1 is not
head-shaped) or `unparsed` (a head is there but malformed). It already owns the authored part of the
state file, reads it strictly, and turns every bad input into a Problems row. Every reader goes
through it: `render_state`, `state_brief`, `role_brief`, and the Stop guard. Because `reason` comes
back with the head, the guard never sniffs line 1 itself: there is one head parser. The same module
owns the one head writer (below). Module top-level imports stay stdlib-only, because the guard
imports it under its time budget, as it does `role_brief`.

**Import paths.** The guard runs under `python3 -I` and loads `role_brief.py` by path
(`spec_from_file_location`), which does not put `scripts/` on `sys.path`. So `role_brief` imports
`state_view` lazily inside its health-line function, inserting `HERE` first, exactly as
`context_brief` does today (`role_brief.py:222`). A top-level `import state_view` would raise
`ModuleNotFoundError` in the guard, `role_facts` would catch it as `role_error`, and the enforced role
check would fail open on the day of the version bump.

**The head.** The first three lines of the file, before the `# ` title, exactly:

```
updated_at: 2026-11-16T13:37:51Z
writer: local_<uuid> (account <account id>)
since-last-session: <one line: what changed since the previous head, naming its writer and updated_at>
```

- `updated_at` is RFC3339 UTC to the second with `Z`, not in the future (the existing
  `check_time` plus a seconds requirement, as the manifest rule already has).
- `writer` is the full `local_<uuid>` of the session that wrote the head (row 4: full ids only). The
  account id is the store's account directory. It is a label for readers; checks compare only the
  session id. A bare CLI uuid is not a valid writer (A's ad hoc head today uses one).
- `since-last-session` is non-empty. On a program's first head it says `first head`.
- A missing, misordered or malformed key makes `read_head` return `(None, "missing")` or
  `(None, "unparsed")` with one Problems row naming the line and the expected form.

**The head writer.** Managers never compose or paste the head. One CLI writes it:

```
python3 state_view.py --write-head <slug> --since "<one line>"
```

- It resolves the writer from `CLAUDE_SESSION_ID`, which is the CLI uuid, not the `local_` id
  (`role_brief.py:302` has only that). Inside the CLI path, never at module top level, it calls
  `program_family.load_store()` and selects the one store row whose `cliSessionId` equals it. That
  row gives `sessionId` (the `local_` id) and `_acct` (the account directory), the same match
  `mine_all.detect_here` makes (`mine_all.py:59-61`).
- It stamps `updated_at` with the real current UTC time to the second, at the moment it runs, then
  rewrites lines 1-3 of `<slug>.state.md` in place (inserting them above the `# ` title when absent)
  and leaves the rest of the file byte-identical.
- It refuses, writes nothing and exits non-zero when the lookup fails: no `CLAUDE_SESSION_ID`, no
  store row, more than one row, or an empty `--since`. The message names which, for example
  `write-head refused: CLAUDE_SESSION_ID <8 hex> matches no store row`. It never falls back to
  writing the CLI uuid.
- After writing, it re-reads the file through `read_head` and exits non-zero unless the reason is
  `ok`, so the writer and the parser cannot drift.

**Change.**

- **(a) Rewrite the head on every turn that changes state.** That covers the founder's "every manager
  turn that changes state". Role card line and wake step 5: "run
  `state_view.py --write-head <slug> --since "<what changed>"` as the turn's last state write, then
  update `## VIEW`". `role_brief` prints that exact command with the slug filled in, never a pasted
  template: a template's time would be stale from the next turn on.
- **(b) Dated lines.** In `## VIEW`, `done` and `decisions` rows now need a `date`. A row without one
  is still shown, tagged `date_missing`, with a Problems row (never dropped). Done, decision and
  ruling lines outside `## VIEW` start with their absolute date. That is a role-card rule with no
  machine check, because free prose cannot be parsed reliably.
- **(c) Current state, not a log.** The file holds exactly one `## AT-WAKE` block and one `## VIEW`
  block, rewritten in place. Superseded material moves to `<slug>.notes/` (prose) or
  `<slug>.events.jsonl` (events). `render_state` adds a `State file` Problems row when it counts more
  than one of either heading: "N AT-WAKE blocks: the file is current state; move the superseded
  blocks to `<slug>.notes/`". The guard's last-block rule (`at_wake_tail`) is unchanged and still
  reads the right block either way.
- **(d) The Stop guard checks the head** (§Guard change below).
- **(e) Nothing program-critical lives only in a worktree.** The role card's child-notes line names
  the absolute path `~/.claude/sessions-to-chips/relay/<slug>/child-notes.md` instead of the relative
  `relay/<slug>/…`, and adds "never in a worktree". The contract already names that folder.

**Guard change** (private harness; mirrors the existing page check line for line):

- New `head_facts(state_text, records, now, own_ids, read_head)` returns `{head_due, head_reason}`.
- **Turn start** is `records[turn_spans(records)[-1][0]]["timestamp"]` (`turn_spans` returns index
  ranges, not records), rounded down to the whole second. The head carries whole seconds, so without
  rounding a head written at `13:37:51Z` in a turn opening at `13:37:51.800Z` would read as stale.
- **Due** when the manifest is not done, the last `## AT-WAKE` does not say `Status: DONE`, and this
  turn changed state: it changed the state file (`page_facts.state_changed_this_turn`), or any tool
  use in the turn `tool_acts` (a dispatch, message, merge, non-state-file edit or mutating Bash).
  A turn that only reads, or a silent CI event that needs nothing, is normally not due. This is
  best-effort, not exact: `state_changed_this_turn` counts any Bash that names the state file and
  runs `python3` (`manager_arm_guard.py:695-697`), so a read-only `python3` over the file can make a
  turn due. The cost is one extra `--write-head` run, never a wrong pass. A grill round is not
  exempt: the questions it asks are state.
- **Reasons**, checked in this order, mapped one-to-one from `read_head`'s reason so the guard has no
  parser of its own: `head_missing` (reason `missing`), `head_unparsed` (reason `unparsed`),
  `head_foreign` (`writer` is not this session's `sessionId` or local id), `head_older_than_turn`
  (`updated_at` < turn start).
- **Shadow by default**: the guard's JSONL row gets `head_reason` set to one of `ok`, `head_missing`,
  `head_unparsed`, `head_foreign`, `head_older_than_turn`, plus the `turn` id (so a block and its
  passing stop can be paired), and, when not `ok`, the `would_block` tag
  spelled exactly `would_block:head_missing`, `would_block:head_unparsed`, `would_block:head_foreign`
  or `would_block:head_older_than_turn` (never `head_head_*`). A clean turn is visible too.
  `touch ~/.claude/run/manager-head-check.enforce` (env `MANAGER_HEAD_CHECK_ENFORCE_FILE`) makes it
  block once per turn on its own stamp (`<cli>.head.turn`), after the page check and before the arm
  check. An enforced block logs `decision: "block"`, `reason: "<head_reason>"` (so `reason` starts with
  `head_`), with `would_block` null, as the enforced page check does today. The block message names
  the reason and prints the exact `state_view.py --write-head <slug> --since "…"` command to run.
- **Chained blocks keep every check alive.** `once_guard` skips a check when `stop_hook_active` is
  set and that check's stamp is under `LOOP_BACKSTOP_S` (900 s) old (`manager_arm_guard.py:418`).
  Today only the role path strips the inherited flag, and only before the arm check (`:766-769`).
  The page check is already enforced on this machine and has no strip, so a head block (or a role,
  page or org-uuid-check block) would let the following stop in the same turn skip the later checks,
  including the arm check: a manager could end WORKING with no wake armed. Generalise the strip into
  one helper run before **each** check (role, page, head, arm): if any stamp among `.role`, `.page`,
  `.head` and the arm stamp equals this turn and the check about to run has not blocked this turn,
  drop `stop_hook_active` for that check. The check's own stamp still stops it blocking twice in one
  turn, and the 900 s backstop still bounds a loop.
- **Fail open**: an import or parse error in loading `read_head` logs `head_error:<type>` and never
  blocks, like `role_error`.

**Ownership: keel vs the private harness.**

| Piece | Lives in | Public-safe |
| --- | --- | --- |
| The head format, `read_head` (the one parser) and `--write-head` (the one writer), its tests, the render and brief readers, role.md, contract | keel, this repo | Yes. The format, rule and check names carry no machine or program facts. |
| The decision (due, shadow or enforce, message, stamp), its tests, the enforce file | `~/.claude/scripts/manager_arm_guard.py` and `test_manager_arm_guard.py`, the operator's private harness | It imports `read_head` by path from the skill's `scripts/` (the `load_role_module` pattern) and never copies the rule. |
| Program slugs, which heads are stale, migration progress | the private state files and relay | Never written here; this spec says A to D and names the census command, not its output. |

`render_state` already imports the guard for its AT-WAKE facts. That runs in the other direction and
does not change.

**Deleted.**

- The `## VIEW` `updated_at` key: `state_view.TEXT` drops it, and so does its check
  (`state_view.py:132-133`). `render_state.staleness` (`:473-482`), the payload's `updated_at`
  (`:565`), `author_line`'s "updated_at: set it after the edits" (`:513`) and `state_brief`'s
  "Narrative updated" (`:211`) read the head instead. A VIEW block that still has `updated_at` gets a
  `V1_HOME` entry ("moved to the file head"), so it shows under "not migrated" and is never dropped
  silently. One "updated" fact per file.
- Wake step 5's "set `updated_at`" and step 7's "Append a block" (role.md). Step 7 becomes "Rewrite
  the one `## AT-WAKE` block in place". Contract line 27's "`updated_at` fresh in your state file"
  points to the head.
- Four more instructions that still tell managers to keep a state-file or VIEW `updated_at` fresh
  (probe, 2026-11-16: `grep -rn updated_at .claude/skills/sessions-to-chips --include='*.md'`,
  excluding `specs/`), each re-pointed to the head and the `--write-head` command:
  `WRAPUP_MESSAGE.md:25` ("a current `updated_at`"), `SKILL.md:173` ("has a fresh `updated_at`"),
  `references/manager-contract.md:467` (the VIEW schema lists `updated_at` first; the key is removed
  from that list) and `references/manager-contract.md:818` (the DONE close-out's "fresh
  `updated_at`"). The other hits in that grep (contract `:349`, `:382-384`, `:503`) are the
  **manifest's** `updated_at` and stay.
- No second head parser exists to delete. Probe, 2026-11-16: `grep -n "updated_at" scripts/*.py`
  (non-test) and the same grep over the guard. Every other hit reads the **manifest** JSON
  (`mine_all.py:98,102`, `program_family.py:209`, `work_state_migrate.py:133`, the guard's
  `find_program`) or `<slug>.arch.json` (`state_arch.py`). Those are different files and different
  facts, and they stay. The AT-WAKE stamp that `render_state.read_at_wake` reads is the wake record's
  own time and also stays. `mine_all.checkpoint_for` keeps using the state file's mtime. mtime is
  never earlier than the head's `updated_at`, so the window stays conservative.

**Migration** (the guard must not brick managers on day one):

1. **Day 0, the ship.** The keel commit edits role.md, which changes the computed role version. The
   enforced ROLE CHECK then makes every non-DONE manager run `/manager-role <slug>` at its next turn.
   The delta shows the head rule, and the new `role_brief` health line names the exact defect for
   that program (missing, unparsed, foreign or older than the newest event). The guard half lands
   in shadow, so nothing blocks on the head yet.
2. **Who rewrites.** Each program's own manager, at its first wake after the role change. Nobody
   rewrites another program's head: a dispatcher's rewrite would itself be a foreign head. Every
   program in the census converts its head by running `state_view.py --write-head`, which replaces
   whatever ad hoc lines are there (A's `session: <bare uuid>` head included: a renamed key would
   still fail, because a bare CLI uuid is not a valid writer). C also folds its 7 AT-WAKE blocks
   into one, and so does every other census program the `State file` problem names. D does a full current-state rewrite: its
   2049-line file moves to `D.notes/state-log-through-<date>.md`, and the new file keeps one AT-WAKE
   and one VIEW block. A program with no live manager keeps its stale head. The page and the role
   brief show it, and the next manager to take the program rewrites it at takeover (contract: the
   takeover writes a fresh state file).
3. **Enforce.** The Harness manager runs
   `touch ~/.claude/run/manager-head-check.enforce` once both of these hold over the last 24 h of
   the guard log (the shadow window; it replaces any replay of the old log, whose rows hold verdicts
   only, not the transcripts or head lines the check needs): every live non-DONE manager has at
   least one `head_reason: "ok"` row, and there are zero `would_block:head_*` rows. Proof command:
   `jq -r 'select(.ts >= "<now-24h>") | select((.would_block // []) | any(startswith("would_block:head_"))) | .program' ~/.claude/analytics/manager-arm-guard.jsonl | sort | uniq -c`
   prints nothing.

**Rollback.** `rm ~/.claude/run/manager-head-check.enforce` reverts the head check to shadow. A
shadow-mode bug costs log rows only, never a block. A broken role-version bump (the Day 0 risk) is
switched off with the existing kill switch, `touch ~/.claude/run/manager-role-check.off`
(`MANAGER_ROLE_CHECK_OFF_FILE`, `manager_arm_guard.py:85`), not by another role.md edit: a second edit
bumps the version again and blocks every manager once more.

**Test.**

- keel `test_render_state.py`: `read_head` accepts the canonical three lines with reason `ok`. It
  returns `(None, "unparsed")` with one Problems row for each of: a missing key, misordered keys, a
  date-only `updated_at`, a future `updated_at`, a short `local_<8 hex>` writer, a bare CLI uuid
  writer, and an empty `since-last-session`. A file whose line 1 is the `# ` title returns
  `(None, "missing")`. Each of the real formats from the table (A, B, C, de-identified) is rejected
  with a row naming the expected form.
- keel `test_render_state.py`, `--write-head` against a temp store (`S2C_STORE`) and programs dir:
  with one store row whose `cliSessionId` matches, it writes `writer: local_<uuid> (account <dir>)`
  and an `updated_at` within a second of now, replaces an existing ad hoc head, inserts above a bare
  title, leaves every later byte unchanged, and its output passes `read_head` as `ok`. With no
  matching row, two matching rows, no `CLAUDE_SESSION_ID`, or an empty `--since`, it exits non-zero,
  names the failure, and the file is byte-identical.
- keel `test_render_state.py`: a VIEW with `updated_at` shows it under "not migrated" with the
  head as its home; `staleness` reads the head; a `decisions` row with no `date` is still shown,
  tagged `date_missing`; two `## AT-WAKE` blocks give the `State file` problem, and one does not.
- keel `test_role_brief.py`: the health line fires for a missing head, for a foreign writer, and for
  a head older than the newest event; the wake steps print the `--write-head` command with the slug
  filled in, and no head template.
- private `test_manager_arm_guard.py`: load `role_brief.py` by path in a `python3 -I` subprocess, as
  the hook does, and confirm `role_facts` returns no `role_error` (pins the lazy `state_view` import).
- private `test_manager_arm_guard.py`, beside `test_page_not_rendered_is_shadow_until_the_touch_file`:
  each of the four reasons in shadow logs its exact `would_block:head_<reason>` tag (for example
  `would_block:head_missing`) and returns no block; with the enforce file, an acting turn with a head
  older than the turn's start blocks once with `reason: "head_older_than_turn"`, and the second stop
  in that turn does not; a head whose `updated_at` equals the turn start's whole second passes; a
  read-only turn with no `python3` naming the file is not due; a DONE program is exempt; a fresh head
  written by this session logs `head_reason: "ok"`; a `read_head` that raises logs `head_error` and
  does not block.
- private `test_manager_arm_guard.py`, chained blocks, each with a fresh (< 900 s) stamp for the
  later check from an earlier turn: an enforced head block, then a second stop in the same turn with
  `stop_hook_active: true`, still runs the page check and the arm check (head→page, head→arm); a role
  block followed by a second stop still runs the head check; a page block followed by a second stop
  still runs the head check.

**Acceptance.** All tests pass. After the role change, every program the census command lists
(non-DONE, state file changed in the last 7 days; A to D are among them) has a head that `read_head`
parses as `ok`, written by its own manager after the ship: `head -3 <slug>.state.md` plus
`render_state.py --program <slug> --context` show no head or log-shape problem. A program with no
live manager is listed by name as still stale, never counted as passing. The guard log meets the
enforce criterion above before the switch is flipped. D's file holds one AT-WAKE block. Proof that
the head stays current, a week after enforce: every enforced head block is followed by a passing stop
in the same turn. Query:
`jq -c 'select(.ts >= "<enforce-time>") | select(((.reason // "") | startswith("head_")) or .head_reason == "ok") | {ts, session, turn, reason, head_reason}' ~/.claude/analytics/manager-arm-guard.jsonl`;
each row with `reason` starting `head_` has a later row with the same `session` and `turn` whose
`head_reason` is `"ok"`. The query matches on `reason`, not `would_block`, because an enforced block
leaves `would_block` null.

## Ships

| Ship | Contents | Why one |
| --- | --- | --- |
| 1 | Tier 1 rows 1, 2, 6, 7, tier 2 rows 3, 4, 5, 8, 9, and row 10, with tests | Rows 2, 6 and 7 route by `ownerSessionId` over `roots`, which row 1 introduces. The SKILL.md wording describes plan fields the same change adds. Row 10 edits role.md and the contract in the same skill, and one role-version change is cheaper than two: each change blocks every manager once. No hard ordering dependency splits it. |

The ship is two commits in a fixed order. First the keel commit, so `read_head` exists. Then the
private-harness commit with the guard's head check, in shadow. If the guard commit lands first, its
import fails and it logs `head_error` without blocking, so the order is safe either way.

The repo has no CI. The local verify gate is
`python3 -m unittest discover -s .claude/skills/sessions-to-chips/scripts -p 'test_*.py'`
plus `tooling/leak-check.py --staged`. The private half runs
`python3 ~/.claude/scripts/test_manager_arm_guard.py`. A role.md edit needs its `## Changes` line,
or `role_brief.py --check-staged` refuses the commit. The live proof is one `mine_all.py --dry-run`
on the machine, read against the acceptance lines above. It is owed after the merge, because only
real stores hold the incident's shape. Row 10's live proof is the migration and enforce criterion,
also owed after the merge.

## Spec-review tier

**Standard.** This is behaviour-bearing tooling: it changes what the mine reports and when the relay
may start. No critical gate fires. It touches no access control, credentials, money or tenancy.
Session titles and ids are operator metadata, not customer data. The spec writes no app-owned
state: schedules and bindings are reported, and the owner fixes them through the app's own tools.
The only new writes are the skill's own routes file (one validated writer) and `git fetch`
updating remote-tracking refs. If review moves any row to writing `scheduled-tasks.json` or session
rows directly, the tier rises to critical.

Lanes worth adding at standard: edge-case (candidate thresholds, merge-tree conflicts, fetch
failure) and live-evidence (the registry and `prs[]` shapes, read again on the day of the build).
Row 10 adds a Stop-hook check that can block every manager turn, so it also adds the operator-plane
lane: guard blast radius, the 24 h shadow window before enforce (the existing guard log holds
verdicts only, so it cannot be replayed through the head check), and the once-per-turn stamp
interplay with the role and page checks. Shadow-first keeps the
tier at standard; enforcing without the shadow window would raise it.

## Review log

Three lanes reviewed the first draft on 2026-11-16: edge-case (A), live-evidence (B), architecture
(C). Every claim with a code anchor was re-checked against the scripts before fixing.

| Finding | Outcome |
| --- | --- |
| A1, B3, C1 — PR clause has no window; ~350 old candidates | Fixed: candidate's own `lastActivityAt` in window. A1's "count only OPEN or in-window PRs" rejected: `prs[]` has no timestamp, and own activity already cuts the set to single digits. C1's "exclude archived unless a child is active" rejected: an archived root active in the window may have live children and still needs routing. |
| A2, C2 — nested candidates; the mine routes itself | Fixed: root condition (no candidate or non-manager parent in the store) and `self_cli` exclusion. |
| A3 — candidate set computed three times, circular `since` | Fixed: computed once at the window floor in `mine_all`, passed as `--roots`. |
| A4, C5 — routed lineage loses its owner | Fixed: routes feed `roots`; `absorb` maps to the absorber, `promote` stays a root, `leave` drops. |
| A5 — merge-tree misses main editing the same lines | Fixed: merged-PR step (live `gh`, head SHA match) before merge-tree; the no-PR case is named as `UNPUSHED <n> (conflicts with main)`, failing toward keeping work. Test edits the same line. |
| A6 — `LANDED` drops untracked/gutted state | Fixed: `LANDED` removes only the unpushed issue; `modified:` issue added. |
| A7, C8 — windowed rows break owner walk and here-binding lookup | Fixed: full store for ancestry and lookups; window only on findings; owner-less rows become founder kit lines. |
| A8, B1, C6 — registry shape wrong, `fireAt` epoch ms, `notifySessionId` optional | Fixed: real shape, ms, optional field, `no-target` class, fixture copied from a real file. |
| A9 — duplicate re-creation every mine; missed one-shots excluded | Fixed: suppression when the here registry already holds the task; `missed` class. |
| A10, B6 — stale `prs[].state`, case-sensitive repo key, here binding without autoFix | Fixed: live `gh` re-check, lowercased key, here binding must be live. |
| A11 — `ruling_recipients` clause empty by construction | Fixed: recipients cover programs with no live manager here; test fixture corrected. |
| A12 — two slug functions | Fixed: `pf.program_slug` is the one slug; `child_ledger.slug` deleted; test title has a colon. |
| B2, C7 — `dismissed` ignored | Fixed: live binding = `autoFix` true and `dismissed` not true; real key set named. |
| B4, C11 — no `origin/HEAD` fallback; fetch of a full ref fails | Fixed: `origin/HEAD` → `origin/main` → `origin/master` → `UNKNOWN (no main ref)`; fetch uses the short name. |
| B5 — branches without worktrees lose coverage | Fixed: `landed(repo, ref)`; `--repo` also walks `for-each-ref refs/heads`. |
| B7 — body targets only as `local_<uuid>` | Fixed: bare UUID and short-id matching, `unresolved` kept. |
| C3 — candidate program missing downstream fields | Fixed: built through the manager-program path; field table added; test pins it. |
| C4 — routes file has no writer | Fixed: `program_family` owns path and reader; `mine_report.py --route` is the one validating writer. |
| C9 — `root_manager` starts at self, candidate ledgered as its own child | Fixed: `child_ledger` walks from the parent and skips candidate rows. |
| C10 — more `[Manager]`-title copies | Fixed: `coverage_audit` Test B, `wrapup_roster.has_manager_ancestor`, `hygiene_candidates.descendants` listed and rerouted. |
| C12 — invalid merged-PR acceptance; "Read-only" docstring | Fixed: cross-check restricted to `HEAD` = merged head SHA; docstring updated. |

Row 10 was added after that review, on 2026-11-16, at the founder's request. Its four measurements
were re-checked against the live files and the archived copies the managers wrote today; all four
match.

Two lanes then reviewed row 10 on 2026-11-16: edge-case (R10a) and operator-plane (R10b). Each code
anchor was re-read in the guard, `role_brief.py`, `mine_all.py` and the skill's markdown before
fixing; the census was re-run (15 state files changed in the last 7 days).

| Finding | Outcome |
| --- | --- |
| R10a-3, R10b-1 — a block leaves `stop_hook_active` set, so later checks (arm included) skip on a fresh stamp | Fixed: the `:766-769` strip is generalised to one helper run before every check; chained head→page, head→arm, role→head and page→head tests added. |
| R10a-4, R10b-2 — `role_brief` knows only the CLI uuid, so its template's writer fails or reads as foreign; the template's time is stale next turn | Fixed: `state_view.py --write-head <slug> --since` resolves `local_` id and account via `program_family.load_store()` by `cliSessionId`, stamps the real current time, refuses and names the failure on lookup failure; role card and block message run it; no template. |
| R10b-3 — a top-level `import state_view` in `role_brief` fails under `python3 -I` and fails the role check open | Fixed: lazy import inside the health-line function, like `context_brief`; `-I` load test added. |
| R10a-1 — A to D undercount the fleet | Fixed: census command defines the fleet; A to D are examples; acceptance covers every census program. |
| R10a-2 — post-enforce proof can never fail; `head_head_*` tag ambiguity | Fixed: exact tags spelled out; enforced block logs `reason` starting `head_` with `would_block` null; proof pairs it with a later same-turn `head_reason: "ok"` row; rows carry `turn`. |
| R10a-5 — four live `updated_at` instructions missing from Deleted | Fixed: `WRAPUP_MESSAGE.md:25`, `SKILL.md:173`, `references/manager-contract.md:467` and `:818` added, with the probe; manifest hits named as staying. |
| R10a-6 — `read_head` returns `None` for both missing and unparsed, forcing a second parser | Fixed: `read_head` returns `(head, reason)`; the guard maps the reason. |
| R10a-7 — "read-only turn never due" overstated; turn start written as a span; no time source for later turns | Fixed: claim softened to best-effort with the `python3` detector named; turn start is `records[turn_spans(records)[-1][0]]["timestamp"]`; `--write-head` is the time source. |
| R10b-4 — a head written in the turn's first second reads as stale | Fixed: turn start rounded down to the whole second; test added. |
| R10b-5 — the guard log cannot be replayed through the head check | Fixed: replay dropped; the 24 h shadow window is the pre-enforce evidence (Migration step 3, Spec-review tier). |
| R10b-6 — rollback names only the enforce file | Fixed: Rollback paragraph names `manager-role-check.off` for a broken bump and states a shadow bug costs log rows only. |

No finding was rejected.
