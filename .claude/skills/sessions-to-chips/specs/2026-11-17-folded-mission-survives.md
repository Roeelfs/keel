# A folded program's mission survives

Row 11 of the account-switch gaps (founder, 2026-11-17). When one program is folded into another,
the absorber takes over the absorbed program's owed items but not its goal. Nothing records the fold
in a way every reader agrees on, and nothing checks that someone still drives the absorbed goal.

This spec makes `absorbed_by` the **only** record of a fold that any reader of the new code decides
from, and records the fold's mission state on the same manifest. The absorber's absorbed set, its
open missions and its folded bindings are all **derived** by inverting `absorbed_by`. The work-state
engine then flags an open mission with no driver. Every rule has one owner; where a rule has copies
today, the spec names the copy it deletes.

*(Second rework, of `f18296f`, after the critical-tier final gate. This rework converges by
shrinking: a single-operator local manifest store gets the simplest rule that kills each defect.
Every finding is in the Review log.)*

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
- The absorbed manifest still holds 20 bindings whose carriers are `session=6, bg=13, agent=2,
  card=1, wake=1` (jq over the live manifest, 2026-11-17). The bg and agent carriers were launched
  by the absorbed manager; nothing proves any of them still runs.

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

The first draft moved bindings and wrote a `missions[]` row into the absorber under two locks: a
cross-manifest transaction the store cannot make atomic (`_Locked.write` replaces one file,
`work_state_store.py:258-265`; events are separate appends; readers take no lock). This design
removes the transaction instead of hardening it:

| Fact | Its one record | Everything else |
| --- | --- | --- |
| A was folded into B | `A.absorbed_by = "B"` | B's absorbed set: derived by inverting `absorbed_by` |
| Who owns A now | none stored | `terminal_owner(A)`: follow `absorbed_by` to the end |
| A's goal | `A.goal` (unchanged) | B's page and snapshot read it from A |
| A's mission open / closed | `A.fold.closed` | B's open missions: derived |
| A's tickets, map, tracker | `A.bindings`, `A.map`, `A.snapshot_cmd` (unchanged) | B's engine judges them against A's tracker |
| Old-code compatibility | `B.absorbs` string entries: a **write-only mirror** | written by the fold writer, read by no new code |

A fold commits in one locked write to A's manifest: `absorbed_by` plus `fold`. Bindings never move,
so there is no collision to merge and no window in which a binding sits in a "wrong" home.

