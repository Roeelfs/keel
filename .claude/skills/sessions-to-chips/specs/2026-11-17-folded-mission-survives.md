# A folded program's mission survives

Row 11 of the account-switch gaps (founder, 2026-11-17). When one program is folded into another,
the absorber takes over the absorbed program's owed items but not its goal. Nothing records the fold
in the absorber's manifest, and nothing checks that someone still drives the absorbed goal.

This spec gives the fold ONE writer, makes the absorbed goal a standing **mission** in the
absorber's manifest, moves the absorbed program's open bindings to the absorber so a ticket's
binding lives in one place, and makes the work-state engine flag a mission with no driver. Every
rule has one owner; where a rule has copies today, the spec names the copy it deletes.

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
  `state_index.live_program` is false for it, but the absorber still records no goal and binds no
  ticket of it. The absorbed manifest still holds its bindings, several with session carriers, and
  because it is absorbed, `ctx["absorbed"]` suppresses its UNBOUND and READY flags
  (`work_state.py:448,496`). Those drivers count nowhere.

**The fold has no writer today.** Every `absorbed_by` / `absorbs` hit in `scripts/` is a read
(`program_family.py:208,407,414`, `mine_all.py:147`, `mine_report.py:106,190-193,284`,
`state_index.py:45`, `work_state_sources.py:253,318`, `work_state_waiters.py:10`); the operator
harness has none either (`grep -rn absorbed_by ~/.claude/scripts ~/.claude/hooks`, 2026-11-17,
zero hits). Managers hand-edit manifests or write prose, so the fold is recorded several ways on the
live store (2026-11-17, python scan of `~/.claude/orchestrator/programs/*.json`):

| Shape | Count | Seen by `absorbed_by` readers |
| --- | --- | --- |
| `absorbed_by: <slug>` | 10 manifests (incl. the row-11 hand edit) | yes |
| `status: merged-into-<slug>` / `superseded-by-<slug>` | 9 manifests (one is a bare `superseded`) | no |
| absorber `absorbs: ["<slug>"]` | 4 absorbers, 6 entries | yes (`program_scope`) |
| absorber `absorbs: [{"program": ..., "fold": ..., "status": ...}]` | 1 absorber, 3 entries | no: `program_scope` keeps only strings |
| prose section in the absorber's state file only | the row-11 case | no |

## Files

| File | Change |
| --- | --- |
| `scripts/work_state_store.py` | Owns the fold record. New `absorb()` and `close_mission()`; `MISSION_KEYS` strict validator, called only by those two writers; binding gains optional `mission`. |
| `scripts/work_state.py` | New verbs `absorb`, `mission-close`; `bind --mission`; derive gains the `MISSION_UNDRIVEN` flag (blocking), refuses the `DONE` exemption while a mission is open, and emits `missions`; `run_snapshot` caches it. `migrate --folds` dispatch. |
| `scripts/work_state_migrate.py` | New `migrate_folds()` pass, independent of the lanes/claims conversion. |
| `scripts/work_state_sources.py` | `program_scope` reads absorbed slugs from `missions[]`; `build_ctx` passes `missions` into ctx and fetches each open mission's map children for `bind --mission`. |
| `scripts/program_family.py` | `load_manifests` carries `missions` instead of `absorbs`. |
| `scripts/render_state.py` | Renders open missions on the derived page next to `goal`. |
| `scripts/role_brief.py` | One health line per undriven open mission, read from the snapshot cache. |
| `scripts/mine_report.py` | `fold-notice` text tells the absorber to run `work_state.py absorb` if the mission is missing. |
| `references/manager-contract.md`, `SKILL.md` | The takeover order runs `absorb` before step (4), and the `fold-notice` paragraph names the verb; the `absorbs` wording goes. |
| `scripts/test_work_state.py`, `scripts/test_render_state.py`, `scripts/test_role_brief.py` | Tests below. |

## Rules and owners

### 1. One writer for a fold

