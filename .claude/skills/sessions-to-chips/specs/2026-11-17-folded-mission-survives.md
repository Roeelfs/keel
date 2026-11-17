# A folded program's mission survives

Row 11 of the account-switch gaps (founder, 2026-11-17). When one program is folded into another,
the absorber takes over the absorbed program's owed items but not its goal. Nothing records the fold
in a way every reader agrees on, and nothing checks that someone still drives the absorbed goal.

This spec makes `absorbed_by` the **only** record of a fold, and records the fold's mission state on
the same manifest. A fold is therefore one write to one file. The absorber's absorbed set, its open
missions and its folded bindings are all **derived** by inverting `absorbed_by`, so no second record
exists to drift. The work-state engine then flags an open mission with no driver. Every rule has one
owner; where a rule has copies today, the spec names the copy it deletes.

*(Rework of `033b713` after critical-tier review; the design change and every finding are in the
Review log.)*

## What happened

A customer-simulation program ("simulate brand-new customers walking every access path to first
value") was folded into a release program during an account-switch takeover on 2026-11-16.

- The release program's state file gained a `## Taken over from <program>` section listing the
  owed items: one parked PR, one grant, one bake, one live child. It names no goal.
- The absorbed program's persona tickets stayed in Backlog and its drive sessions stayed parked.
  No session or lane drove "reach first value" after the fold.
- At the fold, the absorbed manifest kept `absorbed_by: null` and the absorber's `absorbs` list did
  not gain it. On 2026-11-17 the absorbed manifest's `absorbed_by` was set **by hand** (file
  modified 09:01, no `absorb` event in its log). So `mine_report` now emits a `fold-notice` and
  `state_index.live_program` is false for it. But the absorber's engine never reads the absorbed
  manifest: its bindings, several with session carriers, are judged by nobody, and because it is
  absorbed, `ctx["absorbed"]` suppresses its own UNBOUND and READY flags (`work_state.py:448,496`).

**The fold has no writer today.** Every `absorbed_by` / `absorbs` hit in `scripts/` is a read
(`program_family.py:208,407,414`, `mine_all.py:147`, `mine_report.py:106,190-193,284`,
`state_index.py:45`, `work_state_sources.py:253,318`, `work_state_waiters.py:10`); the operator
harness has none either (`grep -rn absorbed_by ~/.claude/scripts ~/.claude/hooks`, 2026-11-17,
zero hits). Managers hand-edit manifests or write prose, so the live store records folds several
ways (2026-11-17, python scan of `~/.claude/orchestrator/programs/*.json`, 124 manifests):

| Shape | Count | Seen by `absorbed_by` readers |
| --- | --- | --- |
| `absorbed_by: <slug>` | 10 manifests (incl. the row-11 hand edit; 2 also carry `status: absorbed`) | yes |
| `status: merged-into-<slug>` / `superseded-by-<slug>` / bare `superseded` | 9 manifests | no |
| `superseded_by: <slug>` (absorbed side) / `supersedes: <slug>` (absorber side) | 1 pair | no |
| absorber `absorbs: ["<slug>"]` | 4 absorbers, 6 entries | yes (`program_scope`) |
| absorber `absorbs: [{"program": ..., "fold": ..., "status": ...}]` | 1 absorber, 3 entries | no: `program_scope` keeps only strings |
| prose section in the absorber's state file only | the row-11 case | no |

Two more live facts shape the design. 5 absorbed manifests hold 65 open bindings that no live
engine judges (carriers: 20 session, 237 lane, 17 bg, 4 agent, 8 workflow). 4 absorbed manifests
are still unmigrated (`lanes` / `claims`). One absorbed/absorber pair shares an open ticket.

## Design: one record, one file, everything else derived

The rejected first draft moved bindings and wrote a `missions[]` row into the absorber under two
locks. That was a cross-manifest transaction the store cannot make atomic: `_Locked.write`
replaces one file (`work_state_store.py:258-265`), events are separate appends (`:274-277`), and
readers take no lock (`:239-241`). It also left two records of one fold (`absorbed_by` and the
mission row). This design removes the transaction instead of hardening it:

