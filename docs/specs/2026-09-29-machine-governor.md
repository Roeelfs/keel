# SPEC — Machine governor: contended admission, local-vs-CI routing, delegated reclaim, red-main coordination

> Status: DRAFT r2 for implementation, 2026-09-29. r1 (650 lines) is preserved at `/tmp/governor/rev/SPEC.v1.md`.
> Design of record: founder-approved "machine governor" plus the founder rulings of 2026-09-29 (in-session), applied in r2.
> Evidence: brief `docs/investigations/2026-09-29-design-an-intelligent-local-vs-ci.md` (cynap worktree `bridge-cse_01Fq6LrfJHPYvR2d28ZhPqFs`), stall report `/tmp/verify-stall/REPORT.md`, critiques `/tmp/governor/critiques.md`, probes `/tmp/governor/design-review-lane/probe{,2}.py`, r2 probes `/tmp/governor/rev/stats2.py` and `/tmp/governor/q1probe/`.
> `/tmp` is volatile. Before implementation, copy this file, `/tmp/governor/spec-author/{req4.json,resp4.json,chains.py}`, `/tmp/governor/rev/stats2.py` and `/tmp/governor/design-review-lane/probe*.py` into keel under `docs/specs/2026-09-29-machine-governor/`.
> §17 maps every critique id to its resolution. V6 (ETA error) moved to phase 2 (§16).

---

## 1. Goal and victory metrics

**Goal.** One governor per machine does four jobs:
1. It decides whether a **contended** heavy job may start now.
2. It routes a cynap verify to local or CI.
3. It reclaims CPU, RAM and disk through a detached, rate-limited sonnet/low lane that can act only through a policy-enforcing executor.
4. It coordinates the sessions on this machine while cynap `main` is red.

**Why now (measured).**
- Over 7 days of `~/.keel/heavy.slots/events.jsonl` (2026-09-22T17:28Z → 2026-09-29T17:28Z) there were 6,284 acquires and **113 deferrals, so 1.8% of acquires were contended** (`probe.py`). The wait from queued to started was p50 0.05 s and p90 5.3 s.
- **61 of 114 deferrals (54%) were re-queued unchanged within 15 min** (`chains.py`). This retry compounding is what turns a 540 s ceiling into waits of 1 h or more.
- Wrapper scripts hold slots. Of the 80 `resource_busy` deferrals, about 34 were blocked by a whole `bash`/`zsh`/`sh`/`*.sh` wrapper holding a slot for its entire life, and 13 of the holders had been alive for more than 30 min (`probe2.py`).
- The fixed policy over-reserves memory. `pressure_reason()` (`heavy_runner.py:63-72`) charges a flat `max_rss_mb=6144` to every second job. Measured peak RSS across 10,284 completions is p50 821 MB, p90 4,018 MB, max 5,163 MB, and zero completions exceeded 6,144 MB.
- Disk sits at 89–91% used (42–48 GiB free). 296 cynap worktrees hold 151 GiB, about half of it on merged branches.
- On 2026-09-29, two sessions raced to fix the same red `main`.

**Victory metrics.** Each one names its probe.

| # | Metric | Baseline | Target (2 weeks after phase 1) | Probe |
|---|---|---|---|---|
| V1 | Deferrals **per 1,000 acquires** (7-day rolling). A raw count swings 1→48 per day with workload. | 18.0 (113 / 6,284) | ≤ 4.0, and ≤ the deterministic-rule counterfactual (§5.2) | `governor grade --since 7d` → `deferrals_per_1k`, `d_rule_counterfactual_per_1k` |
| V2 | Retry chains: a deferral followed by an unchanged re-queue ≤ 15 min later that is itself deferred again | 61 / 114 re-queued | 0 | `governor grade` → `retry_chains` |
| V3 | p90 time from the first feature-branch `cynap-sandbox verify` to a local `started` or a CI route receipt | UNPROVEN; phase 0 measures it | ≤ 600 s | `governor grade` joined with `.cynap/verify-route.jsonl` |
| V4 | Free disk on `/System/Volumes/Data` | 42 GiB free | never < 10 GiB; snapshot p10 ≥ 25 GiB | `governor grade` → `disk_free_gib_min`, `p10` |
| V5 | Kills of an active session's work, from **every** kill engine (§9.6) | n/a | **0, hard.** A violation flips shadow inline (§9.5). | `governor audit-kills` plus the inline check |
| V7 | Red-main episodes where more than one session pushed a fix for the same failing run | 1 (2026-09-29) | 0. Every episode has an owner notice within 10 min of detection and one all-clear. | `governor grade` → `redmain` from `redmain/receipts.jsonl` joined with `gh pr list --search <sinceSha>` |

## 2. Non-goals

- The governor makes no change to CI workflows, runners or the PR matrix. The router only *chooses* CI; it never adds jobs.
- No preemption. A job that was admitted and is progressing (§9.3) is never killed.
- No remote execution backend. The brief's verdict was BUILD a small router and adopt none.
- `apps/backend/src/lib/customer-ai/adapters/jev.ts` stays out of scope. It is drifted and dark-gated (`jev.ts:22-26`); it uses a separate wire shape, language and runtime. The same change files one Linear `CYN` issue (the number is taken from the `create_issue` return value), attaches `req4.json`/`resp4.json`, and adds a pointer comment at `jev.ts:51`.
- No Linux parity. On Linux a missing signal is `unknown`, which selects the deterministic rule.
- The governor does not run `claude -p` inside a caller's process, and it never ships transcript text to a third party.

## 3. Architecture and ownership

| Concern | Owner repo | File | Ship verb |
|---|---|---|---|
| Snapshot, admission (fast path, D rule, floors, JEV on contended acquires only) | keel | `tooling/sandbox/governor/{snapshot,admission,jev_client}.py` (new), called from `heavy_runner.acquire()` | direct commit to `master`, gated by `python3 -m unittest tooling/sandbox/test_*.py` |
| Wrapper broker and heavy-tool shims | keel | `tooling/sandbox/governor/broker.py`, `resource-hooks/shims/*` (new) | same |
| Tick agent (reclaim trigger, red-main detector, single-flight, rate limits, lane spawn) | keel | `tooling/sandbox/governor/tick.py`, LaunchAgent `ai.keel.governor.tick` (new) | same |
| Executor: closed verb set, re-validation, receipts | keel | `tooling/sandbox/governor/act.py`, CLI `governor-act` | same |
| Grading and kill audit | keel | `tooling/sandbox/governor/grade.py`, CLI `governor grade\|audit-kills\|replay` | same |
| Lane spawn primitive (`--effort`, `--allowed-tools`) | keel | `bin/spawn-lane.sh` (the `~/.claude/scripts/spawn-lane.sh` symlink target) | same |
| Deferral-retry guard | keel | `.claude/hooks/serialize-heavy-ops.py` | same, plus the Codex re-trust step (§13) |
| Build-output strip (Pass A only) | claude-harness | `scripts/worktree-reaper.sh` | commit to `main` |
| Cache/tmp sweep; absorbs `disk-clean`'s unique rows | claude-harness | `scripts/disk-keeper.sh` | same |
| Storage discipline and target table (the lane *invokes* this) | claude-harness | `skills/macos-storage-reclaim/SKILL.md` | same |
| Verify route | cynap | `tooling/sandbox/verify-route` (new `.mjs`), folded into `cynap-sandbox verify` | PR → merge (prod-class, needs explicit go-ahead) |
| Red-main registration and signal source | cynap | `.claude/governor/red-main.json` (new) pointing at the existing `tooling/sandbox/lib/main-deploy-health.mjs` | same PR |
| vitest watchdog kill path | cynap | `tooling/process-watchdog/vitest-watchdog.mjs` → `governor-act` | same PR |

- **Why admission lives in keel.** `heavy_runner.py` is the single chokepoint that Claude and Codex callers both pass through.
- **Why the tick is a LaunchAgent and not the caller.** B3 showed that doing reclaim inside `acquire()` runs under the caller's signal handlers (`heavy_runner.py:213-217` raise `Interrupted`) and without single-flight. The tick runs detached, every 300 s. `acquire()` only *requests* a tick early (§9.1).
- **Global-layer rule.** keel names no repo. A repo opts into red-main coordination with its own `.claude/governor/red-main.json`, and the machine list of opted-in repos lives in `~/.keel/governor/repos.json`.

