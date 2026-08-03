# Workflow B — vendor delta: news, changelogs, docs + model pins

Research what the **vendors actually shipped** since the last run — CLI releases, agent/skill spec changes, model lineups, and published agent-design guidance — then map each capability to a concrete harness edit. Every claim is adversarially falsified before it reaches the plan.

**Why the falsifier wave is not optional.** A research agent's failure mode is a *plausible* capability: a config key that reads like it should exist, a version that sounds current, a feature the harness "should" adopt. On one measured run the wave killed **4 of the top-ranked items** — an orchestrator-breakage claim, a permission audit, a hook-semantics fix and a missing-gate finding — all of which dissolved into zero call sites or zero matching rules on inspection. Adopting them would have been pure churn. **A plausible-but-nonexistent config key is the worst possible output of this lane** — worse than a documented gap, because it looks like progress.

**Ground rules baked into every prompt:**
- Every claim carries a **dated primary source** (official changelog, release notes, docs page, GitHub release/tag) with its URL — or it is marked `could-not-confirm`.
- **Never assert a version, CLI flag, env var, hook event, settings key, tool name or model id from recollection.** Corroborate against the **installed binary** where possible (`--help`, or `strings -a <cli> | grep -F <KEY>`) — a string present in the shipped binary outranks a blog post.
- Before calling anything "missing", **read the local files** — the harness may already have it.
- Confidence is per item: `verified / inferred / could-not-confirm`.

**Record the negatives.** Items that are refuted, already-adopted, or app-runtime-class go into `skip_or_watch` **with the reason**, so the next run does not re-research them. That list is a real output, not filler.

**The pin-vs-enforcement check — run it every time.** A model/tool pin written in an instructions file is a *claim*, not a mechanism. Trace each documented pin to the thing that actually selects it at runtime (a CLI flag, a config file key, a default). One measured run found a flagship model documented as the standing second-opinion pin while the runtime config selected a mid-tier model and no call site ever passed `--model` — so months of "independently cross-checked" claims were made against a different model than the one documented. **Generalize:** any pin whose enforcement path you cannot name is unverified.

