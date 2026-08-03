# Workflow E — context & compaction economics (every run)

Fires **every time**. The other lanes ask "is the harness correct?"; this one asks **"what is it costing, and is that improving?"** Its output is a dated report plus one appended row in a persistent ledger, so the trend is visible across runs instead of being re-derived from scratch each time.

**Why it is standing, not conditional.** Measured on one real harness over 7 days: **20.4B context tokens read on the main loop = 51,236 turns × ~399k average context**, against 91.2M output tokens — a **~220:1 context-to-output ratio**. The cost equation is `turns × context_size × model_weight`; output length is a rounding error. Nobody notices this without measuring, because every individual turn feels cheap.

**Analyze in a subagent, never inline** — the raw transcripts are hundreds of MB and reading them in the main loop is itself the anti-pattern this lane exists to find.

## The metrics that matter (compute these, don't editorialize)

Parse the local transcripts (`~/.claude/projects/*/*.jsonl`; also `~/.codex/sessions/**/rollout-*.jsonl` where a second runtime is in play):

1. **Context per turn** — total, median, p90, max; and the share of all context read by turns above ~150k (expect a brutal Pareto: ~86% of turns → ~96% of context).
2. **Fixed preamble** — the session-minimum per-turn floor (system prompt + instructions files + MCP schemas + skill/plugin descriptions) and its share. This is paid on *every* turn, so it is the highest-leverage single number.
3. **Accumulated-payload composition** — `tool_result` vs `tool_use` params vs assistant/user text. Tool traffic usually dominates (~76%), which is what justifies the delegate-reads rule.
4. **Compaction behavior** — count reset events and the **peak-before-reset** distribution (median/p90/max). This is the ONLY empirical read on where compaction actually fires, and it is how you verify a threshold knob is doing what you think.
5. **Subagent context peaks** — median/p90/p99/**max**, and the count above the main-thread cap. This is what licenses (or forbids) an asymmetric cap.
6. **Model mix by output tokens**, main loop and subagents separately — a permissive routing default silently becomes a top-tier default (one measured case: the top model took 61.9% of subagent output while the cheapest took 0.2%).
7. **Session-shape outliers** — the few longest sessions and their `turns × avg_ctx` product; the worst is often >1B tokens alone.
8. **Separate-billing-pool usage** — how much work went to a runtime billed outside the primary window (under-use is free capacity left on the table).

## Knob-conformance audit (the part that catches real bugs)

Verify the compaction/truncation knobs are set **coherently**, and ground every claim in the docs or in strings from the installed CLI binary — never in recollection:

- **Compose the effective threshold from all knobs at once.** A window-size var and a percentage-override var **multiply**; setting one can silently *activate* a dormant other. Real near-miss: a percentage override sat inert for months (compaction empirically fired at ~915k), and setting a window var would have activated it → a **4× tighter** cap than intended, also compacting the top ~10% of research lanes. **A knob sitting inert is not evidence it is harmless — check what activates it before setting a related one.**
- Reconcile the *documented* threshold against the *measured* peak-before-reset from metric 4. A gap means a knob isn't being honored — report it as UNVERIFIED rather than asserting the intended value.
- Confirm each var actually exists in the installed binary (`strings -a <cli binary> | grep -F <VAR>`); a plausible-but-nonexistent env var is worse than a documented gap. Report per item: **verified fact / inference / could-not-confirm.**
- Check whether automatic incremental compaction (stale-`tool_result` clearing) is present and whether it is configurable at all — if it prunes tool output first, that is an independent argument for persisting large outputs to files, since inline evidence gets replaced by a placeholder.
- Check the per-blast truncation knobs (bash/MCP output caps, tool-schema deferral) and whether compaction-steering instructions exist in the instructions files.

## Output contract — one dated report + one ledger row

Write into the **harness repo** (so it is versioned and diffable):

- `analytics/context-economy/<YYYY-MM-DD>.md` — the full report: the metric table, the knob-conformance audit with confidence per item, what changed since the previous run, and ranked recommendations.
- `analytics/context-economy/TRENDS.md` — **append one row per run** (never rewrite history): date · total context · turns · avg/median/p90 ctx · preamble size · tool-traffic share · compaction-peak median · subagent p90/max · model mix · a one-line "what we changed since last run". A knob change with no movement in the next row is a **failed intervention** — say so plainly rather than quietly re-tuning.

Both paths are generic; per-repo character (which surfaces dominate, which hot files, session shape) shows up in the *content*, not the path.

```js
export const meta = {
  name: 'harness-context-economy',
  description: 'Measure context/compaction economics from local transcripts, audit the knobs, append a trend row',
  phases: [{ title: 'Measure' }, { title: 'Audit' }, { title: 'Report' }],
}
const PIN = 'READ-ONLY. Write analysis scripts to a scratchpad and run them by path (multi-line -c reliably breaks). Persist big intermediate output to files; return only computed numbers. Never estimate a number you could compute — if a metric is uncomputable, say so.'

const METRICS = { type:'object', additionalProperties:false,
  required:['totals','per_turn','preamble','payload_composition','compaction','subagents','model_mix','outliers','method'], properties:{
  totals:{type:'object',additionalProperties:true}, per_turn:{type:'object',additionalProperties:true,description:'median/p90/max + share of context from turns >150k'},
  preamble:{type:'object',additionalProperties:true,description:'session-minimum floor + share of all context'},
  payload_composition:{type:'object',additionalProperties:true,description:'tool_result vs tool_use vs text'},
  compaction:{type:'object',additionalProperties:true,description:'reset-event count + peak-before-reset median/p90/max'},
  subagents:{type:'object',additionalProperties:true,description:'peak ctx median/p90/p99/max + count over the main cap'},
  model_mix:{type:'object',additionalProperties:true,description:'output-token share by model, main vs subagent'},
  outliers:{type:'array',items:{type:'string'}}, method:{type:'string',description:'exact scripts/commands so the next run is comparable'} }}

const KNOBS = { type:'object', additionalProperties:false, required:['findings','effective_threshold','conflicts'], properties:{
  findings:{type:'array',items:{type:'object',additionalProperties:false,required:['knob','set_to','exists_in_binary','semantics','confidence','evidence'],properties:{
    knob:{type:'string'}, set_to:{type:'string'}, exists_in_binary:{type:'boolean'},
    semantics:{type:'string'}, confidence:{enum:['verified','inferred','could-not-confirm']}, evidence:{type:'string',description:'doc URL or binary string — never recollection'} }}},
  effective_threshold:{type:'string',description:'COMPOSED from all knobs together (they may multiply), reconciled against the MEASURED peak-before-reset'},
  conflicts:{type:'array',items:{type:'string'},description:'knobs that multiply/activate each other, or documented-vs-measured mismatches'} }}

phase('Measure')
const m = await agent(`${PIN}\nCompute the context-economy metrics from local transcripts (see the metric list in the skill's Workflow E). Cover BOTH runtimes if present. Report the Pareto (share of context from the heaviest turns), the fixed preamble floor, payload composition, compaction peak-before-reset, subagent peak distribution, model mix, and the worst sessions by turns x avg_ctx.`,
  {label:'measure', phase:'Measure', schema:METRICS, model:'sonnet', agentType:'general-purpose'})

phase('Audit')
const k = await agent(`${PIN}\nAudit the context/compaction knobs. Read the live settings + env, then ground EVERY claim in official docs or in strings from the installed CLI binary — state which. COMPOSE the effective threshold from all knobs TOGETHER (a window var and a percentage var multiply; setting one can activate a dormant other), then reconcile it against the MEASURED peak-before-reset: ${JSON.stringify(m?.compaction ?? {})}. A mismatch means a knob is not honored — report UNVERIFIED, do not assert the intended value. Mark each finding verified / inferred / could-not-confirm; "could not confirm" is a better answer than a plausible wrong config key.`,
  {label:'audit', phase:'Audit', schema:KNOBS, model:'sonnet', agentType:'general-purpose'})

phase('Report')
const REPORT = { type:'object', additionalProperties:false, required:['report_markdown','trend_row','recommendations','failed_interventions'], properties:{
  report_markdown:{type:'string',description:'full dated report body'},
  trend_row:{type:'string',description:'ONE markdown table row for TRENDS.md'},
  recommendations:{type:'array',items:{type:'object',additionalProperties:false,required:['rank','change','surface','expected_effect','risk'],properties:{
    rank:{type:'number'}, change:{type:'string'}, surface:{enum:['settings','instructions-file','hook','skill','workflow-habit','plugin/mcp-roster']},
    expected_effect:{type:'string',description:'which measured number should move, and by how much'}, risk:{type:'string'} }}},
  failed_interventions:{type:'array',items:{type:'string'},description:'changes made last run whose target metric did NOT move — name them plainly'} }}
return await agent(`Write the dated context-economy report + ONE TRENDS.md row. Read the PREVIOUS report and TRENDS.md from the harness repo's analytics/context-economy/ first and diff against them — the trend is the product, not the snapshot. Every recommendation must name the specific measured number it should move and by roughly how much, so the NEXT run can falsify it. Call out any prior change whose target metric did not move as a FAILED intervention rather than silently re-tuning. Order by leverage: the fixed preamble and turn-count multipliers beat per-response savings. METRICS: ${JSON.stringify(m)} KNOBS: ${JSON.stringify(k)}`,
  {label:'report', phase:'Report', effort:'high', schema:REPORT, model:'opus', agentType:'general-purpose'})
```

**The load-bearing choices to keep when you adapt it:** measurement in a subagent (never inline); the composed effective threshold reconciled against measured behavior (the multiply trap); `verified / inferred / could-not-confirm` on every knob claim; the append-only trend ledger; and `expected_effect` naming a falsifiable number so the next run can grade the last one. Its output feeds step 2's reconcile and lands in step 4 as settings/instructions/hook changes.
