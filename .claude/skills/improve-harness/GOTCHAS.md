# Execution Gotchas

Hard-won traps, by phase. Read the relevant block before running that phase of step 4.

## Investigation (step 1)

- **Don't mutate the harness while the Workflows run.** Their agents read `~/.claude/{agents,skills,settings.json,plugins}`; pruning or editing mid-flight races them and splits the model pass. Let both Workflows finish, *then* execute.
- **Run two Workflows in parallel, not one giant one** — mining+consolidation is independent of latest-version+models. Both background; you get notified.

## Backup (step 4a)

- **Lean tar, not everything.** Back up `~/.claude/{agents,commands,hooks,skills,settings.json,CLAUDE.md}` + the small plugin manifests + `~/.agents` + the skill-lock. **Exclude `~/.claude/plugins/` cache** — it's hundreds of MB, regenerable, and a full tar of it hangs.
- `~/.claude` is itself a git repo → deletions there are also recoverable via git. `~/.agents` may not be → the tar is its only backup.
- **Verify the backup contains your delete targets** before deleting (`tar tzf … | grep <target>`).

## Prune (step 4b)

- **Verify each delete target exists first** (a stale plan may name a path that's already gone). Delete, then scan for **dangling references** — a command/skill that pointed at a now-deleted engine.

## Vendor cutover (step 4c)

- **`-s` repeats per skill** — `-s a -s b -s c`, NOT `-s a,b,c`. Comma-separated silently installs nothing (treated as one bad name) and just lists available skills.
- **The "PromptScript does not support global skill installation" failures are benign** — that's one agent type rejecting global installs; Claude Code installs fine. Confirm by checking the lock + symlinks, not the failure count.
- **Promote in-progress skills before installing** — `git mv skills/in-progress/<x> skills/engineering/<x>`, add to `.claude-plugin/plugin.json` + `README.md`, commit/push, *then* `npx skills add … -s <x>`.
- **Re-homing a skill deleted upstream** (no source): `cp` it into the fork and register it — never `npx skills update` it (404).
- **After cutover, verify:** every lock row's `source` == the fork, orphan-renamed dirs are gone (`diagnose`→`diagnosing-bugs`), and **no symlink in `~/.claude/skills` dangles**.

## Upgrade (step 4d)

- **Everything is scriptable** — `claude plugin marketplace update|remove` + `claude plugin update|install|enable` exist; no `/plugin` TUI needed. Only the **restart** (to apply) and the **bake** are human steps.
- **Model audit is surgical.** Bump only genuinely-stale IDs (e.g. a prior-gen Opus). Leave anything already on the current flagship, and leave **intentional cheap-tier routing** (a deliberately-cheaper model in an orchestrator/rescue path) — bumping it defeats the tiering.
- **Isolate MAJOR bumps and bake them.** A plugin major (e.g. superpowers 5→6) and the Codex CLI back skills/agents you rely on — do them last, flag a restart + re-test in a throwaway session. A global TypeScript major: hold until `npx tsc --noEmit` passes in the repo (global TS doesn't affect repo `tsc`, but don't assume).
- Tracker-coupled skills (`to-tickets`/`to-spec`/`triage`/`wayfinder`) stay **dormant until pointed at your source-of-truth** via `/setup-matt-pocock-skills` — keel ships GitHub / GitLab / Linear / local seeds, so configure the tracker first, then they're live. Don't rely on them un-configured.

## Hooks (step 4e)

- **A synthetic dry-run proves NOTHING — replay the ACTUAL transcripts that motivated the hook.** This is the hard requirement, not a nicety. Observed 2026-07-24: a `/goal`-condition guard passed **9/9 hand-written test cases** and shipped — then blocked a legitimate `/loop` in a live session. Replaying the three real incident transcripts showed they contained **zero slash-command prompts** (the conditions were plain prose set through the app UI), so the hook was a **false negative on 3 of 3 incidents it cited** while being a false positive on real work. The synthetic dry-run passed precisely *because* the author wrote the fixtures from the same wrong model of the bug that produced the hook. A hook validated only against inputs you invented confirms your theory, never the defect.
  - **Required before any hook is wired:** (1) it FIRES when replayed against the real transcript at the point the friction occurred; (2) it is SILENT on a healthy control session; (3) it is SILENT on the current session's own transcript; (4) its emissions are **bounded** over a long incident (count them — a guard that speaks on every one of 537 fires is a second loop).
  - **Derive the trigger from measurement, not from the lesson's prose.** The same run's first replacement keyed on assistant-message similarity because the mining report said "8 near-verbatim repeated conclusions" — measurement falsified that (consecutive tails ~0.02 similar, normalized-equal on **0 of 46 pairs**) and it missed 2 of 3 incidents. The real progress signal was **tool calls between re-fires** (gaps of `130, 207, 96, 53, 5, 2, 3, 0, 0, 0…`; 34/47 zero). Measure the candidate signal across the incidents BEFORE writing the matcher.
  - **Confirm the event's output contract against the installed binary** (`strings -a <cli> | grep -F <field>`), never from recollection — `UserPromptSubmit` blocks via `{"decision":"block"}`, `PreToolUse` via `hookSpecificOutput.permissionDecision`, and every hook may emit `systemMessage`. A wrong shape fails silently, which reads as "the hook is fine."
  - **A `Stop` hook must NEVER emit `decision:"block"`** — that is how you build the runaway loop you were trying to report. Report and let the human clear it.
- **Hook edits reach the live harness through symlinks — know which clone you just edited.** `~/.claude/skills/<name>` resolves to the CANONICAL clone (master), not to your worktree. Editing through the symlink silently dirties master while your branch stays clean, so the change ships in neither. After any skill edit, run `git -C <canonical> status` and consolidate onto the branch you are actually shipping.
- **A hook can block a tool call — dry-run its matcher before committing.** A `PreToolUse` guard that's too broad (e.g. matches every `gh` call, not just `gh pr merge`) silently wedges normal work. Test the matcher against a recent transcript's tool calls (it should fire on the friction case and stay silent elsewhere) before it lands in `settings.json`.
- **Hooks live in the harness repo** (`~/.claude/settings.json` + scripts under `~/.claude/hooks/`) — never the product or skills repo. **Never weaken `~/.claude`'s `.gitignore`** to land a hook script, and scan the `settings.json` diff for secrets before committing (same rule as step 5).
- **Prefer a hook over a prose rule for a *mechanically-detectable* wrong move; prefer a rule when the judgment is contextual.** "Resolve PR comments before merge" is mechanical → hook. "Don't over-abstract" is contextual → rule. A hook is fail-closed (it blocks), so a false-positive matcher costs more than a missed rule — calibrate width accordingly.
- **A friction loop that recurred ≥3× is the bar for a hook.** A one-off stumble is a memory note, not a hook — don't ossify a single bad session into a standing block.

## Merge (step 5)

- **Three surfaces, three mechanisms:** product-repo `AGENTS.md` → **PR** (if merge = prod deploy in your project, explicit go-ahead only); skills repo → push (then `npx skills update -g`); `~/.claude` → commit + push.
- **Never weaken `~/.claude`'s `.gitignore`.** Confirm `sessions/`, `history.jsonl`, `plugins/`, `shell-snapshots/` stay ignored before `git add -A`. Scan the `settings.json` diff for secrets before committing.
- Committing `~/.claude` also persists **accumulated memory from prior sessions** that was never committed — that's wanted (it makes the harness canonical), just expect more changed files than you authored.

## Agent-stack adoption (Workflow C)

- **Own + cherry-pick; never adopt a stack wholesale.** Every external agent collection/runtime either ships a competing orchestration layer (fails one-architecture — the standing competing-framework rejection) or is disqualified (dormant / no-license / stale-model-pins). Public sets are flat tech-specialist *catalogs* (a parts bin); our crew is a deep *lifecycle* spine — different question, not "better."
- **Verify repos LIVE; the npm name lies.** A prior run mis-identified `oh-my-claudecode` as the 2★ npm-name owner (`ragingstar2063`) and wrongly called it dead — the real active project is `Yeachan-Heo/...` v4.x (36.8k★). Always check `stargazers_count`/`pushed_at`/`archived` on the actual repo, and don't trust a stale "dormant" rationale (re-verify each pass).
- **Port patterns, not repos.** Read a candidate `.md` for its *prompt pattern* only; rewrite from scratch in our `<Agent_Prompt>` house format, re-pin to current model IDs, strip all framework/MCP/collaboration-runtime coupling.
- **Bake in domain invariants or the agent is net-negative.** This is make-or-break: a generic specialist ignorant of your project's data-safety invariants (e.g. delete-protection on the production datastore, the data-access security gate, schema-first migration ordering) is *dangerous* (it'll suggest a drop-recreate). Encode your invariants in the agent's Constraints.
- **A ported agent is UNVERIFIED until it runs once on a real in-scope task** — and new agent files only load next session, so you can't smoke-test them in the run that creates them. Flag them for first-task verification.
- **Cap scope.** Add a role only if we BOTH lack it AND exercise it ~weekly; the ml/mobile/k8s long tail is a maintenance trap — skip.

## Light vs heavy ops

`npx skills`, `claude plugin`, `gh`, `git`, and WebFetch are **light** — they are not machine-global heavy-lock ops (vitest/build/cdk). Run them directly.
