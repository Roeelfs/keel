export const meta = {
  name: 'mine-sessions-to-chips',
  description: 'Mine N Claude sessions in parallel, then narrate each category as one story + unit ledger for a single manager',
  phases: [
    { title: 'Mine', detail: 'one read-only agent per session: goal, state AND the intelligence it produced' },
    { title: 'Narrate', detail: 'one sonnet narrator per category: the story, settled calls, merged/retired units' },
  ],
}

// Invoke via the Workflow tool:
//   Workflow({ scriptPath: "<skill>/scripts/mine_workflow.js",
//             args: { mineScript: "<skill>/scripts/mine_session.py", date: "YYYY-MM-DD",
//                     sessions: [ { idx, title, cli, worktreeName, branch, pr, transcript }, ... ],
//                     groups: [ { category, origin:{title,cli}|null, memberClis:[cli,...] oldest->newest } ] } })
// `groups` comes from group_sessions.py (omit for a single flat set; then no Narrate phase runs).
// Returns { ok, failed, stories:[{category, flat, done, managerTitle, managerTldr,
//   managerPrompt, storyMarkdown, units[], warnings[]}], storiesFailed }.
//   - ONE manager per category (managerPrompt); flat=true -> a single unit, start it directly.
//   - storyMarkdown is the one artifact: narrative + established calls + unit ledger + unit prompts.
//   - warnings[] lists any obligation the narrator tried to drop; the script re-adds it as a unit.
// Pass `transcript` (abs path from find_transcript.py) so agents don't re-glob.
// Pass `title` VERBATIM - it is the desktop session name and becomes the unit title unchanged.
// GOTCHAS baked in: `args` can arrive as a STRING (JSON.parse it); `process` is undefined;
// Date.now()/Math.random() throw. Agents are READ-ONLY (no verify / heavy ops / push).

const input = typeof args === 'string' ? JSON.parse(args) : args
const sessions = input.sessions
const mineScript = input.mineScript

const SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['idx', 'title', 'branch', 'worktree', 'prState', 'sessionGoal', 'lastState', 'continuationPhrase', 'gitState', 'remainingWork', 'isComplete', 'contribution', 'established', 'deadEnds', 'produces', 'needs', 'openQuestions', 'chipTitle', 'chipTldr', 'chipPrompt'],
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
    contribution: { type: 'string', description: '1-3 sentences: what this session ESTABLISHED for the mission (a finding, a decision, a built artifact) as distinct from lastState, which is progress against its goal. The category narrative is built from these.' },
    established: { type: 'array', items: { type: 'object', additionalProperties: false, required: ['claim', 'evidence'], properties: { claim: { type: 'string' }, evidence: { type: 'string', description: 'the PR/ticket comment/ADR/path/test that settled it' } } }, description: 'Durable calls, verified facts and discovered constraints a successor must NOT re-derive or re-litigate. Only claims the transcript actually settled with evidence; empty is fine.' },
    deadEnds: { type: 'array', items: { type: 'string' }, description: 'Hypotheses or approaches this session FALSIFIED or abandoned, one line each with the reason. Prevents a successor re-running a disproven theory.' },
    produces: { type: 'array', items: { type: 'string' }, description: 'Concrete artifacts other sessions may depend on: PR #, spec path, ticket id, ADR, migration, dataset.' },
    needs: { type: 'array', items: { type: 'string' }, description: 'Inputs this session was waiting on from OUTSIDE itself: another session\'s output, a ticket, a founder decision.' },
    openQuestions: { type: 'array', items: { type: 'string' }, description: 'Questions the session raised and did not close.' },
    isComplete: { type: 'boolean', description: 'true ONLY if PR MERGED AND post-merge tail (bake/verify, issue closed, no self-named follow-up) is also done.' },
    chipTitle: { type: 'string', description: 'The ORIGINAL session title (the `title` field) echoed back VERBATIM — keep the name the user recognizes. Do NOT rewrite it into a new imperative. Only trim trailing detail if it exceeds ~70 chars, never the recognizable lead.' },
    chipTldr: { type: 'string', description: '1-2 plain-English sentences; no file paths/code — the mission + what resuming it does.' },
    chipPrompt: { type: 'string', description: 'SELF-CONTAINED cold-start prompt for a fresh zero-memory session, structured: (1) OVERALL GOAL — the sessionGoal so the new session inherits the mission, not just a task; (2) WHAT IS DONE — concrete progress + worktree path + branch + PR #/state; (3) WHERE IT STOPPED — the exact interruption point; (4) CONTINUE FROM HERE — the continuationPhrase verbatim as the opening directive; (5) REMAINING STEPS — ordered, with file paths + how to verify. If gitState.uncommitted OR gitState.unpushed, START the whole prompt with a ⚠️ WORKTREE NOTE telling the spawned session to `cd` into the existing worktree (spawn_task makes a FRESH worktree and would lose the work). End with your project\'s dispatch discipline: verify locally (your project\'s verify gate, plus a typecheck), run the full verify gate once when green, push once, do NOT poll CI.' },
  },
}

