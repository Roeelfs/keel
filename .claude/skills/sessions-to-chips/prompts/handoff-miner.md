# Handoff miner (Mode 4) — one haiku agent per program

Dispatch: `Agent` with `model: "haiku"`, effort default, one per program, all in one message.
Mining a digest into a fixed template is extraction, not judgment, so haiku is enough; escalate a
program to sonnet only when its digest is too thin and the agent must read the raw JSONL.

Fill `{{PROGRAM}}`, `{{DIGEST}}` (output of `mine_session.py <transcript>` for that program's
manager on the other account, saved to a file), `{{TRANSCRIPT}}`, `{{CHECKPOINT_NOTE}}` (this
account's last wrap-up note for the program, or "none"), `{{OUT}}`.

```text
Read-only except for the one file you write. Program: {{PROGRAM}}.
The program's manager ran on another Claude account after the last checkpoint. A manager on this
account will take it back and needs to know what changed.
Inputs: digest {{DIGEST}} (goal, steering arc, latest compaction summary, last instruction, tail);
full transcript {{TRANSCRIPT}} (JSONL: extract with python or jq, never draw conclusions from
grep); checkpoint note {{CHECKPOINT_NOTE}}.
Write {{OUT}}, at most ~3 KB:
1. Goal, one line.
2. Since the checkpoint: what shipped, with PR numbers. Write MERGED only where `gh pr view <n>
   --json state,mergedAt` confirms it (one call per PR you cite as open or uncertain); otherwise
   "claimed".
3. Live work at the end: each child or lane with title, session id, worktree, branch, PR and
   state (running, parked, blocked) plus the gate blocking it.
4. Every map, spec, story file or draft the program created or updated (repo docs, PRs, files
   under ~/.claude/sessions-to-chips/), with its path or PR and its state. Do not skip these: a
   handoff that names only PRs loses the maps.
5. Owed to the founder, most blocking first, as a ready grill round: the exact question and the recommended answer (the default), so the receiving manager grills it first.
6. Divergence from the checkpoint note: items already finished or superseded, so they are not
   redone.
7. One paste-ready continuation phrase.
Return one line: ACTIVE-MOVED (substantial work, live children), LIGHT (little changed) or DONE,
plus any overlap you saw with another program.
```
