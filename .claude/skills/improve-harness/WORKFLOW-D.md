# Workflow D — production-stability / regression RCA (conditional)

Fire this when the period included a **regression cluster, a prod incident, or an unstable-prod stretch**. It mines the incidents into a robustness program whose north star is **keeping production stable** — and it is **NOT CI-specific**: its output spans every lever — **documentation, CI gates, harness rules, cross-session coordination, the lack-of-research / insufficient-grounding gap, and cheap standing invariants**. (Distilled from a past regression-cluster RCA — adapt the incident-discovery commands to your own tooling.)

The load-bearing finding it operationalizes: **local green is structurally blind to whole defect classes** — `tsc` + boundary-mocked `vitest` cannot see a missing infra env/IAM-role/runtime-config wiring, a stale config-store value, a hardcoded recipient, two disagreeing string literals, a browser CSS cascade, or existing-data drift (fresh-DB green). So the lever is a **reflex to add a cheap standing invariant at the un-mockable layer** whenever a change introduces a new runtime dependency / recipient / writer / schema column — *not* "understand the feature better" (every regression that day passed local green, so comprehension changes zero outcomes).

**Discover the incident list inline FIRST** (don't guess): merged PRs in the window that regressed (`gh pr list --state merged`), CI failures, prod incidents from your logs / run-ledger / issue tracker. Each incident = `{id, title, introduced_by (PR#+commit+change), fixed_by, summary, commits:[...]}`; pass as `args.incidents`. The spine is a 5-phase adversarial fan-out — **one agent per incident** (grounding beats aggregation), cluster, a guardrail per class, then a **SEPARATE skeptic that REFUTES each guardrail** (3/5 ship as false-security without this), then synthesize the program (`effort:'high'`).

```js
export const meta = {
  name: 'harness-prod-stability-rca',
  description: 'RCA a batch of regressions → failure classes + hot-zones → adversarially-verified guardrails → a prod-stability program (docs/CI/harness/cross-session/research)',
  phases: [{ title: 'RCA' }, { title: 'Synthesize' }, { title: 'Mitigate+Verify' }, { title: 'Program' }],
}
const ARGS = typeof args === 'string' ? JSON.parse(args) : args
const INCIDENTS = ARGS.incidents // [{id,title,introduced_by,fixed_by,summary,commits}] — discovered inline first
const PIN = 'RCA only — read-only; ground every claim in the actual `git show` of the introducing+fixing commit; no mutation, no nested dispatch, no log confabulation.'

const RCA = { type:'object', additionalProperties:false,
  required:['incident_id','root_cause','failure_class','blast_radius','why_passed_local_green','earliest_cheap_signal','shared_substrate','confidence','evidence'], properties:{
  incident_id:{type:'string'}, root_cause:{type:'string',description:'mechanism grounded in the diff'},
  failure_class:{type:'string'}, blast_radius:{enum:['prod-outage','customer-facing','security','data-correctness','cosmetic','internal-only']},
  why_passed_local_green:{type:'string',description:'THE crux — why tsc+vitest were green'},
  earliest_cheap_signal:{type:'string',description:'cheapest gate that would have caught it pre-merge'},
  shared_substrate:{type:'string',description:'hot-zone file/cluster or "isolated"'},
  parallel_session_factor:{type:'string'}, confidence:{enum:['high','med','low']}, evidence:{type:'string'} }}
phase('RCA')
const rcas = await parallel(INCIDENTS.map(i=>()=>agent(
  `${PIN}\nRoot-cause ONE regression: ${JSON.stringify(i)}. \`git show --stat <sha>\` + \`git show <sha> -- <files>\` for BOTH the introducing and fixing commit — the pair reveals the mechanism. Pin deploy-timestamp-vs-onset (a PR deployed AFTER onset is exonerated) and read terminal status (your run-ledger / logs) before theorizing. The two questions that matter MOST: (A) WHY did local green (tsc + local vitest) NOT catch this? (B) what is the CHEAPEST signal — test/lint/ci-gate/one-flow bake — that would have caught it before the bad merge? Verify any prior memory claim against the actual diff.`,
  {label:`rca:${i.id}`, phase:'RCA', schema:RCA, model:'sonnet', agentType:'general-purpose'})))

phase('Synthesize')
const TAX = { type:'object', additionalProperties:false, required:['report_markdown','failure_classes','cross_cutting'], properties:{
  report_markdown:{type:'string'},
  failure_classes:{type:'array',items:{type:'object',additionalProperties:false,required:['id','name','common_root','incident_ids','blast'],properties:{
    id:{type:'string'}, name:{type:'string'}, common_root:{type:'string',description:'single shared MECHANISM, not symptom'}, incident_ids:{type:'array',items:{type:'string'}}, blast:{type:'string'} }}},
  cross_cutting:{type:'array',items:{type:'string'},description:'hot-zone files (few, high-blast); parallel-session role; local-green-insufficiency; repeated-fix chains'} }}
