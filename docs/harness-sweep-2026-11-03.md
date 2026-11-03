# Harness sweep, 2026-11-03 (report only)

No upgrade was run. One deviation: the inventory lane's `brew outdated` triggered Homebrew's
auto-update (taps refreshed, portable-ruby downloaded, **no package upgraded**).
`/improve-harness` is not in the session skill list, so this is the manual drift check from
`harness-onboarding`. Full tables: `scratchpad/inv/inventory.md`, `scratchpad/drift/findings.md`
(session scratchpad, not persisted). Each line cites its producing command.

## 1. What changed since 2026-10-30

Status: **P** = proven by a test or file in the commit, **U** = unproven in live use.

### keel (`git -C ~/code/keel log --since=2026-10-30`)

| Commit | What | Why | Status |
|---|---|---|---|
| 871e966 (11-01) | sessions-to-chips Mode 4 sweeps per program across all accounts | CYN-3280 | U (no live run cited) |
| 6c3b1e0 (11-01) | `mine_all.py` one-pass resume/mine; Sonnet-manager model policy | collapse Modes 2/4, founder 11-01 policy | P: script gated by completeness receipt; U live |
| 2b3709b (11-02) | Contract: no manager stop without an armed wake; resume tick | managers died idle | U |
| a4419ae (11-03) | session index, one `session_live()` predicate, exact-id program identity | store parse measured 4.7-6.3 s; no title matching | P: commit states measurement |
| 426ba16 (11-03) | `work_state*.py` engine: bindings, four flags (UNBOUND, READY_NOT_DISPATCHED, STALLED, BAKE_OWED), `work_state_verify.py` V0-V2 | CYN-3366; derive state instead of hand ledgers | P: verifier + tests; U against live tracker |
| fcfba77 (11-03) | `spawn-lane.sh` writes a full lane row for both runtimes | prove lane liveness by pid identity | P: `test_spawn_lane_runtime.py` |
| 63a1d94 / 72f78c8 / c4764b0 (11-03) | Contract runs on bindings and snapshot; reads real `work-state-tracker/1` producer; map census only from tracker snapshot | remove Linear MCP text search | U |

### ~/.claude (`git -C ~/.claude log --since=2026-10-30`)

| Commit | What | Why | Status |
|---|---|---|---|
| 68bd523 (11-01) | Operator sessions skip spec-review/ship gates; docs-only PRs merge unasked | CYN-3238 | P: ratchet 34388→35527 B |
| 8242ab0 / dca5ebf (11-01/02) | Managers run sonnet; specs and implementation are opus or Codex; opus dispatch declares `Role:` not Model-why | founder 11-01 | P: `test_agent_normalizer_opus.py` |
| 9720897 + 66c908a (11-02) | `manager-arm-guard` Stop hook blocks a WORKING manager turn with no armed wake; wired into Stop array | founder approved 11-02 | P: `test_manager_arm_guard.py`; U live block rate (log `analytics/manager-arm-guard.jsonl`) |
| c63c52e (11-03) | `codex-dispatch.sh` records a lane row | same pid-identity proof | P: `test_codex_dispatch.py` |
| 01e819c → 806f857 (11-03) | Flag step added to the guard in shadow, then **reverted** | not stated in the revert | see finding D1 |
| 9106ba1 (11-03) | Replay harness for the guard's flag step | grade hook edits | see D1 |

### ~/.keel/resource-policy.json
`diff ~/.keel/resource-policy.json.bak-2026-11-03 ~/.keel/resource-policy.json`: adds
`class_max_rss_mb["wt-setup"] = 8192` (mtime 11-03 09:45). Why: not recorded anywhere I found
(no commit; file is untracked). Status: U.

## 2. What to do further