```
agent Bash ─► serialize-heavy-ops.py ─► (retry guard §8) ─► with-heavy-lock
   with-heavy-lock: wrapper? ─yes─► broker (§6): no slot; PATH shims route heavy children back into with-heavy-lock
                    else ─► acquire(): fast path (free slot within policy.slots AND pressure_reason() is None) ─► admit, no JEV
                                       contended ─► floors ─► arbiter = JEV (after promotion, cached 20 s) | D rule (fallback + comparator)
                                       deny/defer ─► write reclaim.request; `launchctl kickstart` the tick (async, never waits)
ai.keel.governor.tick (300 s, detached) ─► reclaim tier 0 ─► sonnet/low lane ─► governor-act …
                                        └► red-main check per opted-in repo ─► sonnet/low lane ─► SendMessage / gh pr comment
cynap-sandbox verify ─► verify-route ─► with-heavy-lock --admit-preview --class cynap-verify-<mode> --json
```

## 4. Snapshot (`snapshot.take()`)

Budget: 300 ms total, 250 ms per subprocess probe. A failed probe records `null` plus its name in `unknown[]`. Samples are appended to `~/.keel/governor/snapshots.jsonl` at most once per 10 s; the file rotates at 20 MB and keeps 2 generations.

| Field | Source |
|---|---|
| `ncpu`, `load[3]`, `load1_per_core` | `sysctl -n hw.ncpu vm.loadavg` |
| `mem_pressure_level` (1/2/4), `mem_free_percent`, `mem_total_mb` | `sysctl kern.memorystatus_vm_pressure_level`; existing `heavy_resources.free_percent()` / `total_memory_mb()` |
| `swap_used_mb`, `swap_total_mb`, `swap_growth_mb_per_min` | `sysctl vm.swapusage`; the growth is the delta against the newest sample that is between 60 s and 10 min old |
| `disk_free_gib`, `disk_used_percent` | `os.statvfs('/System/Volumes/Data')` |
| `hang_reports_recent` | `~/Library/Logs/DiagnosticReports/*.{hang,spin}` with mtime < 600 s (unproven on Tahoe, §18 Q2) |
| `leases[]`: `{slot, job_id, class, age_s, rss_mb, members}` | the lease files; `members` holds the `[pid, pgid, identity]` triples that `heavy_runner` already records (`heavy_runner.py:285-303`) |
| `queued`, `deferrals_last_60m` | the `queue/` tickets and `events.jsonl` |
| `class_stats[class]`: `{run_p50_s, run_p90_s, rss_p90_mb, rss_s_p90, n}` | `started`/`completed` events, recomputed at most every 10 min into `~/.keel/governor/class-stats.json`. A class with n < 10 uses `other-heavy`. |

- **Job classes.** `heavy_command.classify(executable, args)` returns one of `cynap-verify-full`, `cynap-verify-quick`, `vitest-targeted`, `vitest-suite`, `tsc`, `wt-verify`, `wt-setup`, `pnpm-install` or `other-heavy`. The `queued` event gains a `class` field, which closes the stall report's UNPROVEN (b) from now on.
- **Session and worktree joins.** These are computed only in tick and executor snapshots, never on the admission path.
  - The registry is `~/.claude/sessions/<pid>.json`, with keys `pid, sessionId, cwd, status, procStart, statusUpdatedAt, kind, entrypoint, …` (read 2026-09-29: 40 desktop idle, 5 desktop busy, 4 sdk-cli).
  - An entry is live only if `kill -0` succeeds AND `procStart` equals `lstart`.
  - The transcript is `~/.claude/projects/<cwd with / → ->/<sessionId>.jsonl`.
  - A tree's owner is found by walking the ppid chain to a registry pid, then by a cwd match. If neither finds one, the owner is `unknown`. `unknown` never means dead.

## 5. Admission

### 5.1 Fast path: uncontended acquires never wait on anything new

Inside `acquire()`'s loop (`heavy_runner.py:229-241`), the first `claim_slot(directory, policy, position)` runs exactly as today, with `policy.slots` and `pressure_reason()`.
- If it returns a slot, the job is admitted. No snapshot, no D rule, no JEV.
- This covers about 98.2% of acquires. It removes r1's 84% JEV hot-path share (critique BLOCKING#1: 5,272 of 6,284 acquires missed the cache, adding ~45–130 min of latency per week).

**Contended** means `claim_slot` returned `resource_busy` or `memory_pressure`. Only then does the arbiter below run. Every call it makes happens **outside** all slot flocks (§5.6).

### 5.2 Deterministic rule D (the fallback AND the shadow comparator)

```
reserve_mb   = Σ over live leases of max(0, class_stats[lease.class].rss_p90_mb − lease.rss_mb)   # peak each running job has not reached yet
fit          = floor(((free_pct − min_free_percent)/100 × mem_total_mb − reserve_mb) / class_stats[job].rss_p90_mb)
slots_now_D  = clamp(running + fit, 1, max_slots)
admit_D      = no floor fires AND running < slots_now_D
```

