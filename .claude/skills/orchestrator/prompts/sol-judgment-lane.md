# Sol judgment lane — bounded frontier escalation

Sol is the frontier tier. It earns its cost on **judgment**: investigation, grilling, adversarial
falsification, "is this reasoning actually sound?". It does not earn it on synthesis, summarizing,
mining, or execution — those stay on Terra or Luna.

## The shape that makes it affordable

**One question · fresh context · one document · stop.**

A Sol lane is a *lane*, never a root. `model-routing.md` rule 10 says this; the burn data says why.
Measured 2026-08-17: the weekly window went 15% → 100% in four hours, and that burst was **59% root
sessions** — 37 roots in seven hours. Cost is `turns × context_size × model_weight`. A root
maximizes the first two terms, so putting the heaviest model on one multiplies the worst case. A
fresh bounded lane pays the weight exactly once, on the turn where judgment happens.

So the rule is not "use Sol sparingly." It is **use Sol freely in this shape, never in the other
one.**

## When Sol, when Terra

| The ask | Tier | Why |
|---|---|---|
| "Is this design sound? Attack it." | **Sol** | adversarial judgment is the frontier's edge |
| "Grill this plan / find what I'm missing" | **Sol** | the value is in what a weaker model fails to notice |
| "Investigate why X — competing hypotheses" | **Sol** | hypothesis discrimination, not retrieval |
| "Falsify this finding" | **Sol** | the falsifier wave is the canonical Sol use |
| "Security / irreversible-architecture judgment" | **Sol** | already the standing escalation |
| "Summarize these N documents" | Terra | synthesis, not judgment |
| "Research how library X's API works" | Terra | retrieval; the answer is in the docs |
| "Census / locate / extract / existence check" | Luna | mechanical |
| "Run this command group" | Terra-low | procedural worker |

The split inside *research* is the one that gets missed: **research-as-retrieval is Terra;
research-as-judgment is Sol.** "What does the vendor document?" is Terra. "Which of these three
readings is right, and what would falsify each?" is Sol.

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

Spawn with `fork_turns: "none"`, `model: "gpt-5.6-sol"`, and the highest effort the question
warrants. Native `spawn_agent` exposes only Sol and Terra; the CLI form is:

```bash
cd <repo> && echo '' | codex exec --skip-git-repo-check -m gpt-5.6-sol \
  -c model_reasoning_effort=high -s read-only -o <outfile> -- "<mission>"
```

## Grading

**Grade by the artifact.** `codex exec` exits 0 having answered a different question; a lane can also
die on the weekly cap while exiting normally. Before counting a Sol lane done: the outfile exists,
it answers the QUESTION as written, and its load-bearing claims carry printed probes. A lane whose
verdict has no probe beside it is UNSUPPORTED, not confirmed — the polarity matters most here,
because a frontier model's wrong answer is the most persuasive kind.

## Before dispatching

Ask the gate — `codex-headroom.sh --model falsifier` — and honor it. At 99%+ it answers `CLAUDE`, and
a Sol lane you cannot afford is a Claude lane you did not plan for. The cap has saturated four times
(2026-07-18, 2026-08-02..05, 2026-08-11, 2026-08-17); a fresh 0% window is as often the aftermath of
a blowout as it is headroom.
