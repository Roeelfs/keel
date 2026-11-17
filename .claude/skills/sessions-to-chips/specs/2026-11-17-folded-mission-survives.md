# A folded program's mission survives

Row 11 of the account-switch gaps (founder, 2026-11-17). When one program is folded into another,
the absorber takes over the absorbed program's owed items but not its goal. Nothing records the fold
in the manifest, so every reader that keys on `absorbed_by` misses it, and nothing checks that
someone still drives the absorbed goal.

This spec gives the fold ONE writer, makes the absorbed goal a standing **mission** in the
absorber's manifest and state file, and makes the work-state engine fail while a mission has no
live driver. Every rule has one owner; where a rule has copies today, the spec names the copy it
deletes.

## What happened

A customer-simulation program ("simulate brand-new customers walking every access path to first
value") was folded into a release program during an account-switch takeover on 2026-11-16.

- The release program's state file gained a `## Taken over from <program>` section listing the
  owed items: one parked PR, one grant, one bake, one live child. It names no goal.
- The absorbed program's persona tickets stayed in Backlog and its drive sessions stayed parked.
  No session or lane drove "reach first value" after the fold.
- The absorbed manifest kept `absorbed_by: null`, and the absorber's `absorbs` list did not gain
  it. So `mine_report` never emitted a `fold-notice`, `state_index.live_program` and
  `work_state_waiters._programs` still treat the absorbed program as live, and
  `work_state_sources.program_scope` does not count its children toward the absorber.

**The fold has no writer today.** Every `absorbed_by` / `absorbs` hit in `scripts/` is a read
(`program_family.py:208,407`, `mine_all.py:147`, `mine_report.py:106,190-193`,
`state_index.py:45`, `work_state_sources.py:253,318`, `work_state_waiters.py:10`); the operator
harness has none either (`grep -rn absorbed_by ~/.claude/scripts ~/.claude/hooks`, 2026-11-17,
zero hits). Managers hand-edit manifests or write prose, so the fold is recorded three ways on the
live store (2026-11-17, python scan of `~/.claude/orchestrator/programs/*.json`):

| Shape | Manifests | Seen by `absorbed_by` readers |
| --- | --- | --- |
| `absorbed_by: <slug>` | 9 | yes |
| `status: merged-into-<slug>` / `superseded-by-<slug>` | 9 | no |
| absorber `absorbs: ["<slug>"]` | 4 | yes (`program_scope`) |
| absorber `absorbs: [{"program": ..., "fold": ..., "status": ...}]` | 1 | no: `program_scope` keeps only strings |
| prose section in the absorber's state file only | the row-11 case | no |

## Files

| File | Change |
| --- | --- |
| `scripts/work_state_store.py` | Owns the fold record. New `absorb()` and `close_mission()`; `MISSION_KEYS` strict validator; binding gains optional `mission`. |
| `scripts/work_state.py` | New verbs `absorb`, `mission-close`; `bind --mission`; derive gains the `MISSION_UNDRIVEN` flag (blocking) and refuses the `DONE` exemption while a mission is open. `migrate` normalizes the old fold shapes. |
| `scripts/work_state_sources.py` | `program_scope` reads absorbed slugs from `missions[]`; `build_ctx` passes `missions` into ctx. |
| `scripts/program_family.py` | `load_manifests` carries `missions` instead of `absorbs`. |
| `scripts/state_view.py` | `--write-head` also rewrites a derived `## MISSIONS` block from the manifest. |
| `scripts/role_brief.py` | One health line per open mission with no live driver. |
| `scripts/mine_report.py` | `fold-notice` text tells the absorber to run `work_state.py absorb` if the mission is missing. |
| `references/manager-contract.md`, `SKILL.md` | The takeover order runs `absorb` before step (4), and the `fold-notice` paragraph names the verb; the `absorbs` wording goes. |
| `scripts/test_work_state.py`, `scripts/test_state_tabs.py` (or the state-view test that owns `--write-head`), `scripts/test_role_brief.py` | Tests below. |

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
  A second `absorb` of the same pair is a no-op that prints the existing mission (idempotent, so a
  retried takeover never doubles it).
- Append one `{"event": "absorb", "from": ..., "into": ..., "by": ...}` row to BOTH programs'
  event logs.

**Deleted.** The manifest key `absorbs` (both shapes). `missions[].program` is the one list of
absorbed programs. `program_scope` (`work_state_sources.py:253`) and `load_manifests`
(`program_family.py:208`) read it instead. Hand-editing `absorbed_by` stops being a documented path.

### 2. The absorbed goal is a standing mission with its own drivers

**Owner of the record.** The absorber's manifest `missions[]` (rule 1). Nothing else stores the goal.

**Drivers.** A binding gains an optional `mission: "<absorbed slug>"` key, set by
`work_state.py bind --mission <slug>` (the strict binding validator gains the key; an unknown slug
is refused). The absorbed program's tickets are bound in the absorber with that key, so its
children and lanes are the absorber's carriers, tracked like any other.

**State file.** `state_view.py --write-head` rewrites one `## MISSIONS` block in place, derived from
the manifest on every head write: one line per open mission (`<program>: <goal>`, map, since, the
number of bindings tagged with it). The manager never edits it; `state_view` never parses it back.
It is a rendered view, not a second record. The prose `## Taken over from ...` section stays the
manager's narrative of owed items, as today.

**Closing.** `work_state.py mission-close --program <absorber> --mission <slug> --reason "<evidence>"`
sets `closed` to `{"at": ..., "reason": ...}` and appends an event. A non-empty reason is required.
A founder decision to park the goal is closed this way, with the founder named in the reason. Nothing
else closes a mission, and a closed mission is never deleted.

### 3. The convergence check fails while a mission has no live driver

**Owner.** `work_state.py derive`. It already decides blocking and the `DONE` exemption (R29); a
second checker would be a second owner.

**Behaviour.**

- New flag `MISSION_UNDRIVEN`, added to `FLAGS` and to the blocking set beside `UNBOUND` and
  `READY_NOT_DISPATCHED`. It fires for each mission with `closed: null` and no binding tagged
  with it that has a live **driver** carrier. A driver is a carrier of type `session`, `lane`, `agent`,
  `workflow` or `bg` whose `carrier_state` is live. `founder`, `bake`, `card` and `wake` carriers
  hold a ticket but do not drive a goal, so they never satisfy it. A `Hold:` does not exempt it.
  The fix text names both exits: `bind --mission <slug>` plus a carrier, or `mission-close`.
- `Status: DONE` gets no exemption while any mission is open; the note is
  `status_done_open_mission_<slug>:no_exemption`.
- `map_line` appends `missions open N, undriven M` when the program has missions.
- `Status: GRILLING` does not exempt it, the same as `UNBOUND`.

The Stop guard calls `work_state.py guard`, so the flag reaches the guard with no guard change. It
rides the guard's current SHADOW mode: `would_block:MISSION_UNDRIVEN` is logged and nothing blocks
until flags are enforced for every flag at once.

**Wake surface.** `role_brief.py` prints one health line per undriven open mission (read from the
manifest and the last snapshot cache, no network), so the manager sees it at every role load.

### 4. Migration of the old shapes

**Owner.** `work_state.py migrate` (`work_state_migrate.py`), the existing one-shot converter.

- `absorbs: ["<slug>"]` and `absorbs: [{"program": "<slug>", ...}]` become `missions[]` entries, with
  the goal copied from the absorbed manifest and `since` from its newest `absorb` event, else the
  migration time. `absorbs` is removed. The absorbed manifest gets `absorbed_by` if unset.
- `status: merged-into-<slug>` / `superseded-by-<slug>` set `absorbed_by` to that slug and get NO
  mission. Those programs were closed before this rule existed; a mission for them would flag
  absorbers for goals nobody owes. An unresolvable target, such as a bare `superseded`, is reported, not
  guessed.
- The row-11 case has no machine record to migrate from. It is fixed by running `absorb` once
  (acceptance A1), not by migration.

## Tests

`test_work_state.py`:

- `absorb` sets `absorbed_by`, appends one mission with the verbatim goal, writes both events; a
  second call is a no-op.
- `absorb` refuses: self-fold, an absorbed absorber, a conflicting `absorbed_by`, a missing goal.
- `bind --mission` with an unknown slug is refused; the strict validator rejects a misspelled key.
- derive: an open mission with no tagged binding gives `MISSION_UNDRIVEN` in `blocking` (exit 4).
  A tagged binding whose only carrier is `founder`/`bake` still flags. A live `session` or `lane`
  carrier clears it. `mission-close` clears it. `Status: DONE` with zero open children and an open
  mission gets no exemption.
- `program_scope` counts children of a mission's program toward the absorber (replaces the
  string-only `absorbs` read).
