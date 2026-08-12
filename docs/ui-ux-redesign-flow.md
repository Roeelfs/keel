# UI/UX product-redesign flow

Use this flow for a connected product workflow spanning several surfaces, especially when
the problem may be information architecture or handoff logic rather than visual styling.
It is not the default for a landing page or a small component polish pass.

## The stack

| Stage | Skills | Required output |
|---|---|---|
| Ground | `investigation`, then `grill-with-docs` | constraints, prior decisions, actors, jobs, failure modes, open decisions |
| Model | `service-blueprint`, `information-architecture-and-navigation`, `interaction-design`; add `conversational-ux` for chat/voice | end-to-end service loop, object/label model, task flows, state and recovery model |
| Diverge | `prototype` | 3–5 structurally different, URL-switchable variants that answer named design questions |
| Author | `brief`, `shape`, `craft` through `ui-craft`; add `ux-writing` | one confirmed design brief and one coherent visual system applied across variants |
| Evaluate | `heuristic`, `critique`, `usability-test-plan`; use `design-critique` for a live team session | comparable evidence, task-success findings, chosen direction and rejected tradeoffs |
| Harden | `unhappy`, `fixing-accessibility`, `adapt`, `finalize`, `web-design-guidelines` | non-happy states, keyboard/touch/responsive coverage, code-level findings |
| Ship | return to `to-spec` → `to-tickets` → `implement` | only the winning architecture enters the live product path |

Keel is the canonical skill source. Run `tooling/wire-skills.sh --kind skills` after
adopting or updating the stack, then require a zero-change dry run. UI Craft's optional
machine gate layer is healthy when `ui-craft doctor --json` reports `"ok": true`; install
only `mcp-gates` through the CLI so it does not replace Keel's skill symlinks with copies.

## Operating rules

1. Hold real product and trust-boundary constraints fixed. Label any variant that reopens a
   settled product decision instead of quietly treating it as greenfield.
2. Vary the workflow structure before the visual skin. At least three variants must differ
   in object model, navigation, or cross-surface handoff—not merely color, cards, or density.
3. Use exactly one visual authoring lane: UI Craft. `design-taste-frontend` can be an
   adversarial polish reference, but it is not the architect for dashboards or multi-step UI.
4. Evaluate complete user threads. A variant is not better because one isolated screen is
   prettier; it must improve comprehension, continuation, recovery, and outcome visibility.
5. Prototype code is disposable. Preserve the verdict, evidence, and winning interaction
   contract; implement the winner through the normal spec and verification flow.
6. Keep deterministic gates separate from judged critique. Accessibility, overflow, keyboard,
   console/network health, and route/data correctness can block. Aesthetic scores inform the
   decision but do not impersonate product evidence.

## Default prototype matrix

For a workflow spanning an assistant, a durable business view, and an operational queue,
start with these four hypotheses:

1. **Connected destinations** — preserve three destinations; make receipts and continuation
   explicit between them.
2. **Unified owner workspace** — one workspace with chat, business state, and work queue as
   modes of the same loop.
3. **Contextual assistant** — durable workspaces remain primary; the assistant becomes a
   sidecar or drawer available in context.
4. **Request-first** — the durable request/work object is primary; chat and business context
   appear inside its lifecycle.

Before visual work, score each hypothesis on: first-time comprehension, continuity after an
interruption, visibility of commitment and progress, recovery from failure, power-user speed,
mobile viability, accessibility, and compatibility with the real system boundaries.
