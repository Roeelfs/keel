---
name: investigation
description: Ground an external-facing or unfamiliar task in real web facts before acting - ALWAYS as a dynamic multi-agent Workflow that frames the task in THIS codebase, fans out across angles x sources, adversarially cross-verifies, and bakes in evidence + the industry standard/elevation. Deciding test: do you need a vendor's DOCS or your own LOGS? Fire generously (over-grounding is cheap; a miss is the costly error) when you need a third-party library/API/framework's documented API, limits, or version - even if the name is familiar but its current API isn't; on version-currency or deprecation; on approach-selection where a standard applies; on an unfamiliar third-party error; on the fence, fire. Hard-skip (overrides the fire, even when a vendor is named): debugging or baking your project's OWN runtime (services/jobs/handlers/deploys/alarms you run) - truth is your logs + codebase; a mechanical one-line diff; pure internal authoring (spec/issue/memory/PR/git). Escalate to `deep-research` for a fully-cited report.
---

# Investigation

Ground an unfamiliar task in real external facts **before** you act. The output is a short **grounded brief** — enough to start correctly — not a report.

## When to ground

The deciding test: **do you need a third-party vendor's DOCS, or your own LOGS?** Vendor docs → ground; your own logs/codebase → skip, even when the task names a vendor.

**Ground** when you need a library/API/SDK/framework's real shape, limits, idioms, or current version (even if the name is familiar but its current API isn't); on version-currency or deprecation ("is X still the way"); on approach-selection where an industry standard shapes the design; on an unfamiliar third-party error. Over-grounding is cheap — on the fence, ground.

**Currency self-check** (the gap topic-class can't see): familiarity is not currency. If your memory of a third-party API/SDK/version predates your knowledge cutoff and the work depends on its *current* shape, ground — you won't feel uncertain about a confidently-remembered-but-changed API, so make currency, not familiarity, the trigger. A borderline tie-breaker; it does not override the hard-skips.

**Hard-skip** (overrides the fire, even when a vendor is named): debugging or baking *your own* runtime — the services, jobs, handlers, sandbox, sign-in, deploys, backups, alarms you operate — where the truth is your own logs + this codebase, not the web; a one-sentence mechanical diff (typo, rename, log line); and pure internal authoring (spec, issue/tracker, memory, PR body, git mechanics).

## The grounding run — always a dynamic Workflow

Once the gate fires, grounding **always runs as a dynamic multi-agent Workflow** — never an ad-hoc handful of inline queries. The fan-out is what bakes in real *evidence* (every load-bearing claim adversarially cross-verified against an independent source) and what *the industry is actually doing* (the `industry_standard` + `elevation` sections, grounded in primary sources). The workflow-script template and guardrails live in [`DEEP-WORKFLOW.md`](./DEEP-WORKFLOW.md) — launch it, stop, and read its result when it completes (it runs in the background; never poll it).

**Width scales to breadth — it does not switch the run off.** A narrow topic fans out to 2–3 research agents; a broad one to 8–12. The template clamps width to `N` (default 4, range 2–12) so "always a Workflow" never means "always 12 agents" — it means the run is always the framed → fanned-out → cross-verified pipeline, sized to what the topic earns. (The truly trivial case never reaches here: the hard-skips above gate it out before a Workflow is ever launched.)

The three phases are the frame → research → brief contract, scaled out:

1. **Frame (internal fan-out).** Parallel reader agents map the premise's own reality — what the task needs, what already exists in this codebase/architecture, the real goal and constraints, prior art. Every codebase claim cites a real `file:line`, never a guess; a synthesis step distils them into a Problem Frame plus the sharp research questions that seed phase 2. The frame is what makes the research queries *yours*, not generic.
2. **Research (external fan-out, seeded by the frame).** One agent per research question, queries shaped by the real stack the frame named. Prefer primary sources (official docs/changelogs, the source repo, GitHub code search) over the top SEO hit — [`SOURCES.md`](./SOURCES.md) holds the per-source recipes (GitHub, TLDR, Hacker News, docs, …) and the search gotchas that silently un-ground a brief. A verify stage adversarially cross-checks load-bearing claims against an independent source, and the verdicts are **enforced in code** — refuted/unchecked claims are partitioned out before synthesis, so a refuted claim can't land as a stated fact.
3. **Synthesize — the brief.** Merge frame + verified findings into a grounded brief (~1–2k tokens), sections: `TL;DR · Problem frame · Industry standard · Elevation (best-in-class) · Tips & gotchas · Recommendations for THIS task · What to research next · Sources`. **One LIVE source URL per claim** (liveness-check each before citing — dead/fabricated URLs are the top failure mode); build the industry-standard + elevation sections only from verified claims. Date-check anything fast-moving and surface the source's date.

Save the brief to `docs/investigations/YYYY-MM-DD-<slug>.md` — **create the dir first (`mkdir -p docs/investigations`)**; a bare write to a missing dir silently loses the brief. Open it with a freshness header — `> Grounded <date> against sources current as of <dates>; supersede on re-investigation of this slug` — so a stale "is X current" brief can't mislead later; a same-slug brief supersedes the older one. Then post it and hand off to `/grill-with-docs` (if present) — its open questions and recommendations are the grilling's ammunition.

When the Workflow won't do — every claim cited and cross-checked into a standalone, fully-cited report — escalate to the `deep-research` skill.

## Done when

The brief exists, every claim carries a source (or is flagged unconfirmed), and it's saved and handed off. A brief padded past ~2k tokens, or carrying an ungrounded assertion, isn't done — it's drifting toward deep-research; cut it back or escalate deliberately.

---

**Maintaining this skill** — the gate-calibration recipe (mine real session openers → confusion-matrix eval), the re-eval cadence, the watched over-fire set, and the install/desync runbook live in the private overlay if present: `~/.claude/skills-overlay/investigation/MAINTAINING.md` (adopter-private; never in this public repo). Read it before editing the gate or reinstalling.
