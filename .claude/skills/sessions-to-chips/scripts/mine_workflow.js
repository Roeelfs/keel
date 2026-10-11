export const meta = {
  name: 'mine-sessions-to-chips',
  description: 'Mine N Claude sessions in parallel for overall goal + exact continuation point to author resume chips',
  phases: [
    { title: 'Mine', detail: 'one read-only agent per session' },
    { title: 'Consolidate', detail: 'one sonnet reviewer per category group proposes merges/drops across the mined sessions' },
    { title: 'Manage', detail: 'one read-only synthesis agent per category group -> manager chip + map + sub-chip specs' },
  ],
}

// Invoke via the Workflow tool:
//   Workflow({ scriptPath: "<skill>/scripts/mine_workflow.js",
//             args: { mineScript: "<skill>/scripts/mine_session.py",
//                     sessions: [ { idx, title, cli, worktreeName, branch, pr, transcript }, ... ] } })
// OPTIONAL `groups` (from group_sessions.py): [{ category, manager:{title,cli}|null, memberClis:[cli,...] }].
//   When present, phase 2 synthesizes ONE manager chip per group from the mined results.
//   Phase 2 (Consolidate) reviews the mined group and merges what is clearly one piece of work;
//   the rest is handed to the manager as decisions it owns (see MANAGER_PLAYBOOK.md).
//   Returns { ok, failed, consolidations, managers:[{category, managerTitle, managerTldr, managerPrompt, mapMarkdown, subChips[]}] }.
// Pass `transcript` (abs path from find_transcript.py) so agents don't re-glob.
// Pass `title` VERBATIM — it is the desktop session name and becomes the chip title unchanged.
// GOTCHAS baked in: `args` can arrive as a STRING (JSON.parse it); `process` is undefined;
// Date.now()/Math.random() throw. Agents are READ-ONLY (no verify / heavy ops / push).

const input = typeof args === 'string' ? JSON.parse(args) : args
const sessions = input.sessions
const mineScript = input.mineScript

const SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['idx', 'title', 'branch', 'worktree', 'prState', 'sessionGoal', 'lastState', 'continuationPhrase', 'gitState', 'remainingWork', 'isComplete', 'chipTitle', 'chipTldr', 'chipPrompt'],
  properties: {
    idx: { type: 'number' },
    title: { type: 'string', description: 'the ORIGINAL desktop session title, passed in, echoed back verbatim' },
    branch: { type: 'string' },
    worktree: { type: 'string', description: 'absolute worktree path' },
    prState: { type: 'string', description: 'MERGED / OPEN / CLOSED / NO_PR, plus CI rollup if OPEN' },
    sessionGoal: { type: 'string', description: 'The OVERALL mission in 2-4 sentences — the OUTCOME / victory-condition the session was driving toward, mined from ORIGINAL GOAL + USER STEERING ARC + the summary\'s "Primary Request and Intent", NOT just the last step and NOT a flat list of activities touched. PIVOTS: if the goal evolved (the summary often flags a "MOST RECENT / CRYSTALLIZING REQUEST"), LEAD with the CURRENT crystallized mission and note the pivot from the original framing in one clause (the session title may still reflect the old framing — bridge it). COMPLETION HONESTY: state the victory-condition as still-open if it is; never write "culminating in <X>" when <X> (bake / merge / validation) never actually happened.' },
    lastState: { type: 'string', description: '3-6 sentences: what the session actually accomplished against the goal, and the EXACT terminal state — distinguish DONE from the unmet victory-condition. Name the precise stop reason: weekly limit mid-task, awaiting bake, PR open, interrupted before the last step, a sub-agent/executor dispatched but not yet reported, or blocked on another ticket (e.g. "blocked on ABC-139"). Do not imply more finished than the transcript shows.' },
    continuationPhrase: { type: 'string', description: 'THE deliverable. A single paste-ready instruction, in the user\'s own imperative voice, that resumes the mission from the EXACT point it stopped — as if the user typed it to pick up the thread. NOT "do the last mission from the session". Name the concrete next action AND enough of the goal to orient (e.g. "Resume the ABC-397 nightly-timeout fix: the per-op timeout guard is committed but unverified — run your project\'s verify gate, then open the PR and bake the nightly job against staging."). TERMINAL-STATE GROUNDING (hard rule): read LAST ASSISTANT TEXT + the summary\'s Next-Step and NEVER propose a step the session explicitly ruled out or already settled — e.g. do not say "push" when it established no write access or deliberately committed locally; do not say "present results" when they were already presented. If a sub-agent was dispatched and hadn\'t reported, the next action is "check that agent\'s result"; if blocked on another ticket, it is "unblock <ticket>, then <the true end-game>". Point at the FRONTIER — the first not-yet-done step — never an already-completed sub-task, and when the tail is bookkeeping (commit/save-state/handoff), give the mission\'s next substantive action, not "redo the wrap-up". 1-3 sentences, concrete, grounded.' },
    gitState: {
      type: 'object', additionalProperties: false,
      required: ['uncommitted', 'unpushed', 'summary'],
      properties: {
        uncommitted: { type: 'boolean' },
        unpushed: { type: 'boolean', description: 'true if local commits are NOT on origin (a fresh worktree would miss them)' },
        summary: { type: 'string' },
      },
    },
    remainingWork: { type: 'array', items: { type: 'string' }, description: 'concrete ordered steps to truly finish the mission. Empty if genuinely complete.' },
    isComplete: { type: 'boolean', description: 'true ONLY if PR MERGED AND post-merge tail (bake/verify, issue closed, no self-named follow-up) is also done.' },
    chipTitle: { type: 'string', description: 'The ORIGINAL session title (the `title` field) echoed back VERBATIM — keep the name the user recognizes. Do NOT rewrite it into a new imperative. Only trim trailing detail if it exceeds ~70 chars, never the recognizable lead.' },
    chipTldr: { type: 'string', description: '1-2 plain-English sentences; no file paths/code — the mission + what resuming it does.' },
    chipPrompt: { type: 'string', description: 'SELF-CONTAINED cold-start prompt for a fresh zero-memory session, structured: (1) OVERALL GOAL — the sessionGoal so the new session inherits the mission, not just a task; (2) WHAT IS DONE — concrete progress + worktree path + branch + PR #/state; (3) WHERE IT STOPPED — the exact interruption point; (4) CONTINUE FROM HERE — the continuationPhrase verbatim as the opening directive; (5) REMAINING STEPS — ordered, with file paths + how to verify. If gitState.uncommitted OR gitState.unpushed, START the whole prompt with a ⚠️ WORKTREE NOTE telling the spawned session to `cd` into the existing worktree (spawn_task makes a FRESH worktree and would lose the work). End with your project\'s dispatch discipline: verify locally (your project\'s verify gate, plus a typecheck), run the full verify gate once when green, push once, do NOT poll CI.' },
  },
}

