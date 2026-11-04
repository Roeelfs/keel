# Manager state viewer, v2

Founder direction 2026-11-03: the page carries the knowledge of the WORK, not the mechanics of the
session. It covers the codebase, production, bakes and tests, design changes, and whatever holds the
work. Implementation is fast, so the founder's attention is the scarce resource. **Now** looks forward;
**History** keeps decisions and merged work. Page shape and the cross-program index are approved and fixed
(brief: `state-page-v2-brief.md`). This spec settles how each fact is obtained.

Founder direction 2026-11-04, on the ticket-and-lane graph: the page must make the content and actual output
of the work understandable by reading it, not the lanes or sessions; it names the program as its manager
session is named; and it is per-track state management, updated continuously and used as the context for the
next wake and session, so the work always proceeds with the map in mind. See "Reads as the work" and "The
context brief".

v1 is replaced, not extended. The ticket graph (`scripts/state_graph.py`), the v1 VIEW keys and the lane
table on the main view are deleted in the same change.

## Files

| File | Role |
| --- | --- |
| `references/state-viewer/template.html` | The ONE template for program pages and the index (`payload.kind`). Static; never per-program. |
| `scripts/render_state.py` | `--program <slug> [--out] [--context]`. Reads owners, writes the page, its sidecar and the index; `--context` prints the brief instead and writes nothing. |
| `scripts/state_story.py` | The work as outcomes: joins each VIEW `done` line to the derived ladder of its PRs, marks claims, lists merged work not yet summarized. Pure. |
| `scripts/state_brief.py` | The context brief: the same payload as bounded plain text. Pure. |
| `scripts/test_state_story.py` | Names, the story join, claims, not-yet-summarized, the brief and its bound. |
| `scripts/state_sources.py` | New. The derived readers below (gh, deploys, red main, overlap, skills rules). Pure functions plus one runner. |
| `scripts/state_arch.py` | New. Validates `<slug>.arch.json`, runs Archify only when its hash changes, archives versions. |
| `scripts/work_state_store.py` | Gains `validate_repos`, called by the renderer only, never inside `_Locked.write`. |
| `scripts/test_render_state.py` | Hermetic tests with recorded `gh` fixtures; real-Archify tests skip when absent. The graph import, `GraphSpec`, `RealArchify`, degraded-graph cases and v1 VIEW fixtures go; the no-network template test allows only a relative sibling `<iframe src>`. |

