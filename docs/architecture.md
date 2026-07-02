# Architecture

keel has no runtime of its own. It's a set of files that shape how an existing AI
coding CLI (primarily Claude Code) behaves. Four layers, each doing one thing:

```
┌──────────────────────────────────────────────────────────────────┐
│  RULES        CLAUDE.md / AGENTS.md / docs/security-policy.md      │
│               docs/testing-config.md                              │
│               → the contract every agent reads; the law of the repo│
├──────────────────────────────────────────────────────────────────┤
│  SKILLS       investigation · spec-review · spec-test-plan/execute │
│               root-cause-analysis · improve-harness · … (36 total) │
│               → multi-step procedures the agent invokes on demand  │
├──────────────────────────────────────────────────────────────────┤
│  AGENTS       architect · code-reviewer · critic · debugger        │
│               executor · explore · refactorer · scientist          │
│               security-reviewer · sql-specialist · tracer          │
│               → focused sub-agents the skills dispatch in parallel │
├──────────────────────────────────────────────────────────────────┤
│  SUBSTRATE    hooks (session lifecycle, id capture, heavy-op lock) │
│               tooling/workflow (path ownership + in-flight registry)│
│               → the coordination layer that runs under everything  │
└──────────────────────────────────────────────────────────────────┘
```

### Why this split

Each layer answers a different failure mode of naive agent use:

- **Rules** answer *"the agent doesn't know how we do things here."* They live in
  version control, get read on every session, and are phrased as a contract so the
  agent can't rationalize around them.
- **Skills** answer *"complex work needs a repeatable procedure, not improvisation."*
  A skill is a checked-in playbook: the spec-review pipeline always mines decisions,
  always dispatches the same ten lanes, always cross-examines disagreements — and
  the grounding skills (`investigation`, the RCA gate) always fan out for outside
  evidence instead of trusting the model's baked-in knowledge.
- **Agents** answer *"one context doing everything does each thing worse."* A
  dispatched sub-agent has a tight prompt, its own context window, and one job —
  and several run in parallel.
- **Substrate** answers *"multiple agents/sessions collide and the machine melts."*
  Path ownership and the heavy-op lock are pure coordination, invisible until two
  sessions would otherwise step on each other.

### How a typical flow uses all four

1. You write a spec under `docs/specs/`.
2. You invoke **`spec-review`** (skill). It reads the **rules** to know your
   security policy and conventions, mines the session via **`claude-sessions`**, and
   dispatches the review **agents** in parallel.
3. You invoke **`spec-test-plan`** then **`spec-test-execute`** (skills), which read
   `docs/testing-config.md` (**rules**) to run real tests and dispatch
   **`debugger`/diagnostician agents** on failures.
4. Throughout, the **substrate** keeps your session's file claims registered, shows
   the in-flight registry so parallel sessions don't duplicate work, and serializes
   heavy test/build commands.

Nothing here is magic — it's the boring infrastructure that makes the model's
output trustworthy. The deep-dives:

- [parallel-agents.md](parallel-agents.md) — the path-ownership + coordination layer.
- [spec-flow.md](spec-flow.md) — the spec → review → test pipeline.
- [investigation.md](investigation.md) — dropping into an unfamiliar codebase.
- [philosophy.md](philosophy.md) — the engineering discipline encoded in the rules.