const tax = await agent(`Cluster these RCAs into failure CLASSES by shared root MECHANISM (not symptom). Surface cross-cutting: (1) hot-zone files — a few high-blast files own most incidents; (2) uncoordinated parallel sessions on the same substrate; (3) where local-green is necessary-but-insufficient; (4) repeated-fix chains. RCAs: ${JSON.stringify(rcas.filter(Boolean))}`, {label:'synthesize', phase:'Synthesize', schema:TAX, model:'opus', effort:'high', agentType:'general-purpose'})

if (!tax || !Array.isArray(tax.failure_classes)) {
  // A failed or rate-limited synthesize must not crash the Workflow and discard every RCA already
  // collected. Observed 2026-07-16: the synthesize agent hit the account session limit and the next
  // line threw "Error: null is not an object (evaluating 'tax.failure_classes')", losing 6 completed RCAs.
  log(`Synthesize returned ${tax ? 'a malformed result' : 'null'} — likely a failed or rate-limited agent call. Returning partial RCAs instead of crashing; resume via resumeFromRunId once the limit clears.`)
  return { error: 'synthesize-failed', partial_rcas: rcas.filter(Boolean), raw_tax: tax }
}
const deadRcas = INCIDENTS.length - rcas.filter(Boolean).length
if (deadRcas > 0) log(`${deadRcas} of ${INCIDENTS.length} incidents produced no RCA — the taxonomy below covers the survivors ONLY, and is not a complete picture of the period`)

phase('Verify-Findings')
// D refutes its GUARDRAILS and never its FINDINGS. Observed 2026-08-03: a hot_zone asserting "the
// divergence is STILL LIVE" described a fail-open fixed six days earlier; it rode into the executive
// summary and was filed into a real tracker as a live P2 security exposure for four hours. An RCA is a
// claim about the PAST and needs no liveness check; a hot_zone is a claim about NOW and always does.
const LIVE = { type:'object', additionalProperties:false, required:['still_live','probe','corrected'], properties:{
  still_live:{enum:['yes','no','could-not-confirm']},
  probe:{type:'string',description:'the EXACT command run at current HEAD and its output — a probe you cannot name means could-not-confirm'},
  corrected:{type:'string'} }}
const liveClaims = (rcas.filter(Boolean)).filter(r => r.blast_radius === 'security' || r.blast_radius === 'data-correctness')
const liveness = await parallel(liveClaims.map(r=>()=>agent(
  `${PIN}\nREFUTE that this defect is still live. It was root-caused from a historical diff; your only question is whether it exists at CURRENT HEAD. Re-derive it fresh — read the file at HEAD, \`git log\` the path for a later fix, and where a runtime signal exists prefer it (the strongest evidence is a log or metric series that STOPS at a deploy timestamp). Do NOT reason from the RCA's own diff. Default to 'no'. FINDING: ${JSON.stringify(r)}`,
  {label:`live:${(r.incident_id||'x').slice(0,20)}`, phase:'Verify-Findings', schema:LIVE, model:'sonnet', agentType:'general-purpose'})
  .then(v=>({rca:r, live:v})).catch(e=>({rca:r, live:null, error:String(e)}))))
const stillLive = liveness.filter(l=>l && l.live && l.live.still_live === 'yes')
const notLive = liveness.filter(l=>l && l.live && l.live.still_live !== 'yes')
log(`liveness: ${stillLive.length} of ${liveClaims.length} high-blast findings still live at HEAD; ${notLive.length} already fixed or unconfirmed`)

phase('Mitigate+Verify')
const MIT = { type:'object', additionalProperties:false, required:['guardrail_name','guardrail_type','concrete_implementation','existing_pattern_to_extend','prevents_incident_ids','converts_to_local_failure','lever','effort','leverage'], properties:{
  guardrail_name:{type:'string'}, guardrail_type:{enum:['test','lint','ci-gate','codeowners-gate','process-rule','architecture-invariant','tooling','doc-rule']},
  concrete_implementation:{type:'string',description:'exact file(s) + the actual assertion'}, existing_pattern_to_extend:{type:'string'},
  prevents_incident_ids:{type:'array',items:{type:'string'}}, converts_to_local_failure:{type:'boolean',description:'turns a deploy-only defect into local-green RED?'},
  lever:{enum:['documentation','ci','harness','cross-session','research-grounding','standing-invariant']}, effort:{type:'string'}, leverage:{enum:['high','med','low']} }}
const VERDICT = { type:'object', additionalProperties:false, required:['verdict','would_have_caught','false_sense_of_security_risk','refinement'], properties:{
  verdict:{enum:['catches','partial','insufficient']}, would_have_caught:{type:'string',description:'per-incident skeptical walk'},
  false_sense_of_security_risk:{type:'string',description:'could a naive version pass while the bug exists?'}, refinement:{type:'string'} }}