| Fact | Its one record | Everything else |
| --- | --- | --- |
| A was folded into B | `A.absorbed_by = "B"` | B's absorbed set: derived by inverting `absorbed_by` |
| Who owns A now | none stored | `terminal_owner(A)`: follow `absorbed_by` to the end |
| A's goal | `A.goal` (unchanged) | B's page and snapshot read it from A |
| A's mission open / closed | `A.fold.closed` | B's open missions: derived |
| A's tickets, map, tracker | `A.bindings`, `A.map`, `A.snapshot_cmd` (unchanged) | B's engine judges them against A's tracker |

A fold is one locked write to A's manifest: `absorbed_by` plus `fold`. Bindings never move, so
there is no collision to merge, no lost or duplicated binding on a crash, and no window in which a
binding sits in a "wrong" home: any manager that binds into A writes where A's owner reads.

## Files

| File | Change |
| --- | --- |
| `scripts/work_state_store.py` | Owns the fold write. New `absorb()`, `close_mission()`, `reopen_mission()`; `FOLD_KEYS` strict validator, called only by those writers. `bind` refuses a ticket already bound elsewhere in the owner's fold family. |
| `scripts/program_family.py` | Owns the fold resolver: `terminal_owner(slug, manifests)` and `fold_family(slug, manifests)`, with cycle detection. `load_manifests` carries `absorbed_by` and `fold`, drops `absorbs`. |
| `scripts/work_state_sources.py` | `program_scope` takes absorbed slugs from `fold_family` (deletes the `absorbs` read at `:253`). `build_ctx` builds one sub-context per folded manifest (its own bindings, its own tracker tier, `live_bg` unknown). |
| `scripts/work_state.py` | Verbs `absorb`, `mission-close`, `mission-reopen`; `migrate --folds` dispatch. derive: `MISSION_UNDRIVEN` (blocking), folded-binding flags lifted as non-blocking, folded carriers counted as bound for UNBOUND, no `DONE` exemption while a mission is open, emits `missions`; `run_snapshot` caches it. |
| `scripts/work_state_migrate.py` | New `migrate_folds()` (census, apply, finish, verify, restore). `migrate_program` refuses when the manifest's bindings changed between planning and the locked write. |
| `scripts/work_state_waiters.py` | `_programs` / `_owners` count bindings on absorbed manifests, owned by their terminal owner. |
| `scripts/state_index.py` | `live_program` is true for a program that is the terminal owner of an open mission, whatever its status. |
| `scripts/mine_report.py`, `scripts/mine_all.py` | Fold-notice target, ruling recipients, `closed-program-rows` target and `absorb <slug>` candidate routes resolve through `terminal_owner`. Route records stay as written. The fold-notice text keys on "`absorbed_by` set and no `fold` record". |
| `scripts/render_state.py` | Renders the owner's open missions on the derived page next to `goal`. |
| `scripts/role_brief.py` | One health line per undriven open mission, read from the snapshot cache. |
| `references/manager-contract.md`, `SKILL.md`, `CATCHUP_MESSAGE.md` | The takeover order runs `absorb` before step (4); "bind each child" becomes `bind --program <absorbed>`; the `absorbs` wording goes; the fold-notice paragraph names the verb. |
| `scripts/test_work_state.py`, `scripts/test_render_state.py`, `scripts/test_role_brief.py`, `scripts/test_mine_all.py` | Tests below. |

## Rules and owners

### 1. The fold record and its one writer

**Record.** On the absorbed manifest only: `absorbed_by: "<absorber>"` and
`fold: {"id": "<absorbed>@<since>", "since": "<ISO>", "by": "<session id>", "closed": null | {"at": "<ISO>", "reason": "<text>"}}`
(strict keys, `FOLD_KEYS`). The absorber's manifest gains nothing. The manifest key `absorbs` is
deleted (rule 5). `absorbed_by` set with no `fold` is the pre-spec hand-edit shape: readers treat it
as an open mission with the note `fold_record_missing:<slug>` (rule 3), so it fails loud.

**Writer.** `work_state_store.absorb(absorber, absorbed, *, by, closed_reason=None, now)`, reached
through `work_state.py absorb --program <absorber> --from <absorbed> [--closed-reason "<text>"]`
and from `migrate --folds --apply`. Nothing else writes `absorbed_by` or `fold`.

**Admission**, checked under the absorbed manifest's lock against a fresh read of every manifest:

- Refuse `absorbed == absorber`.
- Refuse when the absorber is itself absorbed; the message names `terminal_owner(absorber)`, the
  slug to fold into instead.
