# Child-ledger reconciler (Mode 4) — one haiku agent per manager

Dispatch: `Agent` with `model: "haiku"`, one per `children-*.json` from `child_ledger.py`, all in
one message. Fill `{{LEDGER}}`, `{{HANDOFF}}` (the program's handoff file, or "none"), `{{OUT}}`.

```text
Read-only except for the one file you write.
A program's child sessions ran on a Claude account that is now capped. Their conversations will
not be readable from the next account, so anything that lives ONLY there is lost unless the
handoff names it. Find it.
Inputs: child ledger {{LEDGER}} (per child: title, sessionId, archived, status, needsAction,
awaitingPerson, lastReport, prs with stored state, branches, worktree, transcript path); the
program handoff {{HANDOFF}}.
For each child decide one verdict:
- SAFE: its result is durable and the handoff covers it (a MERGED PR, or an OPEN PR / pushed
  branch the handoff names, or a file the handoff names), and nothing in lastReport/needsAction is
  missing from the handoff.
- AT-RISK: something real exists only in the conversation or is not in the handoff: a finding,
  measurement or decision in lastReport; a needsAction / awaitingPerson ask; an OPEN PR or branch
  the handoff does not name; status blocked or interrupted mid-task.
- NOISE: trivial or superseded by a later child (say which).
The stored PR state can be stale: run `gh pr view <n> --repo Cynap-ai/cynap-monorepo-next --json
state,mergedAt` once for each PR stored as OPEN. When lastReport is truncated or empty and the
child is not obviously SAFE, read the tail of its transcript (JSONL: parse it with python, last ~30
assistant text blocks); never conclude from grep.
Before you call a file lost, find the absolute path the child wrote it to (search its transcript
for the file name) and test that path: children write outside their worktree too (operator
workspaces, ~/.claude, side-session notes), and a missing worktree says nothing about them. Print
the path you tested next to any "lost" claim.
A `workflow_run`-triggered deploy reports the default branch as its headSha; the deployed commit
is its TRIGGER_SHA input or the release in the logs. Never call a bake citation wrong from headSha alone.
Write {{OUT}} (≤3 KB): a table of AT-RISK children only (title, sessionId, what would be lost in
one sentence, where it should go: the handoff, a PR, a tracker comment, or a founder question),
then one line counting SAFE / AT-RISK / NOISE. Return that count line plus the single most
important AT-RISK item.
```
