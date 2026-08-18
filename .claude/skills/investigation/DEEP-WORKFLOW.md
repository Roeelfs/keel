# The investigation run — dynamic multi-agent grounding

This is how investigation runs **every time the gate fires** — not an escalation. Once grounding is warranted (see the gate in `SKILL.md`), the run is always this framed → fanned-out → cross-verified pipeline, with width scaled to the topic. What the fan-out buys, and a single inline pass can't reliably deliver: real *evidence* (load-bearing claims adversarially cross-verified) and the real *industry standard + elevation* (grounded in primary sources).

## Shape

Three phases, each a fan-out, context flowing forward — the `frame → research → brief` contract, scaled out:

1. **FRAME (internal fan-out)** — parallel reader agents map the premise's own reality: codebase, architecture/constraints, target & goal, prior art. Each claim cites a real `file:line`; a synthesis step distils them into a Problem Frame plus the sharp research questions that seed phase 2, **each question tagged with the source tier it should open at**.
2. **RESEARCH (external fan-out, seeded by the Frame)** — one agent per research question, queries shaped by the real stack the Frame named and by the catalog slice delivered to it in code. A verify stage adversarially cross-checks claims and returns **one of five verdicts**; the verdicts are **enforced in code**, not left to the synthesizer.
3. **SYNTHESIZE** — merge Frame + verified findings into the brief, **which the synthesize agent writes to disk itself** and returns as `brief_path`.

## Guardrails

- **Width is set by the CALLER's `n`, not by the frame prompt.** `args.n` clamps to 2–12 (default 4). Measured 2026-08-18: a run launched with `n=10` started 10 research lanes on stock code — the template has never under-delivered questions. Scale `n` to breadth; don't fan out wider than the topic earns.
- **Verify is enforced, not requested.** `corroborated` and `primary_attested` may carry a load-bearing section; `contested`, `unverified` and `refuted` are partitioned out *in code* before synthesis. `primary_attested` is the terminal state for a fact whose only authority is the vendor's own documentation — admissible, but **rendered marked**, never as an independent standard. (A binary verified/unverified flag made every vendor-primary fact unverifiable by construction, which is exactly backwards for a catalog of primary sources.)
- **The catalog reaches a lane only as CODE.** A lane starts cold and does not read `SOURCES.md` — measured 2026-08-18 at 2 of 29 generated scripts and 2 of 602 lane transcripts. The `SOURCE_TIERS` constant below is the delivered copy; `SOURCES.md` is canonical. **Edit both in the same change.**
- **Concrete literals survive; pointers don't.** Propagation into generated scripts ranges 100%→7% *within one prompt string* — `select:WebSearch,WebFetch` propagates 29/29 while the words "SOURCES.md" propagate 2/29, ~40 characters apart. The variable is concrete-literal vs unresolvable-pointer, plus whether a verbatim-copy guard is present. Write recipes, not references.
- **Gate the same way** — the Workflow is still *grounding*; the hard-skips in `SKILL.md` decide whether it runs at all, this template decides how wide.
- **No nested dispatch** — the workflow's agents must not spawn their own sub-agents.
- **Don't poll** — the run is background; read its result when it completes.
- **A workflow script cannot touch the filesystem.** No `fs`, no `require`, no `process`; `Date.now()` / `Math.random()` / argless `new Date()` are rejected by the determinism gate **at launch** (errorCode 4 — a whole-run outage, not a missing line). Anything that must write goes through an `agent()`, which has Bash and Write.

## Workflow-script template

Adapt for the Workflow tool. Pass the task as `args.premise` (and optional `args.n` to size the fan-out). Plain JS (no TS).

**Harness globals** — `phase()`, `parallel()`, `pipeline()`, `agent({label, phase, schema})`, `log()`, and `args` are provided by the Workflow tool, not imported. The `args`-as-object-or-string parse is *defensive*: one observed run delivered `args` as a JSON string.