const guarded = await pipeline(tax.failure_classes,
  fc=>agent(`Design ONE cheap guardrail that converts failure class ${JSON.stringify(fc)} from prod/deploy-only into a LOCAL-GREEN FAILURE (or, for a process/doc class, the smallest enforceable rule). Prefer synth-time/static (no cloud creds, runs inside the local verify) over CI-only or bake-only. GREP for an existing in-repo pattern to extend. State whether a NAIVE version could pass while the bug exists (the "present-anywhere" trap) and how to avoid it. Tag the lever (documentation/ci/harness/cross-session/research-grounding/standing-invariant).`, {label:`mitigate:${fc.id}`, phase:'Mitigate+Verify', schema:MIT, model:'sonnet', agentType:'general-purpose'}),
  (mit,fc)=>agent(`ADVERSARIAL verifier — your job is to REFUTE that this guardrail works. For EACH incident in the class: if the guardrail existed the day before, would the bad PR have FAILED a local check? Walk the real mechanism. Default to skepticism — unsure → "partial"/"insufficient", never "catches". Probe specifically: (1) trigger keyed on fix-introduced artifacts (stays green for the bug's whole life); (2) assertion present-anywhere vs on-the-real-surface (a grant on the actual role, not "somewhere"); (3) test-exists vs test-exercises-the-failing-path; (4) guardrail mis-scoped to a broader class than it covers. GUARDRAIL: ${JSON.stringify(mit)} CLASS: ${JSON.stringify(fc)}`, {label:`verify:${fc.id}`, phase:'Mitigate+Verify', schema:VERDICT, model:'sonnet', agentType:'general-purpose'}).then(v=>({class:fc, mitigation:mit, verdict:v})))

phase('Program')
const PROG = { type:'object', additionalProperties:false, required:['executive_summary','hot_zones','prioritized_guardrails','cross_session_coordination','rca_checklist','tracker_issues'], properties:{
  executive_summary:{type:'string',description:'single biggest leverage point for prod stability'},
  hot_zones:{type:'array',items:{type:'object',additionalProperties:false,required:['files','why_hot','contract','gate'],properties:{files:{type:'string'},why_hot:{type:'string'},contract:{type:'string',description:'implicit contract to make explicit+tested'},gate:{type:'string'}}}},
  prioritized_guardrails:{type:'array',items:{type:'object',additionalProperties:false,required:['rank','name','lever','prevents','effort','leverage'],properties:{rank:{type:'number'},name:{type:'string'},lever:{type:'string'},prevents:{type:'string'},effort:{type:'string'},leverage:{type:'string'}}}},
  cross_session_coordination:{type:'string'}, rca_checklist:{type:'string'}, tracker_issues:{type:'array',items:{type:'string'}} }}
return await agent(`Synthesize a tight, ACTIONABLE production-stability program from the verified guardrails. (1) exec summary + the single biggest leverage point; (2) hot zones — the few high-blast files, each with its now-explicit contract + the gate a change must pass; (3) prioritized guardrails ranked by leverage/effort — favor those that convert deploy-only defects to local-green RED, spanning the levers (documentation / CI / harness / cross-session / research-grounding / standing-invariant); (4) a low-ceremony cross-session coordination mechanism on EXISTING primitives (a hot-zones list + a deploy-ledger so an RCA can diff onset-vs-deploy-time; do NOT serialize all work — the real cost is RCA-misdirection, not line collisions); (5) the RCA-process hardening checklist; (6) 4–8 issue-ready tracker titles+priorities. Honor never-slice / delete-legacy / solo-operator (no heavyweight process). Drop any guardrail the verifier rated 'insufficient' unless its refinement is applied.\n\nOnly findings with an affirmative liveness probe may enter hot_zones or tracker_issues as an OPEN issue; anything else is described in the past tense as an already-fixed incident, with its probe. Never file a claim about current production state into an external tracker without the command that re-derived it at HEAD this run — a stale "live exposure" ticket is worse than a documented gap, because it reads as urgent and gets acted on. LIVENESS: ${JSON.stringify(liveness.filter(Boolean).map(l=>({incident:l.rca?.incident_id, still_live:l.live?.still_live ?? 'lane-died', probe:l.live?.probe})))}\n\nVERIFIED: ${JSON.stringify(guarded.filter(Boolean))}\nTAXONOMY: ${JSON.stringify(tax)}`, {label:'program', phase:'Program', effort:'high', schema:PROG, model:'opus', agentType:'general-purpose'})
```

**The load-bearing choices to keep when you adapt it:** one agent *per incident* (aggregation confabulates); the `why_passed_local_green` + `earliest_cheap_signal` fields (the whole point); the Mitigate→Verify `pipeline` where a *separate* skeptic refutes each guardrail; the four false-security probes; `effort:'high'` only on Program; and lever-tagging so the program's fixes route to docs / CI / harness / cross-session / research / standing-invariant — not just code. Its output feeds step 2's reconcile and lands in step 4 as guardrail-adds across your harness surfaces.