- Refuse when `terminal_owner(absorber)` chain contains `absorbed` (a cycle).
- Refuse when the absorbed manifest's `absorbed_by` names a different slug; the message names it.
- Refuse an **open** fold (no `--closed-reason`) into an absorber whose status is DONE or CLOSED,
  or whose manifest has no `manager_session`: the goal would go to an owner who gets no turn. A
  closed fold (history) is allowed into any existing absorber.
- Refuse when the absorbed manifest has no `goal`.
- Note, do not refuse: `fold_no_tracker` when the absorbed manifest has no `snapshot_cmd` (13 of
  19 folded manifests today). Its mission can then be driven only by a binding on its map ticket
  itself, which `bind` already accepts with no tracker (`work_state_store.py:331-333`).

**The write.** One `_Locked(absorbed).write`: set `absorbed_by`, set `fold`. Then append
`{"event": "absorb", "fold_id": ..., "from": ..., "into": ..., "by": ..., "closed": ...}` to the
absorbed log, then the same row to the absorber log.

**Crash safety.** The manifest write is the commit point; it is one `os.replace`, so a reader sees
the fold fully or not at all. Events are history and **no reader decides anything from a fold
event**. A retry with the same arguments finds `absorbed_by == absorber` and a `fold`, then appends
whichever of the two `absorb` rows carrying that `fold_id` is missing, and returns success only
when both exist. With `absorbed_by == absorber` and no `fold` (the row-11 hand edit), the retry
writes the `fold`: a repair. A retry never writes a second `fold`.

**Mission state.** `work_state.py mission-close --mission <absorbed> --reason "<evidence>"` sets
`fold.closed`; `mission-reopen --mission <absorbed> --reason "<why>"` sets it back to `null`. Each is
one locked write to the absorbed manifest plus an event to both logs, repaired by retry the same
way. A non-empty reason is required. A founder decision to park the goal is closed this way, with
the founder named in the reason. A `fold` is never deleted.

**Validation stays off the read path.** `FOLD_KEYS` runs only inside the three writers, like
`validate_repo` (`work_state_store.py:177`), never in `_Locked.write` or `build_ctx`. On the read
path a malformed `fold` becomes the note `fold_malformed:<slug>` and counts as open and undriven.
It never raises `SchemaError`, because the Stop guard treats a `SchemaError` flag step as blind and
blocks the turn (`manager_arm_guard.py:874-876`, `:446-447`); one bad hand edit must not block every
Stop. Bindings gain **no** new key, so a code revert never meets an unknown binding key on the
`validate_bindings` read path (`work_state_sources.py:272`).

### 2. One resolver for who owns a fold

**Owner.** `program_family.terminal_owner(slug, manifests)` follows `absorbed_by` until a manifest
with none. `fold_family(slug, manifests)` returns every manifest whose terminal owner is `slug`.
A cycle, or a target slug with no manifest, returns no owner plus the note
`fold_cycle:<slugs>` / `fold_target_missing:<slug>`; the caller treats the folded program as
unowned and the engine flags its open mission on itself rather than guessing an owner.

**Readers routed through it** (each replaces an immediate-target read):

- `program_scope` (`work_state_sources.py:253`): `[slug] + fold_family(slug)`. This keeps scope for
  every former string `absorbs` entry and adds the 3 dict entries `program_scope` dropped before;
  scope no longer depends on whether a mission is open.
- `mine_report`: fold-notice `absorber`, ruling recipients (`:106-108`), and the
  `closed-program-rows` target (`:190-193`) use `terminal_owner`.
- `mine_all.candidate_owner` (`:107-119`): an `absorb <slug>` route keeps its recorded target and
  resolves the effective owner as `terminal_owner(target)`. Permanent route records are not
  rewritten.
- `work_state_waiters`: an absorbed manifest's bindings count toward ticket ownership, owned by its
  terminal owner (today `_programs` drops them at `:9-11`).
- `state_index.live_program`: a terminal owner of an open mission is live even when DONE/CLOSED, so
  mining never hides an owner that still owes a goal.

**Chains.** If C was folded into B and B later into A, nothing is rewritten: `C.absorbed_by` stays
`B` as history and `terminal_owner(C)` is `A`. C's open mission is A's.

### 3. The absorber judges its folded manifests

**Owner.** `work_state.py derive`, for the terminal owner. A folded program's own derive keeps
`ctx["absorbed"]` and its UNBOUND/READY suppression: the owner reports, not the stopped manager.