**Owner.** `work_state_store.absorb(absorber, absorbed, *, by, now)`, reached only through
`work_state.py absorb --program <absorber> --from <absorbed>`. The store already owns every
manifest write (`ManifestLock`, `append_event`); the fold is a manifest write.

**Behaviour.** Under both manifest locks (taken in slug order, so two folds never deadlock):

- Refuse when `absorbed == absorber`, when the absorber is itself absorbed, when the absorbed
  manifest has `absorbed_by` set to a different slug, or when the absorbed manifest has no `goal`.
  The message names the conflicting slug.
- Set the absorbed manifest's `absorbed_by` to the absorber.
- Append to the absorber's `missions[]`, strict keys (`MISSION_KEYS`):
  `{"program": "<absorbed>", "goal": "<absorbed goal, verbatim>", "map": "<absorbed map.issue or null>", "since": "<ISO>", "closed": null}`.
- **Idempotency keys on the mission row, not on `absorbed_by`.** If the absorber already holds an
  open mission for this program, the call is a no-op that prints it, so a retried takeover never
  doubles it. If `absorbed_by` already names this absorber but no mission row exists (the row-11
  hand edit, or a fold normalized by `migrate --folds`), the call appends the mission: a repair.
- **Bindings move.** Every open binding in the absorbed manifest moves to the absorber in the same
  locked write, carriers intact, tagged `mission: "<absorbed>"` unless it already carries a
  `mission` tag. The absorbed manifest keeps none. A ticket's binding lives in exactly one manifest.
- **Chained folds.** Every open mission the absorbed program itself holds moves to the absorber
  with its `since` kept, so absorbing an absorber never strands a goal on a manifest whose manager
  has stopped. Closed missions stay where they are, as history.
- Append one `{"event": "absorb", "from": ..., "into": ..., "by": ..., "moved_bindings": N, "moved_missions": [...]}`
  row to BOTH programs' event logs.

**Deleted.** The manifest key `absorbs` (both shapes). `missions[].program` is the one list of
absorbed programs. `program_scope` (`work_state_sources.py:253`) and `load_manifests`
(`program_family.py:208`) read it instead. Hand-editing `absorbed_by` stops being a documented path.

**Validation stays off the read path.** `MISSION_KEYS` runs only inside `absorb` and
`close_mission`, like `validate_repo` (`work_state_store.py:177`) and never inside `_Locked.write`
or `build_ctx`. On the read path a malformed mission row becomes a note
(`mission_malformed_<index>`) and counts as open and undriven. It never raises `SchemaError`,
because the Stop guard treats a `SchemaError` flag step as blind and blocks the turn
(`manager_arm_guard.py:874-876`, `:446-447`); one bad hand edit must not block every Stop.

### 2. The absorbed goal is a standing mission with its own drivers

**Owner of the record.** The absorber's manifest `missions[]` (rule 1). Nothing else stores the goal.

**Drivers.** A binding gains an optional `mission: "<absorbed slug>"` key, set by
`work_state.py bind --mission <slug>` (the strict binding validator gains the key; a slug with no
open mission is refused). Today `bind` refuses any ticket that is not a child of the absorber's own
map (`work_state_store.py:331-333`). Under `--mission <slug>`, the accepted set is the children of
`missions[slug].map` instead, fetched through the absorbed manifest's own `snapshot_cmd`; without
`--mission` the absorber's map applies as today. The absorbed tickets, bound this way or moved by
`absorb`, are the absorber's carriers, tracked like any other.

**Page.** `render_state` renders the open missions on the derived page next to `goal` and `map`
(`render_state.py:576-580`): one line per open mission (`<program>: <goal>`, map, since, the number
of bindings tagged with it, and undriven or not from the snapshot). `state.md` is the authored half
and gains no derived block, so a head write does not change it. The prose
`## Taken over from ...` section stays the manager's narrative of owed items, as today.

