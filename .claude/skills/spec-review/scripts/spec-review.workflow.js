export const meta = {
  name: 'spec-review',
  description: 'Spec review agent stages, one per call (args.stage): prepare (Claude miner fallback) -> review -> review2 -> critics -> merge -> falsify -> report. Pure agent work: every command, file check and plan is a Bash gate (scripts/stage.py) the main loop runs between stages. Returns labels only.',
  whenToUse: 'Launched by the spec-review skill; never call directly with a missing stage.',
  phases: [
    { title: 'Prepare', detail: 'Claude miners, only for a Codex miner that died or failed validation' },
    { title: 'Review', detail: 'Claude lanes in parallel, then drift investigators and coverage repair' },
    { title: 'Synthesize', detail: 'substitute critics, extractor fallback, merger, falsifier wave, report' },
  ],
}

// ---------------------------------------------------------------------------
// args + validation. The Bash gates (stage.py) print the exact args of each stage.
// ---------------------------------------------------------------------------
const A = typeof args === 'string' ? (() => { try { return JSON.parse(args) } catch { return {} } })() : (args || {})
const need = (k) => { if (A[k] === undefined || A[k] === null || A[k] === '') throw new Error(`spec-review: args.${k} is required`); return A[k] }
const STAGE = need('stage')
const STAGES = ['prepare', 'review', 'review2', 'critics', 'merge', 'falsify', 'report']
if (!STAGES.includes(STAGE)) throw new Error(`spec-review: unknown stage ${STAGE}`)
const RUN = need('runDir')
if (!RUN.startsWith('/')) throw new Error('spec-review: args.runDir must be an absolute path')
const SKILL = need('skillDir')
const SPEC = need('spec')

const ENVELOPE = {
  type: 'object',
  properties: {
    lane: { type: 'string' },
    verdict: { type: 'string' },
    answered_questions: { type: 'array', items: { type: 'string' } },
    findings: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, severity: { type: 'string', enum: ['CRITICAL', 'MAJOR', 'MINOR', 'ELEVATE', 'CAUTION'] }, title: { type: 'string' }, cites: { type: 'array', items: { type: 'string' } } }, required: ['id', 'severity', 'title'] } },
    founder_approval_needed: { type: 'boolean' },
    founder_approval_marker_present: { type: 'boolean' },
    register_found: { type: 'boolean' },
    sources_read: { type: 'array', items: { type: 'string' } },
    class_counts: { type: 'object' },
    legal_commitment_breach: { type: 'boolean' },
    research_handoffs: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, question: { type: 'string' } }, required: ['id', 'question'] } },
    drift_investigations: { type: 'array', items: { type: 'object', properties: { drift_id: { type: 'string' }, narrow_question: { type: 'string' } }, required: ['drift_id', 'narrow_question'] } },
  },
  required: ['lane', 'answered_questions', 'findings'],
}
const FALSIFIER_ITEM = {
  type: 'object',
  properties: { id: { type: 'string' }, verdict: { type: 'string', enum: ['REFUTED', 'SURVIVES', 'SURVIVES-BUT-FIX-REJECTED', 'NEEDS-LIVE-EVIDENCE'] }, evidence: { type: 'string' } },
  required: ['id', 'verdict', 'evidence'],
}
const FALSIFIER_BATCH = { type: 'object', properties: { verdicts: { type: 'array', items: FALSIFIER_ITEM } }, required: ['verdicts'] }
const MINER = { type: 'object', properties: { ok: { type: 'boolean' }, questions: { type: 'number' } }, required: ['ok'] }
const MERGED = { type: 'object', properties: { units: { type: 'number' } }, required: ['units'] }
const SYNTH = { type: 'object', properties: { report_path: { type: 'string' } }, required: ['report_path'] }

const gateLog = []
const note = (s) => { gateLog.push(s); log(s) }
const labelsOf = (arr) => (arr || []).map((e) => e.label)