- migrate: string and dict `absorbs` become missions and `absorbs` is gone; `merged-into-*` sets
  `absorbed_by` with no mission; bare `superseded` is reported.

State-view test: `--write-head` rewrites `## MISSIONS` in place (twice gives one block) and omits
closed missions. `test_role_brief.py`: the health line appears for an undriven mission and is
absent once it is driven.

## Acceptance (on the real stores)

- **A1.** After `work_state.py absorb --program <release slug> --from <simulation slug>`:
  `jq .absorbed_by` on the simulation manifest is the release slug, and `jq '.missions[].program'` on
  the release manifest lists it with the simulation goal verbatim.
- **A2.** `work_state.py snapshot --program <release slug> --json | jq '.blocking[] | select(.flag=="MISSION_UNDRIVEN")'`
  returns the simulation mission while no persona session or lane is bound with
  `mission`, and returns nothing after one live persona session is bound.
- **A3.** The next mine's plan emits a `fold-notice` for the simulation program, and
  `state_index.live_program` is false for it.
- **A4.** After `migrate --all`, no manifest under `~/.claude/orchestrator/programs/` has an `absorbs` key, and
  every `merged-into-*` manifest has `absorbed_by` set (checked with a python scan, not grep).
- **A5.** The release state file shows a `## MISSIONS` block after the next `--write-head`.

## Ships

One. Rules 1-4, the tests and the contract wording land together; the `absorbs` reads are
deleted in the same change. A1 and `migrate --all` run on the live store after merge, as the
operator's step.

## Spec-review tier

**Standard.** This is behaviour-bearing: a new blocking flag in the engine every manager's guard calls,
and a one-shot migration of a shared store, the manifests. No access, credentials, money, tenancy or
personal data, and the flag is SHADOW at the guard, so a wrong verdict logs and blocks nothing.
That keeps it off critical. It is not light because it changes the manifest schema and blocking.
The migration lane is the one to keep: it rewrites live manifests.

## Review log

_(placeholder: spec-review report path and fixes applied go here)_