- This is the founder formula `clamp(floor((free%−min_free)×total_mb/class_p90_rss),1,max)`. The `/100` fixes units. `running + fit` expresses it as a total, because `free_pct` already nets out running jobs. `reserve_mb` subtracts running jobs' not-yet-reached peaks, so a job that is 10 s into a 4 GB run is not counted as free memory.
- Every input comes from `Policy()` and `class-stats.json`. There are no literals. `min_free_percent` stays in `resource-policy.json`.
- D replaces the flat 6,144 MB second-job charge **on the contended path only**. On the fast path `pressure_reason()` still reserves conservatively, so the fast path is never looser than today.
- **Class asymmetry (r1's rule never fired on real data).** r1 gated on `rss_p90 ≤ 1024`, but wt-verify is 4,497 MB p90, so no job could ever qualify. The r2 gate is on RSS×seconds: a job with `class_stats.rss_s_p90 ≤ cheap_rss_seconds` (default 131,072 MB·s) may take `min(slots_now_D + 1, max_slots)` when no floor fires and `mem_pressure_level < 4`.
  - Measured with `stats2.py` over all history:
    - wt-verify.sh: n=1,323, run p90 8 s, RSS×s p90 27,704. Qualifies.
    - wt-setup: n=490, run p90 23 s, RSS×s p90 67,631. Qualifies.
    - cynap-sandbox: n=413, run p90 612 s, RSS×s p90 2,372,241. Does not qualify.
  - This targets the 12 + 16 cheap deferrals.

### 5.3 Hard floors (nothing overrides them; they deny, never kill)

| Floor | Default (policy field) | Signal |
|---|---|---|
| `disk` | `disk_free_gib < 10` | statvfs |
| `swap_growth` | `> 256 MB/min` sustained ≥ 60 s | snapshots.jsonl |
| `mem_critical` | `mem_pressure_level == 4` | sysctl |
| `app_hang` | `hang_reports_recent ≥ 1` | DiagnosticReports. **Shadow-only** until §18 Q2 proves the signal exists. |

- A floor whose signal is `unknown` does not fire.
- Any unknown machine signal routes the decision to D and never to JEV, so a partial snapshot never reaches the model.
- A contended DENY caused by a floor also writes a reclaim request (§9.1). So does the soft `disk_reclaim_gib = 25` threshold, which never denies.

### 5.4 JEV (contended acquires only; decides only after beating D in shadow)

- **When.** JEV runs only on a contended acquire where no floor fired and no signal is unknown. The decision is cached per class for `decision_ttl_s = 20` in `~/.keel/governor/decision.<class>.json`.
  - A single writer takes `flock(LOCK_EX|LOCK_NB)` on `decide.lock`. A waiter that loses the lock reuses a decision up to 40 s old, or else uses D. It never queues on JEV.
  - Expected volume is on the order of 100 calls per week, not ~5,000.
- **Wire shape.** This is proven and unchanged from r1 (`req4.json`/`resp4.json`).
  - The request is `{model:"typesafe-ai/jev", state, questions:{name: Q}}`.
    - `boolean` needs `instructions` or `criteria`.
    - `choice` takes `criteria` as a record.
    - `score` takes `criteria` as an array.
  - The response is `{answers:{name: {type, probability | choice+probabilities+confidence | score+probabilities+confidence}}, usage, providerMetadata}`.
  - Every call logs `resolvedProvider` and `usage` (the probe saw routing to `digitalocean` with silent fallback).
- **Question set ADMIT.**
  - `state` holds integers and short strings only: `job{class, est_run_p50_s, est_run_p90_s, est_peak_rss_mb}`, `machine{ncpu, load1_per_core, mem_pressure_level, mem_free_percent, swap_used_mb, swap_total_mb, swap_growth_mb_per_min, disk_free_gb}`, `lock{leases_live, lease_ages_s[], lease_classes[], queued, deferrals_last_60m}` and `d_rule{slots_now, admit}`. There are no paths and no session text.
  - Questions:
    - `admit` (boolean: "Can this machine start ONE more job of job.class now without driving memory pressure to critical, exhausting swap, or making interactive apps unresponsive?")
    - `headroom_slots` (choice `"1"`…`"6"`)
    - `saturation` (score over 5 rungs, idle→thrashing).
- **Mapping.** JEV may be more permissive or more restrictive than D; this is the founder's "sometimes more, sometimes less".
  - `admit.p ≥ 0.60` AND `saturation < 3.5` → admit into `clamp(headroom_slots, 1, max_slots)` when confidence ≥ 0.30, else into `slots_now_D`.
  - `admit.p < 0.40` OR (`saturation ≥ 3.5` with confidence ≥ 0.6) → deny.
  - Anything in between → D.
- **Fallback is D.** An error, a 1,500 ms deadline breach, an open breaker, a missing credential, or a contract error each produce `source=fallback:<reason>` and D's verdict. The call has 0 retries.
- **Promotion gate: JEV must beat D, not today's flat budget.** `governor grade` compares the two arms on contended decisions where they disagreed (n ≥ 30 in each direction):
  - *JEV-less*: D admitted and JEV would have denied. The observed outcome is the admitted job's fate: `memory_pressure_during_run`, `resource_limit`, a budget kill, or `mem_pressure_level == 4` or the swap floor firing during its run. JEV wins this side if the bad-outcome rate on these jobs is ≥ 2× the rate on jobs where both arms agreed to admit.
  - *JEV-more*: JEV admitted and D denied. This outcome is counterfactual, so it is projected from the recorded snapshots over the next `run_p90_s`: `used_mb + class rss_p90` must stay below `(100 − min_free_percent)%` and no floor may fire. JEV wins this side if ≥ 95% of these admissions are projected safe.
  - JEV is promoted to arbiter only if it wins both sides. **If it has not won by 2026-11-15, the JEV admission code is deleted** (jev_client, questions, the breaker, the cache and the Keychain read). That removes about a third of the design and avoids a permanent dual path.

### 5.5 Policy fields (`heavy_resources.Policy`; `load_policy()` still rejects unknown keys)

| Field | Default | Note |
|---|---|---|
| `governor_mode` | `shadow` (`shadow` \| `enforce`) | **Deleted on 2026-11-15.** After that date the governor is the only behavior and a rollback is `git revert` of the keel commit. If phase 1 has not been promoted by then, the governor code is deleted instead. `KEEL_GOVERNOR_MODE` may only move enforce → shadow and is deleted with the field. There is no `off` value: `shadow` enforces today's fixed policy verbatim. |
| `jev_admission` | `shadow` (`shadow` \| `enforce`) | Same deletion date. See §5.4. |
| `max_slots` | 6 (replaces `MAX_SLOTS = 4`, `heavy_resources.py:13`) | `§14.2` lock-only replay must show that the peak RSS sum at k=6 fits in RAM before phase 1. Otherwise lower it. |
| `cheap_rss_seconds` | 131072 | §5.2 |
| `disk_floor_gib` / `disk_reclaim_gib` / `swap_growth_floor_mb_per_min` | 10 / 25 / 256 | env overrides may only tighten |
| `jev_deadline_ms` / `decision_ttl_s` / `admit_p_hi` / `admit_p_lo` / `saturation_deny` | 1500 / 20 / 0.60 / 0.40 / 3.5 | |
| `idle_kill_hours` | 6 | K3 (§9.3) |
| `reclaim_min_interval_s` / `reclaim_daily_max` / `reclaim_max_runtime_s` | 1800 (600 for `urgent_disk`) / 6 / 1200 | §9.2 |
| `broker_shells` | `["bash","zsh","sh","dash"]` | §6 |

Invariant tests read these defaults from `Policy()`, never from a literal.

### 5.6 Timeouts, state on disk, credential

| Stage | Budget | On breach |
|---|---|---|
| Snapshot (contended path only) | 300 ms | the probe becomes `unknown`, and the decision goes to D |
| JEV call | 1,500 ms wall clock, 0 retries | `fallback:timeout` → D |
| Breaker | opens after 3 failures in 30 min; stays open 15 min | **State lives in `~/.keel/governor/breaker.json`**, read-modify-written under `flock`. Every `with-heavy-lock` is a fresh process, so an in-memory breaker would never open (M6). |
| Credential | `/usr/bin/security find-generic-password -s vercel-ai-gateway -w`, 250 ms | Read only when `~/.keel/governor/credential.json` says `{ok:true}` and is < 24 h old. Otherwise `fallback:no_credential`. The key stays in process memory only and is never logged. |

- **Hot-loop rule.** The snapshot, D and JEV all run after `claim_slot` has released every flock (`heavy_runner.py:164-198` closes its streams in `finally`), and before the next `claim_slot(…, slots=<arbiter slots>)`. The arbiter's slot count is passed in as a parameter; `claim_slot` never calls admission itself.
- **Keychain is resolved in phase 0, not left as an open question.** A 250 ms timeout cannot suppress a `securityd` dialog, because the dialog belongs to securityd and not to the child. So the founder runs this once, interactively: `security add-generic-password -U -s vercel-ai-gateway -a "$USER" -T /usr/bin/security -w "<key>"`. Then `governor probe-credential` runs from the tick's launchd context and from a Bash-tool context, and writes `credential.json`. Until both pass, JEV stays off.

## 6. Wrapper broker (the dominant `resource_busy` fix)

**Problem.** `with-heavy-lock bash round5.sh` holds a slot for the script's whole life. Nested heavy calls reuse that lease (`valid_lease`, `heavy_runner.py:48-60`, then `execvpe` at `:535`). About 34 of the 80 `resource_busy` holders were wrappers of this kind, and 13 of the 80 holders had been alive for more than 30 min.

**Rule.** At the top level (no valid lease), a command is a wrapper when:
- `basename(command[0])` is in `policy.broker_shells`, OR it ends in `.sh`; AND
- its basename is not a custom rule in `~/.keel/resource-commands.json` (so `wt-verify.sh` and `wt-setup` keep a slot); AND
- it is not self-locking (`heavy_command.is_self_locking`, `heavy_command.py:19`).

A wrapper runs in **broker mode**:
- It takes no slot. It emits `broker_started`/`broker_completed` events with the tree's peak RSS.
- It runs with `PATH=~/.keel/resource-hooks/shims:$PATH`.
- It gets the same `max_seconds` supervision as a leased job.
- It runs as a `setsid` session leader, so `job_members` can still find its tree.

**Shims.** There is one shim per heavy tool name that `heavy_command` already recognises: `PACKAGE_MANAGERS`, `TEST_RUNNERS` (`heavy_command.py:8-10`), plus `tsc`, `turbo`, `cdk`, `next` and `node`. Each shim:
- runs `heavy_command.classify(argv)`;
- if the command is heavy, `exec with-heavy-lock <real> argv…`, so the child queues for its own slot and releases it on exit;
- otherwise `exec`s the real binary, resolved on `PATH` with the shim directory removed.

**Repo scripts called by path cannot be caught by a PATH shim.** cynap `wt-verify.sh` and `wt-setup` gain the same self-lock preamble that `cynap-sandbox` already has (`cynap-sandbox:294-300`). The preamble re-execs under `with-heavy-lock` unless `with-heavy-lock --check-lease` passes.

**Residual.** A heavy binary called by absolute path inside a wrapper runs without a slot. `grade` counts `broker_completed` events with peak RSS > 2 GiB whose tree took no child slot, as `unslotted_heavy_per_1k`. If that exceeds 2 per 1,000 acquires, the offending wrapper names are listed for a shim or a self-lock preamble.

**Exit codes.** A child deferral exits 75 inside the wrapper, and the wrapper's own exit code propagates. The §8 guard then matches on the child's cwd and executable.

## 7. Verify route (cynap `tooling/sandbox/verify-route`)

`cynap-sandbox verify` calls `verify-route --mode <quick|full> [--after-deferral] --json` exactly once, where the CYN-1951 reroute block is today (`cynap-sandbox:891-908`). `verify-route` reads the governor through `with-heavy-lock --admit-preview --class cynap-verify-<mode> --json` under a 3 s timeout.
- `--admit-preview` runs the §5 decision for a hypothetical job without enqueuing and without requesting reclaim. It returns `{decision, source, slots_now, running, queued, eta_wait_p90_s, eta_run_p50_s, eta_total_s}`.
- **Phase-1 ETA (deterministic):**
  - `eta_wait_p90_s = 0` when admitted. Otherwise it is `min over leases of max(0, run_p90(lease.class) − age) + floor(queued / slots_now) × run_p90(cynap-verify-<mode>)`.
  - `eta_total_s = eta_wait_p90_s + run_p50(class)`.
  - The run term is p50, not p90. A p90 run term of 612 s would exceed 600 on its own and would send *every* feature-branch verify to CI, uncontended ones included. That costs about 19–20 billed jobs per push (stall report).
  - A refined model is deferred to phase 2 (§16).

**Rules, first match wins.** `LOCAL_WAIT_CI_THRESHOLD_S = 600` is the only definition of 600.

| # | Condition | Route |
|---|---|---|
| R1 | `CI=true`, OR the branch is `main`/`staging`, OR `--protected` (pre-push) | **LOCAL, never offloaded.** A deferral here prints "no local verdict" and exits 75. |
| R2 | `--full-local` | LOCAL |
| R3 | `--after-deferral` (the lock already exited 75 once in this invocation) | **CI.** A deferral is never retried locally. |
| R4 | preview unavailable (timeout, keel absent) | LOCAL with the policy wait; `route_source=no_governor` |
| R5 | `decision=admit` | LOCAL |
| R6 | `eta_total_s > 600` on a feature branch | **CI** |
| R7 | otherwise | LOCAL with `KEEL_HEAVY_WAIT_MAX = min(eta_wait_p90_s + 120, 600)` |

**Choosing the CI action (R3/R6). Never double-dispatch.**
- (a) There is an open PR and `HEAD` equals the pushed PR head. The PR's `pull_request` run already covers this `headSha`, so do not dispatch. Resolve that run and print its URL.
- (b) There is an open PR with unpushed commits. Print "push once (Push Cadence); the PR's CI verifies". verify-route never pushes.
- (c) There is no PR. If a `workflow_dispatch` run for this `headSha` already exists, queued, in progress or completed, print it. Otherwise dispatch `cmd_verify_remote` **without `gh run watch`**, print the URL, and stop.
- Why (a) matters: `ci.yml` concurrency is `ci-${{ github.ref }}` (`ci.yml:14-16`), so a PR run and a dispatch run sit in different groups and would both run the full matrix.
- The headSha resolver is extracted from `cynap-sandbox:779-787` into one function, `resolve_ci_run --event pull_request|workflow_dispatch`. It is not copied.
- A CI verdict exits 75 with `verify-route: ROUTED TO CI (<rule>) — no local verdict; do not retry locally`.
- `cynap-sandbox verify` re-invokes the router with `--after-deferral` when the lock exits 75 on a feature branch.
- **Receipt.** Each route appends `{ts, route_id, branch, head_sha, mode, rule, route, ci_action, preview}` to `.cynap/verify-route.jsonl`. `route_id` is exported as `CYNAP_VERIFY_ROUTE_ID`, and `append_verify_history` (`cynap-sandbox:88-93`) records it.

## 8. Deferral-retry guard (keel `serialize-heavy-ops.py`)

- **Match.** The guard looks for a `deferred` event in the last 15 min whose `queued` record has the same cwd and executable as the command about to run. Today the hook's heavy path is `serialize-heavy-ops.py:86-100`.
- **On a match.** It calls `with-heavy-lock --admit-preview --class <c> --json` (≤ 2 s).
  - If the preview says `admit`, the command is allowed.
  - Otherwise it denies with: `with-heavy-lock: DEFERRED <n>s ago in this worktree and the machine still cannot admit <class>. Do not retry. In a repo with a verify router run it with --after-deferral (cynap: tooling/sandbox/verify-route); otherwise report "no local verdict".`
- It fails open when the log is unreadable or the preview times out.
- This is V2's mechanism. `governor replay` asserts that the matcher intercepts all 61 re-queues in the frozen corpus.
- Codex callers are covered only after the Codex `/hooks` re-trust (§13).

## 9. Reclaim

### 9.1 Trigger: detached, single-flight, never in the caller

- **In `acquire()`.** A contended DENY or deferral does two things and returns:
  1. It appends `{ts, reason, class}` to `~/.keel/governor/reclaim.request` with `O_APPEND`.
  2. It runs `launchctl kickstart gui/<uid>/ai.keel.governor.tick` with `Popen`, without waiting.
- Nothing else happens in the caller: no kills, no deletes, no lane. `--admit-preview` never writes a request (B3 d).
- **In the tick** (`ai.keel.governor.tick`, `StartInterval 300`, plus kickstarts):
  - It takes `flock(LOCK_EX|LOCK_NB)` on `~/.keel/governor/reclaim.lock`. A second tick that finds the lock held exits at once.
  - It consumes the requests.
  - It evaluates the reasons:
    - `denial_streak`: ≥ 3 distinct job_ids denied in 15 min;
    - a floor: `urgent_disk` or `memory`;
    - `disk`: free < `disk_reclaim_gib`.
  - It enforces `reclaim_min_interval_s` for **both** tiers, not just for lanes.
  - The tick process ignores SIGINT and SIGHUP, so a user cancel in some session cannot land mid-delete.

### 9.2 Tier 0 (deterministic, in the tick) then tier 1 (lane)

**Tier 0.** `governor-act sweep --auto` runs K1, K2 and K4 (§9.3), then the storage rows marked auto (§9.4). It runs **one action at a time, re-measuring container free after each one**. It is capped at 60 s. If the condition clears, it stops.

**Tier 1.** If the condition persists, and the rate limits allow (at most 6 per 24 h; back-off doubles to a 4 h cap after a lane that freed < 1 GiB and killed nothing), the tick spawns a lane in a detached supervisor.
- The lane runs under `setsid`.
- `reclaim.lease.json` records `{pid, procStart, run_id}`. It is stale when the pid is dead or `procStart` does not match.
- The lane gets SIGTERM at `reclaim_max_runtime_s` and SIGKILL 30 s later.
- The run is graded by its receipts, never by its exit envelope.

```
spawn-lane.sh --runtime claude --model sonnet --effort low --mode dontAsk --cwd ~/.keel/governor/lanes/<run_id> \
  --allowed-tools "Skill,Read,Grep,Glob,Bash(~/.keel/resource-hooks/governor-act:*),Bash(~/.keel/resource-hooks/governor-snapshot:*),Bash(diskutil info:*),Bash(du -shx:*),Bash(tmutil listlocalsnapshots:*),Bash(find:*)" \
  --mission ~/.keel/governor/lanes/<run_id>/mission.md
```

- `spawn-lane.sh` gains `--effort` and `--allowed-tools`, which pass straight through to `claude -p`. Today any unknown argument exits 2 (`spawn-lane.sh:56`). `claude --help` (2.1.284) lists both `--effort <level>` and `--allowedTools, --allowed-tools <tools...>`.
- The lane's `cwd` is its own run directory, so the lane-env hook is inert.
- In shadow, the supervisor exports `GOVERNOR_ACT_FORCE_DRY_RUN=1`, and `governor-act` honours it unconditionally.
- **Mission (template; any leftover `{{…}}` placeholder refuses the spawn):**

```markdown
GOAL: restore headroom. Trigger {{reason}} at {{ts}}. Victory: `governor-snapshot --admit-preview --class {{blocked_class}}`
says admit AND disk_free_gib ≥ {{disk_reclaim_gib}}.
STATE: snapshot {{snapshot_path}}; tier-0 receipts {{tier0_receipts}}; inventory {{inventory_path}}.
STORAGE: invoke Skill(macos-storage-reclaim) and follow its Diagnostic Flow, Enlisting, target table and Verification.
Where the skill says to delete, call `governor-act storage --row <skill row id>` instead (the executor measures the
container-free delta per the skill). Where the skill says ASK, or names a row the executor lacks, write a proposal.
PROCESSES: `governor-act kill --class K1|K2|K3|K4 --pid <pid> --identity <lstart> --why "…"`. A refusal is final.
One action, then re-measure. Never batch. Stop at victory.
FINISH: {{run_dir}}/summary.json = {freed_mib, killed[], refused[], proposals[], victory}.
```

- **Why not Codex.** The lane mutates machine state and reads the harness session registry, so it fails the global offload test (a)/(c).
- **Why not `bypassPermissions`.** The executor is the policy. The lane cannot run `kill`, `rm` or `git worktree remove` directly.

### 9.3 Kill policy (executor re-derives every gate at kill time)

**Mechanism (B1).** `governor-act kill` never calls a bare `killpg`.
1. It re-samples `heavy_resources.processes()`.
2. It refuses if the target pid's `Process.identity` (lstart, `heavy_resources.py:119-140`) differs from the `--identity` the lane recorded. This closes the pid-reuse TOCTOU.
3. It builds the victim set:
   - For a leased job or a brokered tree (both are session leaders; `heavy_runner.py:458` uses `start_new_session=True`), the set is `job_members(root, identity, table)` (`heavy_resources.py:158-169`).
   - For any other root, the set is the root's descendant subtree by ppid.
4. It signals through `signal_members` (`heavy_runner.py:339-350`). That function signals a whole group only when the group's leader is a member, and never signals its own process group. Any other member is signalled by pid.
5. The signal sequence is TERM, a 10 s wait, then KILL.
6. It refuses when any member's pgid equals the pgid of a live registry session or bridge process. Measured case: `claude.exe` pid 48648 had pgid 44317, which is its `claude rc` bridge, and `spawn-lane.sh:213-216` `exec`s `claude -p` in the caller's group.

**Never-kill set.** This set is computed first. The protected-tree logic moves from `free-resources.py` into `act.py`: the self tree, busy session trees, `/Applications/Claude.app`, the heavy-op veto, and the rule that ppid==1 is not a licence to kill.

| Class | Detection (all must hold) | Auto? |
|---|---|---|
| **K1 orphan tree** | The owner is **positively dead on two samples ≥ 5 min apart**: the registry pid is gone or its `procStart` mismatches, AND that registry file's mtime did not advance between the samples. The samples are kept in `~/.keel/governor/owner-samples.json`. No live registry session has a cwd inside the tree's worktree. The tree is **not progressing** (§9.3.1). **Churn guard:** if > 25% of registry pids are dead in the current sample (a desktop restart, crash or update), the cycle makes no K1 kills. | tier 0 |
| **K2 same-worktree duplicate** | ≥ 2 trees with the same worktree and the same normalized command. The victim is not the newest, is not progressing, and its owner is the same live session or dead. | tier 0 |
| **K3 idle session's heavy tree** | Deterministic; **no JEV and no transcript text leaves the machine** (M1). All of these must hold: the tree is **not progressing** per §9.3.1 (not merely "holds no progressing lease", M4); there is **no pending background tool_use** in the owner's transcript tail (a `tool_use` with `run_in_background` and no matching `task-notification` or result); the worktree branch's PR is `MERGED` or `CLOSED` (`gh pr list --state all --head <b> --json state`, cached 15 min); the owner's transcript has been idle ≥ `idle_kill_hours` (6); and the worktree is not shared with another live session. It kills the heavy tree only, never the session process. | lane, phase 1 |
| **K4 orphan dev server** | ppid==1; `next dev`, `\bvite\b` or `nodemon`; nothing heavy in its subtree | tier 0 |
| **K6 unleased runaway vitest** (from the watchdog, §9.6) | A vitest with RSS ≥ 2 GiB that is **not** a member of any lease's `members`. Leased jobs are already budgeted by `supervise()`. | watchdog |
| N1 active | registry `busy`, OR transcript mtime < 5 min, OR an unmatched tool_use in the tail | **never** |
| N2 progressing | §9.3.1 | **never** |
| N3 | self, the desktop app, MCP children of live sessions, launchd, non-user processes | **never** |
| N4 | a Codex tree whose owner is not positively dead (the Codex transcript location is unverified) | report only |
| N5 | whole Claude session processes | out of scope; interactive `free-resources` only |

#### 9.3.1 Progressing

A tree is progressing if any of these held in the last 5 min:
- its summed CPU time advanced by more than 5 s, measured as the `ps time=` delta across two samples 30 s apart, taken inside `governor-act`;
- any file under its cwd changed, excluding `node_modules`, `.git` and `.turbo`;
- it is younger than `run_p90_s(class) × 1.5`.

### 9.4 Storage and worktree rows (gates live in the executor; the skill supplies yields and discipline)

The yields are the skill's measured, dated figures (`SKILL.md` "Reclaim Target Table", L76-104). Every action is sized by the `diskutil info /` container-free delta, one action at a time.

| Row | Target | Executor gate | Tier |
|---|---|---|---|
| S1 | leaked `$(getconf DARWIN_USER_TEMP_DIR)` prefixes (`lambda-asset-size-*`, `deploy-parity-*`, `ci-parity-*`, `handler-size-*`); +18,125 MiB on 09-29 | `-mmin +120` and no holder (`lsof +D`) | auto |
| S2 | repo-root `.turbo/cache`; +6,775 MiB | no live heavy tree in that repo | auto |
| S3 | `~/.cache/uv`, `~/.npm/_cacache`, `~/Library/Caches/Google`. `~/.npm/_npx` is **excluded** (it holds MCP server code). | none | auto |
| S4 | worktree build output via **`worktree-reaper.sh --apply --pass A`** (new selector; today `--apply` runs Pass A, Pass B and `worktree prune` over every repo, `worktree-reaper.sh:21-22,255-302`) | the reaper's own liveness and coverage gates | auto |
| S5 | `~/.codex/logs_2.sqlite` + WAL | no `lsof` holder | auto |
| S6 | `worktree-remove` | See below. | auto from phase 1 |
| S7 | Colima `docker image prune -a -f` then `colima ssh -- sudo fstrim -av` | profile running; no container started in the last 10 min | lane |
| S8+ | unused Colima profiles, abandoned desktop profiles, OS assets | **proposal only** | human |

**`worktree-remove` gate (M2).** All of these must hold:
- The worktree is **not locked**. This is absolute and no flag overrides it.
- No live session has its cwd in the worktree, and no file is younger than 60 min.
- The branch's PR is `MERGED` or `CLOSED`. PR state is used rather than ancestry, because squash merges never pass `merge-base --is-ancestor` (`worktree-reaper.sh:288`).
- `git status --porcelain --ignored` is empty **after removing entries under the regenerable allowlist**: `node_modules/`, `.turbo/`, `.next/`, `dist/`, `coverage/` and `cdk.out/`.
- It refuses outright if any of these exist: `WORKING.md`, `.env*`, `.cynap/`, `.claude/workflow-state/` or `.claude/settings.local.json`.
- A plain `git worktree remove` would silently delete ignored files. This gate matters because this very worktree holds `apps/{backend,portal}/.env.local`.
- The executor then runs plain `git worktree remove` against the worktree's own repo. The branch is kept.

### 9.5 Receipts and inline halt (M5)

- Every attempt appends to `~/.keel/governor/receipts.jsonl`. A `pending` line is written before the side effect and a final line after, both with the same `receipt_id`.
  - Fields: `{verb, class, target{pid, identity, pgid, cmd, cwd}, session{id, status, idle_s}, gates{…}, result, bytes{before, after, delta_mib} | rss_freed_mb}`.
  - Receipts carry no message text.
- **Inline halt.** `governor-act kill` re-reads the owner's transcript tail for N1 at kill time. It re-reads it again 60 s after each `done` kill. If a user or assistant record is timestamped within 5 min before the kill, or if a new record appears within 60 s after it, it rewrites `governor_mode=shadow` in `~/.keel/resource-policy.json` at once and records `halt:late_activity`.
- The daily `audit-kills` run is only the backstop.

### 9.6 One kill policy for every engine (M3)

| Engine | Today | r2 |
|---|---|---|
| `ai.cynap.vitest-watchdog` (60 s) | kills any vitest with RSS ≥ 2 GiB regardless of owner or lease, and orphans ≥ 600 s (`vitest-watchdog.mjs:150-155`) | The RSS arm calls `governor-act kill --class K6`, which refuses lease members. The orphan arm calls `--class K1`, which applies the two-sample dead-owner rule. Its own `process.kill` is deleted. Its kills land in `receipts.jsonl`, so V5 sees them. |
| `ai.cynap.workflow.reaper` | its plist points at `.claude/hooks/heartbeat-reaper.sh`, which does not exist in the main checkout or on `origin/main`; the plist is not loaded (`launchctl list`, 2026-09-29) | delete the plist |
| `free-resources.py` | its own kill loop (`free-resources.py:328-340`) | becomes a thin CLI over `governor-act`, keeping the interactive whole-session close (N5) |
| `heavy_runner.supervise()` | budget kills of the job it owns | unchanged. It kills only its own job's members. |

## 10. Session archiving (§18 Q1 answered 2026-09-29, read-only)

**Answer: a headless `claude -p` lane cannot archive a desktop session. No supported path exists.** Evidence:
- `archive_session` is a tool of **`ccd_session_mgmt`**, an in-process server that the desktop app serves. It is defined in `/Applications/Claude.app/Contents/Resources/app.asar` alongside `list_sessions`, `unarchive_session`, `stop_session` and others.
- The CLI binary (2.1.284, `readlink -f $(which claude)` → `…/@anthropic-ai/claude-code/bin/claude.exe`) lists `ccd_session_mgmt` only in the set of **desktop-injected** server names. The server type is `"sdk"`, which only the desktop host supplies.
- `strings -a <binary> | grep -ci archive_session` → 3 hits. All three are the telemetry name `fleet_view_archive_session`, which is `claude agents` view archiving a *remote/cloud* session through `archiveRemoteSession` → `POST /v1/sessions/<id>/archive`. None is a local-session tool.
- Sanity control: `--effort` → 21 hits.
- `claude --help` lists no archive command. `claude rm <id>` deletes *background* sessions only. `spawn-lane.sh:39-40` already records that interactive MCPs do not load in `-p`.
- UNPROVEN residue: a one-turn live lane listing `ccd_session*` tools was not run, because this lane was barred from spawning. It is phase-0 item 3 and is expected to confirm the answer.

**Safe equivalent.**
- (a) **Disk** does not depend on archiving. The skill's 7,173 MiB came from removing 33 worktrees; archiving only hides sidebar rows (`SKILL.md` L141-166). S6's gate is PR state plus cleanliness, not archive state, so the lane recovers the bytes without archiving anything.
- (b) **Sidebar hygiene.** The lane writes `~/.keel/governor/archive-candidates/<date>.tsv` with columns `sessionId, cwd, branch, pr_state, idle_days, worktree_state`. It lists sessions that are not running, idle ≥ 7 d, and have a clean or gone worktree with no OPEN PR. The founder, or any **desktop-hosted** session, then runs the skill's step 4 on that file. The skill's "ALWAYS ASK" stays intact, so SKILL.md needs no consent amendment and r1's §12 consent change is dropped.
- (c) **Transcript compression is not built.** Top-level transcripts total 2.46 GiB across 713 files, and only 0.22 GiB (76 files) have been idle for more than 30 d. That is not worth breaking `--resume` or the `/rp` and `/work-report` miners (`SKILL.md` Common Mistakes). The decision is recorded in §16.

## 11. Red-main coordination (Job 4)

**Registration.** cynap adds `.claude/governor/red-main.json`:

```json
{"repo": "Cynap-ai/cynap-monorepo-next", "status_context": "main-health",
 "health_cmd": ["node", "tooling/sandbox/lib/main-deploy-health.mjs", "--repo", "Cynap-ai/cynap-monorepo-next", "--out", "{out}"]}
```

`~/.keel/governor/repos.json` lists the repo root.

**Detection (the tick, every 300 s).**
1. Make one cheap call: `gh api repos/<repo>/commits/main/status`, and read the `main-health` context (`main-health.mjs:33`).
2. Only when that context is red or missing, run `health_cmd`. Its TSV contract is `RED\t<wf>\t<conclusion>\t<run url>\t<sha>\t<since>\t<owner>\t<context>`, with exit 0 green, 1 red, 2 unknown (`main-deploy-health.mjs:28-32`). `owner` is `#<PR>`, taken from the first red commit's subject (`:156-162`).
3. Exit 2 (unknown) never triggers a message.
4. The **episode key** is `<repo>@<sinceSha>`. Its state lives in `~/.keel/governor/redmain/<key>.json`: `{detected_at, owner_pr, owner_session, notified_at, broadcast_at, commented_at, allclear_at}`.

**Lane.** This is the same sonnet/low spawn as §9.2, with the same single-flight lease (`redmain.lock`). Its tools are `ListAgents,SendMessage,Read,Bash(gh pr view:*),Bash(gh run view:*),Bash(gh pr comment:*),Bash(governor redmain-record:*)`. The tick puts **only the steps that are due** into the mission, so each step happens once per episode:
- **(a) Map the owner.** Run `gh pr view N --json headRefName`. Find a live registry entry (`kill -0` and `procStart` both pass) whose `git -C <cwd> branch --show-current` equals `headRefName`. If none is found, use jq over transcripts for a `gh pr create` tool_use whose result contains `/pull/N`, and take that transcript's sessionId if it is live.
- **(b) Owner live.** Use `SendMessage` to the owner with the failing run URL, a ≤ 40-line `gh run view --log-failed` excerpt, and a likely fix. Record `notified_at`.
- **(c) Broadcast.** Send one line to every other live session whose cwd is under the repo root: `main red since <since>, #<N> owns it (<run url>); don't pile on — merges wait via main-health.` Record `broadcast_at`.
- **(d) Owner dead or unmappable.** Run `gh pr comment N` with the run URL, the excerpt and the fix recipe. Record `commented_at`. The broadcast still goes out.
- **(e) All-clear.** On the first green `main-health` after the episode, send one all-clear to the same audience. Record `allclear_at`, then close the episode.

**Rules.**
- Messages use the supported `ListAgents`/`SendMessage` tools. ListAgents' own description reads "Lists agents you can SendMessage to — … other local Claude sessions on this machine", found in binary 2.1.284. The registry's undocumented `messagingSocketPath` is never used.
- Rate limits: at most one lane per episode step and at most 6 red-main lanes per day.
- The lane never pushes, merges or edits code.

**UNPROVEN.** It is not yet known whether a `-p` lane's `ListAgents` returns *local desktop* sessions. That is phase-0 item 4. If it does not, steps (b), (c) and (e) degrade to (d) plus a line in `~/.keel/governor/redmain/broadcast.log`, and the grade reports `redmain_channel=pr_comment_only`.

## 12. Telemetry and grading (phase 1 scope)

**Events.** These go through `heavy_resources.event()` into `events.jsonl`:
- `governor_decision`: `{job_id, class, contended, source, enforced, slots_now, d_rule{slots_now, admit}, jev{latency_ms, admit_p, headroom, saturation, provider, tokens}|null, floors_fired[]}`;
- `broker_started` and `broker_completed`;
- `reclaim_triggered`, `reclaim_lane_{started,finished}`;
- `redmain_{detected,step,closed}`.

**`governor grade --since <d>`** reports:
- V1–V5 and V7;
- the D-vs-JEV disagreement table and the promotion verdict (§5.4);
- `unslotted_heavy_per_1k`;
- reclaim yield (container-free MiB), refusals by gate, and proposals.

The grade reads and writes nothing else and always prints the size of the set it scanned.

**`governor audit-kills`.** It fails on any `done` kill receipt where a user or assistant transcript record falls within 5 min before the kill. It also covers watchdog receipts. On an empty input it prints `0 kills examined`. (The "user mentions the killed command later" heuristic moved to phase 2.)

## 13. Rollout

| Phase | Exit criterion | Admission | Route | Reclaim | Red-main |
|---|---|---|---|---|---|
| **0 — shadow + probes** | ≥ 7 d AND ≥ 1,000 acquires AND ≥ 30 contended decisions; all phase-0 items done | fast path plus today's fixed policy enforced; D and JEV logged; floors logged | live R1–R7 (it selects only among existing gates) | tier 0 and lane run under `FORCE_DRY_RUN`; receipts are `would_do` | detection live; lane runs; messages sent (they are advisory, not mutations) |
| **1 — enforce D + safe reclaim** | the phase-0 grade shows D's contended admits have a bad-outcome rate ≤ the fixed policy's (replayed) AND no `would_do` kill is flagged by `audit-kills --dry` | **D arbitrates contended acquires**; floors enforced; broker live; `max_slots` up to 6 | unchanged | K1, K2, K4, K6, S1–S7 apply; K3 applies; S8+ are proposals | unchanged |
| **1b — JEV arbiter** | §5.4 promotion gate passed before 2026-11-15 | JEV arbitrates contended acquires; D is the fallback | — | — | — |

**Phase-0 items** (each writes its evidence to `~/.keel/governor/phase0/`):
1. Keychain pre-grant and `probe-credential` from both contexts (§5.6).
2. `governor replay --mode lock-only` for k = 2..6. It must reproduce the observed deferrals within ±5% at k = 2, and it reports the peak RSS sum per k, which sets `max_slots`.
3. A one-turn lane listing `ccd_session*` tools, to confirm §10.
4. A one-turn lane calling `ListAgents` and recording whether local desktop sessions appear (§11).
5. `governor-snapshot --json` run 10×, with p95 `took_ms ≤ 300`.
6. `spawn-lane.sh` argv test for `--effort`/`--allowed-tools`.

**Halt rule.**
- An inline V5 hit (§9.5) sets shadow at once.
- If V1 per 1,000 over a 3-day window exceeds 1.25× baseline with ≥ 1,000 acquires, the daily grade sets shadow. Normalizing per 1,000 acquires removes r1's workload false triggers.
- A rollback is a one-field edit of `~/.keel/resource-policy.json`, effective on the next acquire.

**Install.** `install-resource-hooks.py` adds `governor/*`, the shims, `governor-act`, `governor-snapshot` and the tick plist to `RUNTIME_FILES`. Codex does not pick up hook changes (`mutate_codex`), so the install prints the Codex `/hooks` re-trust as a required step. `grade` reports `codex_guard_active=false` until a Codex-caller retry has been denied.

## 14. Test plan

keel's gate is `python3 -m unittest tooling/sandbox/test_*.py`. cynap's is `cynap-sandbox verify --quick` + `wt-verify.sh`, with CI authoritative.

### 14.1 keel unit tests (stdlib only; every gate test has a mutant that removes the gate and must fail)

- **Fast path.** When a free slot exists and `pressure_reason()` is None, admission makes zero snapshot, D or JEV calls (a sentinel raises if any runs).
- **Hot loop.** `claim_slot` never calls admission. The arbiter runs with every slot flock already taken by the test.
- **D rule.** The formula rows are tested, including `reserve_mb`. So is the cheap-class `+1`, using the measured `rss_s_p90` of wt-verify (27,704) and cynap-sandbox (2,372,241). All inputs are read from `Policy()` and a fixture `class-stats.json`.
- **Floors beat everything.** Each of the 4 floors is tested with a stub JEV that returns `admit.p=0.99`.
- **JEV.** It is never called when uncontended. The fallback matrix (timeout, breaker-open from `breaker.json` written by another process, no credential, contract error, grey band) each produce exactly D's verdict. Five concurrent contended `decide()` calls make ≤ 1 JEV call. The contract test parses `resp4.json` and rejects 4 mutants.
- **Broker.** `bash x.sh`, whose body runs a shimmed `vitest`, holds 0 slots while the child holds 1. `wt-verify.sh` and self-locking scripts are not brokered. A child's exit 75 propagates. A nested call under a lease is unchanged.
- **Kill mechanism (B1).**
  - A victim whose pgid equals a live session's pgid is refused.
  - An identity mismatch is refused.
  - `signal_members` never signals the caller's group.
  - A fixture tree with a `spawn-lane`-style shared pgid is killed by pid only.
- **K1 (B2).** One dead sample is refused. Two samples 5 min apart succeed. At 30% dead registry pids, nothing is killed.
- **K3.** A pending background tool_use is refused. PR `OPEN` is refused. Idle 5 h is refused. A tree that is not leased but is burning CPU is refused. The receipt contains no message text.
- **`worktree-remove` (M2).** An ignored `.env.local`, `WORKING.md` or `.cynap/` refuses. An ignored `node_modules` alone passes. A locked worktree refuses, with no override flag.
- **Tick (B3).** A second tick exits on `reclaim.lock`. `acquire()` never imports `act`. SIGINT during tier 0 is ignored. `--admit-preview` writes no request. `worktree-reaper.sh --apply --pass A` runs no Pass B and no prune (fixture home).
- **Inline halt (M5).** A transcript record 2 min before a kill flips `governor_mode` to shadow in the fixture policy.
- **Red-main.**
  - Episode dedupe: the same `sinceSha` twice gives one notify step.
  - An unknown health result (exit 2) gives no lane.
  - Green after red gives exactly one all-clear.
  - The owner mapping works both through the registry branch and through the transcript `gh pr create` fallback, using jq over fixture JSONL.
- **Retry guard.** A deferred event for (cwd, exe) denies within 15 min while the preview says deny. It allows when the preview says admit. It fails open on an unreadable log.

### 14.2 Replay and live probes

- **Corpus.** `governor/testdata/deferrals-2026-09-29.jsonl` is frozen, observed data. Replay asserts the matcher catches 61 re-queues. It reports the D-rule counterfactual deferrals per 1,000 (V1's comparator) and the lock-only k-sweep.
- **Live.**
  - `with-heavy-lock --admit-preview --class cynap-verify-quick --json` answers in ≤ 2 s.
  - `governor-act sweep --auto --dry-run` prints K1 candidates, each with two dead samples, and S-rows with container-free sizes.
  - `governor audit-kills --since 30d` on an empty file prints `0 kills examined`.

### 14.3 cynap tests

- `tooling/sandbox/__tests__/verify-route.test.mjs` has one test per rule R1–R7 and per CI action (a)–(c). This includes the case "an existing dispatch run for headSha → no second dispatch". `with-heavy-lock` is stubbed on PATH. Confirm that the `--quick` glob matches `.mjs`.
- Invariant tests:
  - `600` appears only in `LOCAL_WAIT_CI_THRESHOLD_S`, and there is no `slots` literal;
  - `grep -c 'gh run watch' tooling/sandbox/cynap-sandbox` → 0;
  - there is exactly one `select(.headSha` across the two files;
  - `vitest-watchdog.mjs` has no `process.kill`.
- `wt-verify.sh` and `wt-setup` self-lock: run under a fake lease they exec directly, and without one they re-exec through the stub.

## 15. Delete-legacy (same change)

| Replaced | Where | Deletion |
|---|---|---|
| `MAX_SLOTS = 4` and the flat second-job charge as the *contended* authority | `heavy_resources.py:13`; `heavy_runner.py:63-72` | `MAX_SLOTS` becomes `max_slots`. `pressure_reason()` survives only as the fast-path check. |
| The "defer, exit 75, agent retries" advice | `heavy_runner.py:242-245`; `cynap-sandbox:77-92` (`_report_lock_deferral`), `CYNAP_VERIFY_HEAVY_WAIT_MAX` (L49) | Rewrite the keel message to name the router. Delete the knob and the three "options" lines. |
| The CYN-1951 reroute block and `gh run watch` | `cynap-sandbox:892-908`, `:792` | Delete both. The rationale moves into the `verify-route` header. |
| Duplicated headSha resolution | `cynap-sandbox:779-787` | Extract it into `resolve_ci_run`. |
| Kill engines outside the policy | `free-resources.py:328-340`; `vitest-watchdog.mjs` kill calls; `ai.cynap.workflow.reaper.plist` | Route the first two through `governor-act` (§9.6). Unload and delete the dead plist. |
| Ancestry-based merged test and the second worktree remover | `worktree-reaper.sh` Pass B (L255-300, `is-ancestor` L288) and `git worktree prune` (L302); `macos-storage-reclaim/prune-stale-worktrees.sh`; SKILL.md L113 "ancestor of `origin/main`" | Delete Pass B and `prune-stale-worktrees.sh`; `governor-act worktree-remove` is the one rule. The reaper keeps Pass A behind `--pass A`, and `disk-keeper.sh:375-376` calls it that way. SKILL.md L113 and step 5 point to `governor-act worktree-remove` (PR state). |
| **`com.roeealfasi.disk-clean` (weekly), deleted.** | `~/.claude/scripts/disk-clean` (68 lines) and its plist | Its `find ~/code -name node_modules/.next/dist -mtime` rules (`disk-clean:44-57`) exclude `~/code/cynap/*`, but the repo lives at `~/code/cynap-monorepo-next`, so those rules reach **live** worktrees with no liveness check. They are superseded by reaper Pass A. Its unique rows (`brew autoremove`, `brew cleanup -s`, `uv cache prune`, Xcode `DerivedData`, `~/.cache/puppeteer`) move into `disk-keeper.sh` as a weekly-stamped block (`~/.keel/governor/weekly.stamp`). Its Chrome OptGuide row is already disk-keeper 3b (L150), and its `npm cache verify` is covered by S3. Delete the script and plist, and unload the agent. |
| r1's JEV REDUNDANT question set, the K3 JEV gate, and the SKILL.md consent amendment | r1 §5.3, §12 | Never built. |

Absence claims in this table come from reads made on 2026-09-29: `sed -n`/`grep -n` of the cited files, `git ls-tree origin/main .claude/hooks/ | grep -c heartbeat` → 0, and `launchctl list | grep -i 'cynap\|keeper\|disk-clean'`, which showed the workflow reaper absent. The implementer re-runs them at change time, because line numbers drift.

## 16. Phase 2 (after phase 1 is graded; nothing below is built in phase 1)

- **R-ETA refined model.** This covers per-lease remaining time, per-worktree verify-history p50, and the full-vs-quick split once `class` has n ≥ 10 per mode. It adds **V6**, ETA MAE ≤ 180 s, measured from `verify-route.jsonl` against local actuals and against CI actuals by `head_sha` (`gh run list`, TTL 15 min).
- **Ramp limiter.** `slots_now` would rise by at most +1 per 300 s. Build it only if phase-1 grading shows oscillation, i.e. a bad outcome within 5 min of a slot increase.
- **audit-kills heuristics.** The rule "a user record within 10 min after the kill mentions the killed command" is a heuristic, reported as such.
- **Session archive in a lane.** Revisit only if a future CLI exposes a local archive tool in `-p` (re-run §13 item 3 on each major CLI version).
- **Transcript compression.** It stays unbuilt unless idle-over-30-day transcripts exceed 5 GiB (today 0.22 GiB).
- **S8 automation.** Deleting Colima profiles stays proposal-only until 3 proposals have been accepted by hand.

## 17. Revision log (r1 → r2)

| Critique | Resolution (code it relies on) |
|---|---|
| BLOCKING#1 JEV on the hot path | §5.1: JEV runs only on contended acquires (~1.8%), and the fast path is today's `claim_slot` (`heavy_runner.py:164-198`). JEV volume drops from ~5,272 calls/week to ~10². |
| BLOCKING#2 dead class-asymmetry | §5.2: the gate is RSS×s p90 ≤ 131,072 MB·s; wt-verify (27,704) and wt-setup (67,631) qualify (`stats2.py`). |
| BLOCKING#3 JEV never compared to a deterministic rule | §5.2: the D rule (founder formula plus `reserve_mb`) is the fallback and the shadow comparator. §5.4: a two-sided promotion gate, with JEV deleted on 2026-11-15 if it does not win. |
| MAJOR wrapper `resource_busy` | §6: the broker plus shims (`heavy_command.py:8-19`), and self-lock preambles for `wt-verify.sh`/`wt-setup` modelled on `cynap-sandbox:294-300`. |
| MAJOR archive parked behind an unrun probe | §10: probe run. The answer is no. The safe equivalent is disk via S6, sidebar via a candidates TSV for a desktop session, and no compression. |
| MAJOR K3's second JEV integration | §9.3: K3 is deterministic. §5.3 of r1 is deleted. |
| MAJOR metrics noise and baselines | §1: V1 per 1,000 acquires with the D counterfactual. V6 moved to phase 2. The halt rule uses a 3-day per-1,000 window. |
| MAJOR permanent mode flag and deferred disk-clean decision | §5.5: `off` removed; `governor_mode`/`jev_admission` deleted on 2026-11-15. §15: disk-clean deleted, with its unique rows folded into disk-keeper. |
| MAJOR size | Phase 1 is the retry guard, route R1–R7, D plus floors, broker, tier-0 plus lane reclaim, and red-main. The ETA model, ramp, V6 and audit heuristics are in §16. |
| B1 blind killpg | §9.3: `job_members`/`signal_members` (`heavy_resources.py:158-169`, `heavy_runner.py:339-350`), `Process.identity` pinning, and a refusal on a shared session or bridge pgid (`spawn-lane.sh:213-216`). |
| B2 K1 hysteresis | §9.3: two dead samples ≥ 5 min apart plus registry mtime, a 25% churn guard, and not-progressing (`worktree-reaper.sh:80-96` idiom, now fail-closed). |
| B3 reclaim inside `acquire()` | §9.1: request file plus `launchctl kickstart`; the detached tick with `reclaim.lock`; min interval on both tiers; preview never triggers; the reaper gains `--pass A` (`worktree-reaper.sh:21-22`). |
| M1 transcript egress | §5.4: ADMIT state is numeric. K3 has no JEV. Receipts carry no message text. |
| M2 ignored files | §9.4: `--ignored` minus a regenerable allowlist, a refuse-list, and an absolute lock. |
| M3 missing kill engines | §9.6: vitest-watchdog goes through `governor-act` (K6/K1); the dead workflow-reaper plist is deleted. |
| M4 K3 progress text | §9.3: "not progressing per §9.3.1" plus no pending background tool_use. |
| M5 halt latency | §9.5: an inline transcript-recency check at kill time and again at +60 s flips shadow. |
| M6 breaker, cache and Keychain state | §5.6: `breaker.json` and `decision.<class>.json` on disk, and the Keychain `-T /usr/bin/security` pre-grant plus `probe-credential` in phase 0. |
| Founder: verify-route | §7: R3 after a deferral goes to CI; R6 ETA > 600 goes to CI; R1 never offloads; CI action (a)/(c) prevents double dispatch. |
| Founder: storage via the skill | §9.2: the mission invokes `Skill(macos-storage-reclaim)`, and mutations map to `governor-act storage --row`. |
| Founder: Job 4 red-main | §11. |

## 18. Open questions and STILL UNPROVEN (2026-09-29)

1. Q1 (archive in `-p`) is answered statically: no (§10). A live one-turn confirmation is owed as phase-0 item 3.
2. Q2: does Tahoe write `.hang`/`.spin` reports for user app hangs? `app_hang` stays shadow-only until firings are counted against reported beach-balls.
3. Q3: the Codex transcript location. Until it is known, Codex owners are N4 (report only).
4. Q4: whether `ListAgents` in `-p` sees local desktop sessions (phase-0 item 4, §11 fallback).
5. **UNPROVEN:**
   - (a) JEV quality on real states. Only one probe exists. Re-derive with `governor grade --since 7d`.
   - (b) That D reduces deferrals without raising `memory_pressure_during_run`. Re-derive with `governor replay --mode lock-only` and the phase-0 grade.
   - (c) The V3 baseline.
   - (d) The broker's `unslotted_heavy_per_1k`.
   - (e) Lane cost: measure tokens and wall time over the first 5 lanes, with a target median < 10 min.
6. **Proven now:**
   - the `/v1/evaluate` shape (`resp4.json`);
   - `claude` 2.1.284 accepts `--effort` and `--allowed-tools`;
   - the registry fields;
   - the 113/6,284 and 61/114 counts;
   - the per-class RSS×s figures (`stats2.py`);
   - `main-deploy-health.mjs`'s TSV and owner contract;
   - the absence of a local `archive_session` in the CLI binary (the strings probe above).