**Folded sub-contexts.** `build_ctx` builds one sub-context per member of `fold_family(slug)` that
holds bindings or an open mission. Each uses that manifest's own bindings, its own tracker tier
through its own `snapshot_cmd` (TTL-refreshed in `snapshot`, cache-only in `guard`), and
`live_bg = None`. The guard's `live_bg` comes from the current manager's transcript
(`manager_arm_guard.py:311-345`) and holds no launch from the absorbed manager, so absence from it
must not read as dead (`work_state.py:207-210`). An unmigrated folded manifest gets no sub-context
and the note `folded_unmigrated:<slug>`; its open mission is undriven with the fix
`work_state.py migrate --program <slug>`.

**What lifts into the owner's snapshot.**

- Each sub-derive's binding flags (`STALLED`, `BAKE_OWED`, `STALE_OPEN`, `PROOF_FAILED`,
  `DUPLICATE_TITLE`) and notes go under `folded.<slug>`, non-blocking in this ship. Retirement and
  bake keep working unchanged: `retire --program <absorbed>` and `bake_body` read the absorbed
  manifest's own tracker (`work_state.py:628-662`), because the binding never left it.
- Carriers on folded bindings count as bound for the owner's UNBOUND check, so a child of the owner
  bound into the absorbed manifest is not reported unbound.
- A ticket or non-shared carrier bound in two manifests of one family gives the note
  `fold_duplicate:<ticket|carrier>:<slugs>`. `bind` refuses a ticket already open in another
  manifest of the target's family (an unlocked best-effort read; a race only produces that note).
  The one live duplicate pair is listed by the census (rule 5) for the managers to retire one copy.

**Driver, defined once.** A mission is driven when at least one binding **on the absorbed
manifest** has a carrier that is:

- of a driver type: `session`, `lane`, `agent`, `workflow` or `bg`. `founder`, `bake`, `card` and
  `wake` hold a ticket but do not drive a goal; and
- live by the sub-context's `live_of` (`work_state.py:313-317`), where `None` counts live, **or** a
  session awaiting the manager (`carrier_state` returns `False` for it at `:198-199`, but it is
  alive and waiting). A retired carrier is no longer in `carriers` (`work_state_store.py:383-389`),
  so it never counts.

A dead carrier stays STALLED's job, so the two flags never disagree about one carrier. When a
mission is driven only by `None` carriers, derive adds `mission_<slug>_driver_unverified`.

**Behaviour.**

- New flag `MISSION_UNDRIVEN`, added to `FLAGS` and to the blocking set beside `UNBOUND` and
  `READY_NOT_DISPATCHED`. It fires per open mission in the family (`fold.closed` null, malformed, or
  missing) that is not driven. A `Hold:` does not exempt it. The fix text names both exits:
  `bind --program <absorbed>` plus a carrier, or `mission-close`.
- `Status: DONE` gets no engine exemption while a mission is open
  (`status_done_open_mission_<slug>:no_exemption`); `GRILLING` does not exempt it either.
- `map_line` appends `missions open N, undriven M` when the family has missions.
- derive emits `missions`: one row per open mission with `program`, `goal`, `undriven`,
  `drivers`, `bindings`. `run_snapshot` writes `cache["missions"] = {"taken_at": ..., "rows": [...]}`.

**At the guard.** The Stop guard calls `work_state.py guard`, so `would_block:MISSION_UNDRIVEN` is
logged in its current SHADOW mode with no guard change. The guard returns `manifest_done`,
`state_done` and `state_grilling` before it reads flags (`manager_arm_guard.py:439-448`), so at the
guard an owner that writes `Status: DONE` with a mission open is exempt. This ship narrows that
hole on the repo side (an open fold into a DONE absorber is refused; a DONE owner of an open mission
stays live for mining; the engine reports the flag in `snapshot`, `role_brief` and the page).
**Enforcement prerequisites**, all owed outside this ship: (1) an operator-harness guard change in
which `MISSION_UNDRIVEN` in `blocking` overrides those three exemptions; (2) its own enforce file,
beside the ready, page and head files; (3) A2 holding on the live store with the shadow
`would_block:MISSION_UNDRIVEN` log reviewed for false positives.