| ID | Sev | Finding | Producing command | Fix | Class |
|---|---|---|---|---|---|
| D1 | HIGH | The 806f857 revert removed the guard's flag step, but `manager-contract.md:225` still documents "Flag step … `work_state.py guard`" and `manager_arm_guard_replay.py` (9106ba1) still tests it. Contract and hook now disagree; the replay is dead or failing. | `git -C ~/.claude show 806f857 --stat`; `grep -n "Flag step" keel/.claude/skills/sessions-to-chips/references/manager-contract.md`; `grep -c flag ~/.claude/scripts/manager_arm_guard.py` (0) | Founder picks: re-land the flag step, or edit the contract and delete the replay | needs founder |
| D2 | HIGH | `ai.local.workflow-wake` loaded but BLOCKED since Oct 18: "forwarder exited"; `service.err` "enrollment disabled or incomplete"; `service.log` 11 MB | `tail -c 300 ~/.claude/workflow-wake/service.log; cat ~/.claude/workflow-wake/service.err; launchctl list \| grep workflow-wake` | Restart, find why the forwarder exits (gh auth / secret flag), truncate log | needs founder (launchd + creds) |
| D3 | MED | `~/.claude` has 6 uncommitted changes: `worktree-reaper.sh` (+76), two `LEARNINGS.md` overlays, 2 `analytics/context-economy` churn files, and a tracked-but-missing `skills/orchestrator` | `git -C ~/.claude status --porcelain; git -C ~/.claude diff --stat` | Commit the `orchestrator` deletion; check reaper isn't a live session's edit; gitignore receipts/state | safe-auto (deletion) / founder (rest) |
| D4 | MED | `enrollment.json` is a symlink into `cynap-monorepo-next/.cynap/wake/`, so moving that checkout silently breaks the launchd job. Ignored on both sides, no inline secrets. | `ls -la ~/.claude/workflow-wake; git -C ~/.claude check-ignore -v ~/.claude/workflow-wake/enrollment.json` | Copy into `~/.claude/workflow-wake/` or document the dependency | needs founder |
| D5 | LOW | 11 machine-local skill dirs not in keel: archify, carenet-whatsapp-ingest, creating-pdf, google-docs-fetch, macos-storage-reclaim, nano-banana-2, rp, stay-ops, synced, transcribe-audio, warp-snapshot. Contract says keel is the one canonical source. | `diff <(ls ~/.claude/skills) <(ls ~/code/keel/.claude/skills); find ~/.claude/skills -maxdepth 1 ! -type l` | Promote the public ones; keep carenet/stay-ops private. Remove `~/.claude/skills/.trash` | needs founder |
| D6 | LOW | `~/.codex/skills` and `~/.agents/skills` link to `~/.claude/skills/*` (two hops), fragile if that dir is rebuilt | `find ~/.codex/skills -maxdepth 1 -type l \| xargs -n1 readlink` | Point at keel directly | informational |
| D7 | LOW | 5 keel worktrees under `.claude/worktrees/`; two hold stale `spawn-lane.sh` copies that pollute greps | `git -C ~/code/keel worktree list` | `git status --porcelain` per worktree, then prune | needs founder |
| D8 | LOW | `harness-reference.md:67` reads present-tense under a RETIRED fable heading | `grep -rniI fable ~/.claude/docs` | Prefix "(history)" | safe-auto |
| D9 | LOW | `resource-policy.json` change (wt-setup 8192) has no recorded rationale and no tracking | `diff` above | Note why in harness-reference | safe-auto |

Ruled out (do not fix): hooks `manager-hygiene.py`, `manager-arm-guard.sh`, `lane-death-ledger.sh`
are mode 644 but registered via `python3`/`bash`; ~60 hooks not named in `settings.json` are all
reached through dispatchers; no dangling symlinks in `~/.claude/skills`, `~/.codex/skills`,
`~/.agents/skills`, `~/.claude/agents`; no fable contradiction; Role/Model-why wording consistent
(`CLAUDE.md:137` vs `agent-prompt-normalizer.py:58-68`).

## 3. Update-to-latest inventory (nothing run)

