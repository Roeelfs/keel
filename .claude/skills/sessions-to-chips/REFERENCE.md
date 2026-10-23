# sessions-to-chips — Mode 2 reference (resume from sessions)

> Scope: Mode 2 (resume from sessions) depth. Mine-only audits stop before any
> session is started. All filesystem discovery below requires permitted access; use
> supported direct reads, permitted exports or authorized UI when source stores are
> unavailable or denied. Do not bypass access limits or treat incomplete work as
> permission to start a session.

## Where session data lives

| Thing | Path | Notes |
|---|---|---|
| Desktop session metadata | `~/Library/Application Support/Claude/claude-code-sessions/<account-uuid>/<org-uuid>/local_*.json` | All accounts, dead sessions included. **"Another account" = a different `<account-uuid>` dir.** Keys: `title, cliSessionId, cwd, worktreePath, worktreeName, branch, prNumber, prState, isArchived, lastActivityAt`. No `pinned` field. |
| Transcript JSONL | `~/.claude/projects/<worktree-slug>/<cliSessionId>.jsonl` | Per-worktree dir, not the main project dir. Find by `cliSessionId`, not directory name. |
| Live interactive sessions | `~/.claude/sessions/<PID>.json` | Only currently-running ones — usually NOT the pinned set. Don't rely on this for parked/dead sessions. |
| Pinned order | `~/Library/Application Support/Claude/Local Storage/leveldb/*.{ldb,log}` key `pinnedOrder` | LevelDB chunking makes the array hard to parse reliably and it's per-active-account. **Prefer matching screenshot titles via `list_sessions.py --grep`.** |

The MCP `mcp__ccd_session_mgmt__list_sessions` only returns the *current* account's recent sessions and excludes the running one — insufficient for "another account" / older pinned sessions. Use the filesystem store.

## Deep-mining sources inside a transcript (what makes a unit prompt non-surface-level)

`mine_session.py` reads the WHOLE arc, not just the last messages. The signals it extracts and why each matters:

| Signal | Where in the JSONL | Why it matters |
|---|---|---|
| **Original goal** | first substantive `type:"user"` message (skip `isMeta`, tool_results, `<…>` reminders) | The mission statement — what the session set out to do before any pivot. |
| **User steering arc** | every substantive `type:"user"` message, in order | Shows how intent *evolved*. A session often pivots; the goal is the arc, not turn 1. |
| **Latest session summary** | the most recent `type:"user"` with `"isCompactSummary":true` | The richest single artifact. This desktop store does **not** use classic `type:"summary"` — long sessions carry one canonical compaction summary per compaction ("Primary Request and Intent / Key Technical Concepts / Pending Tasks / Next Step"). The **last** one is the freshest goal+state digest; its "Next Step" / "Pending Tasks" sections are gold for the continuation phrase. Short sessions have **zero** (never compacted) — then the steering arc + tail ARE the full record. |
| **Exact last instruction** | last `type:"last-prompt"` entry's `lastPrompt` | The literal final thing the user typed — the most reliable anchor for "where we stopped". |
| **Tail** | last assistant text, latest `TodoWrite`, last ~20 tool uses | Where/why it stopped (weekly limit mid-task, half-finished verify, open review). |

The whole point: synthesize **goal** (arc + summary) and name the **exact continuation point** (last-prompt + summary's Next-Step + tail), so the unit prompt says "resume THIS mission from HERE", not "do the last thing".

### Pivot & terminal-state discipline (where surface-level unit prompts fail)

Adversarial validation on real sessions surfaced one dominant failure class — sessions that **pivoted** or **stopped short**. Apply these rigorously when authoring `sessionGoal` / `continuationPhrase`:

- **Pivots are the norm, not the exception.** Sessions drift ("fix ABC-40" → a broader ABC-314 epic → a narrow ABC-328 sub-fix; "merge the test plan" → "audit every page"). Don't flatten original+evolved into one bland activity list. **Lead with the CURRENT crystallized mission** (the summary flags it as "MOST RECENT / CRYSTALLIZING REQUEST"), name the pivot in a clause. The `chipTitle` stays the **original** name, so the `chipPrompt`'s GOAL line must **bridge title ↔ current goal** (e.g. "titled for the ABC-40 build; the session evolved into the ABC-328 wake-latency fix").
- **State the goal as an OUTCOME / victory-condition, not activities.** "Find the data-basis contradictions and fix them" beats "touched the test plan, audited pages, wrote a doc".
- **Never overclaim completion.** If the victory-condition wasn't reached (validation not run, bake not done, PR not opened, a dispatched executor hadn't reported), say exactly that. Don't write "culminating in production baking" when the transcript never reaches it.
- **Never invent a ruled-out step.** Scan LAST ASSISTANT TEXT for explicit "nothing pushed / no write access / deliberately local / can't / already done" facts and honor them. A `continuationPhrase` proposing "push to origin/main" when the session established there's no write access is a hard defect — it breaks on the first action.
- **In-flight and blocked are first-class stop-states.** In-flight dispatched work → "check `<agent>`'s result, then …". Blocked → "unblock `<ticket>`, then `<the true end-game>`".
- **Continue from the FRONTIER, not the literal last keystroke.** The continuation is the first *not-yet-done* substantive step. Two traps: (a) don't point at a sub-task that already **finished** earlier in the arc ("resume the sweep" when the sweep is done and its output saved); (b) don't treat a **wrap-up/handoff** tail ("commit locally", "bake a resume doc so a future session can continue") as the mission — the next action is the mission's Next-Step / top pending item from the summary + persisted state, not redoing the bookkeeping.
- **A self-authored handoff wins — carry it, don't reinvent it.** If the session wrote its own resume artifact (`session-resume-YYYY-MM-DD.md`, a "Resume path:" block, an explicit "Next Step / Optional Next Step"), anchor the `continuationPhrase` on it: name the artifact to load and lead with its stated first action/priority. The session already decided what comes next; re-deriving a different plan loses that signal (e.g. a session that named its top-priority item plus a sweep's results in its own resume doc — carry that ordering, don't re-derive a different one).

