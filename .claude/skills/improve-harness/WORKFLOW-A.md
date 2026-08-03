# Workflow A — mine + consolidate

Mines the past week of work and surveys every harness surface, then consolidates one sequenced plan.

**A falsifier wave is not optional here either.** B and D both run one; A did not, and it cost a
measured run. On 2026-08-03 a survey lane read a tracker ticket titled *"main CI is RED as of
2026-08-01, blocks every PR"*, took it as current, and A sequenced its **entire plan** behind that
blocker. One `gh run list --branch main` showed zero failing runs since 08-01 and the named check
reading SKIPPED, not FAILURE — the ticket recorded a *mutable status* that had been fixed and never
closed. Three of six miners' top findings were likewise already shipped.

The general shape: **a miner reports what a source SAYS; only a verifier checks what is TRUE now.**
Tracker status, "this rule doesn't exist", "that hook is missing", "this PR is blocked" are all
claims about live state that decay, and none survive contact with a direct query. Verify every
finding that asserts current state before it reaches the plan.

```js
export const meta = {
  name: 'harness-mine-consolidate',
  description: 'Mine recent sessions + survey harness surfaces, adversarially verify, consolidate one improvement plan',
  phases: [{ title: 'Mine' }, { title: 'Survey' }, { title: 'Verify' }, { title: 'Consolidate' }],
}

// Bucket the past-week transcripts so each miner gets a slice (find them first, inline).
// BOTH runtimes — friction lessons must correlate across the WHOLE harness, not just Claude:
//   ls -t ~/.claude/projects/*/*.jsonl                    (Claude Code sessions)
//   ls -t ~/.codex/sessions/*/*/*/rollout-*.jsonl         (Codex rollouts)
//   ~/.claude/history.jsonl
// Mix both runtimes into the buckets; the miner prompt below handles either schema.
const ARGS = typeof args === 'string' ? JSON.parse(args) : args  // REQUIRED: see the args-is-a-string trap in Launching
const BUCKETS = ARGS.transcriptBuckets // [[path,...], ...]  passed in by the skill
const LESSON_SCHEMA = { type:'object', additionalProperties:false, required:['report_markdown','lessons'], properties:{
  report_markdown:{type:'string'},
  lessons:{type:'array',items:{type:'object',additionalProperties:false,
    required:['title','category','evidence','recurrence','status','change_kind','proposed_change'],
    properties:{ title:{type:'string'}, category:{type:'string'},
      evidence:{type:'string',description:'quote + session file; for a friction loop, the repeated-call count + what kept failing'}, recurrence:{enum:['once','few','recurring']},
      status:{enum:['new','refines-existing','already-documented-but-still-recurring']},
      change_kind:{enum:['settings-hook','claude-md-rule','agents-md-rule','memory','ci-gate','prune','tooling'],description:'a RECURRING friction loop that is mechanically detectable at a tool boundary MUST be change_kind:settings-hook (a PreToolUse/Stop block) — never demote a mechanical block to a prose rule the model "should remember"'},
      proposed_change:{type:'string',description:'the exact edit: for settings-hook, the matcher + the PreToolUse/Stop guard it adds; else the AGENTS.md/CLAUDE.md/memory text'} }}},
}}

phase('Mine')
const minings = await parallel(BUCKETS.map((b,i)=>()=>agent(
  `Mine these transcripts for harness lessons. Extract THREE things: (1) human-typed turns + corrections; (2) the assistant's own self-flagged mistakes; (3) RECURRING FRICTION LOOPS — the same operation retried ≥3× to no effect, repeated identical errors, repeated permission denials, a merge/push/CI step attempted-and-blocked over and over. Friction loops are usually SILENT (the agent never flags them) — detect them by counting repeated near-identical tool calls and their failures, not by looking for an apology. Files: ${b.join(', ')}. Transcripts are EITHER Claude JSONL (\`{message:{role,content}}\`; tool_use frames, human turns are type:"user" with string content) OR Codex rollout JSONL (\`{type:"event_msg"|"response_item", payload:{type,...}}\`; human turns are \`event_msg.user_message.text\`, tool calls are \`response_item.function_call\` name+arguments and \`event_msg.patch_apply_end\`, and \`response_item.message\` frames are model-IO echoes to IGNORE) — parse whichever a file is; friction = the same \`exec_command\`/\`function_call\` (codex) or \`Bash\`/tool_use (claude) payload repeated to no effect. Rank by impact — a recurring friction loop ranks at the TOP, it is the highest-signal lesson there is. Quote evidence with the session file (include the repeated-call count). Set change_kind per lesson: a friction loop that is mechanically detectable at a tool boundary MUST be change_kind:settings-hook (a PreToolUse/Stop guard that blocks the wrong move) — never demote a mechanical block to a prose rule the model "should remember" (a remembered rule is exactly what failed in the stuck-on-merge case). Return report_markdown + lessons[].`,
  {label:`mine:${i}`, phase:'Mine', schema:LESSON_SCHEMA, model:'sonnet', agentType:'general-purpose'})))

