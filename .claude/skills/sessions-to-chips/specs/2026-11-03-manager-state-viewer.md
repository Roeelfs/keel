# Manager state viewer, v2

Founder direction 2026-11-03: the page carries the knowledge of the WORK, not the mechanics of the
session. It covers the codebase, production, bakes and tests, design changes, and whatever holds the
work. Implementation is fast, so the founder's attention is the scarce resource. **Now** looks forward;
**History** keeps decisions and merged work. Page shape and the cross-program index are approved and fixed
(brief: `state-page-v2-brief.md`). This spec settles how each fact is obtained.

v1 is replaced, not extended. The ticket graph (`scripts/state_graph.py`), the v1 VIEW keys and the lane
table on the main view are deleted in the same change.

## Files

| File | Role |
| --- | --- |
| `references/state-viewer/template.html` | The ONE template for program pages and the index (`payload.kind`). Static; never per-program. |
| `scripts/render_state.py` | `--program <slug> [--out]`. Reads owners, writes the page, its sidecar and the index. |
| `scripts/state_sources.py` | New. The derived readers below (gh, deploys, red main, overlap, skills rules). Pure functions plus one runner. |
| `scripts/state_arch.py` | New. Validates `<slug>.arch.json`, runs Archify only when its hash changes, archives versions. |
| `scripts/test_render_state.py` | Hermetic tests with recorded `gh` fixtures; real-Archify tests skip when absent. |