const results = await parallel(sessions.map((s) => () =>
  agent(
`Deep-mine ONE finished/paused Claude Code session so a resume prompt can be authored that carries its OVERALL GOAL and the EXACT phrase to continue from where it stopped — not a vague "do the last thing". READ-ONLY: do not edit files, build, test, verify, run any heavy op, or push. Only read, git status/log, and gh.

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

   PIVOT & TERMINAL-STATE DISCIPLINE (this is where surface-level resume prompts fail — apply rigorously):
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

INTELLIGENCE (this is what a later narrator stitches into the category story; capture it from the transcript, never invent it)
- contribution: what this session ESTABLISHED, not how far it got. A decision, a verified fact, a built artifact.
- established: only calls the session settled WITH evidence (PR, ticket comment, ADR, test). A hunch is an openQuestion, not an established claim.
- deadEnds: theories falsified or approaches abandoned, with why.
- produces / needs: the handoffs between this session and others (PR #, spec path, ticket, another session's output, a founder decision).

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

// ---- Phase 2: one NARRATOR per category -> ONE story + a unit ledger ----------------------------
// The narrator reads the mined intelligence of every member, tells the category's story, and
// decides merges/retirements itself (single decision layer).
// The script (not an LLM) renders the story file and the manager prompt, so unit prompts and
// titles reach the user verbatim from the mined results.
const groups = input.groups || []
const date = input.date || ''

const NARR_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['category', 'thesis', 'storyline', 'established', 'conflicts', 'openFront', 'units', 'retired', 'gates'],
  properties: {
    category: { type: 'string' },
    thesis: { type: 'string', description: 'ONE sentence: the outcome the whole category is driving toward (a victory-condition, not a list of tickets or activities).' },
    storyline: { type: 'array', items: { type: 'string' }, description: '4-10 beats in CAUSAL order. Each beat: which session (by title) found or decided what, and why that forced the next beat. Handoffs (one session\'s produces = another\'s needs) are beats. Not a per-session dump.' },
    established: {
      type: 'array',
      description: 'The category\'s settled calls, de-duplicated from the members. A successor must not re-derive or re-litigate these.',
      items: { type: 'object', additionalProperties: false, required: ['claim', 'evidence'], properties: { claim: { type: 'string' }, evidence: { type: 'string', description: 'the PR/ticket/ADR/path/test that settled it, with the session title' } } },
    },
    conflicts: {
      type: 'array',
      description: 'Where two sessions assert different outcomes for the same thing (status, design choice, artifact owner). Resolve from evidence; needsHuman=true only when evidence cannot settle it AND it is a founder/product or prod-mutation call.',
      items: { type: 'object', additionalProperties: false, required: ['what', 'resolution', 'needsHuman'], properties: { what: { type: 'string' }, resolution: { type: 'string', description: 'the call + the evidence, or your recommendation if needsHuman' }, needsHuman: { type: 'boolean' } } },
    },
    openFront: { type: 'array', items: { type: 'string' }, description: 'What is genuinely unproven or unbuilt at category level (bakes owed, decisions not yet taken). Honest: never list as done what is merged-but-unbaked.' },
    units: {
      type: 'array',
      description: 'The FEWEST units of remaining work. One unit = one fresh session\'s mission.',
      items: {
        type: 'object', additionalProperties: false,
        required: ['cli', 'mergedFrom', 'mergeEvidence', 'dependsOn', 'title', 'tldr', 'prompt'],
        properties: {
          cli: { type: 'string', description: 'cliSessionId of the carrier member (for a merged unit: the member whose mission leads).' },
          mergedFrom: { type: 'array', items: { type: 'string' }, description: 'all member cli ids this unit covers, carrier included; just [cli] when not merged.' },
          mergeEvidence: { type: 'string', description: 'merged unit: the shared ticket/artifact/files that make it one piece of work. Empty string when not merged.' },
          dependsOn: { type: 'array', items: { type: 'string' }, description: 'cli ids of units whose OUTPUT this unit needs. Empty when independent.' },
          title: { type: 'string', description: 'merged unit: the carrier\'s ORIGINAL title verbatim. Unmerged: empty string (the caller copies it).' },
          tldr: { type: 'string', description: 'merged unit only; empty string otherwise.' },
          prompt: { type: 'string', description: 'merged unit only: ONE 5-part prompt (GOAL, DONE, STOPPED, CONTINUE FROM HERE, REMAINING STEPS = union of members\') opening with a WORKTREE NOTE for every member worktree holding uncommitted/unpushed work. Empty string for an unmerged unit — the caller copies the mined chipPrompt unchanged.' },
        },
      },
    },
    retired: {
      type: 'array',
      description: 'Members that get NO unit: isComplete, or named evidence they are superseded by / duplicate of another member. Never retire for age.',
      items: { type: 'object', additionalProperties: false, required: ['cli', 'reason'], properties: { cli: { type: 'string' }, reason: { type: 'string' } } },
    },
    gates: { type: 'array', items: { type: 'string' }, description: 'Human-only steps (prod mutation, founder decision). Each names the unit it blocks.' },
  },
}

function narratorPrompt(g, members) {
  const slim = members.map(m => ({
    cli: m._cli, title: m.title, sessionGoal: m.sessionGoal, lastState: m.lastState,
    contribution: m.contribution, established: m.established, deadEnds: m.deadEnds,
    produces: m.produces, needs: m.needs, openQuestions: m.openQuestions,
    remainingWork: m.remainingWork, isComplete: m.isComplete, prState: m.prState,
    branch: m.branch, worktree: m.worktree, gitState: m.gitState, chipPrompt: m.chipPrompt,
  }))
  return `You are the NARRATOR for ONE category of Claude Code sessions. READ-ONLY: no edits, no builds, no pushes, no re-mining. Understand the intelligence inside these sessions, tell the category's story as ONE coherent narrative, then reduce what remains to the fewest units of work. You are the only decision layer: nobody downstream re-decides your merges or retirements, so decide them.

CATEGORY: ${g.category}
ORIGIN SESSION (the top-level thread that spawned the rest): ${g.origin ? g.origin.title + ' [' + g.origin.cli + ']' : '(none)'}

MEMBERS, oldest to newest (already mined; JSON):
${JSON.stringify(slim, null, 1)}

DO, IN ORDER
1. THESIS: the one outcome the whole category is driving toward.
2. STORYLINE: 4-10 beats in CAUSAL order. Use each member's contribution / established / deadEnds / produces / needs to find handoffs: when one member's needs is another's produces, that is a beat and a dependsOn. Name sessions by title.
3. ESTABLISHED: merge the members' established claims into the category's settled calls, each with its evidence.
4. CONFLICTS: where members disagree on the same fact, settle it from evidence (PR state, merged commit, a later session overriding an earlier one) and say how.
5. UNITS: reduce remaining work to the fewest units.
   - Merge members ONLY when they are one piece of work: same ticket/artifact, one a strict subset or direct follow-up of the other, or they would edit the same files. Different tickets that merely share a theme stay separate. Put the shared evidence in mergeEvidence.
   - A merge never loses an obligation: every member's remainingWork survives in the merged prompt. A merged unit with more than ~3 independent deliverables should be split instead.
   - Retire a member (no unit) only when isComplete, or with named evidence that another member supersedes or duplicates it. Never retire for age.
   - The origin session is a normal member: it gets a unit only if it has implementation work of its own left.
   - dependsOn is a real input->output dependency only; independent units get [].
   - If unsure whether to merge, keep separate and say why in the storyline: a wrong merge hides an obligation, a wrong split costs one extra session.
6. GATES: human-only steps (prod mutation, founder decision), each naming the unit it blocks.

Do not overclaim: use each member's isComplete / prState / lastState as given; a merged-but-unbaked PR is not done. A step a member explicitly ruled out stays ruled out.
Return ONLY the structured object.`
}

function assemble(g, members, n) {
  const byCli = Object.fromEntries(members.map(m => [m._cli, m]))
  const warnings = []
  const covered = new Set()

  const units = n.units.map((u) => {
    const from = (u.mergedFrom && u.mergedFrom.length ? u.mergedFrom : [u.cli]).filter((c) => {
      if (byCli[c]) return true
      warnings.push(`unit ${u.cli} references unknown member ${c}`)
      return false
    })
    from.forEach(c => covered.add(c))
    const carrier = byCli[u.cli] || byCli[from[0]]
    const merged = from.length > 1
    if (merged && !u.prompt) warnings.push(`merged unit ${u.cli} came back without a merged prompt; carrier prompt used, so the union of remainingWork is NOT guaranteed`)
    return {
      cli: u.cli, mergedFrom: from, mergeEvidence: u.mergeEvidence || '',
      title: u.title || (carrier && carrier.chipTitle) || '',
      tldr: u.tldr || (carrier && carrier.chipTldr) || '',
      prompt: (merged && u.prompt) ? u.prompt : ((carrier && carrier.chipPrompt) || u.prompt || ''),
      dependsOn: u.dependsOn || [],
      state: carrier ? carrier.prState : '',
      stoppedAt: carrier ? carrier.lastState : '',
    }
  })

  n.retired.forEach(x => {
    covered.add(x.cli)
    const m = byCli[x.cli]
    if (m && !m.isComplete && (m.remainingWork || []).length) warnings.push(`retired with owed work: "${m.title}" (${x.reason})`)
  })

  // Guard against a silently lost obligation: any incomplete member the narrator left out gets its own unit.
  members.forEach((m) => {
    if (covered.has(m._cli) || m.isComplete || !(m.remainingWork || []).length) return
    warnings.push(`"${m.title}" had owed work but was in no unit; added as its own unit`)
    units.push({ cli: m._cli, mergedFrom: [m._cli], mergeEvidence: '', title: m.chipTitle, tldr: m.chipTldr, prompt: m.chipPrompt, dependsOn: [], state: m.prState, stoppedAt: m.lastState })
  })

  const managerTitle = '[Manager] ' + (g.origin ? g.origin.title : g.category)
  const gates = n.gates || []
  const flat = units.length === 1
  const done = units.length === 0
  const idxOf = Object.fromEntries(units.map((u, i) => [u.cli, i + 1]))
  const ctxLines = (n.established || []).map(e => `- ${e.claim} (${e.evidence})`).join('\n')

  const finalUnits = units.map((u) => ({
    ...u,
    prompt: flat
      ? `${u.prompt}\n\nCATEGORY CONTEXT: ${n.thesis}\nAlready established, do not re-litigate:\n${ctxLines || '- (nothing recorded)'}`
      : `${u.prompt}\n\nSTORY: read {{STORY_PATH}} first; its Established section lists calls already settled, so do not re-litigate them. The manager for this category is the session titled "${managerTitle}"; report your PR/outcome there.`,
  }))

  const deadEnds = members.flatMap(m => (m.deadEnds || []).map(d => `- ${d} (${m.title})`))
  const originState = g.origin && byCli[g.origin.cli] ? byCli[g.origin.cli] : null
  const storyMarkdown = [
    `# ${g.category}${date ? ' (' + date + ')' : ''}`,
    `## Mission\n${n.thesis}`,
    originState ? `## Where the origin session stopped\n${originState.lastState}` : '',
    `## How we got here\n${(n.storyline || []).map((b, i) => `${i + 1}. ${b}`).join('\n')}`,
    `## Established (do not re-derive)\n${(n.established || []).map(e => `- ${e.claim} — ${e.evidence}`).join('\n') || '- (none recorded)'}`,
    (n.conflicts || []).length ? `## Conflicts\n${n.conflicts.map(c => `- ${c.what} -> ${c.resolution}${c.needsHuman ? ' **[needs human]**' : ''}`).join('\n')}` : '',
    (n.openFront || []).length ? `## Open front\n${n.openFront.map(o => `- ${o}`).join('\n')}` : '',
    deadEnds.length ? `## Dead ends (do not retry)\n${deadEnds.join('\n')}` : '',
    `## Units of work\n| # | unit | state | depends on | stopped at |\n|---|---|---|---|---|\n` + units.map((u, i) =>
      `| ${i + 1} | ${u.title}${u.mergedFrom.length > 1 ? ' (merged ' + u.mergedFrom.length + ': ' + u.mergeEvidence + ')' : ''} | ${u.state} | ${u.dependsOn.map(d => idxOf[d] ? '#' + idxOf[d] : d).join(', ') || '-'} | ${String(u.stoppedAt).replace(/\|/g, '/').replace(/\n/g, ' ').slice(0, 160)} |`).join('\n'),
    gates.length ? `## Gates (human)\n${gates.map(x => `- ${x}`).join('\n')}` : '',
    (n.retired || []).length ? `## Retired (no unit)\n${n.retired.map(r => `- ${(byCli[r.cli] || {}).title || r.cli}: ${r.reason}`).join('\n')}` : '',
    `## Unit prompts (start as written, in dependsOn order)\n` + finalUnits.map((u, i) => `### ${i + 1}. ${u.title}\n~~~~\n${u.prompt}\n~~~~`).join('\n\n'),
  ].filter(Boolean).join('\n\n')

  const managerPrompt = flat || done ? null :
`You are the manager for "${g.category}". You own its narrative AND dispatch its remaining work.

GOAL: ${n.thesis}

CONTRACT: ~/.claude/skills/sessions-to-chips/references/manager-contract.md binds you: verify before acting, grade by artifact, hold the gates, keep your family small, close out once. Read it first. Start each child with the arguments in ~/.claude/skills/sessions-to-chips/SKILL.md, section "Starting a manager".

READ FIRST: {{STORY_PATH}}. It holds how the work got here, what is already established (do not re-litigate), open conflicts, and one unit per piece of remaining work, each with a ready prompt.

THIS STORY
1. A story row is a claim, not proof: verify the facts you act on (gh pr view, git worktree list --porcelain).
2. Settle every open conflict yourself and record the call plus its reason in the story. Escalate only for a prod mutation, a founder/product decision, or an unrecoverable conflict, one question at a time.
3. Start each unit yourself, from THIS session, so it nests under you. Title and prompt exactly as written, in dependsOn order; independent units together, first wave at most 5. Do not do a unit's work.
4. Keep the Units table current as units report. Merged is not baked.
5. Your first act: declare the program state files (manifest, events, state) per the contract; the state file points at the story.
6. At every stopping boundary, run the session-hygiene pass in ~/.claude/skills/sessions-to-chips/HYGIENE.md: archive finished children, fold true duplicates, report it in one line.
GATES: ${gates.length ? gates.join('; ') : 'none'}`

  return {
    category: g.category, flat, done, managerTitle,
    managerTldr: `Manager for "${g.category}": holds the story and dispatches ${units.length} unit(s); does not do their work.`,
    managerPrompt, storyMarkdown, units: finalUnits, warnings,
  }
}

const stories = await parallel(groups.map((g) => () => {
  const members = (g.memberClis || []).map(c => ok.find(r => r._cli === c)).filter(Boolean)
  return agent(narratorPrompt(g, members),
    { label: `narrate:${g.category}`.slice(0, 60), phase: 'Narrate', schema: NARR_SCHEMA, agentType: 'general-purpose', model: 'sonnet' }
  ).then(r => r ? assemble(g, members, r) : { category: g.category, _failed: true })
   .catch(() => ({ category: g.category, _failed: true }))
}))

return {
  ok, failed,
  stories: stories.filter(s => s && !s._failed),
  storiesFailed: stories.filter(s => !s || s._failed).map(s => s && s.category),
}
