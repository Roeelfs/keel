---
name: spec-visualization
description: Produce a single-file interactive HTML dashboard visualizing a finalized spec — architectural planes, end-to-end pipeline (React Flow), wave timeline, review evolution, decisions, components, open gates. Self-contained, opens in browser, no build step. Trigger after spec-review fixes are applied, or on demand for any approved spec.
---

# Spec Visualization

Produces a single HTML file that lets a reader grok an entire spec at a glance: the 4-plane data-boundary architecture, the commit→deploy pipeline as an interactive flow chart, wave-by-wave rollout with gating items, review evolution charts, decisions status, component inventory, open items dashboard.

## When to invoke

- **As Step 10 of `spec-review`** — after fixes are applied, before commit. Skip if spec is still Draft or no review files exist.
- **Standalone** — when the user asks to "visualize the spec", "see the spec model", "render the design", or wants a fitness check against a vision.
- **NOT for** specs under 200 lines (overkill) or specs with no waves/reviews (the dashboard sections won't have data).

## Output

`<spec-path>.viz.html` — single HTML file next to the spec. Opens in Chrome. Self-contained (CDN imports for React 18, @xyflow/react, Recharts, Tailwind, lucide-react, Babel standalone).

## Process

### Step 1: Locate inputs

- **Spec file** — the canonical .md (typically `docs/specs/active/YYYY-MM-DD-<name>.md`)
- **Review files** — any sibling `<spec-basename>.review*.md` files
- **Decisions doc** — sibling `*-decisions.md` if present
- **Related platform specs** — sibling specs referenced in the spec's frontmatter

If only the spec exists with no reviews/decisions, the dashboard renders with those sections empty — that's fine.

### Step 2: Extract data into the canonical schema

Read the spec end-to-end. Map its content onto this canonical schema (the full field reference is defined inline below):

```javascript
{
  "meta": {
    "title": "...",                          // from spec H1
    "specPath": "docs/specs/active/...",
    "version": "v0.3.1",                     // from "Status:" line
    "issueRef": "#379",                      // from "Issue:" line
    "branch": "spec/...",                    // git branch the spec lives on
    "statusBadges": [                        // array of {label, variant}
      {"label": "v0.3.1", "variant": "accent"},
      {"label": "Wave 1 ready", "variant": "success"}
    ],
    "summary": "..."                         // 1-2 sentence top-of-page summary
  },
  "planes": [                                // architectural layers, typically 3-5
    {
      "id": "workspace",
      "label": "Plane 1 · Authoring",
      "title": "Workspace",
      "store": "Git repo · per project",
      "desc": "Canonical multi-file source...",
      "items": ["manifest.json", "schema.json", "..."],
      "color": "violet",                     // violet | indigo | cyan | emerald | amber | rose
      "icon": "GitBranch"                    // lucide-react icon name
    }
  ],
  "pipelineNodes": [                         // React Flow nodes
    {
      "id": "agent",
      "position": {"x": 0, "y": 0},
      "data": {
        "label": "Agent",
        "sub": "build agent",
        "plane": "workspace",                // matches a plane id
        "icon": "Sparkles"
      }
    }
  ],
  "pipelineEdges": [                         // React Flow edges
    {
      "id": "e1",
      "source": "agent",
      "target": "validate",
      "label": "pushed",                     // optional
      "animated": true,                      // optional
      "color": "violet",                     // matches plane palette
      "dashed": false                        // optional
    }
  ],
  "reviewRounds": [                          // chronological
    {"round": "v0.1", "critical": 7, "major": 14, "minor": 9, "verdict": "block"},
    {"round": "v0.2", "critical": 10, "major": 18, "minor": 13, "verdict": "block"}
  ],
  "waves": [                                 // rollout plan, typically from §17
    {
      "id": 0,
      "title": "Spec + Model",
      "state": "done",                       // done | next | pending
      "ships": ["Spec finalized", "..."],
      "gates": [
        {"id": "NEW-NC7", "sev": "critical", "label": "I-1 amendment"},
        {"id": "NEW-M2",  "sev": "fixed",    "label": "AND→OR"}
      ]
    }
  ],
  "decisions": [                             // Wave 0 / open decisions
    {
      "id": "D1",
      "topic": "Wave 5/6 ordering",
      "flag": "NEW-NC8",
      "rec": "Merge Wave 6 INTO Wave 5...",
      "owner": "platform-architecture",
      "status": "pending",                   // pending | updated | approved
      "note": null                           // optional expanded note
    }
  ],
  "components": {                            // infra inventory grouped
    "db": {
      "label": "Database tables",
      "count": "8 + 1 queue",
      "icon": "Database",
      "items": [
        {"name": "project_repositories", "note": "one row per project · pointers + state"}
      ]
    }
  },
  "openItemsByWave": [                       // for stacked bar
    {"wave": "W0", "critical": 1, "major": 0}
  ],
  "boundaries": [                            // data-store boundaries narrative
    {
      "color": "violet",
      "label": "Git repo / object store",
      "title": "Configuration",
      "contents": "schema.json · automations · ..."
    }
  ]
}
```

**Extraction heuristics:**

- **Planes** — most specs have a "§4.1 Planes" or "Architecture" section with a table. If not, infer from the data-boundaries section. Typical specs have 3-4 planes mapping to data stores.
- **Pipeline nodes** — read the "High-Level Flow" / sequence diagram / §X.Y materializer narrative. Each step becomes a node. Aim for 8-18 nodes — fewer than 8 is too sparse, more than 18 is overwhelming.
- **Pipeline edges** — connect nodes in flow order. Color edges by source plane. Use `animated: true` for the critical happy path; static for diverging branches. Add labels for state transitions (e.g., `pushed`, `bundled`, `accepted`).

- **Pipeline layout — strict lane discipline (do this, not ad-hoc x/y).** Overlapping edges are the #1 readability failure. React Flow uses `smoothstep` (orthogonal) routing, so the layout must be planned as horizontal lanes:
  - **Stride:** `x` += **230** per pipeline stage (nodes are ~140-200px wide; 230 leaves a clean gap). `y` lanes **≥130px apart**.
  - **The spine is sacred.** The happy path lives on **one lane, `y: 0`**, strictly left-to-right. Nothing else may occupy `y: 0`, and **no edge may route through the `y: 0` band between two spine nodes** except the spine edge itself.
  - **Branches get their own lanes, never the spine.** Parallel/alternative concerns (e.g. triage axes) → a vertical **fan column** at one shared `x`, stacked at `y: -180, -50, 80, 210`. Recovery / safety / out-of-band → **lower lanes** (`y: 300+`), one lane per concern, running *parallel* to the spine then turning up into their join node — never diagonally across it.
  - **Order branch endpoints to match.** When several edges fan from one node to a column (or converge from a column into one node), order the targets vertically in the same order the edges leave/enter so lines don't cross each other.
  - **Feedback / backward edges** (loops returning to an earlier stage) go on the **lowest empty lane**, `dashed: true`, distinct color, with a label. Accept one clean long edge there; never route a backward edge through the spine or node bands.
  - **Long-distance edges hug a lane.** An edge spanning many stages must travel along an empty `y` lane (its own), not cut diagonally. If two long edges would share a lane, give one a lane 130px lower.
  - **Collapse before you lay out.** Template nodes have a *single* left (target) / right (source) handle, so every off-spine edge loops around — N parallel sub-concerns rendered as N nodes produces N looping edges and guaranteed overlap. Model parallel/alternative concerns as **one spine node** with a summarizing `sub` (e.g. "Three-axis triage · urgency · safety · statutory"); push the per-item detail into the Components section, not the flow. A flow chart shows *flow*, not every rule. Aim for a near-linear spine with ≤4 short off-spine edges + ≤2 isolated dashed lanes (one branch, one feedback).
  - Sanity check before render: every edge is either (a) a short spine hop, (b) a short confirm→{outputs,followup}-style stub, or (c) one of the ≤2 lane-hugging branch/feedback edges. Any edge that visually crosses a node = collapse nodes or relayout.
- **Review rounds** — count CRITICAL/MAJOR/MINOR per `.review*.md` file. The spec usually has a "review history" or change-log section with these counts.
- **Waves** — from §17 (or "Rollout Plan"). The "Must close before exit" subsections are the gates. Mark wave state: `done` (status indicates done), `next` (the immediately-next wave), `pending` (everything later).
- **Decisions** — from any `*-decisions.md` companion. If none, omit the section.
- **Components** — from the spec's infrastructure sections: database tables, config/credential stores, inferred compute units (functions/services) from handler refs, encryption keys from the secrets section.
- **Open items by wave** — count gating items in each wave by severity. Used for the stacked bar chart.

If the spec is too unstructured to extract any of these, drop the section from the data — the template renders gracefully with missing fields.

### Step 3: Render

Copy `template.html` from this skill directory to `<spec-path>.viz.html`. Locate the `<script id="spec-data" type="application/json">` block in the template and replace its inner text with the JSON-stringified data object from Step 2.

```bash
TEMPLATE="$HOME/.claude/skills/spec-visualization/template.html"
OUTPUT="${SPEC_PATH%.md}.viz.html"

# Read template, inject JSON data, write output. Use Python to avoid shell-escaping JSON:
python3 - "$TEMPLATE" "$OUTPUT" "$DATA_JSON_PATH" <<'PYEOF'
import sys, json, re
template = open(sys.argv[1]).read()
data = json.load(open(sys.argv[3]))
data_str = json.dumps(data, indent=2)
out = re.sub(
    r'<script id="spec-data" type="application/json">[\s\S]*?</script>',
    f'<script id="spec-data" type="application/json">{data_str}</script>',
    template, count=1
)
open(sys.argv[2], 'w').write(out)
PYEOF
```

### Step 4: Open + report

```bash
open -a "Google Chrome" "$OUTPUT"
```

Tell the user: file path, what sections rendered, any sections skipped (and why).

### Step 5: Commit (optional)

If the spec is on a branch, offer to commit the `.viz.html` next to the spec:

```bash
git add "$OUTPUT"
git commit -m "docs(<scope>): visualize spec — interactive dashboard"
```

The `.viz.html` is reproducible from the spec, so committing is optional. If the spec is volatile (Draft early), don't commit.

## Tips

- **Layout the pipeline once** — apply the strict lane discipline from the extraction heuristics (spine at `y:0`, 230 x-stride, branches/feedback on their own lower lanes). Re-renders preserve positions; record final `x`/`y` in the data. If any edge visually crosses a node after the first render, relayout — don't ship overlapping edges.
- **Wave count >8** — switch the wave timeline from horizontal to vertical lanes. Edit the template's wave-grid Tailwind class from `lg:grid-cols-8` to `lg:grid-cols-4` for two rows.
- **No review history** — drop the review evolution section entirely. The page is still informative without it.
- **Light mode** — the template is dark-only by design (operational dashboard aesthetic). Light mode adds complexity without payoff.
- **Failure paths** — color them rose. Use `dashed: true` on edges that represent recovery / out-of-band paths.

## When NOT to use

- Specs without a clear architectural model (e.g., bug fixes, refactor specs) — the planes/pipeline sections won't have meaningful content
- One-shot reference docs (CLAUDE.md, runbooks) — those aren't specs
- Pre-Draft specs — the dashboard implies stability the spec hasn't reached

## LEARNINGS.md

Append findings under **What Worked** / **Patterns** as you go. Specific entries worth saving: which extraction heuristic worked for a non-obvious spec shape, what makes a pipeline diagram readable, when to drop a section.