**Wake surface.** `role_brief.py` prints `mission <slug>: undriven (snapshot <age>)` per undriven
row of `cache["missions"]`, and `missions: unknown (no snapshot)` when the key is missing. It never
re-derives liveness.

**Page.** `render_state` renders, next to `goal` and `map` (`render_state.py:576-580`), one line per
open mission: `<program>: <its goal>`, its map, since, binding count, undriven or not from the
snapshot. `state.md` is the authored half and gains no derived block.

### 4. The absorbed manifest stays writable, on purpose

The absorbed manager stays live through handover (`manager-contract.md:25-26`), and the owner
drives the mission with `bind --program <absorbed>`. Both write the absorbed manifest under its own
lock, which is exactly where the owner's engine reads. So no binding writer is fenced, a delayed
`carrier` or `retire` from the old manager still finds its binding, and a retried `absorb` has no
transfer to verify.

### 5. Migration of the old shapes

**Owner.** `work_state.py migrate --folds` (`work_state_migrate.migrate_folds`), a separate pass of
the existing converter. It does not take that pass's early return (`work_state_migrate.py:239`) or
its `todo_open` gate (`:241`), and never writes the R36 `migrated` event. It writes fold records
only through `work_state_store.absorb`, so the writer stays one.

- **`--census`** (read-only) writes a plan file: every legacy fold edge from every shape in the
  table above, `superseded_by` included. For each: the recorded target verbatim, the proposed
  target (`terminal_owner` over the proposed graph, so every migrated edge points at a live end),
  binding count and driver-type carriers on the absorbed manifest, open map children, unmigrated
  `lanes` / `claims`, family duplicates, conflicts (an existing `absorbed_by` that differs, a
  status naming one target and a pointer another), self-edges and cycles. Each edge has a
  `disposition` field, pre-filled as a proposal: `open` when the absorbed manifest holds a
  driver-type carrier or its map has open children, else `closed: goal done or dropped before
  fold (census)`.
- **`--apply <plan>`** refuses the whole plan while any edge has a null disposition, a conflict, a
  self-edge or a cycle. One conflict policy covers every shape: a differing existing owner is
  never overwritten; the operator edits the plan's target. Then, per edge, `absorb` with
  `closed_reason` for a closed disposition. Additive only: no key is removed, so code from before
  this ship keeps working on the result. Re-running skips edges already applied (rule 1
  idempotency), so a crash mid-run is fixed by re-running.
- **`--finish`** runs after the merge (see Ships). Per manifest, under its lock: append one
  `fold-migrated` event holding verbatim every key it is about to remove (`absorbs` in either
  shape, `supersedes`, `superseded_by`, a fold-valued `status`: `merged-into-*`, `superseded-by-*`,
  `superseded`, `absorbed*`), then remove them. A re-run finds the event and only removes what is
  still there. A removed fold-valued `status` leaves no `status` key; `absorbed_by` already makes
  the program not live.
- **`--verify`** exits 1 on any violation: a legacy key left; an `absorbed_by` without a valid
  `fold`; a cycle or missing target; a former `absorbs` entry absent from its absorber's
  `program_scope`; any manifest whose binding count differs from the census.
- **`--restore`** re-adds, from `fold-migrated` events, every removed key that is absent now, never
  overwriting a present one. It is the data half of rollback after `--finish`.
- The row-11 case has no legacy entry; its census row is the hand-edit shape and gets `open`.

**`migrate_program` race.** It plans from an unlocked read (`work_state_migrate.py:231-237`) and
writes that plan under the lock (`:244-246`), so a concurrent `bind` is lost. It now refuses with
"manifest changed since planning; re-run" when the locked read's `bindings`, `lanes` or `claims`
differ from the planning read.

## Tests

`test_work_state.py`:

- `absorb` writes `absorbed_by` and `fold` in one manifest write and one `absorb` row to each log;
  the absorber's manifest bytes are unchanged; a second call is a no-op. With `absorbed_by` already
  naming the absorber and no `fold`, it writes the `fold` (repair).
- Fault injection per write boundary: an exception before `os.replace` leaves both manifests
  unchanged; after the manifest write and before the first append, and between the two appends, a
  retry appends only the missing row and both logs end with exactly one row for that `fold_id`.
  The same three boundaries for `mission-close`.
