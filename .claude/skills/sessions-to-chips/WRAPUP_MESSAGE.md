CHECKPOINT MODE ({{DATE}}). The founder is about to switch accounts. Converge to a clean checkpoint: this is NOT a full stop. Let in-flight builds and lanes finish. Start no new units and no new lanes, and do not expand scope.

Your live child sessions at last check:
{{CHILDREN}}

Everything must survive the switch: session history will not be readable from the other account. State that matters lives in git, Linear, and the note below, never in a session's memory.

1. Classify each child (list_sessions / your Units table):
   - DONE: PR merged and its post-merge tail done. Cite the PR and mergedAt. Merged is not baked: list any bake still owed as UNPROVEN.
   - RUNNING: a build, verify, Codex or headless lane, or an agent turn is in progress. Do not interrupt it. Ask the child to finish to its next checkpoint (push or record its work, then stop) with one message. Re-check once when it reports idle; do not poll.
   - PARKED: blocked or gated. One line on why and on exactly what (a founder decision, a merge go-ahead, a prod gate, a usage reset).
   - LIVE-WORK: uncommitted or unpushed work, or an open PR. Push to its feature branch (one push), or record its worktree path, branch, PR and exact resume command. A branch push is fine; a merge, deploy, or prod mutation is not yours to do without the human's explicit in-session go-ahead.
   - MERGE-INTO <other>: the same ticket or artifact as another child, or a strict subset of it.
2. Tell each live child to checkpoint itself (send it the rule in step 1 and step 3). Children report in one line; no other replies are needed.
3. Linear is the record. For every ticket a child touched: post one comment with status (shipped with PR and mergedAt, parked and why, unproven and the exact probe), and set the state to match reality. Never write a CYN- number you did not get back from the tracker. If the Linear MCP is unavailable, write the intended comment into your note under "Linear owed" instead.
4. Archive only DONE children whose work is merged and recorded. Archiving a session archives its children, and it is refused while a child works. Never archive a RUNNING, PARKED or LIVE-WORK child. Never delete anything. When unsure, leave it open and say so.
5. Merge: where two children cover one piece of work, carry the loser's remaining steps and worktree path into the survivor's notes, then archive the loser only if it has no live work.
6. Update your story/map: Units table current, plus a closing section (shipped with PR and mergedAt; parked and why; still unproven).
7. Write the checkpoint note to ~/.claude/sessions-to-chips/wrapup/{{DATE}}-{{CATEGORY_SLUG}}.md with:
   - counts before and after;
   - what you archived, with the evidence for each;
   - the surviving set. For each: one-line goal, state (DONE / RUNNING / PARKED / LIVE-WORK), worktree and branch and PR, what gate blocks it, and the exact continuation phrase to resume it from a fresh session on the other account;
   - "Linear owed": any comment or state change you could not post;
   - "Owed to the founder": grill them in this session BEFORE writing the note (one round, recommended answer first). Only what stays unanswered goes here, written as a ready grill round (numbered question + recommended answer), most blocking first. The dispatcher does not collect or relay them.
   Also refresh ~/.claude/orchestrator/programs/{{CATEGORY_SLUG}}.state.md with the same surviving set and a current `updated_at`: the next account reads it instead of your transcript.
   Write the note even when everything is blocked: a blocked item with its gate named is a finished checkpoint.
8. Spend only on reads, pushes of your own branches, Linear updates, archives, and that note. Use Codex lanes for qualifying reads per the gate. Escalate to the human only for a prod mutation or an unresolvable conflict, as one question. Your final message is one line: the path of the note and the counts.