**Why the mirror.** Code from before this ship recognises `absorbed_by` (it hides A and suppresses
A's UNBOUND/READY) but builds the owner's scope only from string `absorbs` entries
(`work_state_sources.py:253`). A pointer without a matching string entry would leave A judged by
nobody under old code. So the fold writer keeps a string entry on the owner, written **before** the
pointer. Old code then stays correct at every crash point and after any revert, and there is no
separate rollback procedure. New code never reads `absorbs`, so the mirror cannot drift into a
decision. Deleting the mirror is a later change, owed once reverting to pre-ship code is no longer
wanted (Ships).

**One graph lock.** Every fold writer (`absorb`, `mission-close`, `mission-reopen`, and each
`migrate --folds` write pass) takes the exclusive flock `<programs>/folds.lock` first, then the
manifest locks it needs, absorber before absorbed. The graph is read fresh under that lock, so two
writers can never both see an acyclic graph and commit a cycle. `bind` and the other binding writers
never take it, so no lock cycle exists. The lock file's name does not match `*.json`, so no manifest
glob sees it.

## Files

| File | Change |
| --- | --- |
| `scripts/work_state_store.py` | Owns the fold writes and the graph lock. New `absorb()`, `close_mission()`, `reopen_mission()`, `destination_ok()`; `FOLD_KEYS` strict validator, called only by those writers. `bind` refuses a ticket already bound elsewhere in the owner's fold family. |
| `scripts/program_family.py` | Owns the fold resolver: `terminal_owner`, `fold_family`, `open_missions`, with cycle detection. `load_manifests` carries `absorbed_by` and `fold`, drops `absorbs`. |
| `scripts/work_state_sources.py` | `program_scope` takes absorbed slugs from `fold_family` (deletes the `absorbs` read at `:253`). `build_ctx` builds one sub-context per folded manifest. |
| `scripts/work_state.py` | Verbs `absorb`, `mission-close`, `mission-reopen`; `migrate --folds` dispatch. derive: `MISSION_UNDRIVEN` (blocking), the mission driver rule, folded-binding flags lifted as non-blocking, folded carriers counted as bound for UNBOUND, no `DONE` exemption while a mission is open, emits `missions`; `run_snapshot` caches it. |
| `scripts/work_state_migrate.py` | New `migrate_folds()` (census, apply, finish, verify). `migrate_program` refuses when the manifest's bindings changed between planning and the locked write. |
| `scripts/work_state_waiters.py` | `_programs` / `_owners` count bindings on absorbed manifests, owned by their terminal owner. |
| `scripts/mine_all.py` | `program_entry` asks `program_family.open_missions`; `candidate_owner` resolves `absorb` routes through `terminal_owner`. |
| `scripts/mine_report.py` | Fold-notice `absorber`, ruling recipients and the `closed-program-rows` target resolve through `terminal_owner`; an owner with open missions and no live manager gets `no-manager-here`; a missing fold record gets a repair line. |
| `scripts/render_state.py`, `scripts/state_brief.py` | The owner's open missions on the derived page and in the `--context` brief, next to `goal`. |
| `scripts/role_brief.py` | One health line per undriven open mission, read from the snapshot cache. |
| `references/manager-contract.md`, `SKILL.md`, `CATCHUP_MESSAGE.md` | The takeover order runs `absorb` before step (4); "bind each child" becomes `bind --program <absorbed>`; the fold-notice paragraph names the verb. |
| `scripts/test_work_state.py`, `scripts/test_render_state.py`, `scripts/test_role_brief.py`, `scripts/test_mine_all.py` | Tests below. |

## Rules and owners

### 1. The fold record and its writers

**Record.** On the absorbed manifest: `absorbed_by: "<absorber>"` and
`fold: {"id": "<absorbed>@<since>", "since": "<ISO>", "by": "<session id>", "closed": null | {"at": "<ISO>", "reason": "<text>"}}`
(strict keys, `FOLD_KEYS`). On the owner: only the mirror's string entries. `absorbed_by` with no
`fold` is the pre-spec hand-edit shape: readers treat it as an open mission with the note
`fold_record_missing:<slug>`, so it fails loud.

**Writer.** `work_state_store.absorb(absorber, absorbed, *, by, closed_reason=None, now)`, reached
through `work_state.py absorb --program <absorber> --from <absorbed> [--closed-reason "<text>"]`
and from `migrate --folds --apply`. Nothing else writes `absorbed_by`, `fold` or `absorbs`.

**Retry first.** Under the graph lock, if `absorbed.absorbed_by == absorber` and a `fold` exists,
the call is a retry of a committed fold: it skips admission, writes nothing to either manifest, and
only appends whichever `absorb` event carrying that `fold.id` is missing from either log. This holds
even if the absorber has since been folded elsewhere. With `absorbed_by == absorber` and no `fold`
(the row-11 hand edit), the call runs admission and writes the `fold`: a repair.

**Destination eligibility, one check.** `destination_ok(owner, manifests)` is true when the owner's
manifest exists, has no `absorbed_by`, has a status other than DONE or CLOSED, and has a
`manager_session`. It runs on **every** mutation that leaves an open mission under an owner:

- `absorb`, when the new fold is open **or** any member of `fold_family(absorbed)` already has an
  open mission (an inherited mission moves with its family). The owner checked is the absorber; the
  refusal names each open mission and the two exits (close it first, or pick another absorber).
- `mission-reopen`, against `terminal_owner(<mission>)`.

A fold with no open mission anywhere in the moved family may target any existing absorber.

**Admission** for a new fold, against the graph read under the lock:

- Refuse `absorbed == absorber`.
- Refuse when the absorber is itself absorbed; the message names `terminal_owner(absorber)`.
- Refuse when `terminal_owner(absorber)`'s chain contains `absorbed` (a cycle).
- Refuse when the absorbed manifest's `absorbed_by` names a different slug; the message names it.
- Refuse when the absorbed manifest has no `goal`.
- Refuse when `destination_ok` fails, as above.
- Note, do not refuse: `fold_no_tracker` when the absorbed manifest has no `snapshot_cmd` (13 of
  19 folded manifests today). Its mission can then be driven only by a binding on its map ticket,
  which `bind` already accepts with no tracker (`work_state_store.py:331-333`).

**The writes**, in this order, all under the graph lock:

1. `_Locked(absorber).write`: add the string `absorbed` and every member of `fold_family(absorbed)`
   to `absorbs` when absent. Existing entries, string or dict, are untouched.
2. `_Locked(absorbed).write`: set `absorbed_by` and `fold`. **This is the commit point.**
3. Append `{"event": "absorb", "fold_id", "from", "into", "by", "closed"}` to the absorbed log, then
   the absorber log.

A crash after step 1 leaves an extra mirror entry and no fold: new code ignores it, old code judges
the source twice (once on its own, once in the owner's scope), and a re-run completes the fold. No
reader decides anything from a fold event.

**Mission state: idempotent setters.** `work_state.py mission-close --mission <absorbed> --reason
"<evidence>"` sets `fold.closed`; `mission-reopen --mission <absorbed> --reason "<why>"` sets it to
`null` after `destination_ok`. Each runs under the graph lock. If the field already holds the target
state, nothing is written. Then each of the two logs gets a `mission-close` / `mission-reopen` event
only when its latest mission event for that slug does not already name the state just set. A re-run
is therefore safe, and nothing is replayed: there is no automatic retry, and every invocation is a
new operator decision applied to the current state. A non-empty reason is required. A founder
decision to park the goal is a close, with the founder named in the reason. A `fold` is never
deleted.

**Validation stays off the read path.** `FOLD_KEYS` runs only inside the writers, like
`validate_repo` (`work_state_store.py:177`), never in `_Locked.write` or `build_ctx`. On the read
path a malformed `fold` becomes the note `fold_malformed:<slug>` and counts as open and undriven.
It never raises `SchemaError`, because the Stop guard treats a `SchemaError` flag step as blind and
blocks the turn (`manager_arm_guard.py:874-876`, `:446-447`). Bindings gain **no** new key, so a
code revert never meets an unknown binding key on the `validate_bindings` read path
(`work_state_sources.py:272`).

### 2. One resolver for who owns a fold

**Owner.** `program_family.terminal_owner(slug, manifests)` follows `absorbed_by` until a manifest
with none. `fold_family(slug, manifests)` returns every manifest whose terminal owner is `slug`.
`open_missions(slug, manifests)` returns the members of `fold_family(slug)` whose `fold.closed` is
null, missing or malformed. A cycle, or a target slug with no manifest, returns no owner plus the
note `fold_cycle:<slugs>` / `fold_target_missing:<slug>`; the folded program is treated as unowned
and its open mission is flagged on itself.

**Readers routed through it** (each replaces an immediate-target read):

- `program_scope` (`work_state_sources.py:253`): `[slug] + fold_family(slug)`, independent of
  mission state. It no longer reads `absorbs`.
- `mine_report`: fold-notice `absorber`, ruling recipients (`:106-108`) and the
  `closed-program-rows` target (`:190-193`) use `terminal_owner`.
- `mine_all.candidate_owner` (`:107-119`): an `absorb <slug>` route keeps its recorded target and
  resolves the effective owner as `terminal_owner(target)`. Route records are not rewritten.
- `mine_all.program_entry` (`:122-144`): calls `open_missions(slug, manifests)` on the manifests
  `mine_all` already loads (`:260`). A program owing a mission is never dropped by the window floor
  (`:126-127`), and its entry carries `missions_open`. Session liveness stays
  `program_family.session_present`; nothing here duplicates it.
- `work_state_waiters`: an absorbed manifest's bindings count toward ticket ownership, owned by its
  terminal owner (today `_programs` drops them at `:9-11`).

`state_index.live_program` is unchanged: it drives the sidecar index, not mining.

**Chains.** If C was folded into B and B later into A, `C.absorbed_by` stays `B` and
`terminal_owner(C)` is `A`. Folding B into A wrote C into A's mirror too (rule 1, step 1).

### 3. The absorber judges its folded manifests

**Owner.** `work_state.py derive`, for the terminal owner. A folded program's own derive keeps
`ctx["absorbed"]` and its UNBOUND/READY suppression: the owner reports, not the stopped manager.

**Folded sub-contexts.** `build_ctx` builds one sub-context per member of `fold_family(slug)` that
holds bindings or an open mission. Each uses that manifest's own bindings and its own tracker tier
through its own `snapshot_cmd` (TTL-refreshed in `snapshot`, cache-only in `guard`), with
`live_bg = None`, so an unproven `bg` / `agent` / `workflow` carrier is unknown and never STALLED
(`work_state.py:207-210,313-317`). An unmigrated folded manifest gets no sub-context and the note
`folded_unmigrated:<slug>`; its open mission is undriven with the fix
`work_state.py migrate --program <slug>`.

**What lifts into the owner's snapshot.**

- Each sub-derive's binding flags (`STALLED`, `BAKE_OWED`, `STALE_OPEN`, `PROOF_FAILED`,
  `DUPLICATE_TITLE`) and notes go under `folded.<slug>`, non-blocking in this ship. `retire
  --program <absorbed>` and `bake_body` read the absorbed manifest's own tracker
  (`work_state.py:628-662`), because the binding never left it.
- Carriers on folded bindings count as bound for the owner's UNBOUND check.
- A ticket or non-shared carrier bound in two manifests of one family gives the note
  `fold_duplicate:<ticket|carrier>:<slugs>`. `bind` refuses a ticket already open in another
  manifest of the target's family (an unlocked best-effort read; a race only produces that note).

**Driver: positive evidence only.** A mission is driven when at least one binding **on the
absorbed manifest** has a carrier with positive evidence of life:

- `session`: `program_family.session_present(row, now, LEASE["session"])`, the existing predicate
  for "live, or ended a turn inside the window and awaits its manager". A session parked past the
  lease does not drive.
- `lane`: `carrier_state` returns `True` (pid and start time match, `work_state.py:186-193`).
- `bg`, `agent`, `workflow`: the carrier id is in the **owner's** `ctx["live_bg"]`. Absence, or an
  owner `live_bg` of `None`, is unknown: not a driver and, per the sub-context, not STALLED.
- `founder`, `bake`, `card`, `wake` hold a ticket but never drive a goal. A retired carrier is no
  longer in `carriers` (`work_state_store.py:383-389`), so it never counts.

The consequence is deliberate: carriers the absorbed manager launched do not keep the mission
driven. The owner proves it has taken the goal over by binding its own session or lane, or a
background carrier it launched. Missing evidence is never read as death, only as "not proven
driving".

**Behaviour.**

- New flag `MISSION_UNDRIVEN`, added to `FLAGS` and to the blocking set beside `UNBOUND` and
  `READY_NOT_DISPATCHED`. It fires per member of `open_missions(owner)` that is not driven. A
  `Hold:` does not exempt it. The fix text names both exits: `bind --program <absorbed>` plus a
  carrier, or `mission-close`.
- `Status: DONE` gets no engine exemption while a mission is open
  (`status_done_open_mission_<slug>:no_exemption`); `GRILLING` does not exempt it either.
- `map_line` appends `missions open N, undriven M` when the family has missions.
- derive emits `missions`: one row per open mission with `program`, `goal`, `undriven`,
  `drivers`, `bindings`. `run_snapshot` writes `cache["missions"] = {"taken_at": ..., "rows": [...]}`.

**At the guard.** The Stop guard calls `work_state.py guard`, so `would_block:MISSION_UNDRIVEN` is
logged in its current SHADOW mode with no guard change. The guard returns `manifest_done`,
`state_done` and `state_grilling` before it reads flags (`manager_arm_guard.py:439-448`), so at the
guard an owner that writes `Status: DONE` with a mission open is exempt. This ship narrows that
hole on the repo side: no verb can place an open mission under a DONE or absorbed owner, mining
keeps an owner that owes a mission visible, and the engine reports the flag in `snapshot`,
`role_brief` and the page. **Enforcement prerequisites**, owed outside this ship: (1) an
operator-harness guard change in which `MISSION_UNDRIVEN` in `blocking` overrides those three
exemptions; (2) its own enforce file; (3) A2 holding on the live store with the shadow log reviewed
for false positives.

**Wake surface.** `role_brief.py` prints `mission <slug>: undriven (snapshot <age>)` per undriven
row of `cache["missions"]`, and `missions: unknown (no snapshot)` when the key is missing. It never
re-derives liveness.

**Page and brief.** `render_state` adds the open missions to its payload, next to `goal` and `map`
(`render_state.py:576-580`): `<program>: <its goal>`, its map, since, binding count, undriven or not
from the snapshot. Both the page and the `--context` brief (`state_brief.brief`) show them.
`state.md` is the authored half and gains no derived block.

### 4. The absorbed manifest stays writable, on purpose

The absorbed manager stays live through handover (`manager-contract.md:25-26`), and the owner
drives the mission with `bind --program <absorbed>`. Both write the absorbed manifest under its own
lock, which is exactly where the owner's engine reads. A delayed `carrier` or `retire` from the old
manager still finds its binding.

**Handover routing is separate from record repair.** The existing `fold-notice` branch
(`mine_report.py:192-193`) is unchanged in shape: a live absorbed manager still gets its stop and
handover notice (`CATCHUP_MESSAGE.md:35-40`) whether or not a `fold` record exists, because a record
is not a handover acknowledgement. Only its `absorber` resolves through `terminal_owner`. Separately,
an `absorbed_by` with no `fold` adds one line to the terminal owner's message: "`<slug>` has no fold
record: run `work_state.py absorb --program <owner> --from <slug>`". In `mine_report`, a program
that is not live but has `missions_open` gets `no-manager-here` with a line naming each open
mission and both exits, instead of `closed-program-rows`.

### 5. Migration of the old shapes

**Owner.** `work_state.py migrate --folds` (`work_state_migrate.migrate_folds`), a separate pass of
the existing converter. It does not take that pass's early return (`work_state_migrate.py:239`) or
its `todo_open` gate (`:241`), and never writes the R36 `migrated` event. It writes fold records
only through `work_state_store.absorb`, and every write pass holds the graph lock.

- **`--census`** (read-only) writes a plan file: every legacy fold edge from every shape in the
  table above. For each edge: the recorded target verbatim, the proposed target (`terminal_owner`
  over the proposed graph, so every migrated edge points at a live end), driver-type carriers on the
  absorbed manifest, open map children, unmigrated `lanes` / `claims`, family duplicates, conflicts,
  self-edges and cycles, and a `disposition` proposal: `open` when the absorbed manifest holds a
  session or lane carrier or its map has open children, else `closed: goal done or dropped before
  fold (census)`. Per manifest, the plan also records **the exact legacy values** `--finish` may
  remove (each `absorbs` dict entry, `supersedes`, `superseded_by`, a fold-valued `status`) and the
  set of binding keys `(ticket, carrier type, carrier id)`.
- **`--apply <plan>`** refuses the whole plan while any edge has a null disposition, a conflict, a
  self-edge, a cycle, or an open disposition whose proposed target fails `destination_ok`. A
  differing existing owner is never overwritten; the operator edits the plan. Then, per edge,
  `absorb`, with `closed_reason` for a closed disposition. It removes nothing, and each fold also
  writes its mirror entry, so code from before this ship stays correct on the result. Re-running
  skips committed folds (rule 1, retry first).
- **`--finish <plan>`** removes only the values the plan recorded. Per manifest, under the graph lock
  and its manifest lock: a recorded key that is absent is skipped; one whose current value equals the
  recorded value is removed (for `absorbs`, exactly the recorded dict elements, never a string
  entry); one whose value differs refuses that manifest with "changed since census; re-census". When
  something was removed, it appends one `fold-migrated` event holding the removed values. A re-run is
  idempotent without reading any event. Every key it can remove is one code from before this ship
  never read for scope (table above), so `--finish` does not change what reverted code sees.
- **`--verify <plan>`** (acceptance A4) exits 1 on: a recorded legacy value still present; a census
  edge whose absorbed manifest lacks `absorbed_by` equal to its proposed target or a valid `fold`; a
  cycle or missing target; an absorbed slug missing from its terminal owner's string `absorbs`; a
  recorded binding key that is neither present now nor followed by a `binding-retired` or
  `carrier-retired` event in that manifest's log. Normal work since the census (new binds, retires)
  never fails it.
- The row-11 case has no legacy entry; its census row is the hand-edit shape and gets `open`.

**`migrate_program` race.** It plans from an unlocked read (`work_state_migrate.py:231-237`) and
writes that plan under the lock (`:244-246`), so a concurrent `bind` is lost. It now refuses with
"manifest changed since planning; re-run" when the locked read's `bindings`, `lanes` or `claims`
differ from the planning read.

## Tests

`test_work_state.py`:

- `absorb` writes the mirror entry, then `absorbed_by` and `fold`, and one `absorb` row to each log;
  a second call writes no manifest. With `absorbed_by` already naming the absorber and no `fold`, it
  writes the `fold` (repair).
- Fault injection: an exception before step 1 leaves both manifests unchanged; after step 1, the
  owner's old-code `program_scope` (the pre-ship function, kept as a test fixture) already includes
  the source and a re-run completes the fold; after step 2 and between the appends, a re-run appends
  only the missing row and each log ends with exactly one row for that `fold_id`.
- Old-code compatibility: after `absorb` and after `migrate --folds --apply`, the pre-ship
  `program_scope` fixture covers every absorbed slug, including a status-only legacy fold and a
  chain C→B→A created by two `absorb` calls.
- Graph lock: two processes run `absorb A→B` and `absorb B→A` concurrently; exactly one succeeds,
  the other is refused as a cycle, and no two manifests point at each other.
- Retry: absorb A→B, crash before the events, absorb B→C, re-run absorb A→B: it succeeds, writes no
  manifest, and appends the missing rows.
- Mission setters: `mission-close` twice writes once and logs once; close, crash before the events,
  re-run: the events are completed once; close then reopen then close gives three events in order.
- `absorb` refuses: self-fold, an absorbed absorber (message names the terminal owner), a cycle, a
  conflicting `absorbed_by`, a missing goal, an open fold into a DONE absorber and into one with no
  `manager_session`, and a **closed** fold of B into a DONE absorber while C, folded into B, has an
  open mission. A closed fold with no open mission in the family into a DONE absorber is allowed.
  `mission-reopen` under a DONE terminal owner is refused. No `snapshot_cmd` gives `fold_no_tracker`.
- `terminal_owner` / `fold_family` / `open_missions`: C→B→A resolves C to A; a two-node cycle and a
  missing target give their notes and no owner.
- Driver rule: an open mission with no binding on the absorbed manifest gives `MISSION_UNDRIVEN` in
  `blocking` (exit 4). The **incident shape** (13 `bg` and 2 `agent` carriers absent from the owner's
  `live_bg`, sessions that ended turns past the lease, a `card` and a `wake`) still flags, and no
  carrier in it is STALLED for an unknown `bg`. A present `session`, a live `lane`, or a `bg` id in
  the owner's `live_bg` clears it. A `carrier-retired` event then derive flags again.
  `mission-close` clears it; `mission-reopen` restores it. A malformed or missing `fold` gives a note
  and the flag, never a `SchemaError`. `Status: DONE` with an open mission gets no exemption.
  `run_snapshot` writes `cache["missions"]`.
- Lifecycle on the absorbed manifest: a ship bound there is judged against the absorbed tracker, and
  `retire --program <absorbed>` succeeds once it closes and its bake binding exists. Its flags appear
  under `folded.<slug>`, not in `blocking`.
- A child session of the owner bound on the absorbed manifest is not UNBOUND for the owner. A ticket
  open in both manifests gives `fold_duplicate`; `bind` refuses a third copy. An unmigrated folded
  manifest gives `folded_unmigrated` and the flag with the migrate fix.
- `migrate --folds`: `--census` lists all six shapes with a chain resolved to its live end and
  records exact legacy values and binding keys; `--apply` refuses a null disposition, a cycle, a
  status-vs-pointer conflict and an open edge into a DONE target with every manifest untouched;
  `--apply` re-run after an injected crash applies each edge once; `--finish` removes exactly the
  recorded values, keeps string `absorbs` entries, refuses a manifest whose recorded key changed (a
  dict entry added after the census survives), and a re-run after a crash finishes without a second
  event; `--verify` fails on each violation class and passes after a new `bind` and a `retire`.
- `migrate_program` refuses when a `bind` lands between its planning read and its locked write.
- `work_state_waiters` names the absorbed manifest's session carrier as a ticket's owner.

`test_render_state.py`: the page and the `--context` brief list open missions with the absorbed
program's goal and omit closed ones; `--write-head` leaves `state.md` free of any missions block.
`test_role_brief.py`: the health line appears for an undriven row, is absent once driven, and reads
`unknown` with no cache. `test_mine_all.py`: with C→B→A and an existing `absorb B` candidate route,
the route record is unchanged and resolves to A's manager; a fold-notice for C names A; a valid fold
whose old manager is still live still gets its `fold-notice`; `absorbed_by` without `fold` adds the
repair line; an owner past the window floor with an open mission is kept and, with no live manager,
gets `no-manager-here` naming the mission.

## Acceptance (on the real stores)

`P=~/.claude/orchestrator/programs`, `R` = the release slug, `S` = the simulation slug, `PLAN` = the
census plan file. zsh, so `rc=$?`. Every producer's exit code is asserted on its own line before
its output is searched.

- **A1.** Before: `jq '.bindings|length' $P/$S.json > /tmp/a1n`. Then
  `work_state.py absorb --program $R --from $S --by <session>; rc=$?; test $rc = 0`, and these exit 0:
  `jq -e --arg r $R '.absorbed_by==$r and .fold.closed==null and (.fold.id|type=="string")' $P/$S.json`;
  `jq -e --arg s $S '.absorbs|index($s)!=null' $P/$R.json`;
  `test "$(jq '.bindings|length' $P/$S.json)" = "$(cat /tmp/a1n)"`;
  for each of `$P/$S.events.jsonl` and `$P/$R.events.jsonl`:
  `jq -se --arg id "$(jq -r .fold.id $P/$S.json)" '[.[]|select(.event=="absorb" and .fold_id==$id)]|length==1'`.
  Running the same `absorb` again exits 0 and leaves all four checks true.
- **A2.** `work_state.py snapshot --program $R --json > /tmp/a2.json; rc=$?`, then `test $rc = 4` and
  `jq -e --arg s $S '[.blocking[]|select(.flag=="MISSION_UNDRIVEN" and .item==$s)]|length==1' /tmp/a2.json`.
  This is the incident: the retained `bg` / `agent` carriers prove nothing and the parked sessions
  are past the lease. If it fails, the row's `drivers` names the carrier that cleared it; that is a
  finding to review, never a pass. After one persona session of R is bound on `$S`, re-run and
  check `test $rc = 0 -o $rc = 4` and
  `jq -e --arg s $S '([.blocking[]|select(.flag=="MISSION_UNDRIVEN" and .item==$s)]|length==0) and ([.missions[]|select(.program==$s and .undriven==false)]|length==1)' /tmp/a2.json`.
  Re-checked once that session ends a turn and awaits the manager.
- **A3.** While A2's first phase holds:
  `jq -e --arg s $S '(.missions.taken_at|type=="string") and ([.missions.rows[]|select(.program==$s and .undriven)]|length==1)' <R's cache>`
  exits 0. In R's manager session at its wake (the role ack it writes is that manager's normal
  load): `role_brief.py --program $R > /tmp/a3.txt; rc=$?; test $rc = 0`, then
  `grep -F "mission $S: undriven" /tmp/a3.txt` exits 0. After A2's driver, the same producer exits 0
  and that grep exits 1.