**Closing.** `work_state.py mission-close --program <absorber> --mission <slug> --reason "<evidence>"`
sets `closed` to `{"at": ..., "reason": ...}` and appends an event. A non-empty reason is required.
A founder decision to park the goal is closed this way, with the founder named in the reason. Nothing
else closes a mission, and a closed mission is never deleted.

### 3. The convergence check flags a mission with no driver

**Owner.** `work_state.py derive`. It already decides blocking and the `DONE` exemption (R29); a
second checker would be a second owner.

**Driver, defined once.** A mission is driven when at least one binding tagged with it has a
carrier that is:

- of a driver type: `session`, `lane`, `agent`, `workflow` or `bg`. `founder`, `bake`, `card` and
  `wake` carriers hold a ticket but do not drive a goal, so they never count;
- not retired; and
- live by the engine's existing `live_of` (`work_state.py:314-317`), where `None` (unknown) counts
  live, **or** a session that is awaiting the manager (`carrier_state` returns `False` for it at
  `work_state.py:198-199`, but it is alive and waiting on its manager, not gone).

A dead carrier stays STALLED's job, so the two flags never disagree about one carrier. `agent`,
`workflow` and `bg` carriers read `None` in every `snapshot` (no `live_bg`) and true or false in
`guard` mode; when a mission is driven only by `None` carriers, derive adds the note
`mission_<slug>_driver_unverified` so snapshot mode says what it could not see.

**Behaviour.**

- New flag `MISSION_UNDRIVEN`, added to `FLAGS` and to the blocking set beside `UNBOUND` and
  `READY_NOT_DISPATCHED`. It fires for each mission with `closed: null` that is not driven. A
  `Hold:` does not exempt it. The fix text names both exits: `bind --mission <slug>` plus a
  carrier, or `mission-close`.
- `Status: DONE` gets no engine exemption while any mission is open; the note is
  `status_done_open_mission_<slug>:no_exemption`. `Status: GRILLING` does not exempt it either,
  the same as `UNBOUND`.
- `map_line` appends `missions open N, undriven M` when the program has missions.
- derive emits `missions`: one row per open mission with `program`, `undriven`, and the driver
  count. `run_snapshot` writes it to `cache["missions"]` with `taken_at`.

**At the guard.** The Stop guard calls `work_state.py guard`, so `would_block:MISSION_UNDRIVEN` is
logged in its current SHADOW mode with no guard change. Two limits are stated, not hidden:

- The guard returns `manifest_done`, `state_done` and `state_grilling` before it reads the flags
  (`manager_arm_guard.py:439-448`). So at the guard, an absorber that writes `Status: DONE` with a
  mission open is exempt. The engine still reports the flag in `snapshot`, `role_brief` and the
  page. Closing that hole is a guard change in the operator harness, outside this repo: at
  enforcement, `MISSION_UNDRIVEN` in `blocking` overrides those three exemptions.
- Enforcement is per flag, each behind its own enforce file (ready, page, head today). Enforcing
  `MISSION_UNDRIVEN` gets its own enforce file and lands with that guard change, after A2 holds on
  the live store. This ship does not enforce it.

**Wake surface.** `role_brief.py` prints one health line per undriven open mission, read from
`cache["missions"]` with its age, and `missions: unknown (no snapshot)` when the key is missing. It
never re-derives liveness: that is derive's rule.

### 4. Migration of the old shapes

**Owner.** `work_state.py migrate --folds` (`work_state_migrate.migrate_folds`), a separate pass of
the existing one-shot converter. It creates no missions, so `absorb` stays the one mission writer.

- It runs independently of the lanes/claims conversion: it does not take that pass's early return
  (`work_state_migrate.py:239`) or its `todo_open` gate (`:241`), and it never writes the R36
  `migrated` UNBOUND-floor event.
- For each absorber with `absorbs` (either shape), under both manifest locks: set each absorbed
  manifest's `absorbed_by` if unset (a conflicting value is reported and left alone), remove
  `absorbs`, and append one `absorb-migrated` event to the absorber holding every old entry
  verbatim, including the dict entries' `fold` and `status`, so nothing is dropped.