## Category story / manager structure

One category = one **story** (a markdown file) + one **manager** session. Units are rows in the story, not separate pre-authored artifacts; there is no second decision tier.

| Thing | Rule |
|---|---|
| Lineage source | `spawnedFrom.sessionId` in each `local_*.json` (plus `spawnedFrom.taskId`/`title`). A root has `spawnedFrom: null`. |
| Category | The sidebar group label (e.g. "Apps") is a UI grouping, **not stored in the session JSON**. A category is the lineage root, or a name from `--categories` / the user. |
| Origin | The topmost session in the category. Its own state is the story's "Where the origin session stopped"; it gets a unit only if it has implementation work of its own left. |
| Miner | One haiku agent per session (`mine_workflow.js` Mine phase). It fills the extraction schema from the `mine_session.py` digest and decides nothing. |
| Narrator | One sonnet agent per category, the **only** decision layer. Reads every member's mined state + intelligence and decides merges, retirements, conflicts and gates with evidence. |
| Story | `~/.claude/sessions-to-chips/maps/<date>-<slug>.md`. Sections: Mission, origin state, How we got here (causal beats), Established (do not re-derive), Conflicts, Open front, Dead ends, Units table, Gates, Retired, Unit prompts. One file, one source of truth. |
| Manager | One session per category, titled `[Manager] <origin title>` (a bare origin title would be a twin of the parked origin row). Owns the narrative and dispatches units; never does a unit's work. Its prompt is script-templated (goal, story path, a pointer to the Manager contract, story-specific duties, gates), never LLM-drifted. |
| Unit | One fresh session's mission, with the mined 5-part prompt unchanged (merged units: one prompt, REMAINING STEPS = union). Each prompt ends with a pointer to the story and the manager's title. |
| Merge | Only same ticket/artifact, strict subset/direct follow-up, or same files. Evidence recorded in the unit row. A merge never loses a `remainingWork` item; if unsure, keep separate (a wrong split costs one session, a wrong merge hides an obligation). |
| Guard | After narration the script re-adds any incomplete member with owed work that is in no unit and in no `retired` entry, and reports it in `warnings`. |
| Fan-out | First wave at most 5 concurrent units; later waves follow `dependsOn`. |
| Sidebar nesting | Set by `spawnedFrom.sessionId` = the session that started it. Verified 2026-10-13 against the store: each `[Manager]` is a child of the dispatcher session and its units are children of the manager (deeper levels appear when a unit starts its own). So the manager must start its units itself. |
| Decision tiers | Exactly one manager level. A member that itself has children is its own category (re-run `group_sessions.py --root` on it). |
| Overlap | Two units on one artifact: the narrator merges them, or names the owner and the other prompt says "do not edit X". |
| Flat / done | One unit left: start it directly with the category context inline. Zero units: report done. |

### Intelligence fields (what the story is built from)

| Field | Meaning | Guard |
|---|---|---|
| `contribution` | What the session established for the mission (finding, decision, artifact), distinct from progress. | Not "how far it got". |
| `established` | Settled calls, each with the PR/ticket/ADR/test that settled it. | A hunch is an `openQuestion`, never an established claim. |
| `deadEnds` | Falsified theories / abandoned approaches, with why. | Prevents a successor re-running a disproven idea. |
| `produces` / `needs` | Handoffs: artifacts others depend on / inputs awaited from outside. | One session's `needs` = another's `produces` is a story beat and a `dependsOn`. |
| `openQuestions` | Raised and not closed. | Feeds the story's Open front; the manager resolves facts by lane and grills the rest as its first round. |

Gotchas: a `--grep` target set that includes a child but not its parent makes the child its own root; pass `--root` to pull the full subtree. `--root` prefers an exact title and ignores leftover `[Manager]`-prefixed sessions from earlier runs.

