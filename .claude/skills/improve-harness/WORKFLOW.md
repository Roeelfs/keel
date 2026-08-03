# Investigation Workflows

Two asynchronous `Workflow` scripts. Launch both, then stop — they notify on completion. They are **read-only**: research and design, never mutate. Adapt the inventory/paths to the current machine before launching. `Workflow` is inherently asynchronous; do **not** pass an unsupported `run_in_background` parameter.

Shared rules baked into every agent prompt: *"Investigation only — design the plan, do not mutate. WebFetch / read-only gh / local reads only. No CI polling, no sleep loops, no nested dispatch."*

---

## Workflow A — mine + consolidate

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
  {label:`mine:${i}`, phase:'Mine', schema:LESSON_SCHEMA, agentType:'general-purpose'})))

phase('Survey')
const SURVEY_SCHEMA = { type:'object', additionalProperties:false, required:['report_markdown','findings'], properties:{
  report_markdown:{type:'string'}, findings:{type:'array',items:{type:'string'}} }}
const surveys = await parallel([
  ()=>agent(`Survey GitHub for the period: merged PRs across the repos the user works in, the repos they touch most, and any NEWLY-CREATED repos in their orgs (gh repo list <org> --json name,createdAt). What changed that the harness should know? Return report_markdown + findings[].`, {label:'survey:github', phase:'Survey', schema:SURVEY_SCHEMA, agentType:'general-purpose'}),
  ()=>agent(`Survey GitHub MERGE + CI FRICTION for the period — the friction side, distinct from the merged-PR survey. Find: PRs that were BLOCKED or took many merge attempts, PRs stuck on unresolved review comments, high CI re-run counts, repeated failed checks on the same PR. Use 'gh pr list --state all --json number,title,mergeStateStatus,reviewDecision,statusCheckRollup' and 'gh run list' (read-only). Each RECURRING merge/CI friction pattern is a candidate harness HOOK or rule — e.g. a PreToolUse guard on 'gh pr merge' that refuses while review threads are unresolved (the "stuck 4× on merge before learning to resolve comments first" case). Return report_markdown + findings[] (each friction pattern + its proposed hook/rule).`, {label:'survey:friction', phase:'Survey', schema:SURVEY_SCHEMA, agentType:'general-purpose'}),
  ()=>agent(`Survey your issue tracker (via its MCP if available): recent issue comments + status changes in the active team. Surface decisions/blockers the harness rules or memory should capture. Return report_markdown + findings[].`, {label:'survey:tracker', phase:'Survey', schema:SURVEY_SCHEMA, agentType:'general-purpose'}),
  ()=>agent(`Survey worktrees + memory: 'git worktree list' (prune candidates = merged/stale), and ~/.claude/projects/*/memory/ (MEMORY.md size vs limit, topic drift, uncommitted files). Return report_markdown + findings[].`, {label:'survey:wt-memory', phase:'Survey', schema:SURVEY_SCHEMA, agentType:'general-purpose'}),
  ()=>agent(`Deep-audit the harness: ~/.claude/{agents,commands,hooks,skills} + the skill-lock. Find dead pointers (skills/commands referencing missing engines/files), orphan/misfiled files, never-invoked agents (grep transcripts), and dup/conflicting commands vs native skills. Return report_markdown + findings[] with concrete delete paths.`, {label:'survey:audit', phase:'Survey', schema:SURVEY_SCHEMA, agentType:'general-purpose'}),
  ()=>agent(`Audit the INSTRUCTIONS FILES (read-only): the global ~/.claude/CLAUDE.md + each active repo's AGENTS.md/CLAUDE.md pair (see the skills repo's docs/instructions-files.md for the convention). Find: (1) STALE rules — a rule referencing a file/flow/flag/command that no longer exists; VERIFY each with ls/grep before flagging; (2) DUPLICATION/CONTRADICTION — between the two filenames in one repo (they must be one canonical file + a pointer/symlink, never two divergent contracts — diff them) and between the repo layer and the global layer (the narrower layer wins; flag the shadow copy); (3) DEMOTION candidates — procedure-shaped rules that belong in a skill, fact-shaped entries that belong in memory (an instructions file is a contract, not a manual); (4) BLOAT — sections that grew past what an agent will actually honor. Return report_markdown + findings[] (each = the exact file + a locating quote + the proposed edit/prune/demotion).`, {label:'survey:instructions', phase:'Survey', schema:SURVEY_SCHEMA, agentType:'general-purpose'}),
])

