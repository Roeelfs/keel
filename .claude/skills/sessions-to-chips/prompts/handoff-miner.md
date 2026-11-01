# Handoff miner (Resume / mine, plan phase 1) — one haiku agent per moved program

Dispatch: `Agent` with `model: "haiku"`, effort default, one per program, all in one message.
Mining a digest into a fixed template is extraction, not judgment, so haiku is enough; escalate a
program to sonnet only when its digest is too thin and the agent must read the raw JSONL.

`mine_all.py` writes every input into its plan step (`phases[0].steps[]`): `{{PROGRAM}}`,
`{{DIGEST}}` (one `mine_session.py` digest per transcript of every manager chain of the program:
a session's chain spans several files when the app resumed, moved or forked it), `{{TRANSCRIPT}}`
(the same files), `{{CHECKPOINT}}` (this account's manager's last turn), `{{CHECKPOINT_NOTE}}`,
`{{STATE_FOLD}}` (state, events, manifest and lineage times plus the CURRENT/STALE verdict),
`{{SWEEP_ROWS}}` (the program's `handoff_sweep.py` worktree rows), `{{REPO}}`, `{{OUT}}`.

```text
Read-only except for the one file you write. Program: {{PROGRAM}}.
The program's manager ran on another Claude account after the last checkpoint. A manager on this
account will take it back and needs to know what changed.
Inputs: digests {{DIGEST}} (goal, steering arc, latest compaction summary, last instruction, tail;
read ALL of them, oldest first; the files are segments of one conversation and may repeat rows);
transcripts {{TRANSCRIPT}} (JSONL: extract with python or jq, never draw conclusions from grep);
everything after checkpoint {{CHECKPOINT}} is new to the receiving manager; checkpoint note
{{CHECKPOINT_NOTE}}; state fold {{STATE_FOLD}} (a STALE state file is a lead, not the record);
worktree rows {{SWEEP_ROWS}} (fold each into item 3 or 4); repo {{REPO}}.
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
5b. Cross-cutting founder rulings made since the checkpoint (model ceiling, tool bans, standing
   authorizations), each with its source line, and the program state file's and events file's mtimes.
   If the manifest says this program absorbed or was absorbed by another, say so in one line.
6. Divergence from the checkpoint note: items already finished or superseded, so they are not
   redone.
7. One paste-ready continuation phrase.
Return one line: ACTIVE-MOVED (substantial work, live children), LIGHT (little changed) or DONE,
plus any overlap you saw with another program.
```