function laneAgent(e, phaseName) {
  const opts = { label: e.label, phase: phaseName || 'Review', agentType: e.agentType, schema: ENVELOPE }
  if (e.model) opts.model = e.model
  return opts
}
const laneBrief = (file, extra) =>
  `Your complete, already-filled brief is the file ${file}. Read it now and follow it exactly, including its "Run contract": write your findings file and your envelope file first, then reply with the same envelope via StructuredOutput. Do not read other lanes' files.${extra || ''}`

// ---------------------------------------------------------------------------
// prepare: a Claude miner runs ONLY when its Codex miner was DEAD / BLOCKED-ON-QUOTA / invalid
// ---------------------------------------------------------------------------
async function prepare() {
  phase('Prepare')
  const fb = need('fallback')
  const jobs = []
  if (fb.includes('context-dossier-miner')) jobs.push(['context-dossier-miner', 'opus'])
  if (fb.includes('design-decisions-extractor')) jobs.push(['design-decisions-extractor', 'haiku'])
  const done = await parallel(jobs.map(([label, model]) => () => agent(`ROLE: ${label}\n${laneBrief(RUN + '/prompts/' + label + '.md')}`,
    { label, phase: 'Prepare', agentType: 'general-purpose', model, schema: MINER })))
  jobs.forEach(([label], i) => {
    if (done[i]) return
    if (label === 'context-dossier-miner') throw new Error('spec-review: the context dossier miner died; no dossier, no review')
    note('design-decisions extractor died: reviewers lose the decisions cross-check (non-blocking)')
  })
  return { stage: 'prepare', runDir: RUN, ran: jobs.map((j) => j[0]), gateLog }
}

// ---------------------------------------------------------------------------
// review (Claude lanes) and review2 (drift investigators + coverage repair)
// ---------------------------------------------------------------------------
async function review() {
  phase('Review')
  const lanes = need('lanes')
  const results = await parallel(lanes.map((e) => () => agent(`ROLE: ${e.label}\n${laneBrief(RUN + '/prompts/' + e.label + '.md')}`, laneAgent(e))))
  lanes.forEach((e, i) => { if (!results[i]) note(`${e.label}: FAILED (no result returned)`) })
  return { stage: 'review', runDir: RUN, returned: lanes.filter((e, i) => results[i]).map((e) => e.label), gateLog }
}

async function review2() {
  phase('Review')
  const briefs = A.briefs || []
  const repair = A.repair || []
  const inv = await parallel(briefs.map((b) => () => agent(`ROLE: spec-drift-investigator\n${laneBrief(RUN + '/prompts/' + b.label + '.md')}`,
    { label: b.label, phase: 'Review', agentType: 'general-purpose', model: 'opus', schema: ENVELOPE })))
  briefs.forEach((b, i) => { if (!inv[i]) note(`${b.label}: FAILED (no result returned)`) })
  await parallel(repair.map((e) => () => agent(
    `ROLE: ${e.label}\nYour earlier output ${RUN}/lanes/${e.label}.md did not answer these assigned questions: ${e.questions.join(', ')}. Read your brief ${RUN}/prompts/${e.label}.md (the question texts are in its Run contract), answer exactly those questions by appending to your findings file, then rewrite ${RUN}/envelopes/${e.label}.json with answered_questions and findings updated, and reply with it via StructuredOutput.`,
    laneAgent(e))))
  return { stage: 'review2', runDir: RUN, drift: briefs.map((b) => b.label), repaired: repair.map((e) => e.label), gateLog }
}

// ---------------------------------------------------------------------------
// synthesize stages
// ---------------------------------------------------------------------------
async function critics() {
  phase('Synthesize')
  const cr = A.critics || []
  const ex = A.extractors || []
  const jobs = [
    ...cr.map((e) => () => agent(`ROLE: ${e.label}\n${laneBrief(RUN + '/prompts/' + e.label + '.md')}`, laneAgent(e, 'Synthesize'))),
    // Fallback only: the Codex (luna) extraction of this lane's prose failed validation. Same prompt, run by a Claude lane.
    ...ex.map((e) => () => agent(
      `ROLE: codex-envelope-extractor\nYour complete brief is the file ${e.promptPath}; read it and follow it, with ONE change: ALSO write the envelope object to ${RUN}/envelopes/${e.label}.json (the file is the deliverable the pipeline checks) and reply with it via StructuredOutput.`,
      { label: e.label + ':extract', phase: 'Synthesize', agentType: 'general-purpose', model: 'sonnet', schema: ENVELOPE })),
  ]
  const got = await parallel(jobs)
  const labels = [...cr.map((e) => e.label), ...ex.map((e) => e.label)]
  labels.forEach((l, i) => { if (!got[i]) note(`${l}: FAILED (critic/extractor returned nothing)`) })
  return { stage: 'critics', runDir: RUN, gateLog }
}