- **A4.** After `--finish $PLAN`: `work_state.py migrate --folds --verify $PLAN; rc=$?; test $rc = 0`.
- **A5.** `render_state.py --program $R --context > /tmp/a5.txt; rc=$?; test $rc = 0`, then
  `grep -F "$S: <the simulation goal verbatim>" /tmp/a5.txt` exits 0.

## Ships

One. Rules 1-5, the tests and the contract wording land together, and the `absorbs` **reader** is
deleted in the same change. The live-store steps are the operator's, in this order, because commits
to this repo go live on landing:

1. From the build worktree, before merge: `migrate --folds --census`, fill and review the plan,
   `--apply` it. The result is correct under the code still on master at every crash point, because
   each fold writes its mirror entry before its pointer.
2. Merge. Run A1 (the row-11 repair, if `--apply` did not already write its `fold`), A2, A3, A5.
3. `--finish $PLAN`, then A4.

**Rollback** at any step is reverting the merge. Reverted code reads the string mirror, which covers
every fold written before or after the ship, ignores `fold`, and never read any key `--finish`
removed. No data step is needed.

**Owed follow-up, not this ship:** delete the mirror (its writer and the string `absorbs` entries)
once reverting to pre-ship code is no longer wanted; and the guard override plus enforce file in the
operator harness (rule 3, "At the guard").