- `absorb` refuses: self-fold, an absorbed absorber (message names the terminal owner), a cycle, a
  conflicting `absorbed_by`, a missing goal, an open fold into a DONE absorber and into one with no
  `manager_session`. A closed fold into a DONE absorber is allowed. No `snapshot_cmd` gives the
  `fold_no_tracker` note.
- `terminal_owner` / `fold_family`: C→B→A resolves C to A; a two-node cycle and a missing target
  give their notes and no owner.
- derive for the owner: an open mission with no binding on the absorbed manifest gives
  `MISSION_UNDRIVEN` in `blocking` (exit 4). A binding there with only `founder` / `bake` carriers
  still flags. A live `session` or `lane` carrier clears it, and so does a session awaiting the
  manager. A `bg` carrier launched by the absorbed manager clears it in **guard** mode with the
  owner's `live_bg` lacking it, with the `driver_unverified` note. A `carrier-retired` event then
  derive flags again. `mission-close` clears it; `mission-reopen` restores it. A malformed or
  missing `fold` gives a note and the flag, never a `SchemaError`. `Status: DONE` with zero open
  children and an open mission gets no exemption. `run_snapshot` writes `cache["missions"]`.
- Lifecycle on the absorbed manifest after a fold: a ship bound there is judged against the
  absorbed tracker (kind, `STALE_OPEN`, `BAKE_OWED`), and `retire --program <absorbed>` succeeds once
  it closes and its bake binding exists. Its flags appear under `folded.<slug>`, not in `blocking`.
- A child session of the owner bound on the absorbed manifest is not UNBOUND for the owner. A
  ticket open in both owner and absorbed manifests gives `fold_duplicate`; `bind` refuses a third
  copy. An unmigrated folded manifest gives `folded_unmigrated` and the flag with the migrate fix.
- Concurrency: a `bind` by the absorbed manager after `absorb` lands on the absorbed manifest and is
  counted by the owner; a delayed `carrier` on a pre-fold binding succeeds.
- `program_scope` after `migrate --folds --apply` and `--finish` still counts every former string
  `absorbs` entry, and now counts dict entries.
- `migrate --folds`: `--census` lists all six shapes with `superseded_by` resolved and a chain
  resolved to its live end; `--apply` refuses a null disposition, a two-node cycle and a
  status-vs-pointer conflict with every manifest untouched; `--apply` then re-run after an injected
  crash applies each edge once; `--finish` removes every legacy key after writing its event, and a
  crash between event and removal is completed by re-running without a second event; `--verify`
  fails on each violation class; `--restore` re-adds removed keys and leaves a present key alone.
- `migrate_program` refuses when a `bind` lands between its planning read and its locked write.
- `work_state_waiters` names the absorbed manifest's session carrier as a ticket's owner.

`test_render_state.py`: the page lists open missions with the absorbed program's goal and omits
closed ones; `--write-head` leaves `state.md` free of any missions block. `test_role_brief.py`: the
health line appears for an undriven row, is absent once driven, and reads `unknown` with no cache.
`test_mine_all.py`: with C→B→A and an existing `absorb B` candidate route, the route record is
unchanged and resolves to A's manager; a fold-notice for C targets A; a `fold-notice` is emitted
for `absorbed_by` without `fold` and not once the `fold` exists.

## Acceptance (on the real stores)

`P=~/.claude/orchestrator/programs`, `R` = the release slug, `S` = the simulation slug. Each check
states its expected exit code; zsh, so `rc=$?`.

- **A1.** Before: `jq '.bindings|length' $P/$S.json > /tmp/a1n`. Then
  `work_state.py absorb --program $R --from $S --by <session>` exits 0, and these exit 0:
  `jq -e --arg r $R '.absorbed_by==$r and .fold.closed==null and (.fold.id|type=="string")' $P/$S.json`;
  `test "$(jq '.bindings|length' $P/$S.json)" = "$(cat /tmp/a1n)"`;
  for each of `$P/$S.events.jsonl` and `$P/$R.events.jsonl`:
  `jq -se --arg id "$(jq -r .fold.id $P/$S.json)" '[.[]|select(.event=="absorb" and .fold_id==$id)]|length==1'`.
  Running the same `absorb` again exits 0 and leaves all three checks true.