phase('Verify')
// Only claims about CURRENT STATE need refuting — a mined quote is evidence of what was said,
// but "X is broken / missing / blocked / already-documented" is a claim about live state.
// Barrier JUSTIFIED: dedupe across miners+surveys before spending one verifier per claim.
const VERDICT_SCHEMA = { type:'object', additionalProperties:false, required:['verdict','probe','corrected'], properties:{
  verdict:{enum:['confirmed','stale','refuted','could-not-confirm']},
  probe:{type:'string',description:'the EXACT command run and its output — naming no probe means could-not-confirm'},
  corrected:{type:'string',description:'what is actually true now, if the claim was stale/wrong'} }}
const claims = [
  ...minings.flatMap(m => (m.lessons||[]).filter(l => l.status !== 'new').map(l => ({kind:'lesson', text:l.title, detail:l.proposed_change}))),
  ...surveys.flatMap(s => (s.findings||[]).map(f => ({kind:'finding', text:f}))),
].slice(0, 20)
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
  .then(v=>({claim:c, verdict:v}))))).filter(Boolean)
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

const survivors = verified.filter(v=>v.verdict && v.verdict.verdict==='confirmed')
const killed = verified.filter(v=>!survivors.includes(v))
log(`verify: ${survivors.length} confirmed, ${killed.length} stale/refuted/unconfirmed`)

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
  `Consolidate into ONE sequenced harness-improvement plan. Build it from the CONFIRMED survivors; anything stale/refuted/unconfirmed goes in a "did not survive verification" list WITH its probe, never into the plan and never as a sequencing blocker. NEVER gate the plan on a blocker whose current state you did not query this run. Dedup lessons against existing memory (only NET-NEW or doc'd-but-recurring earn a change).\nVERIFIED SURVIVORS: ${JSON.stringify(survivors)}\nDID NOT SURVIVE: ${JSON.stringify(killed.map(k=>({claim:k.claim.text, verdict:k.verdict.verdict, probe:k.verdict.probe, corrected:k.verdict.corrected})))}. Cross-reference EVERY lesson against the instructions-audit survey for the lesson↔rule correlation feeding doc_edits (rule-should-have-prevented-it → strengthen/hook-promote; no-rule-home → add; subject-gone → prune). For EVERY recurring-friction lesson (from the miners) and merge/CI-friction pattern (from the friction survey), decide its routing and record it in 'hooks' when applicable: a settings.json HOOK is the default for a mechanically-detectable wrong move (block it at the tool boundary), a standing CLAUDE.md/AGENTS.md rule is the fallback, and "both" is allowed — a prose rule the model "should remember" is strictly weaker than a hook the harness enforces. Honor the user's rules (never-slice, delete-legacy, single-source-of-truth tracker, fewer-bigger-PRs). MININGS: ${JSON.stringify(minings.filter(Boolean))}\n\nSURVEYS: ${JSON.stringify(surveys.filter(Boolean))}\n\nProduce the structured plan.`,
  {label:'consolidate', phase:'Consolidate', schema:PLAN_SCHEMA, agentType:'general-purpose'})
