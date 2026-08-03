# Workflow F — plan falsifier (step 3, every run)

Step 3 is the step this ritual skips. Measured across 13 mined runs: **zero `Skill` tool calls, ever**
— sessions narrate *"grilling it against your own rules surfaced..."* and proceed straight to step 4a.
Runs 2026-07-06, 07-15, 07-20, 07-24, 07-25, 07-29 and 08-02 all did it, and the 07-06 plan that
self-certified then shipped a hook that blocked autonomous work for eight hours. A step whose
completion criterion is a sentence the agent grades itself against is not a gate. A Workflow's is a run
id.

The one run that really grilled its plan did it exactly this way — 17 lanes, 4 of 14 findings killed
before execution. Fire this on the step-2 program, one lane per plan item.

```js
export const meta = {
  name: 'harness-plan-falsifier',
  description: 'Adversarially refute every item in the consolidated plan before anything is mutated',
  phases: [{ title: 'Falsify' }, { title: 'Adjudicate' }],
}
const ARGS = typeof args === 'string' ? JSON.parse(args) : args
const ITEMS = ARGS.planItems // [{id,title,surface,change,evidence}] — one per step-2 plan item
const PIN = 'You are a leaf agent: do NOT spawn sub-agents or Workflows; do the work inline and return. READ-ONLY — never mutate, no polling.'
const KILL = { type:'object', additionalProperties:false, required:['verdict','probe','corrected'], properties:{
  verdict:{enum:['confirmed','already-covered','stale','false-premise','wrong-layer','unenforceable']},
  probe:{type:'string',description:'the EXACT command run and its output — naming no probe means the item is NOT confirmed'},
  corrected:{type:'string',description:'the sharpened item, or why it dies'} }}

phase('Falsify')
const judged = await parallel(ITEMS.map(it=>()=>agent(
  `${PIN}\nADVERSARIAL FALSIFIER — kill this plan item. You are graded on kills, not agreement.\nITEM: ${JSON.stringify(it)}\nRun all five probes and print each command with its output: (1) ALREADY COVERED — read the target file and quote the line that already says it; (2) STALE — it was fixed since the evidence was captured (git log the target, then read the live file); (3) FALSE PREMISE — the cited evidence does not say what the item claims (re-read the source verbatim, never a paraphrase); (4) WRONG LAYER — it belongs to a different surface, or it puts a machine/customer-specific fact in a public file; (5) UNENFORCEABLE — it is a sentence the agent must remember where a mechanical check exists. Default to killing. An item whose probe you cannot name is not confirmed. An ABSENCE verdict ("this session never did X", "no such call site") needs the command that enumerated what DOES exist printed beside it — a zero-hit grep on a guessed identifier is indistinguishable from a real absence.`,
  {label:`kill:${(it.title||'item').slice(0,24)}`, phase:'Falsify', schema:KILL, model:'sonnet', agentType:'general-purpose'})
  .then(v=>({item:it, verdict:v})).catch(e=>({item:it, verdict:null, error:String(e)}))))
const dead = judged.filter(j=>!j || !j.verdict)
const survivors = judged.filter(j=>j && j.verdict && j.verdict.verdict==='confirmed')
const killed = judged.filter(j=>j && j.verdict && !survivors.includes(j))
log(`falsify: ${survivors.length} survived, ${killed.length} killed, ${dead.length} lanes returned nothing (item UNJUDGED — a dead lane is not a clearance)`)

phase('Adjudicate')
const OUT = { type:'object', additionalProperties:false, required:['executive_summary','ship_list','did_not_survive','unjudged'], properties:{
  executive_summary:{type:'string'}, ship_list:{type:'string',description:'the surviving program, resequenced — each item with its target surface and the probe that cleared it'},
  did_not_survive:{type:'string',description:'one line per killed item WITH its verdict and probe, so the next run does not re-propose it'},
  unjudged:{type:'array',items:{type:'string'},description:'items whose lane died — carried forward UNVERIFIED, never as cleared'} }}
return await agent(`Adjudicate the falsifier wave into the plan that actually ships. Build ONLY from survivors; a killed item is recorded with its probe and never re-enters. An item whose lane died is UNJUDGED — list it, do not ship it. Prefer a sharpened 'corrected' wording over the original. SURVIVORS: ${JSON.stringify(survivors)}\nKILLED: ${JSON.stringify(killed.map(k=>({item:k.item.title, verdict:k.verdict?.verdict, probe:k.verdict?.probe})))}\nUNJUDGED: ${JSON.stringify(dead.map(d=>d.item?.title))}`,
  {label:'adjudicate', phase:'Adjudicate', effort:'high', schema:OUT, model:'opus', agentType:'general-purpose'})
```

**Completion criterion:** a Workflow F run id exists for this run, and its `did_not_survive` list is
written into the saved program alongside the ship list.

**The falsifier is bound by its own rules.** On the 2026-08-03 self-audit a verifier lane declared a
session "not an `/improve-harness` run at all"; the session held two genuine invocation frames. The
wave that enforces cited absence produced an uncited one. Every kill on an absence ground prints the
enumeration that grounds it.

**Offload candidate.** Falsifier prompts are self-contained, produce a document, and are read-only —
they pass the three offload tests cleanly, and a second model's independent priors are worth more here
than anywhere else in the ritual. Piloting this wave on the second runtime is the first offload to try;
the research lanes stay put, because they carry snapshot state assembled inline from the live machine.