```js
export const meta = {
  name: 'vendor-capability-delta',
  description: 'Research vendor releases/changelogs/docs, adversarially verify, map each capability to a harness change',
  phases: [{ title: 'Research' }, { title: 'Verify' }, { title: 'Plan' }],
}
const ARGS = typeof args === 'string' ? JSON.parse(args) : args
const SNAP = ARGS.snapshot   // installed CLI versions, agent model pins, plugin inventory, known knobs
const PIN = 'You are a leaf agent: do NOT spawn sub-agents or Workflows; do the work inline and return. RESEARCH ONLY — read-only, never mutate, no polling. Ground EVERY claim in a dated primary source and include the URL. NEVER assert a version, flag, env var, hook event, settings key or model id from recollection — corroborate against the installed binary (--help, strings -a) where you can; if you cannot find a primary source, mark it could-not-confirm. Focus on ~the last 90 days plus anything older the harness clearly has not adopted.'

const CAP = { type:'object', additionalProperties:false, required:['report_markdown','capabilities'], properties:{
  report_markdown:{type:'string'},
  capabilities:{type:'array',items:{type:'object',additionalProperties:false,
    required:['name','vendor','source_url','dated','what_changed','confidence','already_adopted','harness_impact','surface','proposed_change'],
    properties:{ name:{type:'string'}, vendor:{type:'string'}, source_url:{type:'string'}, dated:{type:'string'},
      what_changed:{type:'string'}, confidence:{enum:['verified','inferred','could-not-confirm']},
      already_adopted:{type:'boolean'}, harness_impact:{enum:['high','medium','low','none']},
      surface:{enum:['skill','agent','settings','instructions-file','hook','plugin/mcp-roster','cli-upgrade','model-pin','none']},
      proposed_change:{type:'string',description:'exact file + exact text/flag/pin that changes, and why'} }}} }}

phase('Research')
const lanes = await parallel([
  ()=>agent(`${PIN}\nANGLE 1 — YOUR PRIMARY CLI's release deltas since the installed version. Enumerate: new/changed hook events and matchers, new settings keys, new env vars, new flags/subcommands, agent-frontmatter changes, skill-loading changes, plugin/marketplace commands, permission/sandbox changes, and anything touching context/compaction. Sources: the official changelog + docs, the GitHub repo (releases, CHANGELOG, recent issues), npm dist-tags. Corroborate against the INSTALLED binary. SNAPSHOT: ${SNAP}`, {label:'res:cli', phase:'Research', schema:CAP, model:'sonnet', agentType:'general-purpose'}),
  ()=>agent(`${PIN}\nANGLE 2 — agent/skill SPEC + ecosystem. Changes to the skill file format and frontmatter fields, discovery/precedence, bundled-script conventions, packaging, the skills CLI, and the official skills/plugins repos (new, renamed or removed entries worth adopting). For each, say whether THIS harness's skills should change — e.g. a frontmatter field we should start declaring. SNAPSHOT: ${SNAP}`, {label:'res:spec', phase:'Research', schema:CAP, model:'sonnet', agentType:'general-purpose'}),
  ()=>agent(`${PIN}\nANGLE 3 — MODELS + API surface. Establish the CURRENT flagship lineup with exact ids, release dates, deprecation/retirement dates, context windows and reasoning-effort params. Then runtime features relevant to a CLI harness: context-management/editing, tool search, memory tooling, prompt-caching TTLs, structured outputs, MCP changes, the agent SDK. THEN audit this harness's pins against what you found and flag ONLY genuinely-stale or wrong ids — leave deliberate cheap-tier routing alone, and say plainly which pins you CONFIRMED current. Also run the PIN-vs-ENFORCEMENT check: for each documented pin, name the mechanism that actually selects it at runtime; if nothing does, report it as documented-but-unenforced. SNAPSHOT: ${SNAP}`, {label:'res:models', phase:'Research', schema:CAP, model:'sonnet', agentType:'general-purpose'}),
  ()=>agent(`${PIN}\nANGLE 4 — published AGENT-DESIGN guidance. Mine the vendors' engineering blogs, docs and cookbooks for PATTERNS a mature multi-skill harness should absorb: context engineering, subagent orchestration, tool design, agent evaluation, long-horizon/compaction strategy, skill authoring, hooks as guardrails, sandboxed execution, containment/security. For each, name the SPECIFIC skill or agent file here that should change and how. Reject marketing; take only documented technique. SNAPSHOT: ${SNAP}`, {label:'res:patterns', phase:'Research', schema:CAP, model:'sonnet', agentType:'general-purpose'}),
  ()=>agent(`${PIN}\nANGLE 5 — THE SECOND-RUNTIME delta (the other vendor CLI you dispatch to). Current release vs installed: new flags/subcommands, config keys, approval/sandbox modes, MCP support, model selection, session/rollout format, and the non-interactive exec contract. Then its model lineup and exact api ids (is the id this harness pins still current, superseded or renamed?). Say explicitly which of this harness's pieces that touch it need editing — the skill, the agent routing, the documented pin. SNAPSHOT: ${SNAP}`, {label:'res:runtime2', phase:'Research', schema:CAP, model:'sonnet', agentType:'general-purpose'}),
  ()=>agent(`${PIN}\nANGLE 6 — adjacent agent-platform patterns. Survey what the other major vendors shipped for agent builders and judge HARSHLY which are HARNESS-CLASS (a technique or config a CLI-agent harness adopts directly) vs APP-RUNTIME-CLASS (only relevant when building a product on their SDK — out of scope). For harness-class items only, name the concrete file change. Default verdict is skip; justify anything rated high impact. SNAPSHOT: ${SNAP}`, {label:'res:adjacent', phase:'Research', schema:CAP, model:'sonnet', agentType:'general-purpose'}),
])