Outputs, all in `~/.claude/orchestrator/programs/`: `<slug>.state.html` (page), `<slug>.state.json`
(sidecar: the payload minus diagrams, read by the index and by other programs' overlap check),
`<slug>.arch.html` (diagram, sibling file), `index.state.html`. All are derived and deletable, except
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
| Deployed per surface | the surface's deploy record vs the merge SHA | Derived |
| Red main and its owner | the repo's `red_main_cmd`, else its main-health workflow | Derived |
| File overlap with other programs | other programs' sidecars | Derived |
| Skills worth running | the rules table over the facts above | Derived |
| Since you last looked | payload timestamps vs `localStorage` last-seen | Derived, client side |
| Destination, outcomes, exposure (dark/live), proof owed, design changes, workstream findings, decisions, dead ends, incidents | `## VIEW` in `<slug>.state.md` | Authored |
| The system being changed, before and after | `<slug>.arch.json` | Authored |
| Earlier diagram versions | `<slug>.arch/<sha12>.json`, append-only | Archived by `state_arch.py` |

Dark vs live is authored, because no repo exposes flag state through one read-only command today. A
deployed change with no `exposure` row shows **exposure unstated** in amber, never "live". When a repo
gains a `flag_cmd`, that field moves to Derived and the VIEW key for it is deleted.

## Manifest: `repos`

A new top-level manifest key. It is the only place a repo, a surface or a red-main mechanism is named, so
no global rule or script hardcodes one. `work_state_store.validate_repos` owns it, strict like
`validate_binding`.

```json
"repos": [{ "repo": "Cynap-ai/cynap-monorepo-next", "path": "~/code/cynap-monorepo-next",
  "ticket_pattern": "CYN-\\d+", "main": "main",
  "surfaces": [
    { "name": "backend",   "kind": "deployment", "environment": "prod" },
    { "name": "portal",    "kind": "deployment", "environment": "Production", "paths": ["apps/portal/**"] },
    { "name": "customers", "kind": "job", "workflow": "deploy-backend.yml", "job": "deploy-customers",
      "paths": ["apps/customers/**"] } ],
  "red_main_cmd": ["node", "tooling/sandbox/main-health-relay.mjs", "--status", "--json"],
  "main_health_workflow": "main-health.yml",
  "security_paths": ["**/auth/**", "**/security/**"] }]
```

Values above are checked against the cynap repo on 2026-11-03: `deploy-backend.yml:274` deploys to GitHub
environment `prod`; Vercel records portal deploys as environment `Production` (creator `vercel[bot]`);
customers ships as the `deploy-customers` job of Deploy Backend (`deploy-backend.yml:895`), with no
deployment record of its own. A program with no `repos` key gets one Problems row carrying a stub to paste.
`surfaces: []` means "no deploy step": the ladder ends at merged, and merged reads as final.

## Derived reads

**PRs by ticket.** Tickets = snapshot items ∪ binding tickets. Per repo, batch 6 tickets per query
(GitHub's search caps a query at 5 `OR`s):
`gh pr list --repo R --state all --search "T1 OR … OR T6" --limit 100 --json number,title,headRefName,state,isDraft,mergedAt,mergeCommit,additions,deletions,updatedAt`.
Keep a row only when `\bT\b` matches its title or head branch. Measured: the bare search for five cayp
tickets returned 30 PRs, including #3155 and #3256, which matched on PR number alone. Files: one
`gh pr list --repo R --state open --limit 100 --json number,files,additions,deletions` per repo (measured
2.8 s, 23 PRs, 64.7 KB), and `gh pr view N --json files` once per merged PR, cached forever because a
merged PR never changes. A binding `publication: {sha}` (direct-push repos) stands in for a PR.

**Deployed per surface.** `deployment` kind: `gh api "repos/R/deployments?environment=E&per_page=10"`,
then `gh api repos/R/deployments/<id>/statuses --jq '.[0].state'` down the list until the first `success`.
A newer `in_progress` deployment is shown as **deploying** with its log URL. `job` kind:
`gh run list --repo R --workflow W --branch <main> --status success --limit 5 --json databaseId,headSha`,
then `gh run view <id> --repo R --json jobs` and keep a run whose job `J` concluded `success`. Deployed iff
the merge SHA is an ancestor of the deployed SHA: `git -C <path> merge-base --is-ancestor M D`, falling back
to `gh api repos/R/compare/M...D --jq .status` ∈ {`identical`,`ahead`} when the clone lacks either object.
A surface with `paths` that the PR's files miss shows **n/a**. Never read a green workflow run as a deploy
for a `deployment` surface: Deploy Backend's freshness step can pass while deploying nothing. Measured:
#5073 (CYN-3256) merged 15:58:43Z as `1db4db04f`; `prod` deployment 7525062765 for that SHA was
`in_progress` (run 41669391867), so the row reads "deploying", which matches the brief.

**Red main.** `red_main_cmd` must print `{state, sha, owners: [{id,title,runtime}], claim}`. The cynap
repo holds this data (`<git-common-dir>/cynap/main-health-state.json` `lastRed.owners`, `main-red-claim.json`,
formatted by `tooling/sandbox/lib/main-owner.mjs`), but `main-health-relay.mjs` has no read-only status
mode today (its verbs are `--refresh`, `--claim`, `--release`, `--nudge`). Owed in that repo: a
`--status --json` verb that reuses `main-owner.mjs`. Until then the page falls back to
`gh run list --repo R --workflow <main_health_workflow> --branch <main> --limit 1 --json conclusion,headSha`
and shows "red, owner unknown" with the fix. No command and no workflow: a Problems row.

**File overlap.** Intersect this program's open-PR files and binding `paths` with every other live
program's sidecar `open_prs[].files`. Exact paths; no extra gh call. Shown under Held by and on the index.

## Cost and failure

Renders run at every wake across ~10 managers. v1 measured 8.8 s (cayp-cutover) and 5.3 s (apps).

- **Shared repo tier.** Repo-level reads (open-PR files, deploys, red main) are cached once per repo in
  `~/.claude/state/work-state/repo-<owner>__<name>.json` with TTL 120 s, using the existing atomic-rename and
  non-blocking-flock rules of `work_state_sources.write_cache`. Ten managers on one repo pay once per TTL.
  Ticket searches stay in the program's own cache, also TTL 120 s. Merged-PR files never expire.
- **Rate.** A cold render costs, per repo, 1 open list, ⌈T/6⌉ searches, 2–3 calls per surface, and one
  call per newly merged PR. That is about 12 calls; warm renders cost 0. At 10 managers × 12 renders/h the
  ceiling is ~1,400 calls/h against 5,000 core plus 5,000 GraphQL (measured 4,578 core left mid-day). On a
  403 or 429, keep the stale tier, show its age, and do not retry within the render.
- **Timeouts.** 20 s per subprocess, 45 s for the whole render. A timed-out source keeps its last tier and
  shows "as of <age>". The snapshot keeps its own 90 s limit.
- **Size budget.** Page ≤ 200 KB, sidecar ≤ 64 KB, enforced by a test that renders cayp-cutover and apps.
  v1 pages measured 813–871 KB, almost all of it the embedded graph. Diagrams are never inlined.
  `archify compare architecture` measured 2,124,003 bytes in 3.9 s, and a single `render` of the same
  example 758,005 bytes, so diagrams live in the sibling `<slug>.arch.html`, shown in an `<iframe src>` with
  an "open" link. They are rebuilt only when the sha256 of `<slug>.arch.json` changes.
- **A missing source never reads as nothing.** Every zone whose source failed shows the exact reason and
  the fix in place (for example, "no `repos` in the manifest: paste this stub"), and the Problems count stays
  visible on Now. `render_state.py` exits 0 when the page was written, and 1 only for an unknown program or a
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
  "design":     [{ "what": "...", "kind": "spec", "ref": "#5085", "tier": "critical", "review": "<path>", "stop": "..." }],
  "workstreams":[{ "outcome": "...", "building": "...", "found": "...", "artifact": "...", "carrier": "<id>" }],
  "decisions":  [{ "date": "...", "decision": "...", "why": "...", "by": "founder", "supersedes": "..." }],
  "dead_ends":  [{ "date": "...", "what": "...", "why": "..." }],
  "incidents":  [{ "date": "...", "what": "...", "cause": "...", "fix": "...", "rca": "<path>" }],
  "skills_done":[{ "skill": "/spec-review", "ref": "#5085", "date": "..." }] }
```

`outcomes` is in dependency order; an outcome whose tickets are all closed moves to History on its own.
`kind` ∈ `spec|adr|module`; `tier` ∈ `critical|standard|light|none`; `exposure.state` ∈ `dark|live|n/a`.
`needs_you` holds asks not yet in a grill file; once a grill file carries one, the manager deletes it here.
Stop-guard safety is unchanged: a JSON line never starts with `Status:` or `Wake:`, pinned by the
real-guard test.

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
view renders via `deliver <type>`. `--repo-root` and `meta.repository` are never set, and neither is
`ARCHIFY_BRAND_ALLOW_PRIVATE`. When the program's change is live, the manager promotes `head` to `base`.
On every hash change, `state_arch.py` copies the file to `<slug>.arch/<sha12>.json` with its first-seen
time; History lists those versions and renders one on demand. Absent file: the zone says "No system
diagram yet" plus the authoring pointer.

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

The narrative is **stale** when any derived event is newer than VIEW `updated_at`: a merge, a deploy, a
new blocker, a new grill question, or a ticket in `outcomes` that closed. The page shows one banner:
"Narrative stale: 2 merges and 1 deploy since 15:00Z". Each render prints one compact JSON line on stdout,
which the manager reads at wake instead of opening the page:
`{"out":…, "problems":2, "stale":true, "author":["exposure: #5073 deployed, no row", "outcomes: CYN-3256 closed"]}`.
`author` names the exact keys to edit, at most 5 items. The manager edits only those keys, so keeping the
page current costs one small Edit, not a re-read of the program.

## Since you last looked

The template stores `last_seen` per program in `localStorage` (inside try/catch; with no storage the strip
reads "first visit"). Rows with timestamps after it get a marker: merges (`mergedAt`), deploys (deployment
`created_at`), blockers and design rows (first-seen time, kept in the program cache; a lost cache marks
them new once), and decisions (`date`). Clicking "mark seen", or 10 s of visible focus, advances `last_seen`.

## The index page

`index.state.html` is built from every sidecar in the programs directory. No network, so it costs
milliseconds. Every program render rebuilds it, which keeps it current with no extra job. A program is live
when its manifest has no `absorbed_by`, its `status` is not `done` or `closed`, and its sidecar is younger
than 24 h; older sidecars appear in a collapsed "not rendered in 24 h" list. One row per live program:
next landing (first open outcome), needs-you count, top held-by, prod-truth counts per ladder step, the
problems count and the render age. Below the rows: cross-program blockers, meaning file overlap pairs and
held-by rows that name another program's ticket or PR.

## Migration

- Delete `scripts/state_graph.py`, its tests, `graph_section`, and the v1 VIEW keys (`explanation`,
  `next_steps`, `upcoming`, `proven`, `unproven`). A v1 key reads as a Problems row naming its v2 home:
  `explanation` → `destination`, `next_steps` and `upcoming` → `outcomes`, `proven` → derived Production
  truth, `unproven` → `proof_owed`. There is nothing to convert: cayp-cutover and apps hold 0 VIEW blocks
  (`grep -c '^## VIEW'`, 2026-11-03).
- The lane table and wake, armed and carrier facts move to the collapsed machinery footer. The events
  timeline moves to History.
- Re-render the 10 existing pages once: apps, cayp-cutover, cayp-data-invoice, cynap-manager-2026-10,
  harness, marketing, paddle-cayp-legal, repo-hygiene, security-hardening, synthetic-customers. Each
  program without `repos` shows its stub in Problems; its manager adds the key on its next wake.
- Update `references/manager-contract.md` (state viewer paragraph) and `SKILL.md` to the v2 keys, the
  `author` line and `<slug>.arch.json`.

## For the founder

1. **Which pages auto-open in Chrome?** Recommended: only `index.state.html` keeps a live tab (opened
   unfocused once, reloaded on every render). Program tabs are reloaded when already open and never newly
   opened, so ten managers do not produce ten tabs. The alternative is v1's behaviour: each manager keeps
   its own tab.

## Done means

- Template, renderer, `state_sources.py`, `state_arch.py`, tests and the contract paragraph are committed;
  `state_graph.py` is gone.
- `cayp-cutover.state.html` and `apps.state.html` are rendered from real data, each ≤ 200 KB, with a real
  `<slug>.arch.json` showing a before/after diagram on cayp-cutover, and `index.state.html` lists both.
- Both pages and the index load with no console errors in dark and light themes.
- Driven in Chrome through `chrome.sh`, on each page: the History tab opens and its search filters; the
  machinery footer expands; after a re-render with a new merge row, the since-you-last-looked strip counts
  it and marks it; "mark seen" clears it; and the diagram iframe displays from `file://`.
