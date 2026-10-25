export const meta = {
  name: 'spec-review',
  description: 'Spec review pipeline, one stage per call (args.stage): prepare (miners + filled prompts) -> review (Claude lanes) -> synthesize (Codex envelopes, falsifier wave, report.md). Returns paths + counts + gate log only.',
  whenToUse: 'Launched by the spec-review skill; never call directly with a missing stage.',
  phases: [
    { title: 'Prepare', detail: 'init run dir, dossier + decisions miners, filled lane prompts' },
    { title: 'Review', detail: 'Claude lanes in parallel, drift second wave, question coverage' },
    { title: 'Synthesize', detail: 'Codex envelopes, falsifier wave on every CRITICAL/MAJOR, report.md' },
  ],
}

// ---------------------------------------------------------------------------
// args + validation. Everything the stages need arrives here from the main loop.
// ---------------------------------------------------------------------------
const A = typeof args === 'string' ? (() => { try { return JSON.parse(args) } catch { return {} } })() : (args || {})
const need = (k) => { if (A[k] === undefined || A[k] === null || A[k] === '') throw new Error(`spec-review: args.${k} is required`); return A[k] }
const STAGE = need('stage')
if (!['prepare', 'review', 'synthesize'].includes(STAGE)) throw new Error(`spec-review: unknown stage ${STAGE}`)
const RUN = need('runDir')
if (!RUN.startsWith('/')) throw new Error('spec-review: args.runDir must be an absolute path')
const SKILL = need('skillDir')
const SPEC = need('spec')
const WIRING_TYPE = A.wiringAgentType || 'general-purpose'

const sq = (s) => `'${String(s).replace(/'/g, `'\\''`)}'`
const PYOUT = { type: 'object', properties: { exit_code: { type: 'number' }, stdout: { type: 'string' } }, required: ['exit_code', 'stdout'] }
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

const gateLog = []
const note = (s) => { gateLog.push(s); log(s) }

// EXTRACT:BEGIN
function lastJsonObject(text) {
  const lines = String(text || '').split('\n').map((l) => l.trim()).filter(Boolean)
  for (let i = lines.length - 1; i >= 0; i--) {
    if (!lines[i].startsWith('{')) continue
    try { const j = JSON.parse(lines[i]); if (j && typeof j === 'object' && !Array.isArray(j)) return j } catch (e) { /* keep scanning upward */ }
  }
  return null
}
// Checksum over UTF-16 code units; text_sum in run_dir.py computes the same number.
function textSum(text) {
  let h = 0
  for (let i = 0; i < text.length; i++) h = (Math.imul(h, 31) + text.charCodeAt(i)) >>> 0
  return h
}
// EXTRACT:END

// Run one run_dir.py subcommand through a script-runner and parse its JSON. The relayed stdout
// can be mangled by a cheap model, so parse the LAST JSON-object line, retry once on sonnet, then throw.
// soft=true returns the parsed object even when ok is false (the caller decides).
async function py(phaseName, sub, flags, soft, models) {
  const cmd = `python3 ${sq(SKILL + '/scripts/run_dir.py')} ${sub} --run ${sq(RUN)} ${flags || ''}`
  let j = null
  let last = ''
  for (const model of models || ['haiku', 'sonnet']) {
    const r = await agent(
      `ROLE: script-runner\nRun exactly this one command with the Bash tool and do nothing else. Put the command's stdout in the stdout field BYTE FOR BYTE (it is JSON on one line: never summarize, reinterpret, shorten or replace it with a field from it) and its exit code in exit_code.\n\n${cmd}`,
      { label: `py:${sub}`, phase: phaseName, model, schema: PYOUT })
    last = r ? String(r.stdout).slice(0, 300) : '(no result)'
    j = r ? lastJsonObject(r.stdout) : null
    if (j) break
  }
  if (!j) throw new Error(`spec-review: '${sub}' printed no JSON object after a sonnet retry: ${last}`)
  if (!j.ok && !soft) throw new Error(`spec-review: '${sub}' failed: ${(j.errors || []).join('; ') || JSON.stringify(j).slice(0, 300)}`)
  return j
}