```

---

## Workflow B — vendor delta: news, changelogs, docs + model pins

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

---

## Workflow C — agent-stack landscape (periodic / ~quarterly)

Survey the best/newest GitHub agent stacks and gap-analyze our owned agents. The landscape moves slowly — run on a deeper pass, not every time. **CRITICAL: live-verify every repo** (`api.github.com/repos/<o>/<r>` for `stargazers_count`/`pushed_at`/`archived`; `/search/repositories?...sort=stars`) — never trust training-data recall for stars/recency/existence, and never trust the npm package name to identify the active repo (an npm-name squatter mis-led a prior run: the real `oh-my-claudecode` is `Yeachan-Heo/...` v4.x, not the 2★ `ragingstar2063/...` that owns the npm name).

```js
export const meta = {
  name: 'agent-stack-landscape',
  description: 'Survey GitHub agent stacks, gap-analyze vs our owned agents, recommend stay/cherry-pick/adopt',
  phases: [{ title: 'Discover' }, { title: 'Recommend' }],
}
const ARGS = typeof args === 'string' ? JSON.parse(args) : args
const OURS = ARGS.ourStack // read ~/.claude/agents/*.md (names, models) + our rules; pass in
const CAND = { type:'object', additionalProperties:false, required:['report_markdown','candidates'], properties:{
  report_markdown:{type:'string'},
  candidates:{type:'array',items:{type:'object',additionalProperties:false,
    required:['name','repo','stars','last_activity','category','maturity','fit','verdict','notes'],
    properties:{ name:{type:'string'}, repo:{type:'string'}, stars:{type:'string'}, last_activity:{type:'string'},
      category:{enum:['subagent-collection','orchestration-framework','agent-os','sdk','skills','meta-list','adjacent-frontier']},
      maturity:{enum:['active','maintained','dormant','archived','unknown']}, fit:{type:'string'},
      verdict:{enum:['adopt','cherry-pick','skip','watch']}, notes:{type:'string'} }}} }}
const PIN = 'Research only. Live-verify every repo on GitHub. No mutation, no polling, no nested dispatch.'
phase('Discover')
const [subs, orch, frontier, gaps] = await parallel([
  ()=>agent(`${PIN}\nBest Claude Code SUBAGENT COLLECTIONS (native .claude/agents/*.md). Search stars-sorted + check the known ones (wshobson/agents, VoltAgent/awesome-claude-code-subagents, contains-studio/agents, 0xfurai). Are any DEEPER than ours, current-model-pinned, permissive-licensed? OURS: ${OURS}. report_markdown + candidates[].`, {label:'stack:subagents', phase:'Discover', schema:CAND, agentType:'general-purpose'}),
  ()=>agent(`${PIN}\nBest agent ORCHESTRATION frameworks (claude-flow/ruflo, SuperClaude, claude-squad, crystal, oh-my-claudecode v4 Yeachan-Heo). Do any materially beat our own orchestrator + dynamic Workflow engine WITHOUT re-adding a parallel architecture? report_markdown + candidates[].`, {label:'stack:orch', phase:'Discover', schema:CAND, agentType:'general-purpose'}),
  ()=>agent(`${PIN}\nOFFICIAL + frontier: anthropics/claude-agent-sdk, anthropics/skills, superpowers deltas, and adjacent (OpenAI Agents SDK, Google ADK, LangGraph, Agno) — what PATTERN is worth borrowing, harness-class vs app-runtime-class? report_markdown + candidates[].`, {label:'stack:frontier', phase:'Discover', schema:CAND, agentType:'general-purpose'}),
  ()=>agent(`${PIN}\nGAP-ANALYZE our owned agents (read ~/.claude/agents/*.md) honestly: which ROLES are missing that contradict our own rules or recur weekly (e.g. refactorer, sql/data, deployment)? Where are ours already deeper? candidates[] = gaps (name=role, repo=best source to mine). report_markdown + candidates[].`, {label:'stack:gaps', phase:'Discover', schema:CAND, agentType:'general-purpose'}),
])
phase('Recommend')
const REC = { type:'object', additionalProperties:false, required:['recommendation','landscape_md','adoption_plan','what_to_borrow'], properties:{
  recommendation:{type:'string'}, landscape_md:{type:'string'}, adoption_plan:{type:'string'}, what_to_borrow:{type:'string'} }}
