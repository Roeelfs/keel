# Workflow G — vendor-surface adoption + interaction quality (every run)

Fires **every time**. A asks "what did we learn?", B asks "what did the vendor ship?", E asks "what does it cost?" — G asks **"which surfaces the vendor already gives us are we not using, and are the ones we adopted actually working?"**

The two halves are one lane on purpose. A surface census with no grading produces a wishlist that never gets checked; grading with no census only ever re-examines what someone already thought of.

**Why it is standing, not conditional.** Measured 2026-08-09 on one real harness: the operator's single loudest complaint — replies too long, hard to follow up — had a **vendor-shipped surface sitting entirely unused**. `~/.claude/output-styles/` did not exist and `outputStyle` had zero hits in `settings.json`, while the same rule had been written into `CLAUDE.md` twice, reversed once, and duplicated across four instruction files. B would not have caught it: nothing had *shipped*; the surface had been there all along. The gap this lane closes is **available-but-unadopted**, which no other lane looks for.

## Part 1 — surface census (what exists that we are not using)

Enumerate the vendor's configurable surfaces and mark each **adopted / unadopted / deliberately-skipped**. Ground every entry in the installed binary or live docs, never recollection:

- Output styles, `settings.json` keys, hook events and their output contracts, agent/skill/plugin frontmatter keys, statusline, keybindings, permission modes, model/effort selectors, MCP and tool-deferral controls, and any surface the docs list that the harness does not touch.
- **Probe the REAL binary, never the launcher shim.** `readlink -f $(which claude)` may resolve to a wrapper where every probe returns 0 hits and reads as "the feature does not exist."
- **Every probe carries a sanity control AND a false-positive control.** A known-present string proves the probe works; a suspicious hit gets its surrounding context read before it is called a config key. Measured 2026-08-09: `responseLength` (6 hits) is a React spinner ref and `maxOutputTokens` (14) is internal token accounting — either would have shipped as a plausible-but-nonexistent brevity knob.
- For each unadopted surface, state **what problem it would solve here**, or drop it. A census of everything is noise; the product is the short list where an unadopted surface maps onto a known, recorded complaint.
- Read the previous run's `SKIP_OR_WATCH` first. A surface already refuted stays refuted unless the vendor changed it.

## Part 2 — grade the adoptions (including the interaction-quality ledger)

Every adoption from a prior run gets its recorded probe re-run and a verdict. An adoption whose target metric did not move is a **failed intervention**, named plainly — the same discipline as E, applied to behavior instead of cost.

**The standing metric is reply shape**, from `~/.claude/analytics/reply-shape.jsonl` (the log-only `Stop` hook) against the transcript baseline:

| Measure | Baseline 2026-08-09 |
|---|---|
| final-turn chars — median / p90 | 2,270 / 3,389 |
| share >2,000 chars | 61.0% |
| share with ≥3 markdown headers | 26.4% |
| share posing ≥3 questions | 3.8% |

The gap between the last two rows is the finding that shaped the fix: turns end **multi-topic with no question** — unanswerable by construction — so *volume* and *followability* are separate defects with separate numbers. Grade both. If the header share falls while the question share stays flat, the intervention shortened replies without making them answerable, which is the failure the 2026-08-01 reversal already made once.

**Prefer the hook log over transcript parsing.** `last_assistant_message` on `Stop` is the vendor's own payload; transcripts lag, and an assistant message carrying both a thinking block and a text block has been observed losing the text block entirely. Use transcripts only for the historical baseline, where the bias applies equally on both sides of the comparison.

**Report the dispatched-vs-surviving count for the log itself.** An empty `reply-shape.jsonl` means the hook never fired — a dead instrument, not a quiet harness. Say which.

## Part 3 — rank by tier, not by appeal

Every recommendation carries a **tier**, and the tiers are ordered by how little they depend on model compliance:

1. **mechanism** — code that runs regardless: a hook, a ratchet, a script, a settings key. Graded by its own output.
2. **mechanism-carrying-prose** — prose injected at a stronger tier than an instructions file. An output style *modifies the system prompt* and re-asserts during the conversation; `CLAUDE.md` is *a user message after the system prompt* and does neither. The text is still prose; the injection point is not.
3. **subtraction** — deleting instruction text the vendor has made redundant. Graded by diff, costs no context, and pays the instructions-file ratchet. Vendors publish these: the installed binary's own release notes name behaviors that are now default and tell you to delete the instructions for them.
4. **prose** — a new or reworded rule in an instructions file. Listed last, always, and never proposed alone for a defect that already has a prose rule.

**A prose rule that has been applied and reversed does not get re-worded — it gets re-tiered.** If the recorded history of a defect is "we wrote a rule, it drifted, we wrote it better", the next move is a tier change or an instrument, not a third wording. Measured: one such rule missed its metric three consecutive cycles while byte ratchets and `PreToolUse` hooks held.

**Instrument before legislating.** A recommendation whose effect cannot be read off an existing log ships its measurement first, log-only, and the behavioral change waits for the next run. This costs one cycle and is the reason the previous three attempts at this defect were ungradeable. A log-only instrument is `mechanism` tier and always exits 0.

## Output contract — one dated report + one ledger row

Write into the **harness repo**:

- `analytics/harness-adoption/<YYYY-MM-DD>.md` — the surface census with adoption state and probe per row, the adoption grades, the interaction-quality table, and tier-ranked recommendations.
- `analytics/harness-adoption/TRENDS.md` — **append one row per run** (never rewrite history): date · surfaces adopted / unadopted / skipped · reply-shape median chars · ≥3-header share · ≥3-question share · ends-on-action share · adoptions graded pass/fail · a one-line "what we changed since last run".

```js
export const meta = {
  name: 'harness-adoption',
  description: 'Census unadopted vendor surfaces, grade prior adoptions against their probes, rank fixes by tier',
  phases: [{ title: 'Census' }, { title: 'Grade' }, { title: 'Report' }],
}
const PIN = 'You are a leaf agent: do NOT spawn sub-agents or Workflows; do the work inline and return. Investigation only — design the plan, do not mutate. WebFetch / read-only gh / local reads only. No CI polling, no sleep loops. Write analysis scripts to a scratchpad and run them by path (multi-line -c reliably breaks). Every absence claim prints the command that produced it.'

const CENSUS = { type:'object', additionalProperties:false, required:['surfaces','probe_method','dropped'], properties:{
  surfaces:{type:'array',items:{type:'object',additionalProperties:false,required:['surface','state','probe','evidence','solves'],properties:{
    surface:{type:'string'}, state:{enum:['adopted','unadopted','deliberately-skipped']},
    probe:{type:'string',description:'exact command run, so the next run re-derives this row instead of re-deriving the whole census'},
    evidence:{type:'string',description:'doc URL or binary string with its sanity control — never recollection'},
    solves:{type:'string',description:'the RECORDED complaint or measured defect this would address, or "none" — "none" rows are dropped'} }}},
  probe_method:{type:'string',description:'binary path actually probed (resolved, not the shim) + the sanity-control string and its hit count'},
  dropped:{type:'array',items:{type:'string'},description:'surfaces examined and dropped, with why — no silent caps'} }}

const GRADE = { type:'object', additionalProperties:false, required:['adoptions','reply_shape','instrument_health'], properties:{
  adoptions:{type:'array',items:{type:'object',additionalProperties:false,required:['change','shipped_on','probe','verdict','evidence'],properties:{
    change:{type:'string'}, shipped_on:{type:'string'}, probe:{type:'string'},
    verdict:{enum:['held','drifted','failed-intervention','too-early','instrument-dead']}, evidence:{type:'string'} }}},
  reply_shape:{type:'object',additionalProperties:true,description:'median/p90 chars, >2000 share, >=3-header share, >=3-question share, ends-on-action share, n'},
  instrument_health:{type:'string',description:'rows in reply-shape.jsonl and the window they cover; an empty log is a DEAD INSTRUMENT, not a quiet harness — say which'} }}

phase('Census')
const c = await agent(`${PIN}\nCensus the vendor surfaces this harness could use and does not. Resolve the REAL CLI binary first (readlink -f the shim) and sanity-control every strings probe with a string you know is present; read the surrounding context of any suspicious hit before calling it a config key. Read the previous run's program SKIP_OR_WATCH before starting. Drop any surface that maps to no recorded complaint — the product is the short list, not the catalogue.`,
  {label:'census', phase:'Census', schema:CENSUS, model:'sonnet', agentType:'general-purpose'})