// The workflow, not the agent, writes the envelope file: an agent can return a valid envelope
// through StructuredOutput and still skip its own file write. run_dir.py refuses a JSON that
// does not match the checksum, so a failed write leaves no file and check-envelopes reports it.
async function putEnvelope(phaseName, label, env) {
  const text = JSON.stringify(env)
  const flags = `--lane ${sq(label)} --sum ${textSum(text)} --json ${sq(text)}`
  let why = ''
  for (const model of ['haiku', 'sonnet']) {
    try {
      const r = await py(phaseName, 'put-envelope', flags, true, [model])
      if (r.ok) return
      why = (r.errors || []).join('; ')
    } catch (e) { why = String(e.message || e) }
  }
  note(`${label}: envelope NOT written: ${why}`)
}

// The lane plan (tier, profile, gates, lanes, budget, reasons) is resolved ONCE by `run_dir.py plan`
// from lanes.json + the optional per-repo override, and validated there; this script only reads it.
// The relayed copy is checksum-verified, because a cheap relay model can mangle a long line.
async function loadPlan() {
  let last = ''
  for (const model of ['haiku', 'sonnet']) {
    const j = await py('Prepare', 'show-plan', '', true, [model])
    if (j.ok && typeof j.planText === 'string' && textSum(j.planText) === j.sum) return JSON.parse(j.planText)
    last = (j.errors || []).join('; ') || 'checksum mismatch on the relayed plan'
  }
  throw new Error(`spec-review: cannot read ${RUN}/plan.json (run \`run_dir.py plan\` first): ${last}`)
}
const P = await loadPlan()
const PROFILE = P.profile
const GATES = P.gates
const PLAN = { run: P.run.map((e) => (e.label === 'runtime-wiring' ? { ...e, agentType: WIRING_TYPE } : e)), skipped: P.skipped }
const labelsOf = (arr) => arr.map((e) => e.label)
// Hard-stop wording, keyed by run_dir.py's hardStopReasons. An unknown reason is a gate-lane defect.
const HARD = {
  adr: 'the adr-auditor found the spec changes an Accepted ADR/invariant with no founder-approval marker',
  legal: 'the legal-auditor found the spec breaches an in-force legal commitment with no founder-approval marker',
}
const hardText = (sum) => (sum.hardStopReasons || []).map((r) => HARD[r] || `gate lane defect (${r}): relaunch that lane, its verdict is not usable`).join('; ')
const PLANNED = sq(labelsOf(PLAN.run).join(','))
if (!labelsOf(PLAN.run).includes('codex-frontier')) throw new Error('spec-review: the Astra frontier lane is non-droppable in every profile')

function laneAgent(e) {
  const opts = { label: e.label, phase: 'Review', agentType: e.agentType, schema: ENVELOPE }
  if (e.model) opts.model = e.model
  return opts
}
const laneBrief = (file, extra) =>
  `Your complete, already-filled brief is the file ${file}. Read it now and follow it exactly, including its "Run contract": write your findings file and your envelope file first, then reply with the same envelope via StructuredOutput. Do not read other lanes' files.${extra || ''}`

