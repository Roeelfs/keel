# Manager playbook — how a category manager decides and delegates

You are the manager for one category. You were handed a **map**, a **chips file** and this playbook. The mining and a first consolidation pass are already done; what is left is judgement, and it is yours. Goal: fewer, more concise units of work, run autonomously, with the human pulled in only at a real gate.

## 1. Orient (once)
1. Read the map: status table, ordering, overlaps, and **Decisions owed to the manager**.
2. Read the chips file. Entries with `mergedFrom` of length >1 were already merged by a high-confidence review; `spawn:false` entries are done or dropped.
3. Verify the load-bearing facts you will act on (PR state via `gh pr view`, branch/worktree via `git worktree list --porcelain`). A map row is a claim, not proof.

## 2. Settle the owed decisions
Work through **Decisions owed to the manager** one at a time. For each, pick and record the choice in the map with its reason.

| Call | Do it when | Otherwise |
|---|---|---|
| **Merge** two chips | same ticket/artifact, one is a subset or follow-up of the other, or both would edit the same files; union their REMAINING STEPS, keep the carrier's original title | keep separate |
| **Split** a chip | it holds >3 independent deliverables, or two halves have different gates (one touches prod) | keep whole |
| **Drop** a chip | named evidence it is superseded/duplicate/done | never drop for age |
| **Re-order** | a `dependsOn` is real (output feeds input) | run in parallel |

Decide by default; do not ask. Escalate to the human only for: a production mutation, a founder/product decision the sessions themselves flagged as theirs, an unrecoverable ambiguity (two sessions claim the same ticket with conflicting outcomes), or spend beyond the stated cap.

## 3. Delegate
1. Update the chips file with your merges/splits/drops (edit the JSON; keep one entry per unit).
2. Spawn each `spawn:true` entry with `spawn_task`, title verbatim, in `dependsOn` order. Independent entries go together; first wave capped at 5; later waves as predecessors report.
3. Every sub-chip prompt must keep its ⚠️ WORKTREE NOTE when present and end with "report your PR/outcome to <manager title>".
4. You do not do sub-session work. If a unit is tiny (one config line) say so in its chip rather than doing it yourself.

## 4. Track
- Keep the map's status table current as chips report. Status honesty: merged ≠ baked; an open bake is open.
- A sub-chip that comes back blocked gets one of: unblock it, re-order around it, or surface it as the single decision for the human.
- Do not poll CI or sleep-wait; act on reports and notifications.

## 5. Close out
When every row is done or explicitly parked, write a short closing section in the map: what shipped (PR numbers + mergedAt), what is parked and why, what is still unproven. Then give the human **one** summary.

## 6. Bake it back (the re-up loop)
If a merge, split, or ordering call generalizes (a pattern the next manager would also face), append one dated line to `~/.claude/skills-overlay/sessions-to-chips/LEARNINGS.md`: the situation, the call, and the evidence. Never record a project-specific ticket in the public skill itself.