```js
export const meta = {
  name: 'investigation-deep',
  description: 'Deep grounding: fan out to frame the task internally (codebase/architecture/goal/prior-art, claims cite file:line), then research externally seeded by that frame (question × source tier, adversarially cross-verified), then synthesize and save a grounded brief.',
  phases: [
    { title: 'Frame', detail: 'internal fan-out: codebase, architecture, goal, prior art' },
    { title: 'Research', detail: 'external fan-out seeded by the frame, with adversarial verify' },
    { title: 'Synthesize', detail: 'merge into the grounded brief, save it, record metrics' },
  ],
}

const A = typeof args === 'string' ? (() => { try { return JSON.parse(args) } catch { return {} } })() : (args || {})
const PREMISE = (A.premise || '').trim()
if (!PREMISE) throw new Error('investigation-deep: empty premise — pass the task to ground as args.premise')
const N = Math.min(12, Math.max(2, Number(A.n) || 4))
const VERIFY_CAP = 30 // claims sent to the verifier per lane. Measured: mean 18/lane, p90 30 — 30 leaves 2.9% capped.

// ============================================================================
// SOURCE_TIERS — the delivered copy of SOURCES.md.
// COPY THIS BLOCK VERBATIM into the generated script. Do NOT paraphrase it, do NOT
// summarize it, do NOT specialize it to the premise. It is a catalog, not a prompt.
// A lane never reads SOURCES.md; this constant is the only path by which a source
// reaches one. Canonical file: .claude/skills/investigation/SOURCES.md
// ============================================================================
const SOURCE_TIERS = {
  standards_docs: 'llms.txt FIRST: https://<docs-host>/llms.txt or /llms-full.txt | site:docs.<vendor>.com <topic> | site:developer.mozilla.org <topic> | site:rfc-editor.org <topic> | site:github.com awesome <topic>',
  code_impl: 'https://api.github.com/search/repositories?q=topic:<topic>+<terms>&sort=updated&per_page=5 -> items[].{full_name,pushed_at,archived,stargazers_count} | site:stackoverflow.com <error> | site:sourcegraph.com <symbol> (WebSearch ONLY - the app is a JS shell) | GOTCHA: REST code search is 401 unauthenticated; repo search is 10 req/min, /repos/ eats the 60/hr core quota',
  industry_pulse: 'https://hn.algolia.com/api/v1/search?query=<topic>&tags=story (JSON; the bare hn.algolia.com/?q= URL is a JS shell) | site:tldr.tech <topic> | site:lobste.rs <topic> | site:dev.to <topic> | site:changelog.com <topic>',
  agent_ecosystem: 'https://registry.modelcontextprotocol.io/v0/servers?search=<q>&version=latest&limit=10 (WITHOUT version=latest you get isLatest:false rows) | https://registry.smithery.ai/servers?q=<q>&pageSize=10 -> useCount,verified,inactive | https://glama.ai/api/mcp/v1/servers?query=<q>&first=10 | https://skills.sh/api/search?q=<q> | https://raw.githubusercontent.com/anthropics/claude-plugins-official/main/.claude-plugin/marketplace.json | https://api.github.com/search/repositories?q=topic:mcp-server+<terms>&sort=updated',
  community: 'Discourse detect https://<host>/site.json then https://<host>/search.json?q=<terms>+order%3Alatest+after%3A<YYYY-MM-DD> (order:latest is LOAD-BEARING - without it 2022 threads bury this month) | https://github.com/<owner>/<repo>/discussions?discussions_q=<q>+is:answered | https://www.usenix.org/conference/<osdi26|nsdi26|atc26>/technical-sessions | https://itunes.apple.com/search?media=podcast&term=<terms>&limit=3 -> feedUrl -> podcast:transcript URL | GOTCHA: a Discourse 200 with every array empty is NOT absence, retry loosened',
  currency_lifecycle: 'https://endoflife.date/api/v1/products/<product> -> releases[].{isEol,eolFrom,latest} + generated_at (v1 ONLY - v0 has no freshness field) | https://api.github.com/repos/<o>/<r>/releases/latest -> tag_name,published_at (the ONLY non-prerelease surface) | https://github.com/<o>/<r>/releases.atom (unmetered) | https://status.<vendor>/api/v2/summary.json -> page.updated_at,status.indicator | https://raw.githubusercontent.com/<o>/<r>/main/CHANGELOG.md',
  registries_health: 'https://api.deps.dev/v3/systems/<npm|pypi|cargo|maven|go|nuget|rubygems>/packages/<name>/versions/<version> -> isDeprecated,advisoryKeys[],publishedAt (ONE shape, SEVEN ecosystems; the GET replacement for OSV which is 405 POST-only) | https://registry.npmjs.org/<pkg>/latest (NEVER the bare packument - 804KB, truncation reported express as deprecated) | https://pypi.org/pypi/<pkg>/<version>/json | https://crates.io/api/v1/crates/<crate> -> max_stable_version (403s bare curl, SERVES WebFetch) | https://proxy.golang.org/<module>/@latest | https://repo1.maven.org/maven2/<group>/<artifact>/maven-metadata.xml (search.maven.org is 4 MONTHS STALE) | https://api.github.com/advisories?ecosystem=<eco>&affects=<pkg>',
  structured_knowledge: 'https://en.wikipedia.org/api/rest_v1/page/summary/<Title> -> extract,revision,timestamp | https://www.wikidata.org/w/api.php?action=wbsearchentities&search=<q>&language=en&format=json THEN query.wikidata.org/sparql (a guessed QID returns empty bindings = a silent zero) | https://api.w3.org/specifications/<shortname>/versions/latest?format=json (www.w3.org/TR/tr.json is HTTP 300, not JSON) | https://raw.githubusercontent.com/tc39/proposals/main/README.md | https://datatracker.ietf.org/api/v1/doc/document/?name__startswith=draft-ietf-<wg>&format=json | https://api.webstatus.dev/v1/features?q=<feature> | https://openrouter.ai/api/v1/models (675KB - narrow to one model) | site:arxiv.org <topic>',
}
const TIER_NAMES = Object.keys(SOURCE_TIERS)

// Gotchas that silently un-ground a lane. Verbatim; do not paraphrase.
const SEARCH_GOTCHAS = [
  'NEVER pass allowed_domains/blocked_domains to WebSearch - put the host in the query as site:<host>. This is 52 of 52 of all WebSearch hard failures measured.',
  'NEVER guess a raw.githubusercontent.com path (51 of 211 WebFetch 404s). List the tree first.',
  'reddit.com and web.archive.org are refused by this harness on every route - do not spend a retry.',
  'A site: miss is inconclusive, not absence - retry unscoped before concluding nothing exists.',
  'WebFetch RETURNS a cross-host redirect URL instead of following it - re-issue on the target.',
  'WebFetch truncates HEAD-FIRST. Prefer the smallest document that answers the question: pin the version, use /latest.',
  'A 200 whose body says "enable JavaScript" is a JS shell - an empty answer wearing a success code.',
].join('\n- ')

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
    research_questions: { type: 'array', items: {
      type: 'object', additionalProperties: false,
      required: ['question', 'tier'],
      properties: {
        question: { type: 'string' },
        tier: { type: 'string', enum: TIER_NAMES, description: 'the source tier this question should OPEN at — chosen by fit, not round-robin' },
      },
    } },
  },
}

const PROBLEM_FRAME = await agent(
  'Synthesize a Problem Frame from these internal findings + the task. Output the real constraints, the goal in one line, and exactly ' + N + ' SHARP external research questions specific to THIS task and its real stack.\n\nEach question is TAGGED with the source tier it should OPEN at, chosen by FIT: ' + TIER_NAMES.join(', ') + '. A version/deprecation question opens at currency_lifecycle; a "does a package/server/skill for X exist" question at agent_ecosystem or registries_health; an idioms/prior-art question at code_impl; a real-world-pain question at community; a definition/standard question at structured_knowledge. Questions must be MUTUALLY ORTHOGONAL — two lanes researching the same thing is the single most wasteful outcome.\n\nTASK:\n' + PREMISE + '\n\nFINDINGS:\n' + JSON.stringify(frames),
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
      required: ['id', 'statement', 'source_url', 'source_class', 'confidence'],
      properties: {
        id: { type: 'string', description: 'short unique id for THIS claim, e.g. c1, c2 — the verifier echoes it back verbatim' },
        statement: { type: 'string' },
        source_url: { type: 'string' },
        source_class: { type: 'string', enum: ['vendor-primary', 'standards-body', 'registry', 'community', 'independent-secondary', 'aggregator'] },
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
      required: ['id', 'verdict', 'corroborating_urls'],
      properties: {
        id: { type: 'string', description: 'echoed VERBATIM from the bracketed id you were given — never re-worded' },
        verdict: { type: 'string', enum: ['corroborated', 'primary_attested', 'contested', 'unverified', 'refuted'] },
        corroborating_urls: { type: 'array', items: { type: 'string' } },
      },
    } },
    note: { type: 'string' },
  },
}

const QUESTIONS = ((PROBLEM_FRAME && PROBLEM_FRAME.research_questions) || []).slice(0, N)

const researched = (await pipeline(
  QUESTIONS,
  (q, _orig, i) => {
    const tier = (q && q.tier && SOURCE_TIERS[q.tier]) ? q.tier : TIER_NAMES[0]
    const siblings = QUESTIONS.filter((_, j) => j !== i).map(x => '- ' + (x.question || x)).join('\n')
    return agent(
      'Research this question to ground the task. FOUR-PART CONTRACT:\n' +
      '- OBJECTIVE: answer ONLY the one question below.\n' +
      '- OUTPUT: fill the RESEARCH_SCHEMA. Every claim needs a real FETCHED source_url, a source_class, and a short unique id (c1, c2, …). Drop any claim whose source you could not fetch.\n' +
      '- SOURCES/TOOLS: WebSearch + WebFetch (load via ToolSearch "select:WebSearch,WebFetch" if needed); Bash for curl liveness probes.\n' +
      '  OPEN AT THIS TIER — ' + tier + ':\n  ' + SOURCE_TIERS[tier] + '\n' +
      '  Widen to another tier only if this one does not fit the question. Other tiers available: ' + TIER_NAMES.filter(t => t !== tier).join(', ') + '.\n' +
      '  Prefer PRIMARY sources (official docs / llms.txt / the vendor API itself) over SEO recaps.\n' +
      '- BOUNDARIES: research only THIS question — do not fan out to sub-agents, and do NOT re-cover the sibling questions other lanes already own:\n' + siblings + '\n\n' +
      'GOTCHAS THAT WILL SILENTLY UN-GROUND YOU:\n- ' + SEARCH_GOTCHAS + '\n\n' +
      'FRAME: ' + JSON.stringify(PROBLEM_FRAME) + '\nQUESTION: ' + (q.question || q),
      { label: 'research:' + (i + 1), phase: 'Research', schema: RESEARCH_SCHEMA }
    )
  },
  (res, _q, i) => {
    if (!res) return null
    const claims = (res.claims || []).slice(0, VERIFY_CAP)
    if (!claims.length) return { research: res, verification: null, sent: 0 }
    const lb = claims.map(c => '- [' + c.id + '] ' + c.statement + ' (' + c.source_url + ')').join('\n')
    return agent(
      'Adversarially verify these claims — try to REFUTE each. Echo each claim\'s bracketed id VERBATIM into verdicts[].id; never re-word it. Assign exactly one verdict:\n' +
      '- corroborated — an INDEPENDENT source (different domain than the one given) confirms it.\n' +
      '- primary_attested — the claim is about a vendor\'s own product and that vendor\'s own primary documentation attests it, with no independent corroborator AND no contradicting source. This is the honest state for a vendor-specific fact; do not inflate it to corroborated.\n' +
      '- contested — you found a source that disagrees.\n' +
      '- unverified — you could not resolve it either way.\n' +
      '- refuted — you found it to be wrong.\n' +
      'Use WebSearch/WebFetch/Bash. A dead, auth-walled or 403ing source is not corroboration.\n' + lb,
      { label: 'verify:' + (i + 1), phase: 'Research', schema: VERIFY_SCHEMA }
    ).then(v => ({ research: res, verification: v, sent: claims.length }))
  }
)).filter(Boolean)

// ---- Phase 3: SYNTHESIZE ----
phase('Synthesize')

// Enforce the verdicts IN CODE. Join on the echoed id — a 40-char prefix match on the claim TEXT
// lost 43.1% of returned TRUE verdicts, because verifiers paraphrase what they were told to echo.
const LOAD_BEARING = { corroborated: true, primary_attested: true }
const verifiedClaims = [], untrusted = []
let verdictsTrue = 0, matched = 0, sentTotal = 0, unmatchedIds = []
for (const r of researched) {
  sentTotal += r.sent || 0
  const vs = (r.verification && r.verification.verdicts) || []
  for (const v of vs) if (LOAD_BEARING[v.verdict]) verdictsTrue++
  for (const c of (r.research.claims || [])) {
    const v = vs.find(x => x.id === c.id)
    if (v && LOAD_BEARING[v.verdict]) { matched++; verifiedClaims.push({ ...c, verdict: v.verdict, question: r.research.question }) }
    else untrusted.push({ ...c, verdict: (v && v.verdict) || 'unverified', question: r.research.question })
  }
  for (const v of vs) if (LOAD_BEARING[v.verdict] && !(r.research.claims || []).some(c => c.id === v.id)) unmatchedIds.push(v.id)
}
// Make an inert join LOUD at runtime — a greppable identifier passes over a dead fix.
if (verdictsTrue > matched) log('JOIN LOSS: ' + (verdictsTrue - matched) + ' load-bearing verdicts did not match a claim id — unmatched: ' + unmatchedIds.join(','))
log('claims sent to verify: ' + sentTotal + ' | load-bearing: ' + verifiedClaims.length + ' | untrusted: ' + untrusted.length)

function hostOf(u) { const m = /^https?:\/\/([^\/?#]+)/.exec(u || ''); return m ? m[1].replace(/^www\./, '') : '' }
const domains = {}
for (const c of verifiedClaims.concat(untrusted)) { const h = hostOf(c.source_url); if (h) domains[h] = 1 }
const tierCounts = {}
for (const q of QUESTIONS) { const t = (q && q.tier) || 'unknown'; tierCounts[t] = (tierCounts[t] || 0) + 1 }
function hash32(s) { let h = 0; for (let i = 0; i < s.length; i++) { h = ((h << 5) - h + s.charCodeAt(i)) | 0 } return String(h) }
const SLUG = PREMISE.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').split('-').slice(0, 6).join('-')

const BRIEF_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['tldr', 'problem_frame', 'industry_standard', 'elevation', 'tips_gotchas', 'recommendations', 'what_to_research_next', 'sources', 'brief_path'],
  properties: {
    tldr: { type: 'string' },
    problem_frame: { type: 'string' },
    industry_standard: { type: 'array', items: {
      type: 'object', additionalProperties: false, required: ['point', 'source', 'verdict'],
      properties: { point: { type: 'string' }, source: { type: 'string' }, verdict: { type: 'string', enum: ['corroborated', 'primary_attested'] } },
    } },
    elevation: { type: 'array', items: {
      type: 'object', additionalProperties: false, required: ['point', 'source'],
      properties: { point: { type: 'string' }, source: { type: 'string' } },
    } },
    tips_gotchas: { type: 'array', items: { type: 'string' } },
    recommendations: { type: 'array', items: { type: 'string' } },
    contrarian_evidence: { type: 'array', description: 'what argues AGAINST the emerging recommendation', items: {
      type: 'object', additionalProperties: false, required: ['point', 'source'],
      properties: { point: { type: 'string' }, source: { type: 'string' } },
    } },
    source_coverage: { type: 'array', description: 'which source tiers actually produced a cited claim', items: { type: 'string' } },
    what_to_research_next: { type: 'array', items: { type: 'string' } },
    sources: { type: 'array', items: { type: 'string' } },
    brief_path: { type: 'string', description: 'the ABSOLUTE path you actually wrote — never a path you did not write' },
  },
}

const brief = await agent(
  'Synthesize the grounded brief for the task, SAVE IT YOURSELF, and return the path.\n\n' +
  'CONTENT RULES:\n' +
  '- Build industry_standard and elevation ONLY from LOAD-BEARING claims. Carry each one\'s verdict: a `primary_attested` point is rendered "(vendor-attested, not independently corroborated)". Never present it as an independent standard.\n' +
  '- UNTRUSTED claims are not fact. Drop them, or render them explicitly "(unverified)".\n' +
  '- Liveness-check every source_url you cite before citing it; drop or flag what 404s.\n' +
  '- sources = deduped LIVE URLs + file:line.\n\n' +
  'SAVING (do this before you return):\n' +
  '- Get the date with Bash: `date +%F`.\n' +
  '- If the premise is about THIS codebase: `mkdir -p docs/investigations` then write `docs/investigations/<YYYY-MM-DD>-' + SLUG + '.md`.\n' +
  '- If it is NOT about this codebase (personal, financial, vendor-sourcing, correspondence): write it to the session scratchpad instead — never commit it into the repo.\n' +
  '- Open the file with: `> Grounded <date> against sources current as of <dates>; supersede on re-investigation of this slug`\n' +
  '- Return the ABSOLUTE path you actually wrote as brief_path.\n\n' +
  'TASK:\n' + PREMISE + '\nFRAME:\n' + JSON.stringify(PROBLEM_FRAME) +
  '\nLOAD-BEARING CLAIMS (each carries its verdict):\n' + JSON.stringify(verifiedClaims) +
  '\nUNTRUSTED (do not state as fact):\n' + JSON.stringify(untrusted),
  { label: 'synthesize', phase: 'Synthesize', schema: BRIEF_SCHEMA }
)

// Metrics row — the instrument that lets the NEXT run grade this one.
// A script cannot write files, so a terminal agent does the append. Failure-isolated:
// a denied write must never cost the brief.
const METRICS = {
  premise_hash: hash32(PREMISE), n: N,
  questions_emitted: QUESTIONS.length,
  lanes_started: QUESTIONS.length, lanes_returned: researched.length,
  claims_harvested: verifiedClaims.length + untrusted.length,
  verify_claims_sent: sentTotal, verify_verdicts_returned: verdictsTrue,
  join_unmatched: verdictsTrue - matched,
  claims_load_bearing: verifiedClaims.length,
  distinct_domains: Object.keys(domains).length,
  per_tier_counts: tierCounts,
  brief_path: brief && brief.brief_path,
}
try {
  await agent(
    'Append exactly one line to ~/.claude/analytics/investigation-runs.jsonl. Use Bash only:\n' +
    'mkdir -p ~/.claude/analytics, then append the JSON below with a `ts` field added as the output of `date -u +%FT%TZ`.\n' +
    'Do nothing else. Return the single word OK.\n\nJSON: ' + JSON.stringify(METRICS),
    { label: 'metrics', phase: 'Synthesize' }
  )
} catch (e) { log('metrics append failed (brief is unaffected): ' + e) }

return brief
```

## Probes — how the next run grades this one

Read `~/.claude/analytics/investigation-runs.jsonl`; it is the instrument for all of these.

| What | Baseline (2026-08-18) | Target |
|------|----------------------|--------|
| verify join yield — load-bearing verdicts that matched a claim | 56.9% (392/689) | >95%; `join_unmatched` ≈ 0 |
| claims never sent to a verifier | 63–70% | `verify_claims_sent` ≥ 90% of `claims_harvested` |
| distinct domains per brief | median 10 | rising |
| cross-research-lane duplicate URLs | 11.1% (265/2,386) | <7% |
| tiers producing a cited claim | industry-pulse ≈ 0, novelty tiers 0.84% | ≥3 of the 5 new tiers non-zero over 5 runs |
| WebSearch `blocked_domains` InputValidationErrors | 52 corpus-wide | 0 |
| brief saved | 25/30 (and 0/N on the direct-Workflow path) | every row's `brief_path` resolves |

A row still at zero after 10 delivered runs gets **deleted** from `SOURCE_TIERS` and `SOURCES.md`, not defended.
