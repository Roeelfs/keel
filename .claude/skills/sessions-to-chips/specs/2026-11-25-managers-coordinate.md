# Managers coordinate with each other

Founder ask, 2026-11-25: "Manager sessions needs to understand what other managers are doing, so
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
- First claim wins (contract, unchanged). `own` refuses a seam whose paths overlap a non-abandoned
  peer's seam or bound paths and prints the `ask` command instead. The earlier `since` (or the earlier `bound_at`
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

Thread state is derived from its rows, never stored. Precedence, first match wins:
`taken` > `ruled` > `expired` > `escalate` > `contested` > `settled` > `proposed` > `answered` > `open`.

| State | Derived when |
|-------|--------------|
| `taken` | A `takeover` row, and the taker now holds the item. If it does not, `taken-unbound`: the taker re-runs `takeover` |
| `ruled` | A `ruling` row: the founder's answer, written only by the manager that asked (it is the founder liaison for the thread) |
| `expired` | Either party's claim is abandoned (rule 4). The block offers the takeover in its place |
| `escalate` | `contested` with both managers present, or `open`/`proposed` for more than 24 h with both present |
| `contested` | The last decisive row (`settle` or `contest`) is a `contest`: a contest after a settle reopens it, and a contest before any settle contests it |
| `settled` | The last settle names an owner that is not its writer (a cede, final at once), or both parties have settled to the same owner |
| `proposed` | The last settle is a self-award (writer == owner) that the other party has not yet matched |
| `answered` | A `question:` thread with a `reply` from the asked program |
| `open` | An `ask` with none of the above |

Writers are bound to the thread: only its two programs may write to it, `settle` and `ruling` name one of
them as `owner`, and a `ruled` or `taken` thread takes no more rows. One thread per item and pair: `ask`
returns the existing unfinished thread instead of opening a second one.

A cede (`settle` naming the other party) appends `{item, to: owner}` to the settler's `ceded` and, for a
`seam:`, drops the seam from its `owns`. For a ticket, branch, worktree or PR, the settler's block then
carries a `release` line with the exact command: `coordinate.py release --program <me> --item <item>`
retires the binding that holds the item with reason `ceded to <owner>` and verdict `ceded`, which
render_state's shipped history skips. A self-award stays `proposed` until the counterparty matches it, or
contests it (then `contested`, `escalate` with both present). The founder decides an escalation through
`AskUserQuestion` naming both goals and the item (contract, unchanged), and the asker records the answer
with `ruling`.

### 3. The peer view at every wake

`coordinate.py peers --program <slug> [--json] [--all]` prints the block `role_brief.py` embeds. Its inputs
are read fresh each call: every manifest (`work_state_store.read_all`), the session index
(`program_family.session_index(write=False)`), the sidecars through their one reader
(`state_index.other_sidecars`), and the ledger.

**Peers and fold families.** A peer is a terminal owner (`program_family.terminal_owner`) other than mine
that is a live program (`state_index.live_program`) and is either held by a present manager
(`role_brief.holder_live`) or has at least one open binding in its fold family. An absorbed program's
bindings and seams count as its terminal owner's; its duplicates with its own owner stay the engine's
`fold_duplicate` note. `ask` or `takeover` naming an absorbed program is refused with the terminal owner's
name.

**Display versus contact.** Each peer line shows the display name and slug, and separately the contact: the
one full `local_…` session id that the session index resolves from `manager_session` for a present
manager, or `ledger-only (<why>)` when the manager is absent, the id is ambiguous or unresolved, or the
runtime is not Claude Code.

**Block shape.** Render order: escalations, threads, release, takeover, exact overlaps, path overlaps,
peers. Escalations and threads are never cut; the other sections are capped (10 release/overlap lines each,
8 takeover lines, 12 peer lines) with `+N more: coordinate.py peers --program <slug> --all`, and `--all`
disables every cap. Every line names its one next command with the program and item filled in; an overlap
with an open thread names that thread (`coordinate.py show --thread <id>`) instead of a fresh `ask`.