- `status: merged-into-<slug>` / `superseded-by-<slug>` set `absorbed_by` to that slug. An
  unresolvable target, such as a bare `superseded`, is reported, not guessed.
- The census lists every normalized `absorbs` entry (9 on 2026-11-17, on 5 absorbers). Each
  absorber's manager runs `absorb` for any of them whose goal it still owes; that is a repair
  through rule 1, not a migration guess. Old folds whose goals are done get no mission and flag
  nothing.
- The row-11 case has no `absorbs` entry. It is fixed by running `absorb` once (acceptance A1).

## Tests

`test_work_state.py`:

- `absorb` sets `absorbed_by`, appends one mission with the verbatim goal, writes both events; a
  second call is a no-op. With `absorbed_by` already naming the absorber and no mission row, it
  appends the mission.
- `absorb` moves the absorbed program's open bindings with carriers intact and tags them; the
  absorbed manifest keeps none. It moves the absorbed program's open missions with `since` kept.
- `absorb` refuses: self-fold, an absorbed absorber, a conflicting `absorbed_by`, a missing goal.
- `bind --mission` accepts a child of the mission's map and the same ticket is refused without
  `--mission`; a slug with no open mission is refused; the strict validator rejects a misspelled key.
- A malformed `missions` row on the read path gives a note and `MISSION_UNDRIVEN`, never a
  `SchemaError`.
- derive: an open mission with no tagged binding gives `MISSION_UNDRIVEN` in `blocking` (exit 4).
  A tagged binding whose only carrier is `founder`/`bake` still flags. A live `session` or `lane`
  carrier clears it, and so does a session awaiting the manager. An `agent` carrier clears it in
  snapshot mode with the `driver_unverified` note, and flags in guard mode when it is not in
  `live_bg`. A retired carrier flags. `mission-close` clears it. `Status: DONE` with zero open
  children and an open mission gets no exemption. `run_snapshot` writes `cache["missions"]`.
- `program_scope` counts children of a mission's program toward the absorber (replaces the
  string-only `absorbs` read).
- `migrate --folds`: string and dict `absorbs` are removed, `absorbed_by` is set, the event holds
  every entry verbatim, no mission is created, and an open todo does not stop it; `merged-into-*`
  sets `absorbed_by`; bare `superseded` is reported.

`test_render_state.py`: the page lists open missions next to `goal` and omits closed ones; a
`--write-head` leaves `state.md` free of any missions block. `test_role_brief.py`: the health line
appears for an undriven mission in the cache, is absent once it is driven, and reads `unknown` with
no cache.

## Acceptance (on the real stores)

- **A1.** After `work_state.py absorb --program <release slug> --from <simulation slug>` (the
  repair path, since `absorbed_by` is already set): `jq '.missions[]'` on the release manifest
  lists the simulation program with its goal verbatim, the simulation manifest holds no open
  bindings, the release manifest holds them tagged with the mission, and both event logs hold one
  `absorb` row.
- **A2.** `work_state.py snapshot --program <release slug> --json | jq '.blocking[] | select(.flag=="MISSION_UNDRIVEN")'`
  returns the simulation mission while no driver carrier is on a binding tagged with it, and
  returns nothing once one persona session is bound with `mission`, including after that session
  finishes a turn and awaits the manager.
- **A3.** `jq '.missions'` in the release program's snapshot cache lists the simulation mission,
  and `role_brief` prints its health line until A2's driver is bound.
- **A4.** After `migrate --folds --all`, no manifest under `~/.claude/orchestrator/programs/` has an
  `absorbs` key, each former absorber has one `absorb-migrated` event holding its old entries, no
  `missions` key was created by the pass, and every `merged-into-*` manifest has `absorbed_by` set
  (checked with a python scan, not grep).
- **A5.** The release program's derived page shows the simulation mission next to its goal after
  the next render.

## Ships