phase('Survey')
const SURVEY_SCHEMA = { type:'object', additionalProperties:false, required:['report_markdown','findings'], properties:{
  report_markdown:{type:'string'}, findings:{type:'array',items:{type:'string'}} }}
const surveys = await parallel([
  ()=>agent(`Survey GitHub for the period: merged PRs across the repos the user works in, the repos they touch most, and any NEWLY-CREATED repos in their orgs (gh repo list <org> --json name,createdAt). What changed that the harness should know? Return report_markdown + findings[].`, {label:'survey:github', phase:'Survey', schema:SURVEY_SCHEMA, model:'sonnet', agentType:'general-purpose'}),
  ()=>agent(`Survey GitHub MERGE + CI FRICTION for the period — the friction side, distinct from the merged-PR survey. Find: PRs that were BLOCKED or took many merge attempts, PRs stuck on unresolved review comments, high CI re-run counts, repeated failed checks on the same PR. Use 'gh pr list --state all --json number,title,mergeStateStatus,reviewDecision,statusCheckRollup' and 'gh run list' (read-only). Each RECURRING merge/CI friction pattern is a candidate harness HOOK or rule — e.g. a PreToolUse guard on 'gh pr merge' that refuses while review threads are unresolved (the "stuck 4× on merge before learning to resolve comments first" case). Return report_markdown + findings[] (each friction pattern + its proposed hook/rule).`, {label:'survey:friction', phase:'Survey', schema:SURVEY_SCHEMA, model:'sonnet', agentType:'general-purpose'}),
  ()=>agent(`Survey your issue tracker (via its MCP if available): recent issue comments + status changes in the active team. Surface decisions/blockers the harness rules or memory should capture. Return report_markdown + findings[].`, {label:'survey:tracker', phase:'Survey', schema:SURVEY_SCHEMA, model:'sonnet', agentType:'general-purpose'}),
  ()=>agent(`Survey worktrees + memory: 'git worktree list' (prune candidates = merged/stale), and ~/.claude/projects/*/memory/ (MEMORY.md size vs limit, topic drift, uncommitted files). Return report_markdown + findings[].`, {label:'survey:wt-memory', phase:'Survey', schema:SURVEY_SCHEMA, model:'sonnet', agentType:'general-purpose'}),
  ()=>agent(`Deep-audit the harness: ~/.claude/{agents,commands,hooks,skills} + the skill-lock. Find dead pointers (skills/commands referencing missing engines/files), orphan/misfiled files, never-invoked agents (grep transcripts), and dup/conflicting commands vs native skills. Return report_markdown + findings[] with concrete delete paths.`, {label:'survey:audit', phase:'Survey', schema:SURVEY_SCHEMA, model:'sonnet', agentType:'general-purpose'}),
  ()=>agent(`Audit the INSTRUCTIONS FILES (read-only): the global ~/.claude/CLAUDE.md + each active repo's AGENTS.md/CLAUDE.md pair (see the skills repo's docs/instructions-files.md for the convention). Find: (1) STALE rules — a rule referencing a file/flow/flag/command that no longer exists; VERIFY each with ls/grep before flagging; (2) DUPLICATION/CONTRADICTION — between the two filenames in one repo (they must be one canonical file + a pointer/symlink, never two divergent contracts — diff them) and between the repo layer and the global layer (the narrower layer wins; flag the shadow copy); (3) DEMOTION candidates — procedure-shaped rules that belong in a skill, fact-shaped entries that belong in memory (an instructions file is a contract, not a manual); (4) BLOAT — sections that grew past what an agent will actually honor. Return report_markdown + findings[] (each = the exact file + a locating quote + the proposed edit/prune/demotion).`, {label:'survey:instructions', phase:'Survey', schema:SURVEY_SCHEMA, model:'sonnet', agentType:'general-purpose'}),
  // Self-audit: grade the PREVIOUS run only. Four mechanical checks, not a re-mining — full-scope
  // self-mining is what produced a 1.22M-token duplicate on 2026-08-02. Every improvement to this
  // ritual before 2026-08-03 arrived because a human noticed; nothing was ever looking.
  ()=>agent(`Audit the PREVIOUS /improve-harness run — only the previous one, four mechanical checks, no re-mining:
(1) Read the newest file in the harness repo's analytics/harness-improvement/. Diff its 'sequenced_execution' and 'OPEN' sections against what actually landed: 'git -C ~/.claude log --format="%h %ad %s" --date=short -40' and the same in the skills repo. Which planned items produced no commit?
(2) Re-derive every 'OPEN' item by its own recorded command. Report each as still-open / done / command-no-longer-works.
(3) Did that run fire Workflow F? Count Skill and Workflow tool_use frames in its transcript (find it under ~/.claude/projects/*/; parse with python, never grep — grep collapses JSONL records). A run with no 'harness-plan-falsifier' run id skipped step 3.
(4) Does an overlay heading dated that run exist in ~/.claude/skills-overlay/improve-harness/LEARNINGS.md? A run that mutated the harness and wrote nothing about itself is an incomplete run, and its lessons are gone.
Return report_markdown + findings[] — each finding is either a dropped plan item to re-sequence this run, a stale OPEN item to close, or a step the last run skipped that this run must not.`,
    {label:'survey:self-audit', phase:'Survey', schema:SURVEY_SCHEMA, model:'sonnet', agentType:'general-purpose'}),
])

