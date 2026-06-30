# The investigation run — dynamic multi-agent grounding

This is how investigation runs **every time the gate fires** — not an escalation. Once grounding is warranted (see the gate in `SKILL.md`), the run is always this framed → fanned-out → cross-verified pipeline, with width scaled to the topic (2–3 agents for a narrow question, 8–12 for a broad one). What the fan-out buys, and a single inline pass can't reliably deliver: real *evidence* (load-bearing claims adversarially cross-verified against independent sources) and the real *industry standard + elevation* (grounded in primary sources). When even this isn't enough — every claim cited and cross-checked into a standalone, fully-cited report — use the `deep-research` skill instead.

## Shape

Three phases, each a fan-out, context flowing forward — the `frame → research → brief` contract, scaled out:

1. **FRAME (internal fan-out)** — parallel reader agents map the premise's own reality: codebase, architecture/constraints, target & goal, prior art. Each claim cites a real `file:line`; a synthesis step distils them into a Problem Frame plus the sharp research questions that seed phase 2.
2. **RESEARCH (external fan-out, seeded by the Frame)** — one agent per research question, queries shaped by the real stack the Frame named. Each returns structured findings (claims with source URLs, standards, patterns, gotchas). A verify stage adversarially cross-checks load-bearing claims against an independent source — and its verdicts are **enforced in code** (claims partitioned verified vs untrusted before synthesis), not left to the synthesizer's discretion.
3. **SYNTHESIZE** — merge Frame + verified findings into the brief (the `SKILL.md` brief sections: TL;DR · Problem frame · Industry standard · Elevation · Tips & gotchas · Recommendations · What to research next · Sources), saved to `docs/investigations/`.

## Guardrails

- **Scale agents to breadth** — 2–3 for a narrow topic, 8–12+ for a broad one. Don't fan out wider than the topic earns. The template **clamps** research width to `N` (default 4, range 2–12) and slices the model's question list to it, so a malformed frame can't silently fan out 30 agents.
- **Verify is enforced, not requested** — refuted/unchecked claims are partitioned out *in code* before synthesis, so the synthesizer can only build load-bearing sections from verified claims; every shipped `source_url` is liveness-checked. (Prose-only "mark unverified" is theatre — a refuted claim still lands.)
- **Gate the same way** — the Workflow is still *grounding*; it doesn't fire on a one-sentence diff (the hard-skips in `SKILL.md` decide whether it runs at all; this template decides how wide).
- **No nested dispatch** — the workflow's agents must not spawn their own sub-agents.
- **Don't poll** — the run is background; read its result when it completes, never loop waiting on it.
- **Cap concurrency** — heavy local ops serialize on one machine-global lock; over-dispatch just queues.

## Workflow-script template

Adapt for the Workflow tool. Pass the task as `args.premise` (and optional `args.n` to size the fan-out). Plain JS (no TS); no `Date.now()` / `Math.random()`.

**Harness globals** — `phase()`, `parallel()`, `pipeline()`, `agent({label, phase, schema})`, `log()`, and `args` are provided by the Workflow tool, not imported; supply equivalents if you adapt this template elsewhere. The `args`-as-object-or-string parse below is *defensive*: one observed run delivered `args` as a JSON string (the Workflows doc says structured data, so the coercion is harmless when `args` is already an object — not a documented contract). The unconditional wins are the hard-fail-on-empty-premise and the width clamp.

