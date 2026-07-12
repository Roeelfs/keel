# Vendored skill upstreams

Keel adapts upstream skill ideas into one owned architecture. Upstream updates are
reviewed and cherry-picked; they are not copied wholesale when they would introduce
duplicate flows or overwrite project-specific guardrails.

## Matt Pocock skills

- Source: <https://github.com/mattpocock/skills>
- Last reviewed upstream commit: `391a2701dd948f94f56a39f7533f8eea9a859c87`
- Reviewed: 2026-07-12
- Existing skills compared: `ask-matt`, `grilling`, `grill-me`,
  `grill-with-docs`, `domain-modeling`, `codebase-design`, `diagnosing-bugs`,
  `triage`, `to-prd`, `to-issues`, `implement`, `prototype`, `handoff`,
  `improve-codebase-architecture`, `resolving-merge-conflicts`, `tdd`,
  `setup-matt-pocock-skills`, and `writing-great-skills`.
- Imported this review: decision-vs-fact grilling boundary, explicit plan approval
  gate, and the positive-prompting/negation vocabulary.
- Kept as intentional Keel adaptations: `to-prd`/`to-issues` naming;
  `/review` and evidence-grounded `/investigation`; prototype-as-primary-source
  capture; project verify/contamination merge guards; and the current setup flow.
- Not installed as duplicates: upstream `code-review`, `research`, `to-spec`, and
  `to-tickets` overlap Keel-owned flows. Upstream `wayfinder` is represented as a
  composed `/orchestrator` + `/investigation` flow in `ask-matt`, preserving one
  orchestration architecture.

## Update procedure

1. Clone/fetch each upstream and record its immutable reviewed commit here.
2. Compare every mapped `SKILL.md` plus directly referenced assets.
3. Import compatible behavioral improvements with attribution.
4. Record rejected overlaps and the owning Keel replacement.
5. Run `tooling/wire-skills.sh`, verify no runtime symlink dangles, and commit the
   owned source.