phase('Verify')
// Only claims about CURRENT STATE need refuting — a mined quote is evidence of what was said,
// but "X is broken / missing / blocked / already-documented" is a claim about live state.
// Barrier JUSTIFIED: dedupe across miners+surveys before spending one verifier per claim.
const VERDICT_SCHEMA = { type:'object', additionalProperties:false, required:['verdict','probe','corrected'], properties:{
  verdict:{enum:['confirmed','stale','refuted','could-not-confirm']},
  probe:{type:'string',description:'the EXACT command run and its output — naming no probe means could-not-confirm'},
  corrected:{type:'string',description:'what is actually true now, if the claim was stale/wrong'} }}
const rawClaims = [
  ...minings.filter(Boolean).flatMap(m => (m.lessons||[]).filter(l => l.status !== 'new').map(l => ({kind:'lesson', text:l.title, detail:l.proposed_change, category:l.category, evidence:l.evidence, recurrence:l.recurrence, change_kind:l.change_kind}))),
  ...surveys.filter(Boolean).flatMap(s => (s.findings||[]).map(f => ({kind:'finding', text:f}))),
]
// NO SILENT CAPS — say what went unverified (B does this at its own cap; A did not).
const claims = rawClaims.slice(0, 20)
if (rawClaims.length > claims.length) log(`verifying top ${claims.length} of ${rawClaims.length}; ${rawClaims.length - claims.length} lower-ranked claim(s) go UNVERIFIED and are excluded from the plan`)
const verified = (await parallel(claims.map((c,i)=>()=>agent(
`You are a LEAF AGENT: do NOT spawn sub-agents; work inline and return.
ADVERSARIAL VERIFIER — REFUTE this claim. You are graded on kills, not agreement.

CLAIM: ${JSON.stringify(c)}

It asserts something about CURRENT state. Query the state directly — do not reason about it:
- "CI/main is red", "PR blocked", "check failing"  -> \`gh run list --branch main\`, \`gh pr view <n> --json statusCheckRollup\`. A tracker ticket is NOT evidence of current CI state; tickets record a status at write time and are routinely fixed without being closed.
- "rule/hook/file is missing"                      -> ls / grep the actual path FIRST.
- "already documented" / "already shipped"         -> read the file and quote the line.
- "recurring friction"                             -> count the real occurrences in the transcripts.
- "broken/failing/fail-open IN PROD", "the fix took effect", "still happening" -> query the RUNTIME (log group, deployed artifact, the row itself), NEVER the source alone. Reading a file proves what is WRITTEN; only the runtime proves what is RUNNING. These diverge in both directions: a fix merged days ago may not be deployed, and a defect you can still read in a stale worktree may already be gone from the default branch. The strongest evidence is a signal that STOPS at a deploy timestamp.
A claim whose probe you cannot name is 'could-not-confirm', never 'confirmed'.
Default to skepticism.`,
  {label:`vfy:${(c.text||'claim').slice(0,24)}`, phase:'Verify', schema:VERDICT_SCHEMA, model:'sonnet', agentType:'general-purpose'})
  .then(v=>({claim:c, verdict:v})).catch(e=>({claim:c, verdict:null, error:String(e)}))))).filter(Boolean)