// ---------------------------------------------------------------------------
// stage 1: prepare
// ---------------------------------------------------------------------------
async function prepare() {
  phase('Prepare')
  for (const k of ['root', 'sid', 'contextBlock']) need(k)
  const initPrompt = [
    'ROLE: script-runner',
    'Do these three things in order with the Bash and Write tools and nothing else.',
    `1. Bash: mkdir -p ${sq(RUN + '/inputs')}`,
    `2. Write the text between the markers EXACTLY, byte for byte, to ${RUN}/inputs/context.md, and the JSON between its markers EXACTLY to ${RUN}/inputs/gates.json.`,
    '<<<CONTEXT',
    A.contextBlock,
    'CONTEXT>>>',
    '<<<GATES',
    JSON.stringify(GATES),
    'GATES>>>',
    `3. Bash: python3 ${sq(SKILL + '/scripts/run_dir.py')} init --run ${sq(RUN)} --spec ${sq(SPEC)} --root ${sq(A.root)} --sid ${sq(A.sid)} --runtime ${sq(A.runtime || 'claude')} --skill-dir ${sq(SKILL)}`,
    'Return the command exit code and its complete stdout, unmodified, via StructuredOutput.',
  ].join('\n')
  const r = await agent(initPrompt, { label: 'py:init', phase: 'Prepare', model: 'haiku', schema: PYOUT })
  if (!r) throw new Error('spec-review: init agent returned nothing')
  const init = lastJsonObject(r.stdout)
  if (!init) throw new Error(`spec-review: init printed no JSON object: ${String(r.stdout).slice(0, 300)}`)
  if (!init.ok) throw new Error(`spec-review: init failed: ${(init.errors || []).join('; ')}`)
  note(`decisions mining: ${init.decisionsNote}`)
  note(`lane plan: tier ${P.tier}, ${P.planned} lanes (${P.plannedCodex} Codex) from ${P.files.join(' + ')}${P.overBudget.length ? '; over budget (advisory): ' + P.overBudget.join('; ') : ''}`)

  const MINER = { type: 'object', properties: { ok: { type: 'boolean' }, questions: { type: 'number' } }, required: ['ok'] }
  const minerJobs = [() => agent(`ROLE: context-dossier-miner\n${laneBrief(RUN + '/prompts/context-dossier-miner.md')}`,
    { label: 'context-dossier-miner', phase: 'Prepare', agentType: 'general-purpose', model: 'opus', schema: MINER })]
  if (init.decisions) {
    minerJobs.push(() => agent(`ROLE: design-decisions-extractor\n${laneBrief(RUN + '/prompts/design-decisions-extractor.md')}`,
      { label: 'design-decisions-extractor', phase: 'Prepare', agentType: 'general-purpose', model: 'haiku', schema: MINER }))
  }
  const mined = await parallel(minerJobs)
  if (!mined[0]) throw new Error('spec-review: the context dossier miner died; no dossier, no review')
  if (init.decisions && !mined[1]) note('design-decisions extractor died: reviewers lose the decisions cross-check (non-blocking)')

  const lanes = await py('Prepare', 'lanes', `--spec ${sq(SPEC)} --lanes ${sq(labelsOf(PLAN.run).join(','))}`)
  PLAN.skipped.forEach((s) => note(`${s.label}: SKIPPED (gate: ${s.reason.replace(/^gate: /, '')})`))
  return {
    stage: 'prepare', runDir: RUN,
    paths: { dossier: RUN + '/dossier.md', questions: RUN + '/questions.json', decisions: init.decisions ? RUN + '/decisions.json' : null, prompts: RUN + '/prompts', codexPlan: RUN + '/codex/plan.tsv' },
    claudeLanes: lanes.claude, codexLanes: lanes.codex,
    codexCommand: `bash ${SKILL}/scripts/run-codex-lanes.sh ${RUN} ${PROFILE}`,
    skipped: PLAN.skipped, gateLog,
  }
}