const results = await parallel(sessions.map((s) => () =>
  agent(
`Deep-mine ONE finished/paused Claude Code session so a "resume chip" can be authored that carries its OVERALL GOAL and the EXACT phrase to continue from where it stopped — not a vague "do the last thing". READ-ONLY: do not edit files, build, test, verify, run any heavy op, or push. Only read, git status/log, and gh.

SESSION (title is the user-facing name — preserve it):
- idx: ${s.idx}
- title (KEEP VERBATIM as chipTitle): ${s.title}
- branch: ${s.branch}
- worktree: ${s.worktreeName ? '~/code/.../.claude/worktrees/' + s.worktreeName : '(see transcript)'}
- PR: ${s.pr && s.pr !== '-' ? '#' + s.pr : 'NONE'}
- transcript JSONL: ${s.transcript || '(find by cliSessionId ' + s.cli + ' under ~/.claude/projects/*/)'}

STEPS
1. \`python3 ${mineScript} <transcript-path>\` → prints, in this order: SESSION OVERVIEW, ORIGINAL GOAL (first human message), USER STEERING ARC (every human turn oldest→newest — the evolving intent), LATEST SESSION SUMMARY (the freshest compaction digest — canonical "Primary Request and Intent / Pending Tasks / Next Step" — the richest single source for goal+state), EXACT LAST USER INSTRUCTION, LAST USER MESSAGE, LAST ASSISTANT TEXT, LATEST TODOS, RECENT TOOL USES.
2. REASON over the WHOLE arc, not just the tail:
   - sessionGoal = synthesize ORIGINAL GOAL + STEERING ARC + the "Primary Request and Intent" of the LATEST SESSION SUMMARY into the through-line mission — stated as the OUTCOME/victory-condition, not a list of activities. If the arc pivoted, capture the CURRENT crystallized goal (summaries flag a "MOST RECENT / CRYSTALLIZING REQUEST") and note the pivot in one clause.
   - lastState = what got done against that goal + the precise terminal state (read LAST ASSISTANT TEXT + LATEST TODOS + RECENT TOOL USES + the summary's "Pending Tasks"/"Next Step").
   - continuationPhrase = the user's-voice imperative that resumes from that exact point (lean on EXACT LAST USER INSTRUCTION + the summary's Next-Step for the literal next action; never output "continue the last mission").

   PIVOT & TERMINAL-STATE DISCIPLINE (this is where surface-level chips fail — apply rigorously):
   - PIVOT: many sessions drift (e.g. "fix ABC-40" → a broader ABC-314 epic → a narrow ABC-328 sub-fix; or "merge the test plan" → "audit every page"). Do NOT flatten original+evolved into one bland list. LEAD sessionGoal with the CURRENT mission, name the pivot, and remember the chipTitle stays the ORIGINAL name — so the chipPrompt's GOAL line must bridge title↔current-goal.
   - DON'T OVERCLAIM: if the session STOPPED SHORT of its victory-condition (validation not run, bake not done, PR not opened, an executor sub-agent dispatched but not yet reported back), say exactly that. Never describe an end-state ("culminating in production baking") that the transcript does not show reaching.
   - DON'T INVENT RULED-OUT STEPS: scan LAST ASSISTANT TEXT for explicit "nothing pushed / no write access / deliberately local / can't / already done / already presented" facts and honor them. A continuationPhrase that proposes a step the session explicitly ruled out (the classic: "push to origin/main" when there is no write access) is a hard FAIL — it would break on the first action.
   - IN-FLIGHT / BLOCKED are first-class stop-states: in-flight dispatched work → "check <agent>'s result, then …"; blocked → "unblock <ticket>, then <the true end-game>".
   - FRONTIER, not the literal last keystroke: the continuation must be the FIRST not-yet-done substantive step toward the goal. Two traps: (a) do NOT point at a sub-task already COMPLETED earlier in the arc (cross-check the summary's progress + RECENT TOOL USES for what's done — "resume the sweep" is wrong if the sweep already finished and its output was saved); (b) do NOT treat a pure WRAP-UP / handoff step as the mission — when the tail is bookkeeping ("commit locally", "save state so a future session can resume", "bake the resume doc"), the next substantive action is the mission's Next-Step / top pending item read from the summary + persisted state, NOT redoing the wrap-up.
   - SELF-AUTHORED HANDOFF wins: if the session wrote its OWN resume/handoff artifact (e.g. "session-resume-YYYY-MM-DD.md", a "Resume path:" block, a stated "Next Step / Optional Next Step") in LAST ASSISTANT TEXT or the summary, ANCHOR the continuationPhrase on THAT — name the artifact to load and lead with its named first action/priority (e.g. "load session-resume-YYYY-MM-DD.md and execute its ranked next-step: present the top-priority item, drive the auto-fillable ones, hand the rest off paste-ready") instead of re-deriving your own plan. The session already decided what's next; carry it forward verbatim, don't reinvent it.
3. If you need more than the script prints, \`tail -c 160000 <transcript-path>\` and grep — do NOT load the whole multi-MB file.
4. Worktree git state (may be pruned — handle "No such file"): \`git -C <worktree> status --short\`, \`git -C <worktree> log --oneline -8\`, \`git -C <worktree> log --oneline origin/main..HEAD\` (unpushed commits = work a fresh worktree would miss). If gone, set gitState.summary "worktree pruned" and lean on PR + transcript.
5. PR state (if a PR #): \`gh pr view <#> --json state,title,url,mergedAt,mergeStateStatus,statusCheckRollup\`. If NO PR: \`git ls-remote --heads origin <branch>\`.
6. Lightly ground remaining work where the transcript names a follow-up (issue ID in title, "bake on staging" tail, open review). You MAY grep + read your project's instruction files (CLAUDE.md / AGENTS.md). Do NOT attempt the work.

JUDGEMENT
- chipTitle = the ORIGINAL title above, VERBATIM. Do not invent a new imperative title; the user navigates by these names.
- isComplete=true ONLY if PR MERGED AND the post-merge tail it itself named (bake/verify, issue close) is done. A merged PR with a "now bake / verify in prod / follow-up <ticket>" tail is NOT complete.
- remainingWork: OPEN PR → review+merge(+bake); NO PR but commits → finish, verify, open PR; interrupted mid-task (weekly limit) → resume from the exact interruption point; complete → empty.
- chipPrompt MUST be self-contained for a zero-memory agent and follow the 5-part structure (GOAL → DONE → STOPPED → CONTINUE-FROM-HERE [continuationPhrase verbatim] → REMAINING STEPS). If gitState.uncommitted/unpushed, OPEN with the ⚠️ WORKTREE NOTE (cd into the existing worktree; spawn_task makes a fresh one).

Return ONLY the structured object.`,
    { label: `mine:${s.worktreeName || s.idx}`, phase: 'Mine', schema: SCHEMA, agentType: 'Explore', model: 'sonnet' }
  ).then(r => r ? { ...r, idx: s.idx, _cli: s.cli } : { idx: s.idx, _failed: true, title: s.title })
))

