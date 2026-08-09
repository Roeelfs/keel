# Investigation Workflows

Seven asynchronous `Workflow` templates, one per file. **A**, **B**, **E** and **G** fire every run;
**C** is ~quarterly and **D** is conditional (see SKILL.md step 1); **F** is the step-3 plan falsifier
and fires every run. They are **read-only**: research and design, never mutate. Adapt the inventory and paths to
the current machine before launching, launch them together, then stop — they notify on completion.
`Workflow` is inherently asynchronous; do **not** pass an unsupported `run_in_background` parameter.

| Lane | File | When |
|---|---|---|
| A — mine + consolidate | [WORKFLOW-A.md](WORKFLOW-A.md) | every run |
| B — vendor delta (news, changelogs, docs, model pins) | [WORKFLOW-B.md](WORKFLOW-B.md) | every run |
| C — agent-stack landscape | [WORKFLOW-C.md](WORKFLOW-C.md) | ~quarterly |
| D — production-stability / regression RCA | [WORKFLOW-D.md](WORKFLOW-D.md) | when the period regressed prod |
| E — context & compaction economics | [WORKFLOW-E.md](WORKFLOW-E.md) | every run |
| F — plan falsifier (step 3) | [WORKFLOW-F.md](WORKFLOW-F.md) | every run, on the step-2 program |
| G — vendor-surface adoption + interaction quality | [WORKFLOW-G.md](WORKFLOW-G.md) | every run |

**Load only the lanes you are firing.** This index carries the whole shared contract; the lane files
carry only their own template. The file this replaced was 397 lines / 55,114 bytes — 21,463 tokens
against an 8,000 Read cap, four calls to see whole, which nothing ever did. Its `args`-unwrap rule sat
on page 4 of 4 and lanes kept crashing on it.

---

## The shared contract — every lane, every dispatch site

**The `args` trap — unwrap it in every script, first line.** `args` arrives at the script as a JSON
**string**, not the object you passed, so `args.foo` is `undefined` and the script dies on the first
`.map` — or worse, does not die: on 2026-07-24 Workflow A crashed instantly on `BUCKETS.map` while
Workflow B, with the identical bug, silently interpolated the literal text `undefined` into six
already-dispatched research prompts and kept running until it was killed by hand (`TaskStop
wdyqa23vz`). The same trap cost relaunches on 2026-07-06 and 2026-07-20. Every template opens with
`const ARGS = typeof args === 'string' ? JSON.parse(args) : args`. Never read `args.foo` directly.
This is stated on the first screen because it is the single most-repeated crash in this file's
history.

**Every dispatch site carries these three or it is malformed:** the leaf-agent pin — *"You are a leaf
agent: do NOT spawn sub-agents or Workflows; do the work inline and return. Investigation only —
design the plan, do not mutate. WebFetch / read-only gh / local reads only. No CI polling, no sleep
loops."* — an explicit `model:`, and a `schema:`. **The model default is `sonnet`**; `opus` needs a
reason in the label or the comment, and is justified on synthesis lanes, not on mining, census,
existence-checking or per-item verification. An unpinned `agent()` call inherits the expensive tier by
default, which is the exact pathology Workflow E's metric 6 exists to measure.

**"Zero survived" and "zero completed" are different facts — `.filter(Boolean)` erases the
difference.** Every template's `parallel(...).filter(Boolean)` treats a lane that THREW — session
limit, quota, timeout — identically to one that ran and found nothing; both vanish from the array with
no log. Measured 2026-08-03 (`wf_636e88c3-367`): 3 of 3 hunt lanes died on `You've hit your session
limit`, the script's `survivors.length === 0` branch reported `verdict:'clean'` under
`status:'completed'`, and 289,875 subagent tokens bought zero evidence — a dead lane wearing a success
envelope, written by the ritual's own aggregation code rather than by a lying subagent. Before any
phase treats an empty or all-negative `parallel()` result as evidence of absence, compare the
dispatched count to the surviving count and log the difference. Never let a lane death read as a clean
verdict, a refutation, or a completed check.

**Guard every result you are about to dereference.** Workflow E does this (`m?.compaction ?? {}`); A
and D did not, and both paid. Measured 2026-07-16: a synthesize agent hit the account session limit,
the next line read `tax.failure_classes`, and `Error: null is not an object (evaluating
'tax.failure_classes')` killed the whole Workflow — discarding 6 completed RCAs that had to be
hand-recovered in a separate session. A phase that cannot proceed returns its partial results; it does
not throw them away.

**No silent caps.** A lane that verifies only the top N claims logs the N it dropped. An undropped
claim and an unverified one are different facts, and only the log distinguishes them.

---

## Launching

Read the live inventory inline first (`~/.claude/plugins/*.json`, `ls -t ~/.claude/projects/*/*.jsonl`
**and** `ls -t ~/.codex/sessions/*/*/*/rollout-*.jsonl` — bucket BOTH runtimes for Workflow A, and for
C `~/.claude/agents/*.md`), pass it as `args`, launch the Workflows, then **stop and wait** for the
completion notifications. Do not poll.

**Write the run id of every launched Workflow into this run's program file at launch, not at
completion.** Three runs hit a mass rate-limit collapse mid-investigation (2026-07-16 lost 24 of 24
agents in one Workflow and 6 of 16 in another; 2026-08-03 twice). Recovery is `resumeFromRunId` after
the window resets, re-dispatching only the errored lanes — and on 2026-07-16 the human had to name the
crashed run ids by hand, because nothing had recorded them.