// ---------------------------------------------------------------------------
// stage 2: review (Claude lanes)
// ---------------------------------------------------------------------------
async function review() {
  phase('Review')
  const claude = PLAN.run.filter((e) => e.kind !== 'codex')
  const results = await parallel(claude.map((e) => () => agent(`ROLE: ${e.label}\n${laneBrief(RUN + '/prompts/' + e.label + '.md')}`, laneAgent(e))))
  const returned = {}
  claude.forEach((e, i) => { returned[e.label] = results[i] })
  claude.filter((e) => !returned[e.label]).forEach((e) => note(`${e.label}: FAILED (no result returned)`))

  // Second wave: drift investigators, only when the scout asked for them.
  const scout = returned['spec-drift-scout']
  if (scout && Array.isArray(scout.drift_investigations) && scout.drift_investigations.length) {
    const d = await py('Review', 'drift-briefs', `--spec ${sq(SPEC)}`)
    if (d.dropped) note(`drift investigators: ${d.dropped} candidate(s) beyond the cap of 5 were not investigated (user decision needed)`)
    const inv = await parallel(d.briefs.map((label) => () => agent(`ROLE: spec-drift-investigator\n${laneBrief(RUN + '/prompts/' + label + '.md')}`,
      { label, phase: 'Review', agentType: 'general-purpose', model: 'opus', schema: ENVELOPE })))
    d.briefs.forEach((label, i) => { if (!inv[i]) note(`${label}: FAILED (no result returned)`) })
  }

  // Coverage: every assigned Q-id answered; one repair pass, then fail.
  const present = labelsOf(claude).filter((l) => returned[l])
  let chk = await py('Review', 'check-envelopes', `--lanes ${sq(present.join(','))} --codex ''`, true)
  const bad = Object.keys(chk.unanswered || {})
  if (bad.length || (chk.invalid || []).length) {
    note(`coverage repair pass for: ${bad.join(', ') || 'invalid envelopes'}`)
    const byLabel = Object.fromEntries(claude.map((e) => [e.label, e]))
    await parallel(bad.map((l) => () => agent(
      `ROLE: ${l}\nYour earlier output ${RUN}/lanes/${l}.md did not answer these assigned questions: ${chk.unanswered[l].join(', ')}. Read your brief ${RUN}/prompts/${l}.md (the question texts are in its Run contract), answer exactly those questions by appending to your findings file, then rewrite ${RUN}/envelopes/${l}.json with answered_questions and findings updated, and reply with it via StructuredOutput.`,
      laneAgent(byLabel[l]))))
    chk = await py('Review', 'check-envelopes', `--lanes ${sq(present.join(','))} --codex ''`, true)
    if (!chk.ok) throw new Error(`spec-review: question coverage / envelope contract still failing after repair: ${(chk.errors || []).join('; ')}`)
  }
  ;(chk.missing || []).forEach((m) => note(`envelope missing: ${m}`))
  const sum = await py('Review', 'summary', `--lanes ${sq(present.join(','))} --planned ${PLANNED}`)
  if (sum.hardStop) note(`HARD STOP: ${hardText(sum)}; no fixes may be applied until the founder decides`)
  return { stage: 'review', runDir: RUN, paths: { lanes: RUN + '/lanes', envelopes: RUN + '/envelopes' }, counts: sum.raw, hardStop: sum.hardStop, hardStopReasons: sum.hardStopReasons, lanesWithEnvelope: present, gateLog }
}