const ok = results.filter(r => r && !r._failed)
const failed = results.filter(r => !r || r._failed)
log(`mined ${ok.length}/${sessions.length} sessions; ${failed.length} failed`)

// ---- Phase 2: one manager per category group -------------------------------------------
const groups = input.groups || []
const MGR_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['category', 'managerTitle', 'managerTldr', 'managerPrompt', 'mapMarkdown', 'subChips'],
  properties: {
    category: { type: 'string' },
    managerTitle: { type: 'string', description: 'If the group has a real top-level session: "[Manager] " + its ORIGINAL title verbatim. Otherwise "[Manager] <category>".' },
    managerTldr: { type: 'string', description: '1-2 plain sentences: the category mission + that this session coordinates N sub-sessions, it does not do their work.' },
    managerPrompt: { type: 'string', description: 'LEAN cold-start prompt for the manager (<= ~1500 chars): CATEGORY GOAL (one outcome), the MAP PATH to read first (the caller fills in `{{MAP_PATH}}` and `{{CHIPS_PATH}}` verbatim — keep the placeholders; add {{PLAYBOOK_PATH}} as the decision playbook for the manager), the manager contract (spawn each sub-chip from the chips file in dependsOn order via spawn_task, skip isComplete, never do sub-session work itself, update the map status table as chips report, one decision at a time to the human), and any category-level GATE (prod mutation, founder decision). Pointers, not payloads — the map holds the detail.' },
    mapMarkdown: { type: 'string', description: 'The MAP document the manager reads (full detail lives here, not in the prompt): (1) category goal + victory-condition; (2) a status table, one row per sub-session: title | state (done / open PR / blocked / interrupted / not started) | PR+branch | what remains | dependsOn; (3) ordering + which sub-sessions are independent (parallel) vs sequenced; (4) cross-session overlap/conflicts (two sessions touching one file/ADR/ticket) and who owns it; (5) category-level open decisions; (6) for the manager itself: its own prior state if it is a real session.' },
    subChips: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        required: ['cli', 'mergedFrom', 'title', 'tldr', 'prompt', 'dependsOn', 'spawn'],
        properties: {
          cli: { type: 'string', description: 'cliSessionId of the mined sub-session this chip resumes (for a merged unit: the first member)' },
          mergedFrom: { type: 'array', items: { type: 'string' }, description: 'cli ids folded into this chip by a high-confidence merge; just [cli] when not merged.' },
          title: { type: 'string', description: 'chipTitle verbatim' },
          tldr: { type: 'string' },
          prompt: { type: 'string', description: 'the mined chipPrompt, unchanged except: add one line "Your manager is the session titled <managerTitle>; report your PR/outcome there." and keep the ⚠️ WORKTREE NOTE first when present.' },
          dependsOn: { type: 'array', items: { type: 'string' }, description: 'cli ids that must land/report first. Empty when independent.' },
          spawn: { type: 'boolean', description: 'false when the sub-session isComplete (report only, no chip).' },
        },
      },
    },
  },
}

