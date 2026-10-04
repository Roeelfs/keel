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

// Single source of lane data. scripts/run_dir.py and the tests parse this block as JSON:
// keep it strict JSON (double quotes, no comments, no trailing commas).
// MANIFEST:BEGIN
const MANIFEST = {
  "profiles": ["full", "focused", "hotfix"],
  "gates": ["liveSurface", "security", "cutover", "runtimeWiring"],
  "lanes": [
    {"label": "completeness-reviewer", "kind": "claude", "agentType": "general-purpose", "model": "opus", "prompt": "completeness-reviewer.md", "profiles": ["full"], "gate": null, "idPrefix": "COMP", "tags": ["completeness"]},
    {"label": "codebase-verifier", "kind": "codex", "agentType": "codex-dispatch", "model": "gpt-6-sol", "prompt": "codebase-verifier.md", "profiles": ["full", "focused", "hotfix"], "gate": null, "idPrefix": "CB", "tags": ["codebase"], "codexClass": "verify", "codexContract": true},
    {"label": "architecture-auditor", "kind": "codex", "agentType": "codex-dispatch", "model": "gpt-6-sol", "prompt": "architecture-auditor.md", "profiles": ["full"], "gate": null, "idPrefix": "ARCH", "tags": ["architecture"], "codexClass": "falsifier", "codexContract": true},
    {"label": "adr-auditor", "kind": "claude", "agentType": "adr-auditor", "model": null, "prompt": null, "profiles": ["full"], "gate": null, "idPrefix": "ADR", "tags": [],
      "brief": "# ADR-conformance gate\n\nAudit the spec at {{SPEC_PATH}} (project root {{PROJECT_ROOT}}): classify EVERY spec decision CONFORMS | STRAYS | NEEDS-APPROVAL against the Accepted ADRs and platform invariants. Any spec that changes an Accepted ADR or invariant without an explicit founder-approval marker is a HARD STOP: record it as a CRITICAL finding. In your envelope JSON (both the file and the final reply) also set founder_approval_needed (true when the spec changes an Accepted ADR/invariant) and founder_approval_marker_present (true when an explicit founder-approval marker for that change exists in the spec or dossier)."},
    {"label": "cutover-architect", "kind": "claude", "agentType": "cutover-architect", "model": null, "prompt": null, "profiles": [], "gate": "cutover", "idPrefix": "CUT", "tags": [],
      "brief": "# Cutover-structure lane (3c)\n\nThe spec at {{SPEC_PATH}} (project root {{PROJECT_ROOT}}) rewrites/replaces/migrates/cuts over an existing capability, gives one a second plane/profile/twin/runtime, or edits ONE representation of a contract that greppably has others. Run your agent method: build the Contract x Representation matrix and count hand-maintained representations per contract AFTER the change; every contract left at >=2 without a fail-closed parity instrument invoked by the mandatory local gate is CRITICAL; write the MIGRATE ledger (what the old code knew that the owner must inherit) and the post-change probes that print the count. Findings file ends with a line `Verdict: STRUCTURED | COEXISTS`."},
    {"label": "runtime-wiring", "kind": "claude", "agentType": "general-purpose", "model": null, "prompt": null, "profiles": [], "gate": "runtimeWiring", "idPrefix": "RW", "tags": [],
      "brief": "# Runtime-wiring lane: consumer-side reachability\n\nThe spec at {{SPEC_PATH}} (project root {{PROJECT_ROOT}}) introduces a runtime-read env var/secret/credential ARN/flag/URL, a new deployed function, or moves such a read into shared code. For each new name, enumerate every deployed entry point whose call graph can EXECUTE the read (bundle presence is not reachability), and return the consumer list the spec's infra section must wire: env key + permission grant on each function's ACTUAL execution role, plus the same-change standing gate that pins it. Walk from the consumer, never from the stack. Wired into fewer functions than execute it = CRITICAL."},
    {"label": "provider-fit-auditor", "kind": "claude", "agentType": "general-purpose", "model": "opus", "prompt": "provider-fit-auditor.md", "profiles": ["full"], "gate": null, "idPrefix": "PF", "tags": ["provider-fit"]},
    {"label": "edge-case-miner", "kind": "claude", "agentType": "general-purpose", "model": "opus", "prompt": "edge-case-miner.md", "profiles": ["full", "focused"], "gate": null, "idPrefix": "EC", "tags": ["edge-case"]},
    {"label": "security-miner", "kind": "claude", "agentType": "general-purpose", "model": "opus", "prompt": "security-miner.md", "profiles": ["full"], "gate": "security", "idPrefix": "Sec", "tags": ["security"]},
    {"label": "observability-auditor", "kind": "claude", "agentType": "general-purpose", "model": "opus", "prompt": "observability-auditor.md", "profiles": ["full"], "gate": null, "idPrefix": "Obs", "tags": ["observability"]},
    {"label": "live-evidence-auditor", "kind": "claude", "agentType": "general-purpose", "model": "opus", "prompt": "live-evidence-auditor.md", "profiles": [], "gate": "liveSurface", "idPrefix": "LE", "tags": ["live-evidence"]},
    {"label": "spec-drift-scout", "kind": "claude", "agentType": "general-purpose", "model": "sonnet", "prompt": "spec-drift-scout.md", "profiles": ["full"], "gate": null, "idPrefix": "DRIFT", "tags": ["drift"]},
    {"label": "critic-hotfix", "kind": "critic", "agentType": "critic", "model": "fable", "prompt": null, "profiles": ["hotfix"], "gate": null, "idPrefix": "CRIT", "tags": ["completeness", "codebase", "architecture", "provider-fit", "edge-case", "security", "observability", "drift", "live-evidence", "codex-adversarial"],
      "brief": "# Hotfix critic\n\nProd-down review of the spec at {{SPEC_PATH}} (project root {{PROJECT_ROOT}}). Minutes matter: stress-test the fix for what would make it fail or make things worse (rollback safety, blast radius, data loss, the wrong root cause). Answer every assigned question; report only material findings."},
    {"label": "codex-standard", "kind": "codex", "agentType": "codex-dispatch", "model": "gpt-6-sol", "prompt": "codex-standard-reviewer.md", "profiles": ["full"], "gate": null, "idPrefix": "CSTD", "tags": [], "codexClass": "verify"},
    {"label": "codex-adversarial", "kind": "codex", "agentType": "codex-dispatch", "model": "gpt-6-sol", "prompt": "codex-adversarial-reviewer.md", "profiles": ["full", "focused"], "gate": null, "idPrefix": "CADV", "tags": ["codex-adversarial"], "codexClass": "falsifier"},
    {"label": "codex-research", "kind": "codex", "agentType": "codex-dispatch", "model": "gpt-6-sol", "prompt": "codex-research-auditor.md", "profiles": ["full"], "gate": null, "idPrefix": "ELV", "tags": [], "codexClass": "research"},
    {"label": "codex-frontier", "kind": "codex", "agentType": "codex-dispatch", "model": "gpt-6-astra", "prompt": "codex-frontier-judge.md", "profiles": ["full", "focused", "hotfix"], "gate": null, "idPrefix": "AST", "tags": ["codex-adversarial"], "fallback": true, "codexClass": "frontier"},
    {"label": "critic-adversarial", "kind": "critic", "agentType": "critic", "model": "fable", "prompt": null, "profiles": [], "gate": null, "idPrefix": "CADV", "tags": ["codex-adversarial"], "substituteFor": "codex-adversarial",
      "brief": "# Adversarial substitute (Codex lane dead)\n\nThe Codex adversarial lane produced no usable artifact. You replace it: adversarially review the spec at {{SPEC_PATH}} (project root {{PROJECT_ROOT}}): attack surface, data safety, rollback hazards, race conditions, degraded dependencies, observability gaps, architectural fit, over-engineering, vendor semantics under the spec's remedies. Material issues only, each with a concrete failure scenario and a fix."},
    {"label": "critic-frontier", "kind": "critic", "agentType": "critic", "model": "fable", "prompt": null, "profiles": [], "gate": null, "idPrefix": "AST", "tags": ["codex-adversarial"], "substituteFor": "codex-frontier",
      "brief": "# Frontier-judgment substitute (Astra lane dead)\n\nThe Codex Astra lane produced no usable artifact. You replace it as the final reviewer for the spec at {{SPEC_PATH}} (project root {{PROJECT_ROOT}}): rule on whether this is the RIGHT thing to build. Deliver (1) the one decision most likely to be wrong, with codebase evidence; (2) the three highest-leverage cross-cutting risks the narrow lanes miss; (3) what a best-in-class team would do differently here; (4) a verdict: approve / approve-with-changes / redesign. Also rule on whether the stated non-goals are the right non-goals. Set `verdict` in your envelope to that verdict word."}
  ],
  "support": [
    {"label": "context-dossier-miner", "agentType": "general-purpose", "model": "opus", "prompt": "context-dossier-miner.md"},
    {"label": "design-decisions-extractor", "agentType": "general-purpose", "model": "haiku", "prompt": "design-decisions-extractor.md"},
    {"label": "spec-drift-investigator", "agentType": "general-purpose", "model": "opus", "prompt": "spec-drift-investigator.md", "idPrefix": "DI"},
    {"label": "finding-falsifier", "agentType": "general-purpose", "model": "sonnet", "prompt": "finding-falsifier.md"},
    {"label": "codex-envelope-extractor", "agentType": "general-purpose", "model": "sonnet", "prompt": null},
    {"label": "finding-merger", "agentType": "general-purpose", "model": "sonnet", "prompt": null},
    {"label": "synthesis-writer", "agentType": "general-purpose", "model": "opus", "prompt": null},
    {"label": "script-runner", "agentType": "general-purpose", "model": "haiku", "prompt": null}
  ]
}
// MANIFEST:END

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
const PROFILE = need('profile')
if (!MANIFEST.profiles.includes(PROFILE)) throw new Error(`spec-review: profile must be one of ${MANIFEST.profiles.join('|')}`)
const GATES = need('gates')
for (const g of MANIFEST.gates) {
  if (!GATES[g] || typeof GATES[g].run !== 'boolean' || !GATES[g].reason) throw new Error(`spec-review: args.gates.${g} must be {run: boolean, reason: string}`)
}
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
// EXTRACT:END