```js
export const meta = {
  name: 'investigation-deep',
  description: 'Deep grounding: fan out to frame the task internally (codebase/architecture/goal/prior-art, claims cite file:line), then research externally seeded by that frame (question × source, adversarially cross-verified), then synthesize a grounded brief.',
  phases: [
    { title: 'Frame', detail: 'internal fan-out: codebase, architecture, goal, prior art' },
    { title: 'Research', detail: 'external fan-out seeded by the frame, with adversarial verify' },
    { title: 'Synthesize', detail: 'merge into the grounded brief' },
  ],
}

const A = typeof args === 'string' ? (() => { try { return JSON.parse(args) } catch { return {} } })() : (args || {})
const PREMISE = (A.premise || '').trim()
if (!PREMISE) throw new Error('investigation-deep: empty premise — pass the task to ground as args.premise')
// Clamp fan-out width: default 4 research questions, never <2 or >12. FRAME stays fixed-4 by design.
const N = Math.min(12, Math.max(2, Number(A.n) || 4))

// ---- Phase 1: FRAME (internal) ----
phase('Frame')

const FRAME_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['angle', 'findings', 'open_questions'],
  properties: {
    angle: { type: 'string' },
    findings: { type: 'array', items: {
      type: 'object', additionalProperties: false,
      required: ['claim', 'evidence_path', 'confidence'],
      properties: {
        claim: { type: 'string' },
        evidence_path: { type: 'string', description: 'real file path or file:line — never a guess' },
        confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
      },
    } },
    open_questions: { type: 'array', items: { type: 'string' } },
  },
}

const FRAME_ANGLES = [
  { key: 'codebase', prompt: 'Map where this task lives in THIS codebase: relevant modules/files, what already exists, the conventions in play. Use Read/Grep/Bash; every claim cites a real file:line.' },
  { key: 'architecture', prompt: 'Map the architectural constraints this task touches: relevant ADRs, platform invariants, data boundaries, the seams involved. Cite real file paths (docs/adr, CLAUDE.md, etc.).' },
  { key: 'goal', prompt: 'State the real target & goal: what success looks like, scope boundaries, constraints. Pull from the issue/spec/premise; cite where each constraint comes from.' },
  { key: 'prior-art', prompt: 'Find prior art in-repo: has this been attempted? related code, PRs, similar handlers/flows. Cite file paths.' },
]

const frames = (await parallel(FRAME_ANGLES.map(a => () =>
  agent('TASK TO GROUND:\n' + PREMISE + '\n\nANGLE: ' + a.prompt, { label: 'frame:' + a.key, phase: 'Frame', schema: FRAME_SCHEMA })
))).filter(Boolean)

const FRAME_OUT_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['constraints', 'goal', 'research_questions'],
  properties: {
    constraints: { type: 'array', items: { type: 'string' } },
    goal: { type: 'string' },
    research_questions: { type: 'array', items: { type: 'string' } },
  },
}

const PROBLEM_FRAME = await agent(
  'Synthesize a Problem Frame from these internal findings + the task. Output the real constraints, the goal in one line, and 4-8 SHARP external research questions specific to THIS task and its real stack.\n\nTASK:\n' + PREMISE + '\n\nFINDINGS:\n' + JSON.stringify(frames),
  { label: 'frame:synthesize', phase: 'Frame', schema: FRAME_OUT_SCHEMA }
)

// ---- Phase 2: RESEARCH (external, seeded by the frame) ----
phase('Research')

const RESEARCH_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['question', 'claims', 'standards', 'patterns', 'gotchas'],
  properties: {
    question: { type: 'string' },
    claims: { type: 'array', items: {
      type: 'object', additionalProperties: false,
      required: ['statement', 'source_url', 'confidence'],
      properties: {
        statement: { type: 'string' },
        source_url: { type: 'string' },
        confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
        recency: { type: 'string' },
      },
    } },
    standards: { type: 'array', items: { type: 'string' } },
    patterns: { type: 'array', items: { type: 'string' } },
    gotchas: { type: 'array', items: { type: 'string' } },
  },
}

const VERIFY_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['verdicts', 'note'],
  properties: {
    verdicts: { type: 'array', items: {
      type: 'object', additionalProperties: false,
      required: ['claim', 'verified', 'corroborating_urls'],
      properties: {
        claim: { type: 'string' },
        verified: { type: 'boolean' },
        corroborating_urls: { type: 'array', items: { type: 'string' } },
      },
    } },
    note: { type: 'string' },
  },
}

const QUESTIONS = (((PROBLEM_FRAME && PROBLEM_FRAME.research_questions) || []).slice(0, N)) // clamp model-supplied width

const researched = (await pipeline(
  QUESTIONS,
  (q, _orig, i) => agent(
    'Research this question to ground the task. FOUR-PART CONTRACT:\n- OBJECTIVE: answer ONLY the one question below.\n- OUTPUT: fill the RESEARCH_SCHEMA — claims (each with a real fetched source_url), standards, patterns, gotchas.\n- SOURCES/TOOLS: WebSearch + WebFetch (load via ToolSearch "select:WebSearch,WebFetch" if needed); use the SOURCES.md tiers, prefer PRIMARY sources (official docs / llms.txt / source repo) over SEO hits; mind the SOURCES.md gotchas (a site: miss is inconclusive → retry unscoped; re-issue WebFetch on cross-host redirects).\n- BOUNDARIES: research only THIS question — do not re-answer sibling questions, do not fan out to sub-agents. Drop any claim whose source you cannot fetch.\nFRAME: ' + JSON.stringify(PROBLEM_FRAME) + '\nQUESTION: ' + q,
    { label: 'research:' + (i + 1), phase: 'Research', schema: RESEARCH_SCHEMA }
  ),
  (res, _q, i) => {
    if (!res) return null
    const lb = (res.claims || []).slice(0, 5).map(c => '- ' + c.statement + ' [' + c.source_url + ']').join('\n')
    if (!lb) return { research: res, verification: null }
    return agent(
      'Adversarially verify these claims — try to REFUTE each; verified=true ONLY if an INDEPENDENT source (different domain than the given one) corroborates. Use WebSearch/WebFetch.\n' + lb,
      { label: 'verify:' + (i + 1), phase: 'Research', schema: VERIFY_SCHEMA }
    ).then(v => ({ research: res, verification: v }))
  }
)).filter(Boolean)

// ---- Phase 3: SYNTHESIZE ----
phase('Synthesize')

// Enforce the verify verdicts IN CODE: partition claims into verified vs refuted/unchecked,
// so a refuted claim can't silently land as load-bearing (prose "mark unverified" is not enough).
function verifiedOf(statement, ver) {
  const v = ver && ver.verdicts && ver.verdicts.find(x => x.claim && statement && x.claim.slice(0, 40) === statement.slice(0, 40))
  return v ? v.verified === true : false // false = refuted OR unchecked (beyond the verify cap) — both untrusted
}
const verifiedClaims = [], untrusted = []
for (const r of researched) {
  for (const c of (r.research.claims || [])) {
    (verifiedOf(c.statement, r.verification) ? verifiedClaims : untrusted).push({ ...c, question: r.research.question })
  }
}

const BRIEF_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['tldr', 'problem_frame', 'industry_standard', 'elevation', 'tips_gotchas', 'recommendations', 'what_to_research_next', 'sources'],
  properties: {
    tldr: { type: 'string' },
    problem_frame: { type: 'string' },
    industry_standard: { type: 'array', items: {
      type: 'object', additionalProperties: false, required: ['point', 'source'],
      properties: { point: { type: 'string' }, source: { type: 'string' } },
    } },
    elevation: { type: 'array', items: { type: 'string' } },
    tips_gotchas: { type: 'array', items: { type: 'string' } },
    recommendations: { type: 'array', items: { type: 'string' } },
    what_to_research_next: { type: 'array', items: { type: 'string' } },
    sources: { type: 'array', items: { type: 'string' } },
  },
}

const brief = await agent(
  'Synthesize the grounded brief for the task. Build load-bearing sections (industry_standard, elevation) ONLY from VERIFIED claims. Treat UNTRUSTED claims as not-fact — drop them or render "(unverified)", never as a standard. Before finalizing, liveness-check every source_url you cite (WebFetch it; if it 404s or is unreachable, drop or flag the claim — dead/fabricated URLs are the top deep-research failure mode). sources = deduped LIVE URLs + file:line.\n\nTASK:\n' + PREMISE + '\nFRAME:\n' + JSON.stringify(PROBLEM_FRAME) + '\nVERIFIED CLAIMS:\n' + JSON.stringify(verifiedClaims) + '\nUNTRUSTED (do not state as fact):\n' + JSON.stringify(untrusted),
  { label: 'synthesize', phase: 'Synthesize', schema: BRIEF_SCHEMA }
)

return brief
```