const CONS_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['category', 'merges', 'drops', 'keepSeparate', 'managerDecisions'],
  properties: {
    category: { type: 'string' },
    merges: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        required: ['memberClis', 'mergedTitle', 'mergedGoal', 'rationale', 'confidence'],
        properties: {
          memberClis: { type: 'array', items: { type: 'string' }, description: '2+ cli ids that are really ONE piece of work (same ticket/artifact, one is a strict subset or a follow-up of the other, or they would edit the same files).' },
          mergedTitle: { type: 'string', description: 'The ORIGINAL title of the member that carries the mission (verbatim), not a new invented name.' },
          mergedGoal: { type: 'string', description: 'One outcome sentence covering all members.' },
          rationale: { type: 'string', description: 'Cite the concrete overlap: shared ticket id, file, ADR, or one session\'s output feeding the other.' },
          confidence: { type: 'string', enum: ['high', 'medium', 'low'], description: 'high = same ticket/artifact or strict subset, safe to apply with no human or manager judgement. medium/low = plausible; the manager decides.' },
        },
      },
    },
    drops: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false, required: ['cli', 'reason'],
        properties: { cli: { type: 'string' }, reason: { type: 'string', description: 'superseded by <cli>, duplicate of <cli>, or already done — name the evidence.' } },
      },
    },
    keepSeparate: { type: 'array', items: { type: 'string' }, description: 'cli ids that look related but must stay separate, with the reason appended after a colon.' },
    managerDecisions: { type: 'array', items: { type: 'string' }, description: 'Judgement calls you could not settle from the mined data (ordering, ownership, scope cut, merge vs split). Each one phrased as a question with your recommended answer. 0-5 items; empty is fine.' },
  },
}