- **A2.** `work_state.py snapshot --program $R --json > /tmp/a2.json; rc=$?`, then `test $rc = 4` and
  `jq -e --arg s $S '[.blocking[]|select(.flag=="MISSION_UNDRIVEN" and .item==$s)]|length==1' /tmp/a2.json`.
  After one persona session is bound on `$S` with a carrier, re-run: `test $rc = 0 -o $rc = 4`, and
  `jq -e --arg s $S '([.blocking[]|select(.flag=="MISSION_UNDRIVEN")]|length==0) and ([.missions[]|select(.program==$s and .undriven==false)]|length==1)' /tmp/a2.json`.
  Re-checked once that session ends a turn and awaits the manager.
- **A3.** While A2's first phase holds:
  `jq -e --arg s $S '(.missions.taken_at|type=="string") and ([.missions.rows[]|select(.program==$s and .undriven)]|length==1)' <R's cache>`
  exits 0, and `role_brief.py $R | grep -F "mission $S: undriven"` exits 0; after A2's driver,
  that grep exits 1.
- **A4.** `work_state.py migrate --folds --verify; rc=$?` gives `rc=0` after `--finish`.
- **A5.** `render_state.py $R` output contains `$S:` followed by the simulation goal verbatim
  (`grep -F`), exit 0.

## Ships

One. Rules 1-5, the tests and the contract wording land together, and the `absorbs` reader is
deleted in the same change. The live-store steps are the operator's, in this order, because commits
to this repo go live on landing:

1. From the build worktree, before merge: `migrate --folds --census`, fill and review the plan,
   `--apply` it. The result is additive and fully readable by the code still on master (it ignores
   `fold` and still reads `absorbs`). Run step 2 in the same sitting, because the old code already
   suppresses UNBOUND/READY on the newly absorbed manifests and has no owner-side judging yet.
2. Merge. Run A1 (the row-11 repair, if `--apply` did not already write its `fold`), A2, A3, A5.
3. After A2/A3 hold for one day of normal turns: `--finish`, then A4.

**Rollback.** Before step 3, reverting the merge is the whole rollback: no binding moved and no
binding key was added. After step 3: `migrate --folds --restore`, then revert. Fold records stay;
older code ignores them.

The guard override and enforce file are an operator-harness change outside this repo, owed at
enforcement (rule 3, "At the guard"), not part of this ship.

## Spec-review tier

**Critical.** The tier rule lists shared-store migrations and cutovers as critical: this ship
migrates the manifest store every manager reads, deletes legacy keys, and changes what every
absorber's engine judges. SHADOW at the guard does not contain the risk, because a `SchemaError`
on the flag step blocks the turn.

Run so far: the standard lanes (R11a edge-case + live evidence, R11b architecture + operator
plane), then the critical wave on `033b713`: sol adversarial (F-sol, 10), astra frontier judge
(F-astra, 7, verdict REWORK) and the cutover lane (F-cut, 9). **Owed:** a final-gate re-check of
this rework at critical tier before any build starts.

## Review log

