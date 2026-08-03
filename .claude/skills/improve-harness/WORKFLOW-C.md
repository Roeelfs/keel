# Workflow C — agent-stack landscape (periodic / ~quarterly)

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
  ()=>agent(`${PIN}\nBest Claude Code SUBAGENT COLLECTIONS (native .claude/agents/*.md). Search stars-sorted + check the known ones (wshobson/agents, VoltAgent/awesome-claude-code-subagents, contains-studio/agents, 0xfurai). Are any DEEPER than ours, current-model-pinned, permissive-licensed? OURS: ${OURS}. report_markdown + candidates[].`, {label:'stack:subagents', phase:'Discover', schema:CAND, model:'sonnet', agentType:'general-purpose'}),
  ()=>agent(`${PIN}\nBest agent ORCHESTRATION frameworks (claude-flow/ruflo, SuperClaude, claude-squad, crystal, oh-my-claudecode v4 Yeachan-Heo). Do any materially beat our own orchestrator + dynamic Workflow engine WITHOUT re-adding a parallel architecture? report_markdown + candidates[].`, {label:'stack:orch', phase:'Discover', schema:CAND, model:'sonnet', agentType:'general-purpose'}),
  ()=>agent(`${PIN}\nOFFICIAL + frontier: anthropics/claude-agent-sdk, anthropics/skills, superpowers deltas, and adjacent (OpenAI Agents SDK, Google ADK, LangGraph, Agno) — what PATTERN is worth borrowing, harness-class vs app-runtime-class? report_markdown + candidates[].`, {label:'stack:frontier', phase:'Discover', schema:CAND, model:'sonnet', agentType:'general-purpose'}),
  ()=>agent(`${PIN}\nGAP-ANALYZE our owned agents (read ~/.claude/agents/*.md) honestly: which ROLES are missing that contradict our own rules or recur weekly (e.g. refactorer, sql/data, deployment)? Where are ours already deeper? candidates[] = gaps (name=role, repo=best source to mine). report_markdown + candidates[].`, {label:'stack:gaps', phase:'Discover', schema:CAND, model:'sonnet', agentType:'general-purpose'}),
])
phase('Recommend')
const REC = { type:'object', additionalProperties:false, required:['recommendation','landscape_md','adoption_plan','what_to_borrow'], properties:{
  recommendation:{type:'string'}, landscape_md:{type:'string'}, adoption_plan:{type:'string'}, what_to_borrow:{type:'string'} }}
return await agent(`Decide stay/cherry-pick/adopt for a solo operator under one-architecture + ownable-tooling rules. A wholesale parallel framework is almost always wrong (the standing competing-framework rejection); the realistic win is cherry-picking specific MISSING roles + borrowing prompt patterns, PORTED + owned + decoupled + re-model-pinned + domain-invariants-baked-in (a generic specialist ignorant of our invariants is net-negative). Streams: ${JSON.stringify([subs,orch,frontier,gaps].filter(Boolean))}`, {label:'stack-rec', phase:'Recommend', schema:REC, model:'opus', effort:'high', agentType:'general-purpose'})
```