const consolidations = await parallel(groups.map((g) => () => {
  const members = ok.filter(r => (g.memberClis || []).includes(r._cli))
  return agent(
`You are the CONSOLIDATION REVIEWER for ONE category of Claude Code sessions. READ-ONLY. The goal is FEWER, more concise units of work with no lost obligations — not a tidy-looking list.

CATEGORY: ${g.category}
MINED SESSIONS (JSON):
${JSON.stringify(members.map(m => ({ cli: m._cli, title: m.title, sessionGoal: m.sessionGoal, lastState: m.lastState, remainingWork: m.remainingWork, isComplete: m.isComplete, prState: m.prState, branch: m.branch, gitState: m.gitState })), null, 1)}

JUDGE
- MERGE only when two or more sessions are one piece of work: same ticket/artifact, one a strict subset or direct follow-up of another, or they would edit the same files. Different tickets that merely share a theme are NOT merges.
- A merge never loses a remainingWork item: the union must survive. If a merged unit would exceed one session's reasonable scope (more than ~3 independent deliverables), downgrade confidence to medium.
- DROP only with named evidence (superseded by / duplicate of / already merged+baked). Never drop for being old.
- Anything you cannot settle from the data goes to managerDecisions with your recommended answer. Do not guess.
- confidence=high ONLY where a wrong merge is cheap to undo and the evidence is a shared ticket id or identical artifact.
Return ONLY the structured object.`,
    { label: `consolidate:${g.category}`.slice(0, 60), phase: 'Consolidate', schema: CONS_SCHEMA, agentType: 'general-purpose', model: 'sonnet' }
  ).then(r => r || { category: g.category, _failed: true })
}))
log(`consolidated ${consolidations.filter(c => c && !c._failed).length}/${groups.length} groups`)

const managers = await parallel(groups.map((g, gi) => () => {
  const members = ok.filter(r => (g.memberClis || []).includes(r._cli))
  const cons = consolidations[gi] && !consolidations[gi]._failed ? consolidations[gi] : { merges: [], drops: [], keepSeparate: [], managerDecisions: [] }
  return agent(
`You are the MANAGER-AUTHOR for ONE category of Claude Code sessions. READ-ONLY: no edits, no builds, no pushes. Your input is the already-mined result for every sub-session in the category; you do not re-mine transcripts.

CATEGORY: ${g.category}
TOP-LEVEL (manager) SESSION: ${g.manager ? g.manager.title + ' [' + g.manager.cli + ']' : '(none — synthetic manager)'}

MINED SUB-SESSIONS (JSON):
${JSON.stringify(members, null, 1)}

CONSOLIDATION REVIEW (a prior reviewer's proposals):
${JSON.stringify(cons, null, 1)}

Produce the manager chip, the MAP, and one sub-chip spec per sub-session (spawn=false for isComplete ones).
RULES
- If the TOP-LEVEL session appears in MINED SUB-SESSIONS (its cli matches), it is the manager's OWN prior state: put it in the map section 6 and in managerPrompt's goal, and do NOT emit a subChip for it.
- APPLY merges whose confidence is "high": emit ONE subChip for the merged unit (cli = the first memberClis entry, mergedFrom = all memberClis, prompt = a single 5-part prompt whose REMAINING STEPS is the union of the members'). Do NOT apply medium/low merges: list each in the map under "Decisions owed to the manager" with its rationale and your recommendation, and keep the members as separate subChips until the manager decides.
- Honour drops (spawn=false, noted in the map with the evidence). Carry managerDecisions into that same map section verbatim.
- The manager COORDINATES. It never implements sub-session work and never re-derives a sub-session's plan; each sub-chip carries its own mined prompt.
- Detect real dependencies from the mined goals/stop-states (blocked-on, shared files/ADRs/tickets, one's output feeding another). Do not invent ordering: independent sub-sessions get empty dependsOn so they spawn together (cap the first wave at 5).
- Map status must not overclaim: use each sub-session's isComplete / prState / lastState exactly; an open bake or unmerged PR is not done.
- If two sub-sessions overlap on the same artifact, say so in the map and name which one owns it.
- managerPrompt keeps the literal placeholders {{MAP_PATH}}, {{CHIPS_PATH}} and {{PLAYBOOK_PATH}}; the caller substitutes them.
Return ONLY the structured object.`,
    { label: `manage:${g.category}`.slice(0, 60), phase: 'Manage', schema: MGR_SCHEMA, agentType: 'general-purpose', model: 'sonnet' }
  ).then(r => r || { category: g.category, _failed: true })
}))

return { ok, failed, consolidations: consolidations.filter(c => c && !c._failed), managers: managers.filter(m => m && !m._failed), managersFailed: managers.filter(m => !m || m._failed).map(m => m && m.category) }