return await agent(`Decide stay/cherry-pick/adopt for a solo operator under one-architecture + ownable-tooling rules. A wholesale parallel framework is almost always wrong (the standing competing-framework rejection); the realistic win is cherry-picking specific MISSING roles + borrowing prompt patterns, PORTED + owned + decoupled + re-model-pinned + domain-invariants-baked-in (a generic specialist ignorant of our invariants is net-negative). Streams: ${JSON.stringify([subs,orch,frontier,gaps].filter(Boolean))}`, {label:'stack-rec', phase:'Recommend', schema:REC, agentType:'general-purpose'})
```

---

## Workflow D — production-stability / regression RCA (conditional)

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
  {label:`rca:${i.id}`, phase:'RCA', schema:RCA, agentType:'general-purpose'})))

phase('Synthesize')
const TAX = { type:'object', additionalProperties:false, required:['report_markdown','failure_classes','cross_cutting'], properties:{
  report_markdown:{type:'string'},
  failure_classes:{type:'array',items:{type:'object',additionalProperties:false,required:['id','name','common_root','incident_ids','blast'],properties:{
    id:{type:'string'}, name:{type:'string'}, common_root:{type:'string',description:'single shared MECHANISM, not symptom'}, incident_ids:{type:'array',items:{type:'string'}}, blast:{type:'string'} }}},
  cross_cutting:{type:'array',items:{type:'string'},description:'hot-zone files (few, high-blast); parallel-session role; local-green-insufficiency; repeated-fix chains'} }}
const tax = await agent(`Cluster these RCAs into failure CLASSES by shared root MECHANISM (not symptom). Surface cross-cutting: (1) hot-zone files — a few high-blast files own most incidents; (2) uncoordinated parallel sessions on the same substrate; (3) where local-green is necessary-but-insufficient; (4) repeated-fix chains. RCAs: ${JSON.stringify(rcas.filter(Boolean))}`, {label:'synthesize', phase:'Synthesize', schema:TAX, agentType:'general-purpose'})

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
  fc=>agent(`Design ONE cheap guardrail that converts failure class ${JSON.stringify(fc)} from prod/deploy-only into a LOCAL-GREEN FAILURE (or, for a process/doc class, the smallest enforceable rule). Prefer synth-time/static (no cloud creds, runs inside the local verify) over CI-only or bake-only. GREP for an existing in-repo pattern to extend. State whether a NAIVE version could pass while the bug exists (the "present-anywhere" trap) and how to avoid it. Tag the lever (documentation/ci/harness/cross-session/research-grounding/standing-invariant).`, {label:`mitigate:${fc.id}`, phase:'Mitigate+Verify', schema:MIT, agentType:'general-purpose'}),
  (mit,fc)=>agent(`ADVERSARIAL verifier — your job is to REFUTE that this guardrail works. For EACH incident in the class: if the guardrail existed the day before, would the bad PR have FAILED a local check? Walk the real mechanism. Default to skepticism — unsure → "partial"/"insufficient", never "catches". Probe specifically: (1) trigger keyed on fix-introduced artifacts (stays green for the bug's whole life); (2) assertion present-anywhere vs on-the-real-surface (a grant on the actual role, not "somewhere"); (3) test-exists vs test-exercises-the-failing-path; (4) guardrail mis-scoped to a broader class than it covers. GUARDRAIL: ${JSON.stringify(mit)} CLASS: ${JSON.stringify(fc)}`, {label:`verify:${fc.id}`, phase:'Mitigate+Verify', schema:VERDICT, agentType:'general-purpose'}).then(v=>({class:fc, mitigation:mit, verdict:v})))

phase('Program')
const PROG = { type:'object', additionalProperties:false, required:['executive_summary','hot_zones','prioritized_guardrails','cross_session_coordination','rca_checklist','tracker_issues'], properties:{
  executive_summary:{type:'string',description:'single biggest leverage point for prod stability'},
  hot_zones:{type:'array',items:{type:'object',additionalProperties:false,required:['files','why_hot','contract','gate'],properties:{files:{type:'string'},why_hot:{type:'string'},contract:{type:'string',description:'implicit contract to make explicit+tested'},gate:{type:'string'}}}},
  prioritized_guardrails:{type:'array',items:{type:'object',additionalProperties:false,required:['rank','name','lever','prevents','effort','leverage'],properties:{rank:{type:'number'},name:{type:'string'},lever:{type:'string'},prevents:{type:'string'},effort:{type:'string'},leverage:{type:'string'}}}},
  cross_session_coordination:{type:'string'}, rca_checklist:{type:'string'}, tracker_issues:{type:'array',items:{type:'string'}} }}
return await agent(`Synthesize a tight, ACTIONABLE production-stability program from the verified guardrails. (1) exec summary + the single biggest leverage point; (2) hot zones — the few high-blast files, each with its now-explicit contract + the gate a change must pass; (3) prioritized guardrails ranked by leverage/effort — favor those that convert deploy-only defects to local-green RED, spanning the levers (documentation / CI / harness / cross-session / research-grounding / standing-invariant); (4) a low-ceremony cross-session coordination mechanism on EXISTING primitives (a hot-zones list + a deploy-ledger so an RCA can diff onset-vs-deploy-time; do NOT serialize all work — the real cost is RCA-misdirection, not line collisions); (5) the RCA-process hardening checklist; (6) 4–8 issue-ready tracker titles+priorities. Honor never-slice / delete-legacy / solo-operator (no heavyweight process). Drop any guardrail the verifier rated 'insufficient' unless its refinement is applied. VERIFIED: ${JSON.stringify(guarded.filter(Boolean))}\nTAXONOMY: ${JSON.stringify(tax)}`, {label:'program', phase:'Program', effort:'high', schema:PROG, agentType:'general-purpose'})
```

**The load-bearing choices to keep when you adapt it:** one agent *per incident* (aggregation confabulates); the `why_passed_local_green` + `earliest_cheap_signal` fields (the whole point); the Mitigate→Verify `pipeline` where a *separate* skeptic refutes each guardrail; the four false-security probes; `effort:'high'` only on Program; and lever-tagging so the program's fixes route to docs / CI / harness / cross-session / research / standing-invariant — not just code. Its output feeds step 2's reconcile and lands in step 4 as guardrail-adds across your harness surfaces.

---

## Workflow E — context & compaction economics (every run)

Fires **every time**. The other lanes ask "is the harness correct?"; this one asks **"what is it costing, and is that improving?"** Its output is a dated report plus one appended row in a persistent ledger, so the trend is visible across runs instead of being re-derived from scratch each time.

**Why it is standing, not conditional.** Measured on one real harness over 7 days: **20.4B context tokens read on the main loop = 51,236 turns × ~399k average context**, against 91.2M output tokens — a **~220:1 context-to-output ratio**. The cost equation is `turns × context_size × model_weight`; output length is a rounding error. Nobody notices this without measuring, because every individual turn feels cheap.

**Analyze in a subagent, never inline** — the raw transcripts are hundreds of MB and reading them in the main loop is itself the anti-pattern this lane exists to find.

### The metrics that matter (compute these, don't editorialize)

Parse the local transcripts (`~/.claude/projects/*/*.jsonl`; also `~/.codex/sessions/**/rollout-*.jsonl` where a second runtime is in play):

1. **Context per turn** — total, median, p90, max; and the share of all context read by turns above ~150k (expect a brutal Pareto: ~86% of turns → ~96% of context).
2. **Fixed preamble** — the session-minimum per-turn floor (system prompt + instructions files + MCP schemas + skill/plugin descriptions) and its share. This is paid on *every* turn, so it is the highest-leverage single number.
3. **Accumulated-payload composition** — `tool_result` vs `tool_use` params vs assistant/user text. Tool traffic usually dominates (~76%), which is what justifies the delegate-reads rule.
4. **Compaction behavior** — count reset events and the **peak-before-reset** distribution (median/p90/max). This is the ONLY empirical read on where compaction actually fires, and it is how you verify a threshold knob is doing what you think.
5. **Subagent context peaks** — median/p90/p99/**max**, and the count above the main-thread cap. This is what licenses (or forbids) an asymmetric cap.
6. **Model mix by output tokens**, main loop and subagents separately — a permissive routing default silently becomes a top-tier default (one measured case: the top model took 61.9% of subagent output while the cheapest took 0.2%).
7. **Session-shape outliers** — the few longest sessions and their `turns × avg_ctx` product; the worst is often >1B tokens alone.
8. **Separate-billing-pool usage** — how much work went to a runtime billed outside the primary window (under-use is free capacity left on the table).

### Knob-conformance audit (the part that catches real bugs)

Verify the compaction/truncation knobs are set **coherently**, and ground every claim in the docs or in strings from the installed CLI binary — never in recollection:

- **Compose the effective threshold from all knobs at once.** A window-size var and a percentage-override var **multiply**; setting one can silently *activate* a dormant other. Real near-miss: a percentage override sat inert for months (compaction empirically fired at ~915k), and setting a window var would have activated it → a **4× tighter** cap than intended, also compacting the top ~10% of research lanes. **A knob sitting inert is not evidence it is harmless — check what activates it before setting a related one.**
- Reconcile the *documented* threshold against the *measured* peak-before-reset from metric 4. A gap means a knob isn't being honored — report it as UNVERIFIED rather than asserting the intended value.
- Confirm each var actually exists in the installed binary (`strings -a <cli binary> | grep -F <VAR>`); a plausible-but-nonexistent env var is worse than a documented gap. Report per item: **verified fact / inference / could-not-confirm.**
- Check whether automatic incremental compaction (stale-`tool_result` clearing) is present and whether it is configurable at all — if it prunes tool output first, that is an independent argument for persisting large outputs to files, since inline evidence gets replaced by a placeholder.
- Check the per-blast truncation knobs (bash/MCP output caps, tool-schema deferral) and whether compaction-steering instructions exist in the instructions files.

### Output contract — one dated report + one ledger row

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
  {label:'measure', phase:'Measure', schema:METRICS, agentType:'general-purpose'})

phase('Audit')
const k = await agent(`${PIN}\nAudit the context/compaction knobs. Read the live settings + env, then ground EVERY claim in official docs or in strings from the installed CLI binary — state which. COMPOSE the effective threshold from all knobs TOGETHER (a window var and a percentage var multiply; setting one can activate a dormant other), then reconcile it against the MEASURED peak-before-reset: ${JSON.stringify(m?.compaction ?? {})}. A mismatch means a knob is not honored — report UNVERIFIED, do not assert the intended value. Mark each finding verified / inferred / could-not-confirm; "could not confirm" is a better answer than a plausible wrong config key.`,
  {label:'audit', phase:'Audit', schema:KNOBS, agentType:'general-purpose'})

phase('Report')
const REPORT = { type:'object', additionalProperties:false, required:['report_markdown','trend_row','recommendations','failed_interventions'], properties:{
  report_markdown:{type:'string',description:'full dated report body'},
  trend_row:{type:'string',description:'ONE markdown table row for TRENDS.md'},
  recommendations:{type:'array',items:{type:'object',additionalProperties:false,required:['rank','change','surface','expected_effect','risk'],properties:{
    rank:{type:'number'}, change:{type:'string'}, surface:{enum:['settings','instructions-file','hook','skill','workflow-habit','plugin/mcp-roster']},
    expected_effect:{type:'string',description:'which measured number should move, and by how much'}, risk:{type:'string'} }}},
  failed_interventions:{type:'array',items:{type:'string'},description:'changes made last run whose target metric did NOT move — name them plainly'} }}
return await agent(`Write the dated context-economy report + ONE TRENDS.md row. Read the PREVIOUS report and TRENDS.md from the harness repo's analytics/context-economy/ first and diff against them — the trend is the product, not the snapshot. Every recommendation must name the specific measured number it should move and by roughly how much, so the NEXT run can falsify it. Call out any prior change whose target metric did not move as a FAILED intervention rather than silently re-tuning. Order by leverage: the fixed preamble and turn-count multipliers beat per-response savings. METRICS: ${JSON.stringify(m)} KNOBS: ${JSON.stringify(k)}`,
  {label:'report', phase:'Report', effort:'high', schema:REPORT, agentType:'general-purpose'})
```

**The load-bearing choices to keep when you adapt it:** measurement in a subagent (never inline); the composed effective threshold reconciled against measured behavior (the multiply trap); `verified / inferred / could-not-confirm` on every knob claim; the append-only trend ledger; and `expected_effect` naming a falsifiable number so the next run can grade the last one. Its output feeds step 2's reconcile and lands in step 4 as settings/instructions/hook changes.

---

## Launching

**The `args` trap — always unwrap it.** `args` can arrive at the script as a JSON **string**, not the object you passed; `args.foo` is then `undefined` and the script dies on the first `.map` (observed 2026-07-24: Workflow A crashed instantly on `BUCKETS.map`). Every template above therefore opens with `const ARGS = typeof args === 'string' ? JSON.parse(args) : args`. Never read `args.foo` directly.

Read the live inventory inline first (`~/.claude/plugins/*.json`, `ls -t ~/.claude/projects/*/*.jsonl` **and** `ls -t ~/.codex/sessions/*/*/*/rollout-*.jsonl` — bucket BOTH runtimes for Workflow A, and for C `~/.claude/agents/*.md`), pass it as `args`, launch the Workflows, then **stop and wait** for the completion notifications. Do not poll.