**Overlap kinds compared** (my fold family against each peer's):

| Kind | Predicate |
|------|-----------|
| ticket | equal id |
| branch | equal repo and ref. The same ref with the repo unknown on one side is shown as an overlap marked "repo unknown"; two different repos never overlap |
| worktree | equal real path |
| pr | equal repo and number |
| path | seam paths, binding paths and sidecar PR files, through `state_sources.overlap` (same-PR pairs dropped); advisory |

The first claim is the earlier `since`/`bound_at`; a tie goes to the lower slug, so both sides never read
"yours". An overlap with a `settled`, `ruled` or `taken` thread is silent for the winner and becomes the
loser's `release` line while the loser still holds it.

**Coverage.** Path overlap is only as good as the sidecars. The Overlaps header names every peer whose
sidecar is missing, older than 3 h, collapsed to directories, or has dropped PR files; with any such peer
and no overlap found, the block says "none found in what could be read; this is not a no-overlap verdict".

### 4. Expiry and handover

`coordinate.py` evaluates the contract's abandonment rule on the terminal owner; it does not define a new
one. A claim is **abandoned** when all three hold:

1. the owner manifest's `updated_at` parses and is more than 24 h old (missing or unparseable is not stale);
2. no present manager holds it (`holder_live` is false);
3. no carrier on any binding of any program in its fold family is live, judged by
   `work_state.carrier_state`. Liveness fails closed: `unknown` is live, a `wake` carrier is live, and a
   `pid` that `ps` did not return is live unless `kill(pid, 0)` proves it gone.

`coordinate.py takeover --program <me> --from <peer> --item <ticket:|seam:…>` takes `folds.lock`, then the
coordination lock, re-reads every store and re-applies the rule. Then:

- `ticket:` moves the binding with `work_state_store.transfer`: one operation under both manifest locks in
  sorted slug order, binding at the destination first (branch, worktree, artifact, publication and paths
  kept; carriers reset) and retiring at the source second, with the abandonment rule re-checked under the
  source lock. A ticket outside my map is refused before anything moves (the fold, `work_state.py absorb`,
  is the route for that). Both programs' events get `binding-transferred`, never `binding-retired`, so
  history never reads a hand-over as shipped.
- `seam:` removes the seam from the peer first and adds it to mine second (a crash between leaves it
  unowned, never doubly owned).
- The ledger `takeover` row is written last, so a `taken` row always has a moved claim behind it.

### 5. The role carries it

- **Role card** (`references/role.md`): *Coordinate with the other managers.* Every role load prints the
  other managers, what they own and every overlap; record what you own (`bindings` through the engine,
  unbound seams through `coordinate.py own`); on an overlap or a question, `coordinate.py ask`, then send
  its printed payload; answer every thread addressed to you in the turn you see it; first claim wins, a
  contest goes to the founder through the asker; take over only what the block calls abandoned.
- **Wake steps**: step 3c *Coordinate*, after oversight: act on every line of the block in the same
  message as step 4's dispatches.
- **Contract** §Membership and collisions keeps its rules and gains the mechanics (the `owns` key, the
  ledger, thread states, release, transfer-based takeover, lock order). The clause "or an entry in its
  `.events.jsonl`" is replaced by the ledger. §Program state's manifest example gains `owns`.
- **`role_brief.py`** embeds `coordinate.peers_block(slug, session, now)` after the health lines and before
  the role card. A failure degrades the load (`degraded: true`) and prints the by-hand command; it never
  blocks. Imports stay lazy so the Stop guard's 2 s budget is untouched. Measured: `peers` runs in 0.10 s
  warm and prints 1.8 KB against the live stores (2026-11-25), inside the 250 ms / 4 KiB budget.
- **Transport.** The ledger row is the message; `SendMessage` is the doorbell. `ask` writes the row
  first, then prints the payload (`to` = the resolved full session id, the thread id, item, question and
  reply command, `notify_when_idle: true`) only when the contact resolves; the asker sends it from a
  non-final message of its turn. Otherwise `ask` reports ledger-only, and the row reaches the peer at its
  next role load.
- **Lock order**, for every writer: `folds.lock`, then `coordination.jsonl.lock` (re-entrant within a
  process), then manifest locks in sorted slug order. `own` checks and writes under the coordination lock,
  so two managers cannot both win the same paths, and a retry with the same repo and paths keeps the
  original `since`.

## Files

| File | Change |
|------|--------|
| `scripts/coordinate.py` | New. Peers, overlap, coverage, ledger, thread state, `own/release/ask/show/reply/settle/contest/ruling/takeover`, `peers_block` |
| `scripts/test_coordinate.py` | New. Unit tests over temp programs dirs and a fake session index |
| `scripts/work_state_store.py` | `validate_owns`; `_Locked.write` validates `owns`; `transfer` |
| `scripts/state_index.py` | `other_sidecars` takes a `programs` dir |
| `scripts/render_state.py` | Shipped history skips `ceded` retirements |
| `scripts/role_brief.py` | Embed the peers block; degrade on failure |
| `scripts/test_role_brief.py` | The block appears; a broken ledger degrades, never blocks |
| `references/role.md` | Role card line, wake step 3c, `## Changes` line |
| `references/manager-contract.md` | §Membership and collisions mechanics; §Program state `owns` key; transport rule |

Keel stays repo-agnostic: no repo paths, tracker prefixes or schemas. Item values are opaque strings.

## Tests

`test_coordinate.py` covers: ticket/branch/worktree/PR overlap and the fold family's silence (1, 2); path
overlap against sidecar PR files (3); `own` refusal, acceptance, retry-keeps-`since` and concurrent
admission of exactly one (4, 17, 18); `validate_owns` (5); every thread state, asker-only ruling and closed
threads (6, 6b, 11, 12); idempotent `ask` and non-party refusal (13); ledger-only contact (14); coverage
(15); repo-unknown branches (16); takeover by transfer, foreign-map refusal, live refusals, fail-closed
liveness and folded-peer refusal (7, 7b, 7c, 7d); release of a settled item with a `ceded` verdict that
history skips (8); corrupt ledger lines (9b); caps, `--all` and uncut escalations (10, 10b).
`test_role_brief.py` covers the embedded block and degradation.

### Carried obligations

| Finding | Obligation | Proof |
|---------|------------|-------|
| F-1 | A self-award is `proposed` until matched; writers are thread parties | `test_coordinate` 11, 13 |
| F-2 | One state machine with fixed precedence | `test_coordinate` 6, 6b, 11, 12 |
| F-3 | Abandonment over every binding of the fold family, failing closed | `test_coordinate` 7b, 7c |
| F-4 | No `taken` row without the claim moved, metadata kept | `test_coordinate` 7 (transfer, foreign-map refusal) |
| F-5 | A runnable release for every ceded kind | `test_coordinate` 8 |
| F-6 | Exact recipient or ledger-only | `test_coordinate` 14 |
| F-7 | Serialized admission, fixed lock order | `test_coordinate` 18 (two processes, one winner) |
| F-8 | The feature ticket is linked into its map | Linear parent set; checked on the ticket |
| F-9 | Absorbed claims projected to the terminal owner | `test_coordinate` 2, 7d |
| F-10 | One sidecar reader, coverage reported | `test_coordinate` 15 |
| F-11 | Repo-aware branch keys | `test_coordinate` 16 |
| F-12 | Reachable overflow, fixed cut order | `test_coordinate` 10, 10b |
| F-13 | One thread per item and pair | `test_coordinate` 13 |
| F-14 | Role-load budget measured | 0.10 s, 1.8 KB live (2026-11-25), §5 |
| F-15 | Live bake at the feature revision | Two present managers exchange a thread; evidence on the ticket |
| F-16 | Transfers and cedes never read as shipped | `test_coordinate` 7, 8 (`render_state.publications`) |
| F-17 | Display identity separate from contact | `test_coordinate` 14; live `peers` output |

## Acceptance (live)

- `coordinate.py peers --program harness` and `--program <a second live program>` each list the other as
  a present manager with its ownership, from the real stores.
- One real question thread: the Harness manager `ask`s a second live manager, sends the doorbell, and the
  second manager `reply`s or `settle`s; both role loads show the thread's final state. Evidence on the feature ticket.

## Ships

| Ship | Scope items | Files and contracts | blockedBy | Dependency |
|------|-------------|---------------------|-----------|------------|
| 1 | (a) `owns` key, (b) peers block and overlaps, (c) ledger and threads, (d) expiry and takeover, role wiring | Every file in §Files | none | none |

One PR in keel. No cutover: the ledger starts empty, `owns` is optional, and the peers block is
additive to the brief. The deleted `.events.jsonl` clause has no reader in code (prose only).

## Spec-review tier

Standard: behavior-bearing harness change, no access, money, tenancy or personal data; local files only.