// Run one run_dir.py subcommand through a script-runner and parse its JSON. The relayed stdout
// can be mangled by a cheap model, so parse the LAST JSON-object line, retry once on sonnet, then throw.
// soft=true returns the parsed object even when ok is false (the caller decides).
async function py(phaseName, sub, flags, soft) {
  const cmd = `python3 ${sq(SKILL + '/scripts/run_dir.py')} ${sub} --run ${sq(RUN)} ${flags || ''}`
  let j = null
  let last = ''
  for (const model of ['haiku', 'sonnet']) {
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

// The gate rule: a lane runs when its profile lists it OR its domain gate fired.
// Skips carry the reason; nothing is dropped silently.
function planLanes() {
  const run = []
  const skipped = []
  for (const e of MANIFEST.lanes) {
    if (e.substituteFor) continue
    const gate = e.gate ? GATES[e.gate] : null
    if (e.profiles.includes(PROFILE) || (gate && gate.run)) {
      const entry = { ...e }
      if (e.label === 'runtime-wiring') entry.agentType = WIRING_TYPE
      run.push(entry)
    } else {
      skipped.push({ label: e.label, reason: gate ? `gate: ${gate.reason}` : `gate: profile ${PROFILE} does not include it` })
    }
  }
  return { run, skipped }
}
const PLAN = planLanes()
const labelsOf = (arr) => arr.map((e) => e.label)
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
  const sum = await py('Review', 'summary', `--lanes ${sq(present.join(','))}`)
  if (sum.hardStop) note('ADR HARD STOP: the spec changes an Accepted ADR/invariant with no founder-approval marker; no fixes may be applied until the founder decides')
  return { stage: 'review', runDir: RUN, paths: { lanes: RUN + '/lanes', envelopes: RUN + '/envelopes' }, counts: sum.raw, hardStop: sum.hardStop, lanesWithEnvelope: present, gateLog }
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
      note(`${e.label}: timed-out/${s ? s.status : 'NO-STATUS'} -- ${e.label === 'codex-adversarial' ? 'backfilled by critic (fable)' : e.label === 'codex-frontier' ? 'backfilled by critic (fable)' : 'no substitute (investigation / dossier carry it)'}; cross-examination unavailable for it`)
    }
  }
  const subs = MANIFEST.lanes.filter((e) => e.substituteFor && dead.some((d) => d.label === e.substituteFor))
  MANIFEST.lanes.filter((e) => e.substituteFor && !subs.includes(e)).forEach((e) => note(`${e.label}: SKIPPED (gate: ${e.substituteFor} produced its artifact)`))
  if (subs.length) await py('Synthesize', 'lanes', `--spec ${sq(SPEC)} --lanes ${sq(labelsOf(subs).join(','))}`)

  const extractors = live.map((e) => () => agent(
    `ROLE: codex-envelope-extractor\nRead the Codex lane output ${RUN}/codex/${e.label}.out.md (the lane's full findings; do not edit it). List EVERY finding in it, then write ${RUN}/envelopes/${e.label}.json: {"lane": "${e.label}", "verdict": "<the lane's verdict word, or ''>", "answered_questions": [<the Q-ids the lane answered; assigned ids are in ${RUN}/assignments.json under "${e.label}">], "findings": [{"id": "${e.idPrefix}-1", "severity": "...", "title": "<one line>"}, ...]} with ids ${e.idPrefix}-1.. in file order. ${SEV_MAP} ${e.label === 'codex-research' ? 'Research items use severity ELEVATE or CAUTION, never CRITICAL/MAJOR/MINOR.' : ''} ${e.label === 'codex-frontier' ? 'Frontier: each of its items (1) most-likely-wrong decision, (2) the cross-cutting risks, (3) best-in-class delta becomes a finding; use its stated severity, else MAJOR (CRITICAL when its verdict is redesign for item 1).' : ''} Never drop a finding to keep the envelope short. Reply with the same object via StructuredOutput.`,
    { label: e.label + ':extract', phase: 'Synthesize', agentType: 'general-purpose', model: 'sonnet', schema: ENVELOPE }))
  const critics = subs.map((e) => () => agent(`ROLE: ${e.label}\n${laneBrief(RUN + '/prompts/' + e.label + '.md')}`, { ...laneAgent(e), phase: 'Synthesize' }))
  const got = await parallel([...extractors, ...critics])
  const mkLabels = [...live, ...subs].map((e) => e.label)
  mkLabels.forEach((l, i) => { if (!got[i]) note(`${l}: FAILED (extractor/critic returned nothing)`) })

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
  const idList = (mc.ids || []).map((f) => `  - ${f.id} [${f.lane}, ${f.severity}] ${f.title}${f.cites ? ' (cites ' + f.cites.join(', ') + ')' : ''}`).join('\n')
  const mergePrompt = [
    'ROLE: finding-merger',
    `Cluster the ${mc.totalIds} CRITICAL/MAJOR findings below into units, one unit per distinct underlying defect. Findings from different lanes that describe the same mechanism, boundary or missing guarantee belong together even when worded differently; findings that merely touch the same file but describe different defects stay apart. A single-member unit is fine.`,
    `Read the full findings where a title is ambiguous: Claude lanes in ${RUN}/lanes/<lane>.md, Codex lanes in ${RUN}/codex/<lane>.out.md (find each by its id). Do not judge whether a finding is true; that is the falsifiers' job.`,
    `Findings:\n${idList}`,
    `Write ${RUN}/merged.raw.json: a JSON list of {"title": "<one line naming the defect>", "seam": "<the component/file/contract it lives in>", "members": [<original ids>], "cites": ["<path:line>", ...]}. EVERY id above must appear in exactly one unit's members. Reply via StructuredOutput with the number of units.`,
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
  let sum = await py('Synthesize', 'summary', `--lanes ${sq(ok.join(','))}`)
  if (sum.missingVerdicts.length) {
    const redo = fp.plan.filter((b) => b.ids.some((i) => sum.missingVerdicts.includes(i)))
    note(`falsifier retry for batch(es) ${redo.map((b) => b.batch).join(', ')}: missing ${sum.missingVerdicts.join(', ')}`)
    await parallel(redo.map((b) => () => runF(b)))
    sum = await py('Synthesize', 'summary', `--lanes ${sq(ok.join(','))}`)
    if (sum.missingVerdicts.length) throw new Error(`spec-review: falsifier verdict missing for ${sum.missingVerdicts.join(', ')}`)
  }
  if (sum.falsifierDispatched !== total) throw new Error(`spec-review: verdicts-per-id mismatch (${sum.falsifierDispatched} ids with verdicts vs ${total})`)
  note(`falsifier wave: ${fp.totalUnits} units (${total} ids) in ${fp.plan.length} batches, ${sum.refuted} ids REFUTED`)
  if (sum.hardStop) note('ADR HARD STOP surfaced in report.md')

  // Manifest: every planned lane is listed as run, FAILED, or SKIPPED (gate: ...).
  const rows = [
    ...PLAN.run.map((e) => `| ${e.label} | ${dead.some((d) => d.label === e.label) ? 'DEAD: ' + (st[e.label] ? st[e.label].status : 'NO-STATUS') : failed.includes(e.label) ? 'FAILED (no output)' : 'run'} | ${e.agentType}${e.model ? ' / ' + e.model : ''} |`),
    ...subs.map((e) => `| ${e.label} | run (substitute for ${e.substituteFor}) | ${e.agentType} / ${e.model} |`),
    ...PLAN.skipped.map((s) => `| ${s.label} | SKIPPED (${s.reason}) | - |`),
    ...MANIFEST.lanes.filter((e) => e.substituteFor && !subs.includes(e)).map((e) => `| ${e.label} | SKIPPED (gate: ${e.substituteFor} produced its artifact) | - |`),
  ]
  const manifestLabels = [...PLAN.run.map((e) => e.label), ...PLAN.skipped.map((s) => s.label), ...MANIFEST.lanes.filter((e) => e.substituteFor).map((e) => e.label)]
  const skippedLabels = [...PLAN.skipped.map((s) => s.label), ...MANIFEST.lanes.filter((e) => e.substituteFor && !subs.includes(e)).map((e) => e.label)]
  const falsLine = `${total} dispatched over ${total} CRITICAL/MAJOR — ${sum.refuted} REFUTED, ${total - sum.refuted} SURVIVES.`
  const synthPrompt = [
    'ROLE: synthesis-writer',
    `You write the final spec-review report. Write it to ${RUN}/report.md following the template ${SKILL}/report-template.md exactly (section order, one canonical Falsifier wave line, F-N ids assigned once). Do not read the spec's design discussion; read evidence only.`,
    `Spec: ${SPEC}. Profile: ${PROFILE}. Run dir: ${RUN}. Investigation brief: ${A.investigationBrief || 'none (no investigation Workflow ran)'}.`,
    `Inputs: every ${RUN}/envelopes/*.json (ids + severities per lane); full findings in ${RUN}/lanes/*.md and ${RUN}/codex/*.out.md; the merged units in ${RUN}/merged.json (use its F-N ids and member lists as the report's F-N ids); falsifier verdicts per F-N in ${RUN}/falsifiers/F-*.json (+ batch-*.md reasoning; a unit's verdict is every member's verdict); ground truth in ${RUN}/dossier.md and ${RUN}/decisions.json; LEARNINGS paths (read the parts that apply; never edit): ${RUN}/inputs/learnings.txt lists them.`,
    'Hard rules the pipeline checks mechanically after you finish:',
    `- EVERY CRITICAL/MAJOR id in ANY envelope appears in report.md, each on a line carrying its verdict word (REFUTED or SURVIVES from its falsifier verdict; SURVIVES-BUT-FIX-REJECTED and NEEDS-LIVE-EVIDENCE count as SURVIVES with the note). Keep each lane's own ids (EC-N, Sec-N, Obs-N, LE-N, DRIFT-N, COMP-N ...). Consensus / Codex-only / Claude-only entries get an F-N id AND list the lane ids they merge.`,
    `- The falsifier line is exactly: ### Falsifier wave: ${falsLine}`,
    `- REFUTED findings go to the Resolved section with the refuting evidence; an unrefuted CRITICAL keeps its severity (no downgrade without a REFUTED verdict).`,
    `- Surviving Obs-/Sec-/LE- CRITICAL/MAJOR not applied as spec prose go under "Carried obligations".`,
    `- The Lane manifest section reproduces this table verbatim (a lane with status FAILED or DEAD keeps that status; verdict lines say "timed-out/<status> -- backfilled by <substitute>" where a substitute ran):`,
    '| Lane | Status | Agent / model |', '|---|---|---|', ...rows,
    ...(sum.hardStop ? ['- ADR HARD STOP: open the report with a bold HARD STOP banner: the adr-auditor found the spec changes an Accepted ADR/invariant with no founder-approval marker; no fixes until the founder decides.'] : []),
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
    hardStop: sum.hardStop, failedLanes: failed, gateLog,
  }
}

return STAGE === 'prepare' ? await prepare() : STAGE === 'review' ? await review() : await synthesize()