## Spec-review tier

**Critical.** The tier rule lists shared-store migrations and cutovers as critical: this ship
migrates the manifest store every manager reads, removes legacy keys, and changes what every
absorber's engine judges. SHADOW at the guard does not contain the risk, because a `SchemaError`
on the flag step blocks the turn.

Run so far: the standard lanes (R11a, R11b), the critical wave on `033b713` (F-sol, F-astra, F-cut),
and the final gate on `f18296f` (G-astra2, 8 findings, verdict REWORK).

**Bounded finish line.** After this rework the review closes as follows. A third final-gate pass
checks only that G-astra2-1 and G-astra2-2 (the two CRITICALs) are gone and that the fix
introduced no new CRITICAL. If they are gone, the spec is approved for build; any MAJOR or MINOR
that pass raises goes to the Review log as an owed follow-up, not into another rework.

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

Final gate on `f18296f` (G-astra2, astra frontier judge, verdict REWORK), 2026-11-17. Each finding
was re-checked read-only against the code at `f18296f`, and the incident source's carriers against
the live manifest. Where an earlier row above names a mechanism this rework removed (`--restore`,
`driver_unverified`, `live_program` for mining), the G-astra2 row supersedes it.

Totals: 8 findings; 8 fixed, 1 remedy rejected (G-astra2-3's per-operation identity; its defect is
fixed by setter semantics instead).

