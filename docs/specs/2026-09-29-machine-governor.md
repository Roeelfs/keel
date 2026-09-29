# SPEC — Machine governor: contended admission, local-vs-CI routing, a CONTEXT interface to machine-steward

> Status: r3, as-built 2026-09-29. r2 (this file's prior revision) is preserved in git history at
> commit `0c37b01`. r1 (650 lines) is preserved at `/tmp/governor/rev/SPEC.v1.md` (`/tmp` is volatile).
> Design of record: founder-approved "machine governor" plus the founder rulings of 2026-09-29
> (in-session, r2), plus a same-day founder rescope during phase-1 implementation (r3): the
> headless reclaim/red-main lane, the tick LaunchAgent, the mission-template lane and the
> multi-case `governor-act` executor (§9-§11 of r2) are **dropped, not phase-2'd**. Killing,
> archiving, storage reclaim and red-main coordination move to a single always-on **desktop**
> session named `machine-steward` (charter: `docs/machine-steward.md`). keel's job shrinks to: (1)
> decide contended admission (rule D, floors, JEV in shadow), (2) the wrapper broker, (3) print a
> compact machine CONTEXT block on every deny/defer and hand it to machine-steward. keel never
> kills or deletes on its own initiative in phase 1, except through the one safety-checked
> `governor_kill()` helper machine-steward (or a human) can call.
> Evidence: brief `docs/investigations/2026-09-29-design-an-intelligent-local-vs-ci.md` (cynap
> worktree `bridge-cse_01Fq6LrfJHPYvR2d28ZhPqFs`), stall report `/tmp/verify-stall/REPORT.md`,
> critiques `/tmp/governor/critiques.md`, r2 probes `/tmp/governor/rev/stats2.py`, phase-0 live
> evidence `docs/specs/2026-09-29-machine-governor.phase0.md` (Keychain + one live JEV call).
> §17 maps every r1→r2 critique id to its resolution; this header records the r2→r3 rescope.

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
| V5 | Kills of an active session's work, from **every** kill path (`governor_kill`, and whatever `machine-steward` does per its own charter) | n/a | **0, hard.** | `governor_kill`'s own gate refusals (§9.2) are unconditional, not a post-hoc audit; `machine-steward` keeps its own receipt ledger outside this repo. No `governor audit-kills` CLI is built (§10). |
| V7 | Red-main episodes where more than one session pushed a fix for the same failing run | 1 (2026-09-29) | 0. Every episode has an owner notice within 10 min of detection and one all-clear. | Now `machine-steward`'s charter to run and grade (§9.5), not a keel `governor grade` CLI. |

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
| Snapshot, admission (fast path, D rule, floors, JEV on contended acquires only) | keel | `tooling/sandbox/governor/{snapshot,admission,jev_client}.py`, called from `heavy_runner.acquire()` | direct commit to `master`, gated by `python3 -m unittest tooling/sandbox/test_*.py` |
| Wrapper broker and heavy-tool shims | keel | `tooling/sandbox/governor/broker.py`, `~/.keel/resource-hooks/shims/*` | same |
| Session-registry join (owner pid/cwd/name/idle for the CONTEXT block) | keel | `tooling/sandbox/governor/registry.py` | same |
| The CONTEXT interface: on a deny/defer, print a compact snapshot+floors+d_rule+candidates block to stderr, hand it to `machine-steward`, persist `last-context.json` | keel | `tooling/sandbox/governor/context.py`, called from `heavy_runner.announce_governor_context()` | same |
| Read-only admission preview for `verify-route` (never queues, never claims a slot, never makes a fresh live JEV call) | keel | `heavy_runner.admit_preview()`, CLI `with-heavy-lock --admit-preview --class <c> --json` | same |
| The one safety-checked kill helper | keel | `tooling/sandbox/governor/act.py`, CLI `governor-kill <pid> <lstart>` | same |
| Deferral-retry guard | keel | `.claude/hooks/serialize-heavy-ops.py` | same, plus the Codex re-trust step (§13) |
| **Everything else that acts** (kill orphans/duplicates/idle trees, remove worktrees, reclaim storage, archive sessions, red-main coordination) | **the always-on desktop session `machine-steward`**, not keel automation | `docs/machine-steward.md` (charter) | a human starts the session once; it runs the charter, not a ship |
| Verify route | cynap | `tooling/sandbox/verify-route.mjs`, folded into `cynap-sandbox verify` | PR → merge (prod-class, needs explicit go-ahead) |
| vitest watchdog kill path | cynap | `tooling/process-watchdog/vitest-watchdog.mjs` -> `governor-kill`, or reports to `machine-steward` | same PR |

- **Why admission lives in keel.** `heavy_runner.py` is the single chokepoint that Claude and Codex callers both pass through.
- **Why there is no tick, no lane, no multi-case executor (2026-09-29 rescope).** A detached LaunchAgent doing reclaim on its own initiative, and a headless `claude -p` lane it spawns to do the reasoning, both add a second unattended actor with kill/delete authority -- exactly the surface B1-B3/M1-M6 (§17) spent r1->r2 hardening. The founder's simpler ruling: one always-on **desktop** session (`machine-steward`) is that actor, full stop. keel's only remaining job on the reclaim side is to *tell* it what it's looking at (the CONTEXT block) and to expose one safety-checked verb (`governor_kill`) it can call -- never to decide or act on its own.
- **Global-layer rule.** keel names no repo. `context.py`'s registry join reads `~/.claude/sessions` and `~/.claude/projects`, which are machine-wide, not repo-scoped.

```
agent Bash ─► serialize-heavy-ops.py ─► (retry guard §8) ─► with-heavy-lock
   with-heavy-lock: wrapper? ─yes─► broker (§6, governor_mode=enforce only): no slot; PATH shims route heavy children back into with-heavy-lock
                    else ─► acquire(): fast path (free slot within policy.slots AND pressure_reason() is None) ─► admit, no JEV
                                       contended ─► floors ─► arbiter = JEV (shadow, cached 20 s) | D rule (fallback + comparator)
                                       deny/defer ─► announce_governor_context(): print CONTEXT block, write last-context.json
                                                      ─► "SendMessage to machine-steward" (the session decides and acts, keel does not)
machine-steward (always-on desktop session) ─► refresh state ─► kill/archive/reclaim/red-main per docs/machine-steward.md
                                             └► governor_kill(pid, lstart) when it needs the one safety-checked kill verb
cynap-sandbox verify ─► verify-route ─► with-heavy-lock --admit-preview --class cynap-verify-<mode> --json (read-only; never queues, never claims a slot, never a fresh live JEV call)
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
- A contended DENY (from a floor or from D/JEV) triggers `announce_governor_context()` (§9.1) -- the
  CONTEXT block, not a reclaim request file. There is no `~/.keel/governor/reclaim.request` and no
  detached tick to consume one; that mechanism was r2's, dropped by the 2026-09-29 rescope. The
  soft `disk_reclaim_gib = 25` threshold (`admission.needs_reclaim()`) never denies; it is available
  for a future CONTEXT-block field but is not yet surfaced there.

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
- **Promotion gate: JEV must beat D, not today's flat budget.** A future `governor grade` CLI (not
  built in this phase; §10, §11 item 2) would compare the two arms on contended decisions where they disagreed (n ≥ 30 in each direction):
  - *JEV-less*: D admitted and JEV would have denied. The observed outcome is the admitted job's fate: `memory_pressure_during_run`, `resource_limit`, a budget kill, or `mem_pressure_level == 4` or the swap floor firing during its run. JEV wins this side if the bad-outcome rate on these jobs is ≥ 2× the rate on jobs where both arms agreed to admit.
  - *JEV-more*: JEV admitted and D denied. This outcome is counterfactual, so it is projected from the recorded snapshots over the next `run_p90_s`: `used_mb + class rss_p90` must stay below `(100 − min_free_percent)%` and no floor may fire. JEV wins this side if ≥ 95% of these admissions are projected safe.
  - JEV is promoted to arbiter only if it wins both sides. **If it has not won by 2026-11-15, the JEV admission code is deleted** (jev_client, questions, the breaker, the cache and the Keychain read). That removes about a third of the design and avoids a permanent dual path.

### 5.5 Policy fields (`heavy_resources.Policy`; `load_policy()` still rejects unknown keys)

| Field | Default | Note |
|---|---|---|
| `governor_mode` | `shadow` (`shadow` \| `enforce`) | **Deleted on 2026-11-15.** After that date the governor is the only behavior and a rollback is `git revert` of the keel commit. If phase 1 has not been promoted by then, the governor code is deleted instead. `KEEL_GOVERNOR_MODE` may only move enforce → shadow and is deleted with the field. There is no `off` value: `shadow` enforces today's fixed policy verbatim. |
| `jev_admission` | `shadow` (`shadow` \| `enforce`) | Same deletion date. See §5.4. |
| `max_slots` | 6 | Governor-side ceiling for the D/JEV arbiter on the contended path. **Not a full replacement for `MAX_SLOTS = 4`** (`heavy_resources.py:13`) -- that constant still bounds the fast-path `claim_slot` loop; the rename to one policy-driven ceiling is a real gap, not done in this change (§13). `§12.2` lock-only replay (unbuilt) would show whether the peak RSS sum at k=6 fits in RAM. |
| `cheap_rss_seconds` | 131072 | §5.2 |
| `disk_floor_gib` / `disk_reclaim_gib` / `swap_growth_floor_mb_per_min` | 10 / 25 / 256 | env overrides may only tighten |
| `jev_deadline_ms` / `decision_ttl_s` / `admit_p_hi` / `admit_p_lo` / `saturation_deny` | 1500 / 20 / 0.60 / 0.40 / 3.5 | |
| `broker_shells` | `["bash","zsh","sh","dash"]` | §6 |

**Removed from r2's field list** (2026-09-29 rescope): `idle_kill_hours`, `reclaim_min_interval_s`,
`reclaim_daily_max`, `reclaim_max_runtime_s` -- these rate-limited the tick/lane reclaim engine,
which no longer exists. `Policy()` has no fields for them; nothing reads them.

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

## 7. Verify route (cynap `tooling/sandbox/verify-route.mjs`, PR #3499)

**Keel side implemented and verified 2026-09-29**: `heavy_runner.admit_preview()`, wired to
`with-heavy-lock --admit-preview --class <c> --json`. Confirmed live, end to end, against cynap's
own `admitPreview()`/`decideRoute()` (imported directly from `verify-route.mjs`, not reimplemented):
a real `with-heavy-lock --admit-preview` call parses cleanly (`ok:true`) and routes R5 (LOCAL,
`decision=admit`) on an idle machine. Read-only throughout -- it writes no queue ticket and no
lease -- and never triggers a fresh live JEV call (it reads a cached JEV decision if one exists
from a real contended acquire; see §5.4). Any internal failure exits non-zero, which is what
verify-route's own contract reads as R4 ("preview unavailable").

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

## 9. The CONTEXT interface, and the one safety-checked kill helper (2026-09-29 rescope)

**There is no tick, no lane, no multi-case executor, no red-main automation in keel.** r2 built a
detached LaunchAgent that spawned a headless `claude -p` lane with kill/delete authority (K1-K6,
`worktree-remove`, storage rows S1-S8, red-main coordination). The founder replaced all of it,
same day, before any of it shipped: one always-on **desktop** session, `machine-steward`
(charter: `docs/machine-steward.md`), is now the only thing on the machine that kills a process,
removes a worktree, reclaims storage, archives a session, or coordinates a red `main`. keel's job
shrank to two things: tell that session what it is looking at, and give it (or a human) one
safety-checked verb to act with.

### 9.1 The CONTEXT block: `heavy_runner.announce_governor_context()`

- **When.** Every contended DENY or deferral in `acquire()` calls this, after the existing
  `deferred` event is written. It is called nowhere else -- `--admit-preview` never triggers it
  (a preview must never have a side effect).
- **What it does, and nothing else:**
  1. Takes a snapshot (`governor.snapshot.take(..., persist=False)`), builds the session registry
     (`governor.registry.build()` -- `~/.claude/sessions/*.json`, cross-checked live via `kill -0`
     + `procStart`, joined to idle-minutes via the matching transcript's mtime under
     `~/.claude/projects/`), and evaluates the §5 floors and rule D.
  2. Joins each of the top-RSS live leases to its owning session by ancestry (walk `ppid` to a
     registered pid) or, failing that, a cwd/worktree match (`governor.context.top_candidates`).
     An unmapped pid still gets a candidate row with owner fields `None` -- `unknown` never means
     dead.
  3. Prints a compact block to stderr (reason, floors, d_rule, the JEV verdict if one is cached,
     the candidate list with pid/identity/cwd/session/session_name/idle_minutes/rss) plus exactly
     one instruction line naming `machine-steward` as the sole actor, and persists the identical
     JSON to `~/.keel/governor/last-context.json`.
  4. Emits a `governor_decision` event to `events.jsonl` (for §12 grading).
- **Never kills or deletes.** This call is read-only and exception-swallowing end to end: any
  internal failure (missing governor package, a slow probe, a permission error) is caught, logged
  to stderr as `governor context unavailable`, and the deferral proceeds exactly as it would have
  before this feature existed. It never makes a fresh live JEV call (§5.4's cache/decide.lock
  already bound that traffic; a deny/defer is not itself a trigger for a new JEV call).
- **Live-measured cost** (this machine, 2026-09-29): snapshot ~65ms, a 49-entry registry join
  ~237ms, total ~330ms end to end -- comfortably inside the caller's tolerance for a rare
  (~1.8% of acquires) event.

### 9.2 `governor_kill`: the one tiny, always-safe verb

`tooling/sandbox/governor/act.py`, CLI `governor-kill <pid> <lstart> [--why STR] [--live]`.
Dry-run by default (`--live` is required to actually signal). It is the *only* code path in keel
that can send a signal to another process's tree, and it re-derives its safety gates every call
(B1, §17):

1. Re-samples `heavy_resources.processes()`. Refuses if the target pid's identity (`ps lstart`)
   does not match the caller-supplied `lstart` -- this closes the pid-reuse TOCTOU.
2. Builds the victim set via `job_members` (a leased/brokered job's whole session), falling back
   to the pid's own entry if it is not a session leader.
3. Refuses if any victim's pgid, or the target's own pgid, is shared with a live registry session
   (`~/.claude/sessions/*.json`, cross-checked via `kill -0`) -- this is the `spawn-lane.sh`/bridge
   pgid-sharing case that caused r1's near-miss.
4. On `--live`: TERM, a 10 s wait, then KILL on survivors, via `signal_members` (never the caller's
   own group).

`machine-steward`'s charter (`docs/machine-steward.md`) calls this verb (or the CLI directly) for
every kill it decides to make; it keeps its own receipt ledger
(`~/.keel/governor/steward-receipts.jsonl`), which is outside keel's code.

### 9.3 What moved to `machine-steward`, verbatim

Everything r2 specified as K1-K4/K6 (orphan trees, same-worktree duplicates, idle-session heavy
trees, orphan dev servers, unleased runaway vitest), `worktree-remove`'s ignored-files gate, the
S1-S8 storage rows (via `Skill(macos-storage-reclaim)`), session archiving (§10's answer below is
unchanged: no supported local-archive path exists, so the session works from a candidates list
instead), and red-main coordination (§11's design below is unchanged in substance, only in
*owner*) are now `machine-steward`'s job, described in its own charter rather than duplicated
here. That charter is the living document; this spec records only the keel-side contract it
depends on (`last-context.json`, `governor_kill`, `main-deploy-health.mjs`'s TSV contract).

### 9.4 Session archiving (unchanged answer, different actor)

**Answer, unchanged from r2: a headless `claude -p` lane cannot archive a desktop session.** No
supported path exists (`archive_session` is a desktop-injected `ccd_session_mgmt` tool; the CLI
binary never lists it as available in `-p`). This no longer matters to keel's own scope -- disk
does not depend on archiving (S6 recovers those bytes via PR-state-gated worktree removal, which
`machine-steward` does directly), and sidebar hygiene is `machine-steward`'s to run from **its
own** desktop context, where `archive_session` *is* available to it.

### 9.5 Red-main coordination (unchanged design, `machine-steward` is now the actor)

`machine-steward`'s charter runs this on its own refresh loop, not a keel LaunchAgent: read
`main-health` (`main-deploy-health.mjs`'s TSV contract, unchanged from r2), map the owner PR to a
live session by branch or by a `gh pr create` transcript hit, message the owner directly if live,
broadcast to every other live session in the repo, comment on the PR if the owner is dead, and
send one all-clear on the first green after a red episode. None of this is keel code; keel's only
remaining contribution is that `main-deploy-health.mjs` itself lives in cynap, unchanged.


## 10. Telemetry and grading (phase 1 scope; logging only -- **no `governor` CLI is built in this phase**)

**Events, as built.** These go through `heavy_resources.event()` into `events.jsonl`:
- `governor_decision`: `{job_id, reason, floors_fired, d_rule, enforced}` -- emitted once per
  `announce_governor_context()` call (i.e. once per contended deny/defer), not the richer r2 shape
  (`contended, source, slots_now, jev{...}`); extending it is straightforward but not yet done.
- `broker_started` and `broker_completed` (§6).

**Not built in this phase:** `reclaim_triggered`/`reclaim_lane_{started,finished}` and
`redmain_{detected,step,closed}` events (there is no keel-side reclaim/red-main engine to emit
them; `machine-steward` keeps its own receipt ledger, `~/.keel/governor/steward-receipts.jsonl`,
outside this repo's telemetry), and a `governor grade`/`governor audit-kills`/`governor replay` CLI
(V1-V5/V7 are each individually computable from `events.jsonl` and the (unbuilt) replay corpus, but
no single command does it yet -- §11 phase-0 item 2, §12.2, §16 UNPROVEN (a)-(d)).

**`governor audit-kills`.** It fails on any `done` kill receipt where a user or assistant transcript record falls within 5 min before the kill. It also covers watchdog receipts. On an empty input it prints `0 kills examined`. (The "user mentions the killed command later" heuristic moved to phase 2.)

## 11. Rollout

| Phase | Exit criterion | Admission | Route | Reclaim / red-main |
|---|---|---|---|---|
| **0 — shadow + probes** | ≥ 7 d AND ≥ 1,000 acquires AND ≥ 30 contended decisions; all phase-0 items done | fast path plus today's fixed policy enforced; D and JEV logged; floors logged | live R1–R7 (it selects only among existing gates) | CONTEXT block fires on every deny/defer; `machine-steward` acts on its own judgment per its charter -- this was always advisory to keel, never a keel-owned gate |
| **1 — enforce D + broker** | the phase-0 grade shows D's contended admits have a bad-outcome rate ≤ the fixed policy's (replayed) | **D arbitrates contended acquires**; floors enforced; broker live (`governor_mode=enforce`); `max_slots` up to 6 | unchanged | unchanged -- `machine-steward` is a human-run desktop session, not a keel rollout phase |
| **1b — JEV arbiter** | §5.4 promotion gate passed before 2026-11-15 | JEV arbitrates contended acquires; D is the fallback | — | — |

**Phase-0 items** (each writes its evidence to `~/.keel/governor/phase0/`; live results for items 1
and 5 are recorded in `docs/specs/2026-09-29-machine-governor.phase0.md`):
1. **Done, 2026-09-29.** Keychain pre-grant and `probe-credential` from both a bare Bash context
   and `governor.jev_client`'s own code path (§5.6) -- no prompt either way. One live smoke call
   through the corrected `ai-gateway.vercel.sh` endpoint succeeded (`source=jev`, 1159ms).
2. `governor replay --mode lock-only` for k = 2..6 -- **not built**; there is no `governor` grading
   CLI in this phase (§10 is logging-only; grading itself is deferred). `test_governor_replay.py`
   proves rule D is well-behaved over real class-stats from the 7-day corpus, which is a weaker
   claim than a per-deferral counterfactual.
3. The `ccd_session*` archive-tool probe and the `ListAgents` local-session-visibility probe are
   both moot: neither a keel lane nor keel code calls either tool anymore. `machine-steward` runs
   on the desktop, where both `archive_session` and `ListAgents` are natively available to it.
4. **Done, 2026-09-29 (live).** `governor.snapshot.take()` measured `took_ms=65.5` (budget 300ms)
   and the registry join (`governor.registry.build()`) added ~237ms for a 49-entry registry, one
   sample, not the 10x p95 this item originally asked for.
5. `spawn-lane.sh --effort`/`--allowed-tools` -- moot; lane spawning was dropped.

**Halt rule.**
- A rollback is a one-field edit of `~/.keel/resource-policy.json` (`governor_mode`/`jev_admission`
  back to `shadow`), effective on the next acquire.
- There is no keel-side kill/delete rate to halt in this phase -- `governor_kill` is a manually
  invoked, dry-run-by-default helper, not an automated engine with its own halt condition.

**Install.** `install-resource-hooks.py`'s `RUNTIME_FILES` includes `governor/*` (nine modules,
listed as `GOVERNOR_MODULES`); `test_governor_package_is_installed_as_a_runnable_subpackage`
proves the installed copy is importable from its destination the same way `heavy_runner` imports
it from the source tree. Codex does not pick up hook changes (`mutate_codex`), so the install
prints the Codex `/hooks` re-trust as a required step.

## 12. Test plan

keel's gate is `python3 -m unittest tooling/sandbox/test_*.py` (run from `tooling/sandbox/`, matching
the existing convention -- every prior test file already assumes that cwd). cynap's is
`cynap-sandbox verify --quick` + `wt-verify.sh`, with CI authoritative.

### 12.1 keel unit tests, as built (176 new tests across 12 files, plus the pre-existing suite)

- **Fast path / rule D / floors** (`test_governor_admission.py`). The formula rows are tested,
  including `reserve_mb`, the `slots_now` clamp, and the class-with-n<10-falls-back-to-other-heavy
  rule. The cheap-class `+1` is tested against the measured `rss_s_p90` of wt-verify (27,704) and
  wt-setup (67,631) qualifying and cynap-sandbox (2,372,241) not qualifying. Each of the 4 floors
  fires independently and an unknown signal never fires one. All inputs are read from `Policy()`
  and a fixture `class_stats` -- there is no literal in the assertions that isn't also a literal in
  the fixture.
- **JEV** (`test_governor_jev_client.py`, 16 tests). Never called when `jev_admission` is off. The
  fallback matrix (timeout, breaker-open written by another process, no credential, contract error
  incl. a `{"answers": null}` mutant, grey band) each produce exactly D's verdict. Five concurrent
  contended `decide()` calls make ≤ 1 live call (thread-based test). The contract test parses the
  real `/v1/evaluate` response shape (captured live, §16 "Proven now") and rejects malformed-answer
  mutants. The breaker correctly closes 15 min after opening even if all 3 failures are still
  inside the 30-min count window (a bug caught and fixed by this same test). An endpoint-regression
  test pins `ENDPOINT` to the verified live value (§7, the api.digitalocean.com guess 404'd).
- **Snapshot** (`test_governor_snapshot.py`). A failed probe never raises, only appends to
  `unknown[]`. A missing hang-report directory is `0`, not `unknown`. Persistence is throttled to
  once per 10s.
- **Broker** (`test_governor_broker.py`). `is_wrapper()` on bash/zsh/`.sh` names, exempted by a
  custom rule or a `# keel:self-locking` marker. `shim_is_heavy()` on the always-heavy names
  (tsc/turbo/cdk/next/node), test runners, and package-manager heavy verbs.
- **`governor_kill`** (`test_governor_act.py`). An identity mismatch is refused. A shared live
  registry pgid is refused. Dry-run reports the victim set without signalling. A real subprocess
  kill signals only the target, never its sibling, via a live TERM-then-KILL cycle.
- **Session-registry join** (`test_governor_registry.py`, 12 tests). A live entry (pid alive AND
  `procStart` matches) is reported live; a stale `procStart` is not live but is still recorded. A
  malformed session file or a missing pid field is skipped, not fatal. Idle-minutes comes from the
  matching transcript's mtime; a missing transcript is `None`, not fatal. The whole build is
  time-boxed (`budget_s`) and never raises on a missing sessions directory. `owner_of()` walks
  ancestry first, falls back to a cwd/worktree match, and returns `None` (never raises) on no match.
- **CONTEXT block** (`test_governor_context.py`, `test_governor_heavy_runner_wiring.py`). The
  rendered block and its JSON never contain the string `"kill"`, and the instruction line names
  `machine-steward` by name. `heavy_runner.announce_governor_context()` never raises even when
  `governor.snapshot.take` itself raises, and it emits exactly one `governor_decision` event.
- **`--admit-preview`** (`test_governor_admit_preview.py`, 8 tests -- see §7). No leases admits via
  the fast path and writes no ticket or lease. A full slot set denies with numeric `eta_*` fields.
  A disk floor always denies even when D would admit. A cached JEV decision can flip a D-rule deny
  to admit **without triggering a live call** (mocked `_default_http_post` asserted at 0 calls).
  End to end through the real CLI: exit 0 with parseable JSON on success, non-zero on a missing
  `--class`, and no queue ticket or lease is left behind as a side effect.
- **Policy invariants** (`test_governor_policy.py`). `governor_mode`/`jev_admission` reject any
  value other than `shadow`/`enforce` (no `off`). `KEEL_GOVERNOR_MODE` may only move enforce ->
  shadow. An unknown policy field is still rejected.
- **Install** (`test_install_resource_hooks.py`, extended). `governor/*` lands under the runtime
  dir intact and is importable from there exactly as it is from the source tree; a second `install`
  over the same governor tree is a no-op.

### 12.2 Replay and live probes

- **Corpus.** `test_governor_replay.py` copies the real `~/.keel/heavy.slots/events.jsonl`
  **read-only** to a tempfile, builds real `class_stats` from its `queued`/`started`/`completed`
  events, and checks rule D stays monotonic in `mem_free_percent` and bounded by `[1, max_slots]`
  over those real numbers. **What this does not prove**, stated plainly: a byte-for-byte
  per-deferral counterfactual against the historical corpus, because that corpus predates the
  snapshot module and carries no memory/lease state at each deferral's moment. That replay is
  future work, not phase 1.
- **Live, done 2026-09-29** (see `docs/specs/2026-09-29-machine-governor.phase0.md` for the full
  record): the Keychain credential probe (no prompt, either context); one live JEV call through the
  corrected `ai-gateway.vercel.sh` endpoint (1159ms, `source=jev`); one live run of the whole
  CONTEXT pipeline against this machine's real leases and session registry (330ms end to end,
  printed to the phase-0 doc); and one live round-trip of `with-heavy-lock --admit-preview` through
  cynap's actual `admitPreview()`/`decideRoute()` (imported directly from `verify-route.mjs`,
  routing R5 on an idle machine).

### 12.3 cynap tests (owned by cynap's PR #3499, not this repo)

- `tooling/sandbox/__tests__/verify-route.test.mjs` has one test per rule R1–R7 and per CI action (a)–(c). This includes the case "an existing dispatch run for headSha → no second dispatch". `with-heavy-lock` is stubbed on PATH. Confirm that the `--quick` glob matches `.mjs`.
- Invariant tests:
  - `600` appears only in `LOCAL_WAIT_CI_THRESHOLD_S`, and there is no `slots` literal;
  - `grep -c 'gh run watch' tooling/sandbox/cynap-sandbox` → 0;
  - there is exactly one `select(.headSha` across the two files;
  - `vitest-watchdog.mjs` has no `process.kill`.
- `wt-verify.sh` and `wt-setup` self-lock: run under a fake lease they exec directly, and without one they re-exec through the stub.

## 13. Delete-legacy (same change)

| Replaced | Where | Deletion |
|---|---|---|
| The flat second-job charge as the *contended* authority | `heavy_runner.py:63-72` (`pressure_reason`) | **Partial.** `Policy.max_slots` (new, default 6) now exists and is read by rule D on the contended path. `pressure_reason()`/`MAX_SLOTS` (`heavy_resources.py:13`) are unchanged and still bound the fast path's `claim_slot` loop -- a full rename of `MAX_SLOTS` to a policy-driven ceiling is **not done** in this change; flagged as a real gap, not a completed migration. |
| The "defer, exit 75, agent retries" advice | `heavy_runner.py:242-245`; `cynap-sandbox:77-92` (`_report_lock_deferral`), `CYNAP_VERIFY_HEAVY_WAIT_MAX` (L49) | Rewrite the keel message to name the router. Delete the knob and the three "options" lines. |
| The CYN-1951 reroute block and `gh run watch` | `cynap-sandbox:892-908`, `:792` | Delete both. The rationale moves into the `verify-route` header. |
| Duplicated headSha resolution | `cynap-sandbox:779-787` | Extract it into `resolve_ci_run`. |
| Kill engines outside the policy | `free-resources.py:328-340`; `vitest-watchdog.mjs` kill calls; `ai.cynap.workflow.reaper.plist` | Route the first two through `governor_kill` (§9.2) or `machine-steward`, not through a keel-owned multi-case executor (that executor was dropped, §9). Unload and delete the dead plist. |
| Ancestry-based merged test and the second worktree remover | `worktree-reaper.sh` Pass B (L255-300, `is-ancestor` L288) and `git worktree prune` (L302); `macos-storage-reclaim/prune-stale-worktrees.sh`; SKILL.md L113 "ancestor of `origin/main`" | Delete Pass B and `prune-stale-worktrees.sh`; `governor-act worktree-remove` is the one rule. The reaper keeps Pass A behind `--pass A`, and `disk-keeper.sh:375-376` calls it that way. SKILL.md L113 and step 5 point to `governor-act worktree-remove` (PR state). |
| **`com.roeealfasi.disk-clean` (weekly), deleted.** | `~/.claude/scripts/disk-clean` (68 lines) and its plist | Its `find ~/code -name node_modules/.next/dist -mtime` rules (`disk-clean:44-57`) exclude `~/code/cynap/*`, but the repo lives at `~/code/cynap-monorepo-next`, so those rules reach **live** worktrees with no liveness check. They are superseded by reaper Pass A. Its unique rows (`brew autoremove`, `brew cleanup -s`, `uv cache prune`, Xcode `DerivedData`, `~/.cache/puppeteer`) move into `disk-keeper.sh` as a weekly-stamped block (`~/.keel/governor/weekly.stamp`). Its Chrome OptGuide row is already disk-keeper 3b (L150), and its `npm cache verify` is covered by S3. Delete the script and plist, and unload the agent. |
| r1's JEV REDUNDANT question set, the K3 JEV gate, and the SKILL.md consent amendment | r1 §5.3, §12 | Never built. |

Absence claims in this table come from reads made on 2026-09-29: `sed -n`/`grep -n` of the cited files, `git ls-tree origin/main .claude/hooks/ | grep -c heartbeat` → 0, and `launchctl list | grep -i 'cynap\|keeper\|disk-clean'`, which showed the workflow reaper absent. The implementer re-runs them at change time, because line numbers drift.

## 14. Phase 2 (after phase 1 is graded; nothing below is built in phase 1)

- **R-ETA refined model.** This covers per-lease remaining time, per-worktree verify-history p50, and the full-vs-quick split once `class` has n ≥ 10 per mode. It adds **V6**, ETA MAE ≤ 180 s, measured from `verify-route.jsonl` against local actuals and against CI actuals by `head_sha` (`gh run list`, TTL 15 min).
- **Ramp limiter.** `slots_now` would rise by at most +1 per 300 s. Build it only if phase-1 grading shows oscillation, i.e. a bad outcome within 5 min of a slot increase.
- **audit-kills heuristics.** The rule "a user record within 10 min after the kill mentions the killed command" is a heuristic, reported as such.
- **Session archive in a lane.** Moot -- `machine-steward` runs on the desktop, where `archive_session` is already available to it natively (§9.4). This item only mattered for a headless-lane design, which was dropped.
- **Transcript compression.** It stays unbuilt unless idle-over-30-day transcripts exceed 5 GiB (today 0.22 GiB).
- **S8 automation.** Deleting Colima profiles stays proposal-only until 3 proposals have been accepted by hand.

## 15. Revision log (r1 -> r2)

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

## 16. Open questions and STILL UNPROVEN (2026-09-29)

1. Q1 (archive in `-p`) is **moot** after the rescope -- `machine-steward` runs on the desktop,
   where `archive_session` is natively available; the "no local archive in a headless lane" finding
   (§9.4) only mattered for the dropped lane design.
2. Q2: does Tahoe write `.hang`/`.spin` reports for user app hangs? `app_hang` stays shadow-only until firings are counted against reported beach-balls.
3. Q3: the Codex transcript location. Until it is known, `machine-steward`'s charter treats a Codex tree's owner as not-positively-dead (report only), same substance as r2's N4, now the steward's call rather than a keel kill-class.
4. Q4 (`ListAgents` local-session visibility) is **moot** after the rescope -- there is no keel-side red-main lane to need it; `machine-steward` calls `ListAgents` from its own desktop context, where it is documented to work.
5. **UNPROVEN:**
   - (a) JEV quality on real states. One live smoke call exists (`docs/specs/2026-09-29-machine-governor.phase0.md`); a 7-day promotion-gate comparison (§5.4) needs a `governor grade` CLI that is not built in this phase.
   - (b) That D reduces deferrals without raising `memory_pressure_during_run` on real traffic (only a synthetic/replay check exists so far, §12.2).
   - (c) The V3 baseline (p90 time from a feature-branch verify to a local start or CI route) -- needs live traffic after `verify-route` merges on the cynap side.
   - (d) The broker's `unslotted_heavy_per_1k` -- the broker is built and unit-tested but is inert by default (`governor_mode=shadow`); it has made zero live decisions to measure.
   - (e) The CONTEXT block's real effect on `machine-steward`'s behavior -- only its own emission (snapshot, join, print, persist) is proven live; whether the steward session actually acts correctly on it is that session's own charter to prove, not this spec's.
6. **Proven now:**
   - the `/v1/evaluate` shape, live (this session's smoke call, plus the earlier `resp4.json` capture);
   - the correct live endpoint, `https://ai-gateway.vercel.sh/v1/evaluate` (the `api.digitalocean.com` guess 404'd; corrected before shipping, §7);
   - the Keychain credential path has zero interactive friction from both a bare Bash context and `governor.jev_client`'s own code;
   - the registry fields, live, against this machine's real 121-entry session registry;
   - the 113/6,284 and 61/114 counts (unchanged from r2, still the motivating baseline);
   - the per-class RSS×s figures (`stats2.py`, unchanged from r2);
   - `main-deploy-health.mjs`'s TSV and owner contract (unchanged; now consumed by `machine-steward`, not a keel tick);
   - `with-heavy-lock --admit-preview`'s output parses cleanly through cynap's real `admitPreview()`/`decideRoute()`, live, end to end (§7, §12.2).
