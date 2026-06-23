# The discipline keel encodes

Skills and tooling are the machinery. The *discipline* is what makes the machinery
worth running. These are the convictions baked into the
[`CLAUDE.md` template](../templates/CLAUDE.md.template) and the agent definitions —
the rules an agent should never have to be told twice.

### Verify before claiming done

An agent will tell you it's finished because the code *looks* finished. "It should
work" is not "it works." Every claim of done is backed by an actual command and its
actual output — the build ran, the tests passed, the feature was exercised the way
its user would. The `verifier` agent exists solely to enforce this: it trusts
observed output, including over the claims of whoever asked it.

### Leave exactly one architecture behind

The fastest way to rot a codebase is to add the new path without deleting the old
one — two ways to do the same thing, a flag to pick between them, a "keep it just in
case" copy. Conflicting parallel architectures are the number-one cause of an agent
(or a human) getting lost. So: **delete the code path you replace, in the same
change.** No dead code, no commented-out blocks, no renamed-but-unused vars, no
re-exports for moved symbols.

### No speculative abstraction

Build for the requirement in front of you, not the one you imagine. An abstraction
introduced for a hypothetical future is a cost — more indirection to read, more
surface to maintain — masquerading as foresight. Prefer boring, observable,
reversible designs. Add the seam when the second caller actually arrives.

### Small units, matched to their neighbors

Files in the low hundreds of lines, functions under ~50. New code follows the
conventions of the code around it — naming, structure, error handling, test style.
Consistency is a feature: it's what lets the next agent (or the next human) predict
where things are and how they work.

### Errors are handled, not swallowed

A bare `catch {}` that hides a failure is worse than a crash, because it turns a
loud problem into a silent one. Fail loudly or handle deliberately; never paper over.

### Right-sized changes, off a fresh base

One coherent change per PR. Split only on a true ordering dependency — "it's large"
is not a reason to fragment a feature into half-mergeable slices. And always branch
off fresh trunk: a stale base is the most common cause of divergence, which is why
the in-flight registry shows you how far behind every branch is.

### Traceability is cheap; use it

Conventional commits with a required scope make history searchable and let tooling
key off the scope. A `Session-Id:` trailer links every commit to the agent session
that produced it — so months later you can answer "what was the session that wrote
this, and why." keel's hooks capture the session id; the `claude-sessions` skill
reads the trailer back.

---

None of this is novel — it's the discipline good engineers already hold themselves
to. The point of writing it into the harness is that an AI agent doesn't *have* that
discipline by default. It has to live outside the model, in rules the agent reads
every session and tooling that makes the wrong thing hard. That's the whole idea
behind keel.