// Barrier JUSTIFIED: dedupe the same capability reported by several lanes BEFORE the
// expensive per-item falsifier wave — otherwise you verify the same claim 3x.
const all = lanes.filter(Boolean).flatMap(l => l.capabilities || [])
const seen = new Set()
const deduped = all.filter(c => {
  if (c.harness_impact === 'none' || c.surface === 'none') return false
  const k = (c.name || '').toLowerCase().replace(/[^a-z0-9]/g, '').slice(0, 40)
  if (seen.has(k)) return false
  seen.add(k); return true
})
const rank = { high: 0, medium: 1, low: 2 }
const ordered = deduped.sort((a, b) => (rank[a.harness_impact] ?? 3) - (rank[b.harness_impact] ?? 3))
const toVerify = ordered.slice(0, 26)
// NO SILENT CAPS — say what was dropped.
if (ordered.length > toVerify.length) log(`verifying top ${toVerify.length} of ${ordered.length}; ${ordered.length - toVerify.length} lower-impact items dropped UNVERIFIED`)

phase('Verify')
const VERDICT = { type:'object', additionalProperties:false, required:['verdict','why','corrected_claim','adoption_verdict','risk'], properties:{
  verdict:{enum:['confirmed','partially-wrong','refuted','could-not-confirm']},
  why:{type:'string',description:'what you actually checked — the URL fetched, the binary string grepped, the local file read'},
  corrected_claim:{type:'string'}, adoption_verdict:{enum:['adopt','adapt','skip','watch']}, risk:{type:'string'} }}
const verified = await parallel(toVerify.map(c => () =>
  agent(`${PIN}\nADVERSARIAL VERIFIER — your job is to REFUTE this claim and its proposed change, not confirm it. CLAIM: ${JSON.stringify(c)}\n\nProbes in order: (1) Does it EXIST as described? Fetch the source_url and read it — a 404, or a page that does not say what the claim says, is refuted on its own. (2) Is the version/date right, and actually newer than what is installed? (3) For any env var, settings key, hook event, flag or tool name: confirm it against the INSTALLED binary or a real docs page — a plausible-but-nonexistent key is the worst possible output. (4) Is it ALREADY adopted? READ THE LOCAL FILES before claiming it is missing. (5) Would the change actually help, or is it churn / a fix for a problem this harness does not have? Default to skepticism: unsure → could-not-confirm, and adoption_verdict watch or skip.`,
    {label:`verify:${(c.name||'cap').slice(0,28)}`, phase:'Verify', schema:VERDICT, model:'sonnet', agentType:'general-purpose'})
  .then(v => ({ capability: c, verdict: v }))))

phase('Plan')
const PLAN = { type:'object', additionalProperties:false,
  required:['executive_summary','version_matrix','adopt_now','adapt','skip_or_watch','model_pin_edits','sequenced_execution','open_questions'], properties:{
  executive_summary:{type:'string'}, version_matrix:{type:'string',description:'component | installed | latest | status | update command | risk'},
  adopt_now:{type:'string'}, adapt:{type:'string'},
  skip_or_watch:{type:'string',description:'refuted / could-not-confirm / already-adopted / app-runtime-class — one line each WITH the reason, so the next run does not re-research them'},
  model_pin_edits:{type:'string',description:'only genuinely-stale ids; explicitly LIST the pins confirmed current so nobody churns them'},
  sequenced_execution:{type:'string',description:'cli-upgrades → plugin/marketplace → model pins → skill/agent edits → settings/hooks; each tagged surface + risk; MAJOR bumps isolated last with a bake flag'},
  open_questions:{type:'array',items:{type:'object',additionalProperties:false,required:['question','recommendation'],properties:{question:{type:'string'},recommendation:{type:'string'}}}} }}
return await agent(`Synthesize ONE ready-to-execute vendor-adoption plan. Rules: (a) DROP anything rated refuted or could-not-confirm unless you restate it as an open question — never carry a claim above its evidence; (b) drop already-adopted items but LIST them in skip_or_watch so a future run does not re-research them; (c) prefer few high-leverage changes over a long churn list (fewer-bigger-changes, delete-legacy, one-architecture, and the skills repo stays public + marker-free); (d) every edit names an exact file and the exact text/flag/pin; (e) say plainly which pins you CONFIRMED already current. VERIFIED: ${JSON.stringify(verified.filter(Boolean))}\n\nLANE REPORTS: ${JSON.stringify(lanes.filter(Boolean).map(l => l.report_markdown))}`,
  {label:'vendor-plan', phase:'Plan', effort:'high', model:'opus', schema:PLAN, agentType:'general-purpose'})
```