One. Rules 1-4, the tests and the contract wording land together; the `absorbs` reads are deleted
in the same change. A1 and `migrate --folds --all` run on the live store after merge, as the
operator's step. The guard override and enforce file (rule 3, "At the guard") are an operator-harness
change outside this repo, owed at enforcement, not part of this ship.

## Spec-review tier

**Critical.** The tier rule lists shared-store migrations and cutovers as critical, and this ship
migrates the manifest store every manager reads and deletes a key (`absorbs`) in the same change.
SHADOW at the guard does not contain the risk: a `SchemaError` on the flag step blocks the turn
(rule 1, "Validation stays off the read path"), and the binding move rewrites two live manifests.
Keep the migration and cutover lanes.

## Review log

Two review lanes on 2026-11-17: edge-case + live evidence (R11a) and architecture + operator plane
(R11b). Each finding was re-checked read-only against the code and a python scan of the live store.

| Finding | Verdict | Where / reason |
| --- | --- | --- |
| R11a-1 (CRITICAL) `bind` refuses foreign-map tickets | fixed | `work_state_store.py:331-333` confirmed. Rule 2: `--mission` checks the mission map's children; test added. |
| R11a-2 absorbed bindings left behind | fixed | Live absorbed manifest holds session-carried bindings, release holds 0. Rule 1: `absorb` moves them in the same locked write. |
| R11a-3 "live" undefined for unknown/awaiting | fixed | `work_state.py:198-199,207-209,317` confirmed. Rule 3 defines a driver once: `live_of` plus awaiting-manager; dead stays STALLED. |
| R11a-4 migration opens 9 old folds as undriven | fixed | Scan: 9 entries on 5 absorbers. Rule 4 creates no missions (merged with R11b-4). |
| R11a-5 stale evidence; repeat-`absorb` keyed wrong | fixed | Hand edit confirmed; counts corrected to 10; idempotency keys on the mission row; A1/A3 check only what is new. |
| R11a-6 `role_brief` cache holds no verdict | fixed | `work_state.py:583-598` confirmed. `cache["missions"]` written by `run_snapshot`, read only by `role_brief`. |
| R11a-7 migration owner can't write these | fixed | `work_state_migrate.py:239,241` confirmed. Separate `migrate --folds` pass, file added; `since` moot since migration makes no missions. |
| R11a-8 absorbing an absorber strands missions | fixed | Rule 1 moves open missions with `since` kept; test added. |
| R11a-9 test owner named wrong | fixed | `--write-head` tests are in `test_render_state.py:335-355`; hedge dropped. |
| R11b-1 `bind --mission` can't bind | fixed | Duplicate of R11a-1. |
| R11b-2 strict validator on the read path blocks turns | fixed | `manager_arm_guard.py:874-876,446-447` confirmed. `MISSION_KEYS` only in the two writers; read path notes. |
| R11b-3 DONE/GRILLING exempt at the guard | fixed | `manager_arm_guard.py:439-448` confirmed. The hole is stated; the override and its own enforce file are named as an operator-harness change at enforcement. "All flags at once" corrected. |
| R11b-4 migration invents goals, drops `fold`, 2nd writer | fixed | Adopted: `migrate --folds` keeps every entry verbatim in an event, creates no missions, skips the todo gate and the `migrated` event. |
| R11b-5 stale evidence; repair path | fixed | Duplicate of R11a-5. |
| R11b-6 chained folds orphan missions | fixed | Duplicate of R11a-8. |
| R11b-7 `role_brief` needs its own driver rule | fixed | Duplicate of R11a-6. |
| R11b-8 `## MISSIONS` in the wrong module | fixed | `state_view.py:2-6` confirms `state.md` is the authored half. Missions render in `render_state`; `state_view` change dropped; A5 is against the page. |
| R11b-9 driver semantics ambiguous | fixed | Took R11a-3's semantics (one `live_of` rule, no mode split in the verdict) plus R11b-9's snapshot note `driver_unverified`. A per-mode verdict would be a second liveness rule. |
| R11b-10 tier should be critical | fixed | Shared-store migration is critical by the tier rule. |