Outputs, all in `~/.claude/orchestrator/programs/`: `<slug>.state.html` (page), `<slug>.state.json`
(sidecar: the payload minus diagrams, read by the index and by other programs' overlap check),
`<slug>.arch/<sha12>/<view-id>.html` (diagrams), `index.state.html`. All are derived and deletable, except
`<slug>.arch/`, which is the one owner of "architecture over time" (see below).

## One owner per fact

The manager authors only judgment. Everything else is derived on every render, so it cannot drift.

| Fact | Owner | Kind |
| --- | --- | --- |
| Goal, gates, bindings, map, **repos and surfaces** | `<slug>.json` | Manifest |
| Tickets, state, blockers, bake verdicts, carriers and their liveness | `work_state.py snapshot --json` | Derived |
| Status, wake, armed, holds | last `## AT-WAKE`, read through the guard's `state_facts` / `at_wake_tail` | Derived |
| Open and answered founder questions | `~/.claude/orchestrator/grills/<slug>-*.md` | Derived |
| PRs per ticket, merge SHA, files, diff size | `gh`, matched by ticket id | Derived |
| Deployed per surface | the surface's proof step vs the merge SHA | Derived |
| Red main and its owner | the repo's `red_main_cmd`; without one, "unavailable" | Derived |
| Publications in History | `binding-retired` events in `<slug>.events.jsonl` | Derived |
| File overlap with other programs | other programs' sidecars | Derived |
| Skills worth running | the rules table over the facts above | Derived |
| Since you last looked | payload timestamps vs `localStorage` last-seen | Derived, client side |
| The program's name | its newest `[Manager]` session title, resolved by exact session id through `program_family.program_titles`; else manifest `title`, else the slug plus one Problems row | Derived |
| Destination, outcomes, what was done, architecture and design changes, decisions, findings, exposure (dark/live), proof owed, dead ends, incidents | `## VIEW` in `<slug>.state.md` | Authored |
| Which merged PRs are not yet summarized, and which `done` lines claim more than their proof | `state_story.py` over VIEW and the PR ladder | Derived |
| The system being changed, before and after | `<slug>.arch.json` | Authored |
| Earlier diagram versions | `<slug>.arch/<sha12>.json`, append-only | Archived by `state_arch.py` |

Dark vs live is authored, because no repo exposes flag state through one read-only command today. A
deployed change with no `exposure` row shows **exposure unstated** in amber, never "live". When a repo
gains a `flag_cmd`, that field moves to Derived and the VIEW key for it is deleted.

## Manifest: `repos`

A new top-level manifest key. It is the only place a repo, a surface or a red-main mechanism is named, so
no global rule or script hardcodes one. `work_state_store.validate_repos` owns it, strict like
`validate_binding`. The renderer catches its error per repo as a Problems row and still writes the page, so
a bad hand edit never blocks `bind` or `retire`.

```json
"repos": [{ "repo": "Cynap-ai/cynap-monorepo-next", "path": "~/code/cynap-monorepo-next",
  "ticket_pattern": "CYN-\\d+", "main": "main",
  "surfaces": [
    { "name": "backend",   "kind": "deployment", "environment": "prod", "proof_step": "Deploy stack",
      "paths": ["…the backend filter of tooling/workflow/deploy-backend-paths.yml…"] },
    { "name": "portal",    "kind": "deployment", "environment": "Production", "paths": ["apps/portal/**"] },
    { "name": "customers", "kind": "job", "workflow": "deploy-backend.yml", "job": "deploy-customers / sync",
      "proof_step": "Sync non-org content to S3 (templates, catalog)", "paths": ["apps/customers/**"],
      "unproven": "org changes go live by activation, which has no read source" } ],
  "red_main_cmd": null,
  "security_paths": ["**/auth/**", "**/security/**"] }]
```

Checked against the cynap repo on 2026-11-03: the `prod` job (`deploy-backend.yml:274`) records a `success`
deployment even when its freshness step skips every deploy step; the real deploy is `Deploy stack`
(`:494`). A Vercel `Production` record is the deploy itself, so portal needs no `proof_step`. Customers is
the `sync` job of `deploy-customers.yml`, called from `deploy-backend.yml:895`; its `unproven` text shows
beside its row. No `repos` key: one plain Problems row; the paste-ready stub goes to stdout, never the page.
`surfaces: []` means "no deploy step": the ladder ends at merged, and merged reads as final.

## Derived reads

**PRs by ticket.** Tickets = snapshot items ∪ binding tickets. Per repo, batch 6 tickets per query
(GitHub's search caps a query at 5 `OR`s):
`gh pr list --repo R --state all --search "T1 OR … OR T6" --limit 100 --json number,title,headRefName,state,isDraft,mergedAt,mergeCommit,additions,deletions,updatedAt`.
Keep a row only when `\bT\b` matches its title or head branch, and always keep a binding's own
`publication.pr`. A batch that returns 100 rows is split and re-run, never read as complete. A PR under two
tickets counts once; a ticket's step is its least-advanced PR's. Measured: a bare search for five cayp
tickets returned 30 PRs, some matching on PR number alone. Files: one
`gh pr list --repo R --state open --limit 100 --json number,files,additions,deletions` per repo (measured
2.8 s, 23 PRs, 64.7 KB), and `gh pr view N --json files` once per merged PR, cached forever because a
merged PR never changes. A binding `publication: {sha}` (direct-push repos) stands in for a PR.

**Deployed per surface.** A surface counts as deployed at SHA D only when its proof step ran and
concluded `success` at D; a green record or a green job whose proof step skipped is walked past.
`deployment` kind: `gh api "repos/R/deployments?environment=E&per_page=10"`, then
`gh api repos/R/deployments/<id>/statuses --jq '.[0]'` down the list; for a `success` with a `proof_step`,
read its `log_url` run's jobs (`gh run view <id> --repo R --json jobs`) and require that step's
`conclusion: success`. `job` kind: `gh run list --repo R --workflow W --limit 20 --json
databaseId,headSha,headBranch,conclusion`, filtered locally to main and success (a filtered search has
returned stale pages before), then the same step check on job `J`. Deployed iff M is an ancestor of D:
`git -C <path> merge-base --is-ancestor M D` (exit 1 = not deployed; exit 128 = fall back to
`gh api repos/R/compare/M...D --jq .status` ∈ {`identical`,`ahead`}). A newer `in_progress` deployment
reads **deploying** only when M is an ancestor of its SHA; a newest `failure` reads **deploy failed** with
its log URL. A list exhausted with no proven deploy reads **not established**, with "check this surface's
config" as the fix, never "not deployed". **n/a** needs the PR's complete, non-empty file list missing every
`paths` glob; unread files read **cannot tell**. Measured: `prod` deployments 7522907025 and 7522940338
were `success` with 25 of 30 steps skipped; the proof-step rule walks past both.

**Red main.** `red_main_cmd` runs with cwd = the repo's `path` and prints
`{schema: 1, state: green|red|outage|pending, sha, owners: [{id,title,runtime}], claim}`. The cynap data
exists (`main-health-state.json`: top-level `owners` is the current episode, `lastRed` the previous), but no
read-only verb exposes it; an unknown relay verb exits 0 with empty output. CYN-3398 (#5083, open) owes it.
Until then `red_main_cmd` is `null` and the page shows **main health unavailable**, naming that ticket;
empty or non-contract stdout reads the same, plus a Problems row. The main-health workflow's conclusion is
never read: it succeeds after posting red. Red with `owners: []` reads "red, no owner".

**File overlap.** Repo plus normalized path; this program's open-PR files and binding `paths` against every
other live program's, from sidecars, with one glob matcher (`**` crosses directories), never the prefix
check `paths_intersect`. Same-PR pairs and generated files are dropped. Shown as advisory under Held by and
on the index: manifest ownership stays the authority, and missing files read "unknown", never "no holder".

## Cost and failure

Renders run at every wake across ~10 managers. v1 measured 8.8 s (cayp-cutover) and 5.3 s (apps).

- **Shared repo tier.** Repo-level reads (open-PR files, deploys, red main) are cached once per repo in
  `~/.claude/state/work-state/repo-<owner>__<name>.json` with TTL 120 s, using the existing atomic-rename and
  non-blocking-flock rules of `work_state_sources.write_cache`. Ten managers on one repo pay once per TTL.
  Ticket searches stay in the program's own cache, also TTL 120 s. Merged-PR files never expire.
- **Rate.** A cold render costs, per repo, 1 open list, ⌈T/6⌉ searches, 2–3 calls per surface, and one
  call per newly merged PR: about 12, plus the snapshot's own `load_gh`, which no viewer tier saves. At 10
  managers × 12 renders/h the ceiling is ~1,400 calls/h against 5,000 core plus 5,000 GraphQL. Cold managers
  on one repo may each fetch once (see Later). A rate-limit 403 or 429 keeps the stale tier with its age
  and no retry before the stored reset; a 401, 404 or permission 403 is a Problems row with its fix.
- **Timeouts.** 20 s per subprocess, 45 s for the whole render, and the snapshot gets the remaining
  deadline. A timed-out source reads its cached tier through the no-network `mode="guard"` path, labelled
  "as of <age>". Each tier is written to cache as it completes, so a killed render still advances it. Page
  and sidecar are written by the deadline; Archify and the Chrome reload run after the write.
- **Size budget.** Page ≤ 200 KB, sidecar ≤ 64 KB. The sidecar is a projection (open PRs and their files,
  counts, source health), never the page payload; past the page budget the renderer drops the oldest
  History rows and says how many. A test renders cayp-cutover and apps against both budgets. Diagrams are
  never inlined (`archify compare architecture` measured 2,124,003 bytes): they are sibling files, shown in
  an `<iframe src>` with an "open" link.
- **A missing source never reads as nothing.** Every zone whose source failed shows the reason and the fix
  in plain words, and the Problems count stays visible on Now. The sidecar carries each source's health, so
  the index shows "unknown", never zero, for a failed source. `render_state.py` exits 0 when the page was written, and 1 only for an unknown program or a
  failed write.

## `## VIEW`, schema `state-view/2`

One fenced JSON block under `## VIEW` in `<slug>.state.md`, edited in place, last block wins. The key set
is closed; every key is optional; an unknown key, a wrong type or bad JSON goes to Problems with the reason.

```json
{ "updated_at": "2026-11-03T16:00:00Z",
  "destination": "CAYP runs on Access v2 with its first workspace head, baked.",
  "outcomes":   [{ "outcome": "CAYP has its first workspace head", "tickets": ["CYN-3155"] }],
  "needs_you":  [{ "ask": "...", "recommended": "...", "grill": "<grill file or chip>" }],
  "exposure":   [{ "ref": "#5073", "state": "dark", "evidence": "flag X off in prod" }],
  "proof_owed": [{ "claim": "...", "proof": "...", "org": "...", "runner": "...", "verdict": "owed" }],
  "done":       [{ "date": "...", "what": "Owners can hand ownership to another member through one guarded transfer; it ships dark.", "why": "...", "refs": ["#5073"] }],
  "architecture":[{ "date": "...", "what": "Owner changes go through one guarded transfer; a direct Owner-row edit is refused.", "refs": ["#5024", "#5073"] }],
  "design":     [{ "what": "...", "meaning": "one line: what it means", "kind": "spec", "ref": "#5085", "tier": "critical", "review": "<path>", "stop": "...", "date": "..." }],
  "decisions":  [{ "date": "...", "decision": "...", "why": "...", "by": "founder", "supersedes": "..." }],
  "findings":   [{ "date": "...", "outcome": "...", "found": "...", "refs": ["#5095"] }],
  "dead_ends":  [{ "date": "...", "what": "...", "why": "..." }],
  "incidents":  [{ "date": "...", "what": "...", "cause": "...", "fix": "...", "rca": "<path>" }],
  "skills_done":[{ "skill": "/spec-review", "ref": "#5085", "date": "..." }],
  "adopted":    [{ "refs": ["#4983", "#4991"], "note": "delivered by the invoice program, adopted with its tickets" }] }
```

`outcomes` is in dependency order. An outcome moves to History only when its tickets are all closed and no
bake is open, showing how each ended (done, canceled, duplicate); empty or unknown `tickets` is a Problems
row and stays on Now. A `proof_owed` row names its ticket; the derived bake verdict wins, a conflict is a
Problems row, and a pass reads "ticket records pass", never "proven", since no bake artifact is read.
`date` and `updated_at` are RFC3339; a date-only or future value is a Problems row. `kind` ∈
`spec|adr|module`; `tier` ∈ `critical|standard|light|none`; `exposure.state` ∈ `dark|live|n/a`; `verdict` ∈
`owed|pass|fail`. `refs` and `tickets` are lists of ids (`"#5073"`, `"CYN-3256"`). `workstreams` is retired
(2026-11-04): it read as session tracking; its findings go to `findings`, its output to `done`, and an old
block shows under "not migrated" until converted.
`adopted` names merged PRs that came with tickets this program took over from another program: their delivery
is the other program's, so the manager writes no `done` line for them. A listed PR leaves "not yet summarized"
and the `author` line, never counts in "What was done", and shows on History as one grouped line, the `note`
followed by its refs. A row needs both `note` and a non-empty `refs`.
`needs_you` holds asks not yet in a grill file; once a grill file carries one, the manager deletes it here.
Stop-guard safety is unchanged: a JSON line never starts with `Status:` or `Wake:`, pinned by the
real-guard test.

## Reads as the work

A reader who never saw a session understands the track from the page alone. The bar names the program as its
manager session is titled, with "[Manager] " and a "(fork)" suffix stripped ("Cynap", "Apps", "CAYP cutover
(Access v2)"), with the map id beside it as a link; the slug never appears as a name. Now and History answer
in this order, each in plain language:

1. **What this track is achieving**: the destination, with the manifest goal under it.
2. **What was done**: VIEW `done`, newest first, one line per delivered outcome with its PR refs after the
   sentence and the furthest ladder step those PRs provably reached. Now shows the last 7 days (at most 6;
   the newest 3 when none is that recent), History all. A merged PR or retired direct push that no `done`,
   `architecture`, `design` or `adopted` line names is listed by its title, marked "not yet summarized", and
   named in the `author` line. History closes the section with each `adopted` group as one line.
3. **What changed in the architecture**: one sentence per VIEW `architecture` row, then the before/after
   diagram. Without `<slug>.arch.json`, one line asks for it; no empty panel.
4. **What changed in the design**: VIEW `design`, each `kind: what` with its `meaning` line.
5. **Decisions**: what, why, by whom, what they replaced; grill answers join them.
6. **What was learned**: VIEW `findings`.
7. Then **what is next** (outcomes on the map), **needs you**, **held by**, **proof owed**, production truth,
   problems.

Sessions, lanes, carriers and wakes never appear as a heading or the subject of a sentence above the
collapsed machinery footer. Workers waiting on the manager, flags on a worker id rather than a ticket, the
lane table and the raw event timeline live in the footers. A row that says only that a session is running
is never shown.

**Claims.** A `done` line whose words assert a ladder step (live, in production, rolled out → live;
deployed, reached prod → deployed; baked, proven → baked) beyond what its PRs provably reached shows as
"Manager's claim: proof reaches <step>". The derived proof wins. An `exposure` of `n/a` has nothing to be
live, so it reads as deployed. The rule matches words, so it errs toward flagging; the fix is plainer
wording, never a weaker rule.

## The context brief

`render_state.py --program <slug> --context` prints the payload as plain text, at most 60 lines, writing
nothing: the name and map, when the narrative was last updated and whether it is stale, the destination,
what was done recently (claims and not-yet-summarized marked), architecture and design changes, decisions in
force, what was learned, next outcomes with ticket states, what needs the founder, what holds the work, the
proof owed, production counts, the problem count, and last the keys to update and the re-render command.
The footer always survives the bound; every cut list says how many it left out. It has no second source:
one payload, two renderings. The manager reads it at every wake and session start in place of re-deriving
the program, works the map from it, updates VIEW before ending the turn and re-renders. The Stop guard's
AT-WAKE facts are unchanged.

## `<slug>.arch.json`, schema `state-arch/1`

```json
{ "updated_at": "...",
  "views": [{ "id": "system", "title": "Access v2 ownership transfer", "type": "architecture",
              "base": { "...Archify architecture IR before the program..." },
              "head": { "...the IR after it..." }, "note": "what changes and why" },
            { "id": "transfer", "type": "sequence", "head": { "...IR..." } }] }
```

It draws the product, never tickets or sessions. An `architecture` view with `base` renders via
`archify compare architecture base.json head.json <out> --receipt <r> --json`; its receipt's
`.summary.components` (`added`, `changed`, `removed`) becomes the "3 new, 1 changed" line on Now. Any other
view renders via `deliver <type>`. `--repo-root` is never set; `state_arch.py` strips
`ARCHIFY_BRAND_ALLOW_PRIVATE` from Archify's environment and rejects any input carrying `meta.repository`.
When the change is live, the manager promotes `head` to `base`. A valid file whose hash changed is copied
to `<slug>.arch/<sha12>.json` and each view rendered to `<slug>.arch/<sha12>/<view-id>.html`, listed in
`<slug>.arch/index.json`; History loads older ones lazily. A build reruns when the hash changed, an output
is missing or the last build failed, and records the hash only on success. Absent file: "No system diagram
yet" plus the authoring pointer.

## Skills worth running

A rule fires at most once per `ref`, and a matching `skills_done` row silences it.

| Skill | Trigger | Reads |
| --- | --- | --- |
| `/improve-codebase-architecture` | ≥3 merged PRs whose title type is `fix` match one ticket | ticket PR rows |
| `/spec-review` | a `design` row of kind `spec` with `tier: none` or no `review` | VIEW `design` |
| `/root-cause-analysis` | two `incidents` rows share a `cause`, or any row has no `rca` | VIEW `incidents` |
| `/security-review` | an open or merged PR touches a repo's `security_paths` | PR files, manifest `repos` |
| `/standards-spec-review`, `/simplify` | one ticket's merged PRs total ≥800 changed lines, ticket closed | PR diff stats, snapshot |
| `/spec-visualization` | a `design` spec whose `ref` PR merged in the last 7 days | VIEW `design`, PR rows |

## Staleness and authoring

The narrative is **stale** when any derived event is newer than VIEW `updated_at`: a merge, a deploy that
first carries one of this program's PRs to a surface, a new blocker, a new grill question, or a ticket in
`outcomes` that closed. Each event has a stable identity (kind plus PR, surface or ticket) and a first-seen
time in the program cache; after cache loss the page says "baseline unavailable", never "new". One banner
reads "Narrative stale: 2 merges and 1 deploy since 15:00Z". Each render prints one compact JSON line on
stdout, which the manager reads at wake instead of opening the page:
`{"out":…, "problems":2, "stale":true, "author":["exposure: #5073 deployed, no row", "outcomes: CYN-3256 closed"]}`.
`author` names the exact keys to edit, at most 5, drawn only from what is unresolved on Now. The manager
edits only those keys: one small Edit, not a re-read of the program.

## Since you last looked

The template stores `last_seen` per program in `localStorage` (inside try/catch; with no storage the strip
reads "first visit"). Rows whose event is newer than it get a marker, using the event times above, and
decisions by `date`. Only "mark seen", or leaving the page, advances `last_seen`; a reload never does,
including the index's reload of a page shown inside it (see Chrome tabs).

## The index page

`index.state.html` is built from every sidecar, with no network, by every program render. A program is live
when its manifest has no `absorbed_by` and its `status` is not `done` or `closed`. A sidecar older than 24 h
keeps its row, marked with its age, if it has open asks or PRs; otherwise it goes to a collapsed "not
rendered in 24 h" list. One row per live program, named as on its page with its map id under it (a program
with no readable name keeps its slug, and one Problems row lists them):
next landing (first open outcome), needs-you count, top held-by, prod-truth counts per ladder step, the
problems count and the render age. Below the rows: cross-program blockers, meaning file overlap pairs and
held-by rows that name another program's ticket or PR.

## Migration

- Delete `scripts/state_graph.py`, its tests, `graph_section`, and the v1 VIEW keys (`explanation`,
  `next_steps`, `upcoming`, `proven`, `unproven`). A v1 key reads as a Problems row naming its v2 home:
  `explanation` → `destination`, `next_steps` and `upcoming` → `outcomes`, `proven` → derived Production
  truth, `unproven` → `proof_owed`. Until converted, its text stays visible under "not migrated", and old
  `proven` text reads as the manager's claim. harness and marketing hold one v1 block each (`grep -c
  '^## VIEW'`, 2026-11-03; harness also has `claims` and `lanes`); their managers convert them key by key
  on the next wake. Sidecars and the repo tier carry `schema`; a mismatch reads as a cold cache.
- History's publications are rebuilt from `binding-retired` events, deduplicated by repo plus PR or push
  SHA, with no newest-40 cut, so retiring a binding never erases its publication.
- The lane table and wake, armed and carrier facts move to the collapsed machinery footer. The events
  timeline moves to History.
- Re-render the 10 existing pages once: apps, cayp-cutover, cayp-data-invoice, cynap-manager-2026-10,
  harness, marketing, paddle-cayp-legal, repo-hygiene, security-hardening, synthetic-customers. A program
  without `repos` shows its Problems row; its manager adds the key next wake, or records why it cannot.
- Update `references/manager-contract.md` (state viewer paragraph) and `SKILL.md` to the v2 keys, the
  `author` line and `<slug>.arch.json`.

## Chrome tabs

Founder ruling, 2026-11-04: every state page converges into ONE Chrome tab, showing `index.state.html`,
with no local server. One tab per page flooded the founder's Chrome with about 15 tabs; the one tab lives
in their "Managers" tab group.

- **The index is the dashboard.** A left switcher lists every live program with its next landing,
  needs-you count and first held-by row. Choosing one shows its `<slug>.state.html` in an iframe, and
  the choice lives in the hash (`#program=<slug>`), so a reload keeps it. With no hash, the index shows
  its overview. Each program page still opens on its own.
- **One reload loop.** The index reloads itself every 60 s while Live is on and no one is selecting,
  typing, exploring a diagram or reading an open fold. A program page shown inside the index (`?embed=1`)
  runs no timer. It reports its scroll, tab and busy state to the index by `postMessage`, and the index
  passes them back on the next load (`y`, `tab`). The page scrolls before first paint, so it does not
  flash. Live and the theme inside the iframe drive the index's own Live and theme.
- **Since you last looked, inside the index.** The index passes `auto=1` when it was reloaded. The
  embedded page treats that as a reload, so its last-seen time stays put. Switching programs, or
  leaving and coming back, advances it.
- **`render_state.py` makes one Chrome call per render, for the index only,** and only when the index
  is directly under the real `~/.claude/orchestrator/programs`. Tests and scratch renders never reach
  Chrome, and `RENDER_STATE_NO_OPEN=1` skips the call. One AppleScript lists every tab. The decision
  (`tab_plan`) is pure and covers only tabs whose URL is a `.state.html` directly in that dir. If the
  index is among them, its tab reloads. Otherwise the first match is pointed at the index, with
  `#program=<its slug>`, which keeps the tab in its tab group. Every other match closes. With no match,
  `open -g` opens one. Nothing activates Chrome, selects a tab or touches any other tab. When Chrome is
  not running, nothing opens. The stdout `chrome` field reports what happened: `reloaded`, `repointed`,
  `opened`, `chrome closed`, `skipped` or `error`, plus how many tabs closed.

## Done means

- Template, renderer, `state_sources.py`, `state_arch.py`, tests and the contract paragraph are committed;
  `state_graph.py` is gone.
- Both pages carry real authored `done`, `architecture`, `design`, `decisions` and `findings` content and read
  as the work in the order above; `--context` prints a bounded brief for each.
- `cayp-cutover.state.html` and `apps.state.html` are rendered from real data, each ≤ 200 KB, with a real
  `<slug>.arch.json` showing a before/after diagram on cayp-cutover, and `index.state.html` lists both.
- Both pages and the index load with no console errors in dark and light themes.
- Driven in Chrome through `chrome.sh`, on each page: the History tab opens and its search filters; the
  machinery footer expands; after a re-render with a new merge row, the since-you-last-looked strip counts
  it and marks it; "mark seen" clears it; and the diagram iframe displays from `file://`.
- Recorded-fixture tests pass locally (keel has no CI): a skipped-proof-step `success` deployment, a red
  main under a green health run, a skipped customers sync, an exhausted deploy search, a retired direct push
  still in History after derived outputs are deleted, a canceled bake, and archived diagrams after cache loss.

## Later

- A per-repo refresh lease, so simultaneous cold renders fetch once, and one shared PR read with `load_gh`.
- An activation-evidence source for customer org state; until then customers reads its `unproven` text.
- A bake-evidence link in the snapshot, so a verdict can read "proven" with its artifact.
- A **reverted** ladder state, read from a revert PR naming the merge SHA.
- The review's remaining minor boundary rows (the edge-case table in the `.review.md`).