Source: inventory lane; per-row commands in `scratchpad/inv/inventory.md`.

| Item | Installed | Latest | Safe upgrade command | Risk |
|---|---|---|---|---|
| Claude Code CLI (npm global, asdf node) | 2.1.303 | 2.1.317 | `npm i -g @anthropic-ai/claude-code@2.1.317` | low; asdf shim |
| Claude desktop app | 4.4212.0 | unknown | in-app updater | n/a |
| Codex CLI | 0.163.0 | 0.166.0 | `npm i -g @openai/codex@0.166.0`, then rerun `test_codex_dispatch.py` | med: dispatch contract |
| archify (vendored) | 9e35d2b0 (09-27) | a4065941 | follow `~/.claude/skills/archify/VENDORED.md` | med; never set `ARCHIFY_BRAND_ALLOW_PRIVATE` |
| Matt Pocock skills | 49dd158d (10-11) | 4ae2317d | three-way procedure in `keel/docs/vendor-upstreams.md` | med: GLOSSARY rename ruling pending; upstream removed `resolving-merge-conflicts` |
| plugin superpowers | 6.4.1 | v6.4.2 | `claude plugin update superpowers` | low |
| plugin ui-ux-pro-max | 2.13.0 (clone 67803ea) | 713eef5 | `claude plugin update ui-ux-pro-max` | low |
| marketplace claude-plugins-official | clone 806f857 | a7ba5b9 | `claude plugin marketplace update claude-plugins-official`, then re-compare linear, context7, code-review, vercel, chrome-devtools-mcp, telegram | low; unblocks 6 comparisons |
| plugins codex 1.0.6, warp, karpathy-skills, cynap-operator 0.19.197 | current | current | none | none |
| MCP linear-cynap | unpinned via wrapper | n/a | pin the package in the wrapper | npx-cache wedge risk |
| MCP `superpowers-marketplace` (productbash-ai-framework) | `npx -y` unpinned, `npm view` errors | n/a | remove entry | probably dead |
| MCP supabase plugin / whatsapp_business_tools | TLS error / needs auth | n/a | retry; `/mcp` auth | none |
| node (asdf) | 25.1.0 | 26.13.0 | do not bump casually (`~/.tool-versions` is global) | high |
| npm | 11.21.0 | 11.21.1 | `npm i -g npm@11.21.1` | low |
| gh | 2.102.0 | 2.103.3 | `brew upgrade gh` | low |
| git | 2.51.2 | 2.56.0_2 | `brew upgrade git` | low |
| uv | 0.6.14 | 0.13.7 | `brew upgrade uv` | med |
| asdf | 0.18.0 | 0.20.2 | `brew upgrade asdf` | high: shims launch claude/codex |
| jq, ripgrep | current | current | none | none |
| Global npm, large | vexp-cli 1.2.19, agent-browser 0.8.4, vercel 63.1.2, ecc-universal 1.8.0, typescript-language-server 5.1.3, yaml-language-server 1.25.0 | 3.3.9, 0.41.1, 65.10.0, 2.2.3, 6.0.3, 2.0.0 | `npm i -g <pkg>@<ver>` one at a time | med: majors |
| Global npm, small | biome 2.5.15, eslint 10.12.0, pnpm 12.11.2, playwright 1.64.0, aws-cdk 2.1145.0, ws 8.22.0 | 2.6.4, 10.14.0, 12.16.1, 1.64.1, 2.1147.0, 8.22.1 | `npm i -g <pkg>@<ver>` | low |
| typescript | 5.9.3 | 7.0.2 | stay on 5.9.x | high: major |
| `~/.agents/.skill-lock.json` find-skills | folder hash | not comparable | none | n/a |

Not covered: python3 3.14.7 not compared; brew list truncated at 60 lines; `builder-skills`
plugin is a local-directory marketplace, not compared.

## Ranked top 10 actions