phase('Grade')
const g = await agent(`${PIN}\nGrade every adoption from prior runs by RE-RUNNING its recorded probe, and compute reply-shape metrics from ~/.claude/analytics/reply-shape.jsonl (fall back to transcript final turns for the historical baseline only). Baseline 2026-08-09: median 2,270 chars, p90 3,389, 61.0% >2,000, 26.4% with >=3 headers, 3.8% with >=3 questions. Grade VOLUME and FOLLOWABILITY separately — a header share that falls while the question share stays flat means replies got shorter without getting answerable, which is a failed intervention, not a win. An empty log means the hook never fired: report instrument-dead rather than a clean harness.`,
  {label:'grade', phase:'Grade', schema:GRADE, model:'sonnet', agentType:'general-purpose'})

phase('Report')
const REPORT = { type:'object', additionalProperties:false, required:['report_markdown','trend_row','recommendations','failed_interventions'], properties:{
  report_markdown:{type:'string'}, trend_row:{type:'string',description:'ONE markdown table row for TRENDS.md'},
  recommendations:{type:'array',items:{type:'object',additionalProperties:false,required:['rank','tier','change','surface','metric','risk'],properties:{
    rank:{type:'number'}, tier:{enum:['mechanism','mechanism-carrying-prose','subtraction','prose']},
    change:{type:'string'}, surface:{type:'string',description:'exact file or settings key that changes'},
    metric:{type:'string',description:'the falsifiable number this should move, and by how much, so the NEXT run can kill it'},
    risk:{type:'string'} }}},
  failed_interventions:{type:'array',items:{type:'string'},description:'prior adoptions whose target metric did not move — name them plainly, do not silently re-tune'} }}
return await agent(`Write the dated adoption report + ONE TRENDS.md row. Read the previous report and TRENDS.md from the harness repo's analytics/harness-adoption/ and diff against them — the trend is the product. Rank recommendations by TIER (mechanism > mechanism-carrying-prose > subtraction > prose), never by appeal. A defect that ALREADY has a prose rule may not receive another prose rule: propose a tier change or an instrument. Phrase every instruction positively — the vendor's own guidance is that positive examples of the wanted behavior beat instructions about what not to do. If a recommendation's effect cannot be read off an existing log, its first step is a log-only instrument and the behavior change waits a cycle. CENSUS: ${JSON.stringify(c)} GRADES: ${JSON.stringify(g)}`,
  {label:'report', phase:'Report', effort:'high', schema:REPORT, model:'opus', agentType:'general-purpose'})
```

**The load-bearing choices to keep when you adapt it:** the census asking *what is available and unused* rather than *what shipped* (that is B's job); the resolved-binary probe with both a sanity control and a false-positive control; `solves` forcing every surface row to name a recorded complaint; grading volume and followability as separate numbers; the tier enum ordering recommendations by independence from model compliance; and `metric` naming a falsifiable number so the next run can kill the recommendation instead of re-tuning it. Its output feeds step 2's reconcile and lands in step 4 as settings/style/hook/instructions changes.
