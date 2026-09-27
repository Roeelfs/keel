# Sol judgment lane — bounded frontier escalation

Sol-high handles bounded adversarial judgment; Astra handles architecture, security, hard RCA and final adjudication through the central gate. It earns its cost on **judgment**: investigation, grilling,
adversarial falsification, "is this reasoning actually sound?". It does not earn it on synthesis,
summarizing, mining, or execution — those stay on Sol-medium or Luna.

## The shape that makes it affordable

**One question · fresh context · one document · stop.**

A Sol lane is a *lane*, never a root. `model-routing.md` rule 10 says this; the cost formula says why.
Cost is `turns × context_size × model_weight`. A root maximizes the first two terms, so putting the
heaviest model on one multiplies the worst case, while a fresh bounded lane pays the weight exactly
once, on the turn where judgment happens. Roots are few but heavy: measured 2026-08-21, one session
spawned 30 subagent threads and another produced 81 rollout files, against a median root of 1.

So the rule is not "use Sol sparingly." It is **use Sol freely in this shape, never in the other
one.**

## When Sol-high, when Sol-medium

| The ask | Tier | Why |
|---|---|---|
| "Is this design sound? Attack it." | **Sol-high** | adversarial judgment is the frontier's edge |
| "Grill this plan / find what I'm missing" | **Sol-high** | the value is in what a weaker model fails to notice |
| "Investigate why X — competing hypotheses" | **Sol-high** | hypothesis discrimination, not retrieval |
| "Falsify this finding" | **Sol-high** | the falsifier wave is the canonical Sol use |
| "Security / irreversible-architecture judgment" | **Astra-high** | central gate classes `security` / `architecture` |
| "Summarize these N documents" | Sol-medium | synthesis, not judgment |
| "Research how library X's API works" | Sol-medium | retrieval; the answer is in the docs |
| "Census / locate / extract / existence check" | Luna | mechanical |
| "Run this command group" | Luna-low | procedural worker |

The split inside *research* is the one that gets missed: **research-as-retrieval is Sol-medium;
research-as-judgment is Sol-high.** "What does the vendor document?" is Sol-medium. "Which of these
three readings is right, and what would falsify each?" is Sol-high.

## Mission contract

Paste this whole block. It is self-contained by construction — Codex starts cold, and a lane that
needs accumulated conversation belongs on Claude instead.

```text
You are a leaf agent: do NOT spawn sub-agents or Workflows; do the work inline and return.
READ-ONLY unless this mission names exact writable paths.

QUESTION: <the ONE question this lane exists to answer, stated so a wrong answer is detectable>
CONTEXT: <the smallest evidence slice that makes the question answerable — paths, SHAs, exact
          error text, the claim under test. Never the accumulated conversation.>
DELIVERABLE: <one document at an absolute path, or one structured verdict>
STOP CONDITION: <what "done" is — and that residue is listed, not pursued>

Ground every load-bearing claim in something you can print: a command and its output, a file:line
anchor, a quoted source line. An ABSENCE claim ("there is no X", "nothing else calls this") must
print the enumeration that grounds it — a zero-hit grep on a guessed identifier is indistinguishable
from a real absence.

Default to disagreeing. You are graded on what you found wrong, not on agreement. If the premise of
the question is itself false, say so and stop — that is a successful lane, not a failed one.

Return the deliverable and nothing else. Do not summarize your process.
```

Native children use `fork_turns: "none"` and the effort the question warrants. For a Claude-owned
background document lane, select the judgment class: `falsifier` for adversarial falsification;
`architecture`, `security`, `hard-rca`, or `adjudication` for the hardest decisions. The single
model + effort owner is `~/.claude/scripts/codex-headroom.sh` (`--route <class>`).

Write the mission to a prompt file and launch the managed document wrapper through
harness-tracked background Bash (`run_in_background: true`):

```bash
~/.claude/scripts/codex-dispatch.sh <judgment-class> <promptfile> <outfile> <repo>
```

Consume the completion notification and grade the artifact. The wrapper checks the central gate;
raw CLI calls bypass that enforcement.

## Grading

**Grade by the artifact.** `codex exec` exits 0 having answered a different question; a lane can also
die on the weekly cap while exiting normally. Before counting a Sol lane done: the outfile exists,
it answers the QUESTION as written, and its load-bearing claims carry printed probes. A lane whose
verdict has no probe beside it is UNSUPPORTED, not confirmed — the polarity matters most here,
because a frontier model's wrong answer is the most persuasive kind.

## Before dispatching

Honor the central gate's verdict; `codex-headroom.sh --route <class>` owns the current policy.
The weekly refusal threshold remains 99%; warning routes and unknown-cap routes dispatch.
Pace is measured as telemetry, not a separate refusal or model-degradation rule. The managed
wrapper applies this gate before launching. A refusal means keep the lane on Claude rather than
retrying at a cheaper Codex tier. Preserve the accepted finite review manifest and spent slots.