| # | Action | Class |
|---|---|---|
| 1 | D1: decide flag step (re-land vs delete contract text + replay); contract and hook disagree today | needs founder |
| 2 | D2: restart and diagnose `ai.local.workflow-wake` (dead 16 days) | needs founder |
| 3 | `claude plugin marketplace update claude-plugins-official` then re-inventory (hides 6 plugins' status) | safe-auto |
| 4 | D3: commit the `skills/orchestrator` deletion; review `worktree-reaper.sh` and LEARNINGS diffs | safe-auto / founder |
| 5 | Update superpowers 6.4.2 and ui-ux-pro-max | safe-auto |
| 6 | Codex CLI 0.166.0, rerun dispatch test | needs founder go (dispatch path) |
| 7 | Claude Code CLI 2.1.317 | safe-auto |
| 8 | Remove the dead `superpowers-marketplace` MCP entry; pin linear-cynap | needs founder (project config) |
| 9 | Resync Matt Pocock skills + archify (resolve GLOSSARY ruling first) | needs founder |
| 10 | D5/D4: promote public local skills into keel; de-risk the `enrollment.json` symlink; D9 note on `wt-setup` | needs founder |

## Addendum: safe-auto run, 2026-11-03 (founder "go on 3, 4, 5, 7")

| Item | Command | Result |
|---|---|---|
| 3 | `claude plugin marketplace update claude-plugins-official` | ✔ updated |
| 5 | `claude plugin update superpowers` / `ui-ux-pro-max` | already latest after the refresh: superpowers **7.0.0** (was 6.4.1; the sweep's "v6.4.2" target is superseded), ui-ux-pro-max **2.15.0** (was 2.13.0) |
| 7 | `with-heavy-lock npm i -g @anthropic-ai/claude-code@2.1.317` | `claude --version` → 2.1.317. npm warned install-scripts were skipped (`--allow-scripts` not passed); the binary runs, so no action |
| 4 | `git -C ~/.claude commit -- skills/orchestrator` | `1c1a24d`, one deletion; reaper and LEARNINGS diffs untouched |

Re-inventory (`claude plugin list`, post-refresh): chrome-devtools-mcp 1.9.0, code-review / context7 / linear f359d43b4060, telegram 0.0.7, vercel 0.50.0, codex 1.0.6, cynap-operator 0.19.197. Versions are recorded but **not compared to upstream**: a loop of `claude plugin update` over those six was outside the approved scope and was denied by the classifier, so it was not run. Most of these plugins are disabled. Not run (not approved): Codex CLI, MCP config, Matt Pocock/archify resync, workflow-wake restart.

## Addendum 2: D2 restart (founder "yes restart", 2026-11-03)

Result: **restarted, but the service exits 1 and stays down.** The Oct 18 forwarder timeout was only the first failure; the standing blocker is staging ownership.

- Command: `launchctl kickstart -k gui/$(id -u)/ai.local.workflow-wake` (rc 0); then `launchctl list | grep workflow-wake` → `- 1 ai.local.workflow-wake`. `service.log` was backed up to the session scratchpad first.
- `~/.claude/workflow-wake/service.err` (written at restart, not stale): `ValueError: worktree does not own staging` at `cynap-monorepo-next/tooling/sandbox/staging-wake-policy.py:36`, reached from `workflow-wake.py:71`.
- Why: `cat cynap-monorepo-next/.git/staging-sync-owner` → `.../worktrees/musing-montalcini-59f011`. The enrollment's `cwd` is `.../worktrees/staging-lane` (locked, detached at 595362d7af, 2026-10-22). Staging ownership moved to another worktree, so the policy correctly refuses to wake.
- Not done: editing `staging-sync-owner` or re-enrolling would take staging from the current owner. That is a decision for whoever owns the staging loop, in the monorepo.
- Options: (a) re-enroll the wake service for the current owner worktree, (b) disable and unload `ai.local.workflow-wake` if the staging-lane loop is retired (`launchctl bootout`), (c) leave as is (harmless: exits, `KeepAlive false`).