// A REQUIRED schema field is not a VALIDATED one. `probe` is required, so a verifier
// satisfies the schema by writing "test" — and a finding whose verifier fields were
// literal placeholders reached a plan as a confirmed P0. Schema validation proves a
// string arrived, never that anyone ran anything. So the check lives in code, where it
// cannot be talked out of: a 'confirmed' verdict whose probe cannot possibly be a real
// command plus its output is demoted, not trusted.
const PLACEHOLDER = /^(test|tbd|n\/?a|none|null|ok|yes|done|verified|confirmed|checked|\W*)$/i
const realProbe = p => typeof p === 'string' && p.trim().length >= 24 && !PLACEHOLDER.test(p.trim())
let demoted = 0
for (const v of verified) {
  if (v.verdict && v.verdict.verdict === 'confirmed' && !realProbe(v.verdict.probe)) {
    v.verdict.verdict = 'could-not-confirm'
    v.verdict.corrected = `[auto-demoted: probe is not a real command+output] ${v.verdict.corrected || ''}`
    demoted++
  }
}
if (demoted) log(`verify: DEMOTED ${demoted} 'confirmed' verdict(s) with a placeholder probe`)

const dead = verified.filter(v=>!v.verdict)
const survivors = verified.filter(v=>v.verdict && v.verdict.verdict==='confirmed')
const killed = verified.filter(v=>v.verdict && !survivors.includes(v))
log(`verify: ${survivors.length} confirmed, ${killed.length} stale/refuted/unconfirmed, ${dead.length} verifier lanes returned nothing (those claims are UNVERIFIED — a dead lane is not a refutation)`)

// status:'new' lessons are not claims about live state, so they never went to Verify — they are
// admissible with full detail. Everything else in the raw lane output is UNVERIFIED and must not
// reach the synthesizer as evidence; pass the narrative reports only.
const netNewLessons = minings.filter(Boolean).flatMap(m => (m.lessons||[]).filter(l => l.status === 'new'))
const laneReports = [...minings, ...surveys].filter(Boolean).map(x => x.report_markdown)

