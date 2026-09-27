---
name: codex
description: Delegate bounded Codex research, review or implementation from Claude through the central capacity and model routing gate.
---

# Codex dispatch

Claude owns the conversation, accepted scope and integration. Delegate independent work to Codex through one of these two routes. Give each lane one objective, the smallest evidence slice, exact allowed paths, an artifact contract and a stop condition. State: "You are a leaf agent: do NOT spawn sub-agents or Workflows; do the work inline and return."

## Read-only artifact

Use `~/.claude/scripts/codex-dispatch.sh <class> <promptfile> <outfile> [repo]` for research, census, a named-file review or a bounded second opinion. It isolates HOME and keeps the repo outside the writable scratch root. For a diff review, name the exact base and changed paths in the prompt. The final artifact must contain the answer, evidence and limitations.

## Implementation and local commits

Use `~/.claude/scripts/spawn-lane.sh --runtime codex --class <class> --mission <file> --cwd <prepared-worktree>` for implementation. It retains the normal profile and allows local git writes. Network is explicitly denied by default; `--allow-network` is only for work that requires network and confers remote-write capability too. The caller owns remote publication after grading the artifact and satisfying project gates. Supplied MCP config and Claude permission/worktree options are rejected; do not assume the normal Codex profile is empty of MCP servers.

Both routes consult `~/.claude/scripts/codex-headroom.sh --route <class>`, the single model/effort table. The shipping route also gates explicit `--model` overrides and applies class effort. At refusal, keep the lane on Claude. Routine coding/retrieval uses `standard`; mechanical mining uses `mining`; adversarial falsification uses `falsifier`; hardest bounded judgment uses `architecture`, `security`, `hard-rca` or `adjudication`. Use Astra judgment when the task warrants it, with fresh context and one decision artifact. Honor the declared finite review manifest and spent slots.

Launch either command through harness-tracked background Bash (`run_in_background: true`), with unique output paths. Read the completed artifact when the completion notification arrives. Grade its objective content before accepting it: exit zero alone does not prove success. No detached `&`, status polling or sleep loops. A bounded launch has a completion owner; consume or interrupt owned work before finalizing.

Project verification requirements remain mandatory. Build lanes run targeted checks; the accepted verify-release task runs its required project gate once. Honor existing same-SHA PASS evidence. Neither this skill nor a plugin can waive a project gate or production approval. Any merge or production publication still requires the project's explicit authorization.

The official Codex plugin may remain installed for explicitly requested plugin capabilities; its companion path is not this harness's central routing path. Do not modify vendor cache files or adopt retired model aliases. Legacy companion jobs use their existing recovery tools until accounted for.