// ---------------------------------------------------------------------------
// stage 3: synthesize
// ---------------------------------------------------------------------------
const SEV_MAP = 'Codex severity words map: critical -> CRITICAL; high -> MAJOR; medium -> MAJOR if user-facing else MINOR; low -> MINOR.'
async function synthesize() {
  phase('Synthesize')
  const codex = PLAN.run.filter((e) => e.kind === 'codex')
  const st = (await py('Synthesize', 'codex-status', '')).lanes
  const live = []
  const dead = []
  for (const e of codex) {
    const s = st[e.label]
    if (s && s.status === 'OK' && s.bytes >= 400) live.push(e)
    else {
      dead.push(e)
      note(`${e.label}: timed-out/${s ? s.status : 'NO-STATUS'} -- ${e.label === 'codex-adversarial' ? 'backfilled by critic (opus)' : e.label === 'codex-frontier' ? 'backfilled by critic (opus)' : 'no substitute (investigation / dossier carry it)'}; cross-examination unavailable for it`)
    }
  }
  const subs = P.substitutes.filter((e) => e.substituteFor && dead.some((d) => d.label === e.substituteFor))
  P.substitutes.filter((e) => e.substituteFor && !subs.includes(e)).forEach((e) => note(`${e.label}: SKIPPED (gate: ${e.substituteFor} produced its artifact)`))
  if (subs.length) await py('Synthesize', 'lanes', `--spec ${sq(SPEC)} --lanes ${sq(labelsOf(subs).join(','))}`)

  const extractors = live.map((e) => () => agent(
    `ROLE: codex-envelope-extractor\nRead the Codex lane output ${RUN}/codex/${e.label}.out.md (the lane's full findings; do not edit it). List EVERY finding in it and build this envelope object: {"lane": "${e.label}", "verdict": "<the lane's verdict word, or ''>", "answered_questions": [<the Q-ids the lane answered; assigned ids are in ${RUN}/assignments.json under "${e.label}">], "findings": [{"id": "${e.idPrefix}-1", "severity": "...", "title": "<one line>"}, ...]} with ids ${e.idPrefix}-1.. in file order. ${SEV_MAP} ${e.label === 'codex-research' ? 'Research items use severity ELEVATE or CAUTION, never CRITICAL/MAJOR/MINOR.' : ''} ${e.label === 'codex-frontier' ? 'Frontier: each of its items (1) most-likely-wrong decision, (2) the cross-cutting risks, (3) best-in-class delta becomes a finding; use its stated severity, else MAJOR (CRITICAL when its verdict is redesign for item 1).' : ''} Never drop a finding to keep the envelope short. Reply with that object via StructuredOutput; write no file (the workflow saves your reply as ${RUN}/envelopes/${e.label}.json).`,
    { label: e.label + ':extract', phase: 'Synthesize', agentType: 'general-purpose', model: 'sonnet', schema: ENVELOPE }))
  const critics = subs.map((e) => () => agent(`ROLE: ${e.label}\n${laneBrief(RUN + '/prompts/' + e.label + '.md')}`, { ...laneAgent(e), phase: 'Synthesize' }))
  const got = await parallel([...extractors, ...critics])
  const mkLabels = [...live, ...subs].map((e) => e.label)
  mkLabels.forEach((l, i) => { if (!got[i]) note(`${l}: FAILED (extractor/critic returned nothing)`) })
  await parallel(live.map((e, i) => ({ e, env: got[i] })).filter((x) => x.env).map((x) => () => putEnvelope('Synthesize', x.e.label, { ...x.env, lane: x.e.label })))

  // Mechanical envelope + coverage + manifest-presence check over everything that ran.
  const planned = [...labelsOf(PLAN.run).filter((l) => !codex.some((c) => c.label === l)), ...codex.map((c) => c.label), ...labelsOf(subs)]
  const chk = await py('Synthesize', 'check-envelopes', `--lanes ${sq(planned.join(','))} --codex ${sq(labelsOf(codex).join(','))}`, true)
  if ((chk.invalid || []).length || Object.keys(chk.unanswered || {}).length) throw new Error(`spec-review: envelope contract failed: ${(chk.errors || []).join('; ')}`)
  const failed = (chk.missing || []).map((m) => m.split(':')[0])
  failed.forEach((l) => note(`${l}: FAILED (no envelope)`))
  Object.entries(chk.codexUnanswered || {}).forEach(([l, qs]) => note(`${l}: Codex lane left assigned question(s) unanswered: ${qs.join(', ')}`))
  if (failed.includes('codex-frontier') && !subs.some((s) => s.label === 'critic-frontier')) throw new Error('spec-review: Astra frontier lane has no envelope and no substitute')
  const ok = planned.filter((l) => !failed.includes(l))
  if (!ok.includes('codex-frontier') && !ok.includes('critic-frontier')) throw new Error('spec-review: no Astra frontier result (lane and critic fallback both failed)')

  // Merge before falsify: one merger clusters the CRITICAL/MAJOR lane findings that describe the
  // same defect into F-N units; run_dir.py rejects any id left out or placed twice.
  let mc = await py('Synthesize', 'merge-check', `--lanes ${sq(ok.join(','))}`, true)
  const mergePrompt = [
    'ROLE: finding-merger',
    `Cluster the ${mc.totalIds} CRITICAL/MAJOR findings listed in ${mc.indexPath || RUN + '/merge-index.txt'} (one line per id: id, lane, severity, title; Read it) into units, one unit per distinct underlying defect. Findings from different lanes that describe the same mechanism, boundary or missing guarantee belong together even when worded differently; findings that merely touch the same file but describe different defects stay apart. A single-member unit is fine.`,
    `Read the full findings where a title is ambiguous: Claude lanes in ${RUN}/lanes/<lane>.md, Codex lanes in ${RUN}/codex/<lane>.out.md (find each by its id). Do not judge whether a finding is true; that is the falsifiers' job.`,
    `Write ${RUN}/merged.raw.json: a JSON list of {"title": "<one line naming the defect>", "seam": "<the component/file/contract it lives in>", "members": [<original ids>], "cites": ["<path:line>", ...]}. EVERY id in that file must appear in exactly one unit's members. Reply via StructuredOutput with the number of units.`,
    'You are a leaf agent: spawn no sub-agents or Workflows.',
  ].join('\n')
  const MERGED = { type: 'object', properties: { units: { type: 'number' } }, required: ['units'] }
  for (let attempt = 0; attempt < 2 && !mc.ok; attempt++) {
    const repair = attempt ? `\nYOUR PREVIOUS merged.raw.json FAILED VALIDATION, fix exactly these: ${(mc.errors || []).join('; ')}` : ''
    await agent(mergePrompt + repair, { label: `finding-merger${attempt ? ':repair' : ''}`, phase: 'Synthesize', agentType: 'general-purpose', model: 'sonnet', schema: MERGED })
    mc = await py('Synthesize', 'merge-check', `--lanes ${sq(ok.join(','))}`, true)
  }
  if (!mc.ok) throw new Error(`spec-review: finding merge failed validation: ${(mc.errors || []).join('; ')}`)
  note(`merge: ${mc.totalIds} CRITICAL/MAJOR ids -> ${mc.clusters} F-N units`)

  // Falsifier wave: unconditional, one verdict per F-N unit, units batched by seam.
  const fp = await py('Synthesize', 'falsify-plan', `--spec ${sq(SPEC)} --lanes ${sq(ok.join(','))} --max-batches ${A.maxFalsifierBatches || 6}`)
  const total = fp.totalIds
  if (fp.plan.reduce((n, b) => n + b.ids.length, 0) !== fp.totalUnits) throw new Error('spec-review: falsifier plan does not cover every unit')
  note(`falsifier plan: ${fp.totalUnits} units (${total} ids) in ${fp.plan.length} batches`)
  const runF = (b) => agent(`ROLE: finding-falsifier\n${laneBrief(b.prompt)}`,
    { label: `falsify:batch-${b.batch}`, phase: 'Synthesize', agentType: 'general-purpose', model: 'sonnet', schema: FALSIFIER_BATCH })
  await parallel(fp.plan.map((b) => () => runF(b)))
  let sum = await py('Synthesize', 'summary', `--lanes ${sq(ok.join(','))} --planned ${PLANNED}`)
  if (sum.missingVerdicts.length) {
    const redo = fp.plan.filter((b) => b.ids.some((i) => sum.missingVerdicts.includes(i)))
    note(`falsifier retry for batch(es) ${redo.map((b) => b.batch).join(', ')}: missing ${sum.missingVerdicts.join(', ')}`)
    await parallel(redo.map((b) => () => runF(b)))
    sum = await py('Synthesize', 'summary', `--lanes ${sq(ok.join(','))} --planned ${PLANNED}`)
    if (sum.missingVerdicts.length) throw new Error(`spec-review: falsifier verdict missing for ${sum.missingVerdicts.join(', ')}`)
  }
  if (sum.falsifierDispatched !== total) throw new Error(`spec-review: verdicts-per-id mismatch (${sum.falsifierDispatched} ids with verdicts vs ${total})`)
  note(`falsifier wave: ${fp.totalUnits} units (${total} ids) in ${fp.plan.length} batches, ${sum.refuted} ids REFUTED`)
  if (sum.hardStop) note(`HARD STOP surfaced in report.md (${(sum.hardStopReasons || []).join(', ')})`)

  // Manifest: every planned lane is listed as run, FAILED, or SKIPPED (gate: ...).
  const rows = [
    ...PLAN.run.map((e) => `| ${e.label} | ${dead.some((d) => d.label === e.label) ? 'DEAD: ' + (st[e.label] ? st[e.label].status : 'NO-STATUS') : failed.includes(e.label) ? 'FAILED (no output)' : 'run'} | ${e.agentType}${e.model ? ' / ' + e.model : ''} |`),
    ...subs.map((e) => `| ${e.label} | run (substitute for ${e.substituteFor}) | ${e.agentType} / ${e.model} |`),
    ...PLAN.skipped.map((s) => `| ${s.label} | SKIPPED (${s.reason}) | - |`),
    ...P.substitutes.filter((e) => e.substituteFor && !subs.includes(e)).map((e) => `| ${e.label} | SKIPPED (gate: ${e.substituteFor} produced its artifact) | - |`),
  ]
  const manifestLabels = [...PLAN.run.map((e) => e.label), ...PLAN.skipped.map((s) => s.label), ...P.substitutes.filter((e) => e.substituteFor).map((e) => e.label)]
  const skippedLabels = [...PLAN.skipped.map((s) => s.label), ...P.substitutes.filter((e) => e.substituteFor && !subs.includes(e)).map((e) => e.label)]
  const gone = (e) => dead.some((d) => d.label === e.label) || failed.includes(e.label)
  const ran = PLAN.run.filter((e) => !gone(e))
  const ranCodex = ran.filter((e) => e.kind === 'codex').length
  const planBlock = [
    `### Lane plan: tier ${P.tier} (profile ${PROFILE}) — planned ${P.planned} lanes (${P.plannedCodex} Codex), ran ${ran.length} (${ranCodex} Codex); advisory budget: max ${P.budget.maxLanes} lanes / ${P.budget.maxCodexLanes} Codex, token ceiling ${P.budget.tokenCeiling} (actual spend: scripts/lane_spend.py on this Workflow run), falsifier scope ${P.budget.falsifier}. Manifest files: ${P.files.join(', ')}.`,
    ...P.overBudget.map((w) => `- over budget (advisory): ${w}`),
    ...PLAN.run.map((e) => `- ${e.label}: ${P.laneReasons[e.label]}`),
  ]
  const falsLine = `${total} dispatched over ${total} CRITICAL/MAJOR — ${sum.refuted} REFUTED, ${total - sum.refuted} SURVIVES.`
  const synthPrompt = [
    'ROLE: synthesis-writer',
    `You write the final spec-review report. Write it to ${RUN}/report.md following the template ${SKILL}/report-template.md exactly (section order, one canonical Falsifier wave line, F-N ids assigned once). Do not read the spec's design discussion; read evidence only.`,
    `Spec: ${SPEC}. Tier: ${P.tier} (profile ${PROFILE}). Run dir: ${RUN}. Investigation brief: ${A.investigationBrief || 'none (no investigation Workflow ran)'}.`,
    `Inputs: every ${RUN}/envelopes/*.json (ids + severities per lane); full findings in ${RUN}/lanes/*.md and ${RUN}/codex/*.out.md; the merged units in ${RUN}/merged.json (use its F-N ids and member lists as the report's F-N ids); falsifier verdicts per F-N in ${RUN}/falsifiers/F-*.json (+ batch-*.md reasoning; a unit's verdict is every member's verdict); ground truth in ${RUN}/dossier.md and ${RUN}/decisions.json; LEARNINGS paths (read the parts that apply; never edit): ${RUN}/inputs/learnings.txt lists them.`,
    'Hard rules the pipeline checks mechanically after you finish:',
    `- EVERY CRITICAL/MAJOR id in ANY envelope appears in report.md, each on a line carrying its verdict word (REFUTED or SURVIVES from its falsifier verdict; SURVIVES-BUT-FIX-REJECTED and NEEDS-LIVE-EVIDENCE count as SURVIVES with the note). Keep each lane's own ids (EC-N, Sec-N, Obs-N, LE-N, DRIFT-N, COMP-N ...). Consensus / Codex-only / Claude-only entries get an F-N id AND list the lane ids they merge.`,
    `- Right after the Profile line reproduce this block VERBATIM (it carries the planned-vs-actual lane count and the per-lane reasons):`, ...planBlock,
    `- Falsifier scope at this tier is ${P.budget.falsifier} (${P.budget.falsifier === 'all' ? 'every CRITICAL/MAJOR' : P.budget.falsifier === 'critical' ? 'CRITICAL only' : 'none'}). A CRITICAL/MAJOR id outside that scope was not falsified: its report line carries the verdict word SURVIVES with the note "(not falsified at tier ${P.tier})".`,
    `- The falsifier line is exactly: ### Falsifier wave: ${falsLine}`,
    `- REFUTED findings go to the Resolved section with the refuting evidence; an unrefuted CRITICAL keeps its severity (no downgrade without a REFUTED verdict).`,
    `- Surviving Obs-/Sec-/LE- CRITICAL/MAJOR not applied as spec prose go under "Carried obligations".`,
    `- The Lane manifest section reproduces this table verbatim (a lane with status FAILED or DEAD keeps that status; verdict lines say "timed-out/<status> -- backfilled by <substitute>" where a substitute ran):`,
    '| Lane | Status | Agent / model |', '|---|---|---|', ...rows,
    ...(sum.hardStop ? [`- HARD STOP: open the report with a bold HARD STOP banner: ${hardText(sum)}; no fixes until the founder decides.`] : []),
    ...(PLAN.run.some((e) => e.reportEveryFinding) ? [`- EVERY finding id of ANY severity and EVERY research_handoffs id in the envelopes of ${labelsOf(PLAN.run.filter((e) => e.reportEveryFinding)).join(', ')} appears in report.md, in that lane's own template section. Its ELEVATE items are a decision surface, never auto-applied; its hand-offs are listed for the main loop to send to the investigation skill.`] : []),
    '- No placeholder text may remain: no {{...}}, no <FOCUS...>, no <ALL_CAPS> tokens.',
    'Reply via StructuredOutput with the path only.',
  ].join('\n')
  const SYNTH = { type: 'object', properties: { report_path: { type: 'string' } }, required: ['report_path'] }
  const checkFlags = `--lanes ${sq(ok.join(','))} --manifest ${sq(manifestLabels.join(','))} --skipped ${sq(skippedLabels.join(','))} ${A.reviewPath ? '--publish ' + sq(A.reviewPath) : ''}`
  let w = await agent(synthPrompt, { label: 'synthesis-writer', phase: 'Synthesize', agentType: 'general-purpose', model: 'opus', schema: SYNTH })
  if (!w) throw new Error('spec-review: synthesis writer returned nothing')
  let rc = await py('Synthesize', 'check-report', checkFlags, true)
  for (let tries = 0; !rc.ok && tries < 2; tries++) {
    note(`report check failed (attempt ${tries + 1}): ${(rc.errors || []).join(' | ').slice(0, 600)}`)
    w = await agent(`ROLE: synthesis-writer\nYour report ${RUN}/report.md failed the mechanical check. Read the report and the original rules below, fix ONLY what the errors name, and rewrite ${RUN}/report.md.\nERRORS:\n${(rc.errors || []).join('\n')}\n\nORIGINAL RULES:\n${synthPrompt}`,
      { label: 'synthesis-writer:repair', phase: 'Synthesize', agentType: 'general-purpose', model: 'opus', schema: SYNTH })
    if (!w) throw new Error('spec-review: synthesis repair returned nothing')
    rc = await py('Synthesize', 'check-report', checkFlags, true)
  }
  if (!rc.ok) throw new Error(`spec-review: report still fails the mechanical check: ${(rc.errors || []).join('; ')}`)
  return {
    stage: 'synthesize', reportPath: RUN + '/report.md', reviewPath: A.reviewPath || null,
    counts: { raw: sum.raw, surviving: sum.surviving, refuted: sum.refuted, falsifierDispatched: total },
    hardStop: sum.hardStop, hardStopReasons: sum.hardStopReasons, failedLanes: failed, lanes: { tier: P.tier, planned: P.planned, ran: ran.length, plannedCodex: P.plannedCodex, ranCodex, overBudget: P.overBudget }, gateLog,
  }
}

return STAGE === 'prepare' ? await prepare() : STAGE === 'review' ? await review() : await synthesize()