## Completion criteria (isComplete)

`isComplete = true` ONLY when the PR is **MERGED** AND the post-merge tail the session itself named is also done (staging/prod bake verified, tracking issue closed, no open follow-up). A merged PR that ends with "now bake on staging / verify in prod / follow-up <ticket>" is **NOT** complete — it still gets a unit for the tail. Complete sessions get no unit; just report them as done.

Map of remaining-work shapes:
- **OPEN PR** → review + merge (+ any bake). Watch for unpushed local commits that the PR doesn't include yet.
- **No PR but commits exist** → finish, verify, open PR.
- **Interrupted mid-task** (e.g. "hit your weekly limit", half-finished verify) → resume from the exact interruption point.
- **MERGED + tail done** → complete, skip.

## Unit-prompt rules

`start_session` (with `context: "fresh"`) creates a session with **zero memory** of the mining conversation **and a fresh worktree**. So every unit prompt (`chipPrompt` in the mined schema) must be:

0. **Goal-led, 5-part structure** — the fix for "surface-level" unit prompts. Order the prompt:
   1. **OVERALL GOAL** — the mined `sessionGoal`, so the fresh session inherits the *mission*, not a stray task.
   2. **WHAT IS DONE** — concrete progress + worktree path + branch + PR #/state.
   3. **WHERE IT STOPPED** — the exact interruption point.
   4. **CONTINUE FROM HERE** — the `continuationPhrase` verbatim, as the opening directive (the user's-voice "do X next", never "continue the last mission").
   5. **REMAINING STEPS** — ordered, file paths + how to verify.
1. **Self-contained**: worktree path + branch (or "cut a fresh worktree off origin/main"), PR number + state, a tight "what's done", and the exact ordered remaining steps with file paths + how to verify.
2. **Worktree-safe**: if the work is **uncommitted or unpushed** in an existing worktree, OPEN the prompt with:
   > ⚠️ WORKTREE NOTE: your prior work is uncommitted/unpushed and lives only in `<abs worktree path>`. `cd` there first; do NOT use a fresh worktree or the changes are invisible. `git status` must show <files>.
   For **unpushed commits behind an OPEN PR**, make "push the N local commits from that worktree" step 0 — the PR doesn't include them yet.
3. **Disciplined**: end with your project's dispatch discipline — iterate locally (your project's quick/affected verify plus a typecheck — the commands your project documents), run the full verify gate once when green, push once, open/update the PR, and **do NOT poll CI**. Include any commit-trailer convention your project uses (e.g. a session-id trailer that links each commit back to its originating session).
4. **Risk-flagged**: if a step mutates prod (a feature-flag flip, a destructive migration, a schema drop), mark it gated — needs a calm bake + a staging rollback drill, not autonomous action.

Strip ephemeral references a fresh session can't resolve (background-task watcher IDs, "the session I just started"). Replace "monitor watcher bxw…" with the durable equivalent for your stack — e.g. "read the logs + run-state store over a ≥1h window".

## Title / tldr conventions (start_session)
- `title`: **keep the original desktop session name, verbatim** (e.g. "Fix nightly AsyncRunParamsHashMismatch (ABC-397)"). The user navigates by these names, so a unit must be recognizable as *that* session — do NOT rewrite it into a fresh imperative. Most session titles are already verb-led; only trim trailing detail if it runs much past ~70 chars, never the recognizable lead. (This overrides the generic "imperative verb, <60 chars" title guidance — the user's "keep the names" requirement wins.)
- `tldr` (the `background` argument for a fresh start): 1-2 plain-English sentences, no paths/code — the mission + what resuming it does.
- `cwd`: only set if the work belongs to a *different* repo than the current project; otherwise omit (defaults to current project).

## Workflow gotchas (these cost retries)
- `args` may arrive as a **string** → `JSON.parse` it inside the script (the template does).
- `process`, `Date.now()`, `Math.random()`, argless `new Date()` are **undefined/throw** in workflow scripts. Pass timestamps via args; vary agent prompts by index for "randomness".
- Mining agents must be **read-only** — no verify/build/test/push.
- Use `agentType: 'Explore'` for mining — fast read-only fan-out.

## Re-running / iterating
The Workflow tool persists the script and returns a `scriptPath` + `runId`. To re-mine after editing the args or template: `Workflow({scriptPath, resumeFromRunId})` — unchanged agent calls return cached results.

## Adopter-private layer (overlay)
If `~/.claude/skills-overlay/sessions-to-chips/LEARNINGS.md` exists, read it too — it holds project-specific sharpeners that must NOT live in this public repo: real session-title examples, named past incidents, the exact verify-gate commands and commit-trailer string for your stack, and any project-specific stop-state patterns. The skill works standalone without it; the overlay just makes the mined unit prompts more precise for your own setup.