phase('Consolidate')
const PLAN_SCHEMA = { type:'object', additionalProperties:false,
  required:['executive_summary','new_lessons_ranked','prune_list','doc_edits','hooks','memory_updates','sequenced_execution','open_questions'],
  properties:{ executive_summary:{type:'string'}, new_lessons_ranked:{type:'string'}, prune_list:{type:'string'},
    doc_edits:{type:'string',description:'exact AGENTS.md + global CLAUDE.md edits — ADDITIONS from the lesson↔rule correlation (a lesson an existing rule should have prevented → strengthen it or promote to a hook; a lesson with no rule home → add at the right layer) AND prunes/demotions/consolidations from the instructions-file audit (stale rules out; procedures → skills; facts → memory; the AGENTS/CLAUDE pair one-canonical-plus-pointer)'},
    hooks:{type:'string',description:'proposed ~/.claude/settings.json hooks from the recurring-friction lessons + the merge/CI-friction survey — each with its matcher, the PreToolUse/Stop guard, the friction it blocks, and a risk note (a hook can block a tool call, so it dry-runs before commit)'},
    memory_updates:{type:'string'},
    sequenced_execution:{type:'string',description:'prune→vendor→upgrade→docs→guardrails+hooks→memory, each item tagged target-surface + risk'},
    open_questions:{type:'array',items:{type:'object',additionalProperties:false,required:['question','recommendation'],
      properties:{question:{type:'string'},recommendation:{type:'string'}}}} }}
return await agent(
  `Consolidate into ONE sequenced harness-improvement plan. Build it from the CONFIRMED survivors; anything stale/refuted/unconfirmed goes in a "did not survive verification" list WITH its probe, never into the plan and never as a sequencing blocker. NEVER gate the plan on a blocker whose current state you did not query this run. Dedup lessons against existing memory (only NET-NEW or doc'd-but-recurring earn a change).\nVERIFIED SURVIVORS: ${JSON.stringify(survivors)}\nDID NOT SURVIVE: ${JSON.stringify(killed.map(k=>({claim:k.claim.text, verdict:k.verdict?.verdict ?? 'lane-died', probe:k.verdict?.probe ?? 'none — the verifier lane returned nothing', corrected:k.verdict?.corrected ?? ''})))}. Cross-reference EVERY lesson against the instructions-audit survey for the lesson↔rule correlation feeding doc_edits (rule-should-have-prevented-it → strengthen/hook-promote; no-rule-home → add; subject-gone → prune). For EVERY recurring-friction lesson (from the miners) and merge/CI-friction pattern (from the friction survey), decide its routing and record it in 'hooks' when applicable: a settings.json HOOK is the default for a mechanically-detectable wrong move (block it at the tool boundary), a standing CLAUDE.md/AGENTS.md rule is the fallback, and "both" is allowed — a prose rule the model "should remember" is strictly weaker than a hook the harness enforces. Honor the user's rules (never-slice, delete-legacy, single-source-of-truth tracker, fewer-bigger-PRs).\n\nNET-NEW LESSONS (not claims about live state, so not verified — admissible): ${JSON.stringify(netNewLessons)}\n\nLANES THAT RETURNED NOTHING (claim UNKNOWN, not refuted): ${JSON.stringify(dead.map(d=>d.claim?.text))}\n\nLANE REPORTS (narrative context ONLY — NOT evidence): ${JSON.stringify(laneReports)}. Any assertion about CURRENT state — a rule's existence, a hook's presence, CI status, "already shipped" — that appears only in a lane report and not in VERIFIED SURVIVORS is INADMISSIBLE: it may not enter the plan and may not gate or sequence anything. If a lane report makes such a claim look load-bearing, list it under open_questions with the probe that would settle it.\n\nProduce the structured plan.`,
  {label:'consolidate', phase:'Consolidate', schema:PLAN_SCHEMA, model:'opus', effort:'high', agentType:'general-purpose'})
```