Standard lanes, 2026-11-17, R11a and R11b: all 19 findings were applied in `033b713` (see that
commit's log). Critical wave on `033b713`, re-checked read-only against the code on 2026-11-17.
The judge's two roots drove the redesign: (1) a two-manifest fold is not atomic or crash-safe;
(2) two records of one fold drift, and migration dropped `absorbs`-based scope. Both are removed,
not hardened: the fold is one file write and `absorbed_by` is its only record.

Totals: 26 findings; 25 fixed, 1 rejected (F-cut-5's remedy; its defect is gone by design).

| Finding | Verdict | Where / reason |
| --- | --- | --- |
| F-astra-1 (CRITICAL) two locks are not atomic | fixed | `work_state_store.py:258-277,239-241` confirmed. Design: one file write is the commit point; events never read for state and repaired by retry; fault-injection tests per boundary (rule 1). |
| F-astra-2 (CRITICAL) no compatible rollback | fixed | No binding key added, so `validate_bindings` (`work_state_sources.py:272`) never meets one on revert. `--apply` is additive and old-code readable; `--finish` is separate and reversed by `--restore` (Ships). |
| F-astra-3 foreign-map lifecycle | fixed | `work_state.py:648-662,301-304` confirmed. Bindings never move: each is judged against its own manifest's tracker; retire and bake work unchanged; lifecycle test (rule 3). |
| F-astra-4 migration deletes scope | fixed | `work_state_sources.py:253` confirmed. Scope = `fold_family`, independent of missions; `--verify` checks scope conservation (rules 2, 5). |
| F-astra-5 binding collision | fixed | Nothing is merged, so no write can fail on it. Cross-manifest duplicates are a note, `bind` refuses a new one, the census lists the live pair (rule 3). |
| F-astra-6 chained folds, stale routes | fixed | `mine_report.py:106-108,190-193`, `mine_all.py:107-119` confirmed. One resolver, `terminal_owner`, routes all of them; route records kept; C→B→A test (rule 2). |
| F-astra-7 source writable after transfer | fixed | `work_state_store.py:318-370` confirmed. Nothing transfers: writes to the absorbed manifest land where the owner reads, so no fence is needed (rule 4); concurrency tests. |
| F-sol-1 (CRITICAL) not crash-safe | fixed | Same as F-astra-1. Stable `fold_id` in both events; retry completes the missing ones. |
| F-sol-2 (CRITICAL) concurrent writers; `migrate_program` stale plan | fixed | Concurrent bind is safe by design (rule 4). `work_state_migrate.py:231-246` confirmed: it now refuses a changed manifest; test added (rule 5). |
| F-sol-3 moved tickets' lifecycle | fixed | Same as F-astra-3. |
| F-sol-4 chain routing | fixed | Same as F-astra-6; repair targets the terminal owner, and migration points every edge at a live end. |
| F-sol-5 collision policy | fixed | Same as F-astra-5. |
| F-sol-6 cutover removes scope before replacement | fixed | Every legacy edge gets a persisted disposition in the plan; `--apply` refuses a null one; keys are removed only by `--finish`, after the merge and a day of A2/A3 (rule 5, Ships). |
| F-sol-7 migration cycles, overwrite | fixed | Census preflights the full graph incl. status edges; one conflict policy, never overwrite; `--apply` refuses a cycle or conflict with all manifests untouched; tests. |
| F-sol-8 transferred bg carriers falsely dead | fixed | `work_state.py:207-210` confirmed. Folded sub-contexts use `live_bg = None` (unknown, `driver_unverified`); guard-mode test (rule 3). |
| F-sol-9 inactive absorber | fixed | Open fold into a DONE/CLOSED absorber or one with no `manager_session` refused; `live_program` keeps a DONE owner of an open mission live (rules 1, 2). A live-manager-session check is not a store fact, so "active" is the manifest's own record. |
| F-sol-10 acceptance cannot fail | fixed | A1-A5 rewritten as `jq -e` / `test` assertions with expected exit codes; snapshot captured to a file and `rc` checked for 4 then 0/4; A4 is `--verify`. |
| F-cut-1 (CRITICAL) two records of one fold | fixed | Adopted: `absorbed_by` is the only record; the absorber stores nothing; its set, missions and bindings are derived (Design). |
| F-cut-2 65 hidden bindings; fold-notice nags | fixed | The owner's engine now judges them (rule 3). Every `absorbed_by` gets one `fold`, open or closed (rule 5); the notice keys on a missing `fold`. Its "no absorbed manifest holds bindings" check is replaced by binding-count conservation, since bindings stay put by design. |
| F-cut-3 moved tickets' tracker; map in two homes | fixed | No copy of `map` or `goal` exists; the absorbed manifest's own `snapshot_cmd` serves its tickets; `fold_no_tracker` note (rules 1, 3). |
| F-cut-4 absorbed manifest writable | fixed | Same as F-astra-7. `CATCHUP_MESSAGE.md` added to Files; contract says `bind --program <absorbed>`. |
| F-cut-5 `absorb` leaves `lanes`/`claims` behind | rejected | Its remedy (refuse until migrated) assumed bindings move. Nothing moves now, so the fold record can be written on an unmigrated manifest; the engine notes `folded_unmigrated` and the open mission's fix names `migrate --program` (rule 3). |
| F-cut-6 `status`, `superseded_by`, `supersedes` left | fixed | Census reads all of them; `--finish` moves each into the `fold-migrated` event and removes it; `--verify` checks (rule 5). |
| F-cut-7 "nothing else stores the goal" false | fixed | The goal is no longer copied; `A.goal` is the mission's goal. |
| F-cut-8 "not retired" matches nothing | fixed | `work_state_store.py:383-389` confirmed; the criterion is dropped and the test is a `carrier-retired` event then derive. |
| F-cut-9 open-mission check on the read path | fixed | Moot: bindings carry no mission key, and `FOLD_KEYS` runs only in the writers. |