async function merge() {
  phase('Synthesize')
  const ok = need('ok')
  const total = A.totalIds || 0
  const repair = (A.repairErrors && A.repairErrors.length) ? `\nYOUR PREVIOUS merged.raw.json FAILED VALIDATION, fix exactly these: ${A.repairErrors.join('; ')}` : ''
  const prompt = [
    'ROLE: finding-merger',
    `Cluster the ${total} CRITICAL/MAJOR findings listed in ${A.indexPath || RUN + '/merge-index.txt'} (one line per id: id, lane, severity, title; Read it) into units, one unit per distinct underlying defect. Findings from different lanes that describe the same mechanism, boundary or missing guarantee belong together even when worded differently; findings that merely touch the same file but describe different defects stay apart. A single-member unit is fine.`,
    `Read the full findings where a title is ambiguous: Claude lanes in ${RUN}/lanes/<lane>.md, Codex lanes in ${RUN}/codex/<lane>.out.md (find each by its id). Do not judge whether a finding is true; that is the falsifiers' job.`,
    `Write ${RUN}/merged.raw.json: a JSON list of {"title": "<one line naming the defect>", "seam": "<the component/file/contract it lives in>", "members": [<original ids>], "cites": ["<path:line>", ...]}. EVERY id in that file must appear in exactly one unit's members.`,
    `Then validate it yourself with Bash: python3 ${SKILL}/scripts/run_dir.py merge-check --run ${RUN} --lanes ${ok.join(',')} ; if it prints ok:false, fix merged.raw.json as its errors say and rerun until ok:true. Reply via StructuredOutput with the number of units.`,
    'You are a leaf agent: spawn no sub-agents or Workflows.',
  ].join('\n') + repair
  const r = await agent(prompt, { label: A.repairErrors && A.repairErrors.length ? 'finding-merger:repair' : 'finding-merger', phase: 'Synthesize', agentType: 'general-purpose', model: 'sonnet', schema: MERGED })
  if (!r) throw new Error('spec-review: the finding merger returned nothing')
  return { stage: 'merge', runDir: RUN, units: r.units, gateLog }
}

async function falsify() {
  phase('Synthesize')
  const batches = need('batches')
  await parallel(batches.map((b) => () => agent(`ROLE: finding-falsifier\n${laneBrief(b.prompt)}`,
    { label: `falsify:batch-${b.batch}`, phase: 'Synthesize', agentType: 'general-purpose', model: 'sonnet', schema: FALSIFIER_BATCH })))
  return { stage: 'falsify', runDir: RUN, batches: batches.map((b) => b.batch), gateLog }
}

async function report() {
  phase('Synthesize')
  const brief = need('briefPath')
  const repair = (A.repairErrors && A.repairErrors.length)
    ? `\nYour report ${RUN}/report.md failed the mechanical check. Read it and the brief, fix ONLY what these errors name, and rewrite ${RUN}/report.md.\nERRORS:\n${A.repairErrors.join('\n')}`
    : ''
  const w = await agent(`ROLE: synthesis-writer\nYour complete brief is the file ${brief}. Read it now and follow every rule in it; spec ${SPEC}.${repair}`,
    { label: repair ? 'synthesis-writer:repair' : 'synthesis-writer', phase: 'Synthesize', agentType: 'general-purpose', model: 'opus', schema: SYNTH })
  if (!w) throw new Error('spec-review: synthesis writer returned nothing')
  return { stage: 'report', runDir: RUN, reportPath: RUN + '/report.md', gateLog }
}

const RUNNERS = { prepare, review, review2, critics, merge, falsify, report }
return await RUNNERS[STAGE]()
