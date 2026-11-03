# Manager state viewer

Founder brief 2026-11-03: open one HTML page in Chrome and see a program's full state without
reading a transcript. Same template for every manager; the manager keeps it current.

## What is built

| File | Role |
| --- | --- |
| `references/state-viewer/template.html` | The ONE template. Static HTML, CSS and JS with one payload placeholder. Never regenerated, never per-program. |
| `scripts/render_state.py` | `render_state.py --program <slug> [--out <path>]`. Reads the owners, injects one JSON payload, writes atomically. |
| `scripts/state_graph.py` | Builds the Archify workflow spec from the snapshot and manifest, runs `deliver` in a temp dir, returns the HTML. |
| `scripts/test_render_state.py` | Hermetic unit tests, plus real-guard and real-Archify tests that skip when those are absent. |

Output: `~/.claude/orchestrator/programs/<slug>.state.html`. It is a derived artifact: deleting it
loses nothing. Nothing reads it back. The renderer keeps no state and no cache of its own.

## One owner per fact

| Page section | Owner | How it is read |
| --- | --- | --- |
| Goal, map link, gates, bindings (lane table) | `<slug>.json` | `json.load`; the store's validator owns its schema |
| Status, wake, armed, next action, owner, prerequisite, stop, holds | last `## AT-WAKE` in `<slug>.state.md` | `at_wake_tail` + `state_facts` imported from the guard, never copied. The remaining `Key:` lines are read from that same tail |
| Done-when, remaining | `## Completion checkpoint` in `<slug>.state.md` | last block |
| Map progress, frontier, what is left, flags, carrier liveness | `work_state.py snapshot --json` | subprocess; exit 0 and 4 both carry a snapshot; exit 1 carries `{error, detail}` |
| Timeline | `<slug>.events.jsonl` | last 40 rows; a bad line is counted and shown, never dropped silently |
| Open and answered founder decisions | `~/.claude/orchestrator/grills/<slug>-*.md` | numbered questions, `Answers:` section |
| Explanation, next steps, what happens next, asks not yet in a grill file, decisions made, proven, unproven | `## VIEW` in `<slug>.state.md` | new, see below |
| Work graph | derived from snapshot + bindings by `state_graph.py` | Archify `deliver`, embedded as an `iframe srcdoc` |

## The `## VIEW` block

One fenced JSON block under `## VIEW` in `<slug>.state.md`. The manager edits it in place each turn;
if two exist the last wins. Closed key set, all optional:

```json
{ "updated_at": "2026-11-03T15:00:00Z",
  "explanation": "What this program is doing and why, in plain language.",
  "next_steps": [ { "step": "...", "owner": "..." } ],
  "upcoming": [ { "when": "...", "what": "..." } ],
  "needs_you": [ { "ask": "...", "recommended": "..." } ],
  "decisions": [ { "date": "2026-11-03", "decision": "...", "why": "...", "by": "founder" } ],
  "proven": [ { "claim": "...", "evidence": "the object that proved it" } ],
  "unproven": [ { "claim": "...", "owed": "what would prove it" } ] }
```

`needs_you` holds founder asks queued for the next grill round. Once a grill file carries the question,
the manager removes it here, so the file stays its one owner. Without it, "Needs you" would read
"nothing" while the founder owes an answer that only AT-WAKE prose records. With no VIEW block at all,
the zone says "None recorded", never "Nothing".

An unknown key, a wrong type or unparsable JSON appears in the page's Problems panel with the exact
reason. Nothing is silently dropped.

**Stop-guard safety.** The guard treats everything from the last `## AT-WAKE` to EOF as its tail and
matches `Status:` and `Wake:` at line start. A JSON line starts with a quote or a bracket, so a VIEW
block anywhere in the file cannot change a guard fact. A test pins this against the real guard.

## Failure behaviour

The page always renders, and every missing source says so on the page with the fix:

- Snapshot refused or unavailable: the engine's exact `detail`, the map section shows no invented
  counts, the graph is absent.
- Archify missing or refusing the spec: the exact reason, and the map list still carries the data.
- Guard missing: AT-WAKE fields are blank and a problem row names the path.

`render_state.py` exits 0 when the page was written, whatever the page reports, and 1 only for an
unknown program or a failed write.

## Rendering rules

- The payload is JSON with `<`, U+2028 and U+2029 escaped, so no data can close the script tag.
- The template writes data with `textContent` only. No `innerHTML` of data.
- No network from the page: no fonts, CDNs or fetches. It works from `file://`.
- The page ticks the wake countdown and the render age locally, and reloads once a minute while
  visible so a new render appears on its own. A toggle pauses this. A stale render is flagged.
- Archify `deliver` may run its own bounded update check. That is the only network the render path
  adds, beside the engine's own tracker and gh tiers.
- `meta.repository` is never set on the graph, and `ARCHIFY_BRAND_ALLOW_PRIVATE` is never set.
- Graph scope: one row per open ticket that has a carrier, a publication or a bake, at most 12,
  running first. Open tickets with none of those, and closed tickets, become one count row per state,
  because an empty swimlane says nothing. The full list is under What is left.

Calling Archify is a soft dependency on another skill. The brief asks for it, and the page works
without it.

## Out of scope

Editing `~/.claude/CLAUDE.md` or `settings.json`. Migrating any manifest. Restoring the guard's
`--state-facts` flag. Any write to a source file by the renderer.

## Done means

Template, renderer, tests and the contract paragraph are committed. `harness.state.html` is rendered
from real data and loads with no console errors in a headless browser, in both themes.