| Finding | Verdict | Where / reason |
| --- | --- | --- |
| G-astra2-1 (CRITICAL) one manifest lock does not protect the fold graph | fixed | `work_state_store.py:244-267` confirmed: `_Locked` guards one `<slug>.json.lock`. One graph lock `<programs>/folds.lock` is taken first by every fold writer, migration passes included; reciprocal-fold concurrency test (Design, rule 1). |
| G-astra2-2 (CRITICAL) staged rollout and rollback lose effective ownership | fixed | `work_state_sources.py:253` confirmed: old scope reads only string `absorbs`. The fold writer keeps a string `absorbs` mirror on the owner, written before the pointer, so old code is correct at every crash point and after a revert; `--finish` removes only keys old code never read; `--restore` is cut. Fault-injection and pre-ship-scope fixture tests (Design, rule 1, Ships). |
| G-astra2-3 retry repair undefined for repeated close/reopen | fixed; per-operation identity rejected | Absorb: a committed fold is recognised before admission, so a retry after a chained fold succeeds (test). Close/reopen become idempotent setters; an event is appended only when the log's latest mission event differs. Per-operation identity was rejected as machinery a single-operator store does not need: there is no automatic retry, so a re-run is a new decision on current state, not a replay. |
| G-astra2-4 migration cleanup deletes uncensused data; A4 count check fails on normal work | fixed | The census records exact legacy values and binding keys; `--finish` removes only values equal to the recorded ones and refuses a changed manifest; `--verify` checks binding containment with retire events allowed, not counts (rule 5, A4). |
| G-astra2-5 open missions reach an inactive owner; mining fix changed the wrong function | fixed | `mine_all.py:122-144` and `mine_report.py:189-199` confirmed; neither calls `live_program`. One `destination_ok` runs on every mutation that leaves an open mission under an owner, inherited missions and `mission-reopen` included. `program_entry` calls `program_family.open_missions`, is not dropped by the floor, and routes to `no-manager-here`. The `state_index.live_program` change is cut (rules 1, 2, 4). |
| G-astra2-6 fold-record repair replaces the handover notice | fixed | `CATCHUP_MESSAGE.md:35-40`, `mine_report.py:192-193` confirmed. The fold-notice branch keeps its condition; repair is a separate line to the terminal owner; test with a live old manager (rule 4). |
| G-astra2-7 driver rule makes A2 unable to detect the incident | fixed | Live manifest: `session=6, bg=13, agent=2, card=1, wake=1`; `work_state.py:207-210` confirmed. Drivers now need positive evidence: `session_present` within the lease, a live lane, or a background id in the owner's `live_bg`. Unknown is neither driver nor STALLED. Incident-shape test (rule 3). |
| G-astra2-8 A3 and A5 commands invalid | fixed | `role_brief.py:358-374` and `render_state.py:794-799` confirmed: both need `--program`; normal render prints a JSON receipt (`:831-834`). A3 and A5 capture output, assert the producer's exit first, and A5 reads `--context`; A2's post-driver check is scoped to `$S`. |

### Final gate (pass 3, bounded finish line): SHIP at `1d8d42e`

Both pass-2 CRITICALs are resolved and no new CRITICAL was found. Two non-blocking findings are owed to the build:

| Finding | Status |
| --- | --- |
| G-astra3-1 (MAJOR) migration cannot repair an existing pointer chain (C to B to A, C missing `fold`): census proposes the terminal target, apply refuses a differing immediate owner, and keeping C to B fails admission | owed to the build: keep the existing edge, write the `fold` record on it, and make the terminal owner's `absorbs` mirror cover the descendants; test with a chained fixture |
| G-astra3-2 (MINOR) `--finish` removes legacy values before appending `fold-migrated`; a crash between them loses the audit row | owed to the build: append the event first, then remove; a retry that finds the event and the values gone is complete |
