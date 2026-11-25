# Managers coordinate with each other

Founder ask (, 2026-11-25): "Manager sessions needs to understand what other managers are doing, so
if there's overlap, or clarifications / questions they can mesage and ask and decide ownership. baked
into the manager role, so they all report ownership and it's actively managed".

## What exists, and what is missing

The rules already exist. Contract §Membership and collisions says: first claim wins, transfer rather
than grab, a live-vs-live contest goes to the human, and a claim is abandoned when its manifest is more
than 24 h stale with no live manager and no live carrier. What is missing is the machinery that lets a
manager see, at every wake, which of those rules is firing now.

| Need | What exists | Gap |
|------|-------------|-----|
| (a) One machine-readable ownership record | The program manifest: `bindings` carry ticket, branch, worktree, PR (`publication`) and `paths`; `ceded` and `shared_touch_not_owned` record give-aways | A seam the program owns but has not yet bound to a ticket (a module, a skill, a directory) has no home. Only 1 of 17 `apps` bindings carries `paths` (jq over the live manifest, 2026-11-25), so path overlap almost never fires. |
| (b) See the others at every wake, overlaps flagged | `state_sources.overlap` compares open-PR files and bound paths between programs, read from rendered sidecars; `state_brief` prints it under "Held by" as "same files as X (advisory)" | Ticket, branch, worktree and seam overlaps are not compared at all. No manager sees who the other live managers are, what they own, or how to reach them. The role load (`role_brief.py`) never shows any of it. |
| (c) Message the other manager and settle ownership | `SendMessage` by session id; the contract names "an entry in its `.events.jsonl`" as the fallback | No record of a question or a settlement that both managers read. A message that arrives during an unattended wake is lost, and nothing tracks whether the question was answered. The live-vs-live escalation has no trigger. |
| (d) Expire a dead claim and hand it over | The abandonment rule, in prose; `role_brief.holder_live` and `program_family.session_present` decide manager liveness | Nothing evaluates the rule, and there is no takeover writer. |

## Design

One new module, `scripts/coordinate.py`, owns the cross-manager view and the coordination ledger. It
reuses every existing owner: manifests for ownership, `state_sources.paths_overlap` and
`state_sources.overlap` for path overlap, `program_family` for liveness, `work_state_store` for
manifest writes and binding retirement. `role_brief.py` prints its block at every role load, so every
manager gets it without opting in.

### 1. Ownership record: the manifest, plus one key (`owns`)

The manifest stays the one ownership record (contract §Program state). Tickets, branches, worktrees, PRs
and bound paths stay in `bindings`, written only by `work_state.py`. One new key records seams:

```json
"owns": [ { "seam": "<short name>", "repo": "<owner/name or local repo dir name>",
            "paths": ["<globs, never a root glob>"], "since": "<RFC3339 UTC>" } ]
```

- `validate_owns` in `work_state_store.py` is its strict schema: unknown key, missing key, wrong type,
  a root glob or a duplicate `seam` refuses the write. `_Locked.write` runs it whenever `owns` is present,
  as it does for `bindings`.
- Only `coordinate.py own|release|settle|takeover` write it, under the manifest lock. A hand edit is a
  schema refusal at the next engine write.
- A seam is program-level intent ("this program owns the manager role code"). A binding's `paths` is a
  ticket-level lock. Both count as claims for overlap.
- First claim wins (contract, unchanged). `own` refuses a seam whose paths overlap another live
  program's seam and prints the `ask` command instead. The earlier `since` (or the earlier `bound_at`
  for a binding) is the first claim.

### 2. The coordination ledger

`~/.claude/orchestrator/programs/coordination.jsonl`, append-only, one JSON object per line, written only
by `coordinate.py` under an flock on `coordination.jsonl.lock`. It is the record both managers read; the
`SendMessage` is only the doorbell. The name does not end in `.json`, so manifest globs skip it.

Row shape (strict; the writer validates it):

```json
{ "ts": "<RFC3339 UTC>", "thread": "c-<YYYYMMDD>-<6 hex>", "verb": "ask|reply|settle|contest|ruling|takeover",
  "from": "<program>", "to": "<program>", "item": "<kind>:<value>", "text": "<one paragraph>",
  "owner": "<program; settle, ruling and takeover only>", "session": "<writer's session id>" }
```

Item kinds: `ticket:<id>`, `branch:<repo>:<ref>`, `worktree:<abs path>`, `pr:<repo>#<n>`,
`path:<repo>:<glob>`, `seam:<name>`, `question:<topic>` (a clarification with no ownership at stake).

Thread state is derived from its rows, never stored:

| State | Derived when |
|-------|--------------|
| `open` | An `ask` with no later `settle`, `ruling` or `takeover` (a `reply` keeps it open) |
| `answered` | A `question:` thread with a `reply` from the asked program |
| `settled` | The last decisive row is a `settle` and no later `contest` exists |
| `contested` | A `contest` after a `settle`, or both programs have written `contest` |
| `escalate` | `contested` with both managers live, or `open` for more than 24 h with both managers live |
| `expired` | The asked program's claim is abandoned (rule 4) while the thread is open |
| `ruled` | A `ruling` row (the founder's answer, written by the manager that asked the founder) |
| `taken` | A `takeover` row |

A `settle` is written by either party and names the `owner`. If the settler is not the owner, it is a
cede: `coordinate.py` appends `{item, to: owner}` to the settler's `ceded` and, for a `seam:`, drops the
seam from the settler's `owns`. If the settler is the owner, the other party sees the settle at its next
wake and either accepts it (no row) or writes `contest`. A contest by both parties is a live-vs-live
deadlock: `escalate`, and the founder decides through `AskUserQuestion` naming both goals and the item
(contract, unchanged). The manager records the answer with `ruling`.

### 3. The peer view at every wake

`coordinate.py peers --program <slug> [--json]` prints the block `role_brief.py` embeds. Its inputs are
read fresh each call: every manifest (`work_state_store.read_all`), the session index
(`program_family.session_index(write=False)`), the rendered sidecars for PR files
(`state_index.other_sidecars` and this program's own sidecar), and the ledger.

**Peers.** A peer is another manifest that is a live program (`state_index.live_program`: not absorbed,
not done) and is either held by a present manager (`role_brief.holder_live` over
`HOLDER_WINDOW_S`) or has at least one open binding. Dormant manifests (no manager, no bindings) are not
peers; there are 30+ of them today.

**Block shape** (bounded: at most 12 peer lines, 10 overlap lines, 8 thread lines; a cut prints
`+N more: coordinate.py peers --program <slug>`):

```
Other managers (3 live, 1 abandoned):
- Apps [apps] manager local_6511f250-… present 12m; owns seam "portal billing"; 17 tickets, 2 PRs, 3 worktrees
Overlaps (2):
- ticket T-123 is bound by you and by Apps (theirs first, 2026-11-20): ask → coordinate.py ask --program <me> --to apps --item ticket:T-123 --text "…"
- path keel:.claude/skills/x/** (your seam) vs Legal open PR #12 files (advisory): ask, or re-scope
Threads for you (1): c-20261125-ab12cd from Apps asks about seam:portal billing (open 2h) → reply/settle
Escalate to founder (0)
Takeover available (1): Ops claim ticket:T-9 is abandoned (manifest 31h stale, no live manager, no live carrier) → coordinate.py takeover …
```

Every line names its one next command, with the program and item filled in.

**Overlap kinds compared** (mine against each peer's):

| Kind | Mine | Theirs | Predicate |
|------|------|--------|-----------|
| ticket | open binding tickets | open binding tickets | equal id |
| branch | binding `branch` (+ publication repo) | same | equal repo and ref |
| worktree | binding `worktree` | same | equal real path |
| pr | binding `publication` repo + pr | same | equal |
| path | seam paths, binding paths, own open-PR files | same | `state_sources.paths_overlap`; PR-file pairs through `state_sources.overlap` (same-PR pairs dropped) |

An overlap whose item has a `settled`, `ruled` or `taken` thread is suppressed when the record agrees
with the manifests (the loser no longer holds it). If the loser still holds it, the line reads
`settled to <owner> on <date>, but <loser> still holds it: release it` and goes to the loser's block.

**Fold families are not peers of each other.** A program and the programs absorbed into it already
share one owner (`program_family.terminal_owner`); their duplicates are the engine's `fold_duplicate`
note, never a coordination thread.

### 4. Expiry and handover

`coordinate.py` evaluates the contract's abandonment rule; it does not define a new one. A peer claim is
**abandoned** when all three hold:

1. the peer manifest's `updated_at` is more than 24 h old;
2. no present manager holds it (`holder_live` is false);
3. none of the binding's carriers is live: a `session` carrier with no present session-index row, a
   `lane`/`bg`/`agent` carrier whose `pid` is gone or whose `pid_start` no longer matches
   (`work_state_store.pid_start`), and `wake`/`card`/`founder` carriers never count as live.

A seam is abandoned when conditions 1 and 2 hold. `coordinate.py takeover --program <me> --from <peer>
--item <item> [--text]` re-checks the rule under the peer's manifest lock and refuses unless it holds.
Then it:

- `ticket:` retires the peer's binding through `work_state_store.retire` with
  `reason: "takeover by <me>"` and an allow predicate that accepts only this case, and prints the
  `work_state.py bind --program <me> --ticket <id> --continue` command (binding needs the tracker
  snapshot, which `work_state.py` owns);
- `seam:` moves the seam from the peer's `owns` to mine;
- appends `takeover` to the ledger and `{"event": "takeover", ...}` to both programs' `.events.jsonl`.

A thread to an abandoned program is `expired`; the block offers the takeover in its place.

### 5. The role carries it

- **Role card** (`references/role.md`), one new line replacing the current membership line:
  *Coordinate with the other managers.* Every role load prints the other managers, what they own and
  every overlap; record what you own (`bindings` through the engine, unbound seams through
  `coordinate.py own`); on an overlap or a question, `coordinate.py ask` and `SendMessage` the peer's
  `local_` id in the same turn; answer every thread addressed to you in the turn you see it (reply,
  settle or contest); first claim wins, a contest by both goes to the founder; take over a claim only
  when the block says it is abandoned.
- **Wake steps**: a new step 3c *Coordinate*, after oversight: act on every line of the "Other managers"
  block in the same message as step 4's dispatches.
- **Contract** §Membership and collisions keeps its rules and gains the mechanics: the `owns` key, the
  ledger, the thread states, the takeover writer. The clause "or an entry in its `.events.jsonl`" is
  deleted: the ledger replaces it. §Program state's manifest example gains `owns`.
- **`role_brief.py`** embeds `coordinate.peers_block(slug, session, now)` after the health lines and
  before the role card. A failure degrades the load (`degraded: true`) and prints one line naming the
  by-hand command; it never blocks the load. Imports stay lazy so the Stop guard's 2 s budget, which
  imports `role_version` from this module, is untouched.
- **`SendMessage`**: `ask` prints the exact payload: `to` = the peer's `local_` id parsed from its
  `manager_session`, a message that names the thread id, the item, the question and the reply command,
  and `notify_when_idle: true`. The ledger row is written first, so a message lost to an unattended wake
  still reaches the peer at its next role load.

## Files

| File | Change |
|------|--------|
| `scripts/coordinate.py` | New. Peers, overlap, ledger, thread state, `own/release/ask/reply/settle/contest/ruling/takeover`, `peers_block` |
| `scripts/test_coordinate.py` | New. Unit tests over temp programs dirs and a fake session index |
| `scripts/work_state_store.py` | `validate_owns`; `_Locked.write` validates `owns` |
| `scripts/role_brief.py` | Embed the peers block; degrade on failure |
| `scripts/test_role_brief.py` | The block appears; a broken ledger degrades, never blocks |
| `references/role.md` | Role card line, wake step 3c, `## Changes` line |
| `references/manager-contract.md` | §Membership and collisions mechanics; §Program state `owns` key; events.jsonl clause deleted |

Keel stays repo-agnostic: no repo paths, tracker prefixes or schemas. Item values are opaque strings.

## Tests

1. Two temp manifests with the same open ticket → one `ticket` overlap line on each side, naming the
   earlier `bound_at` as first claim.
2. Same branch, same worktree, same PR → one line each; a fold-family pair → no line.
3. A seam glob against a peer's open-PR file list (sidecar) → one `path` line; a same-PR pair → none.
4. `own` refuses an overlapping seam of a live peer and prints the `ask` command; accepts a disjoint one.
5. `validate_owns` refuses an unknown key, a root glob and a duplicate seam.
6. Ledger: ask → `open`; reply on a `question:` → `answered`; settle by the non-owner → `settled`, and
   the settler's `ceded` gains the item and its `owns` loses the seam; settle by the owner then contest →
   `contested`; both live → `escalate`; ruling → `ruled`; an `open` ask older than 24 h with both live →
   `escalate`.
7. Abandonment: stale manifest + absent manager + dead lane pid → `takeover` succeeds, the binding goes
   to the peer's events as `binding-retired` with the takeover reason; a live manager or a live carrier
   → refused.
8. A settled overlap the loser still holds → the "still holds it: release it" line on the loser's side.
9. `role_brief` brief contains "Other managers"; a corrupt ledger line is skipped with one note; an
   exception inside `peers_block` degrades the load and records the ack.
10. Block bounds: 20 peers → 12 lines plus the `+N more` line.

## Acceptance (live)

- `coordinate.py peers --program harness` and `--program <a second live program>` each list the other as
  a present manager with its ownership, from the real stores.
- One real question thread: the Harness manager `ask`s a second live manager, sends the doorbell, and the
  second manager `reply`s or `settle`s; both role loads show the thread's final state. Evidence on  the feature ticket.

## Ships

One PR in keel. No cutover: the ledger starts empty, `owns` is optional, and the peers block is
additive to the brief. The deleted `.events.jsonl` clause has no reader in code (prose only).

## Spec-review tier

Standard: behavior-bearing harness change, no access, money, tenancy or personal data; local files only.
