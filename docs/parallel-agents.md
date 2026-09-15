# Parallel agents: path ownership & coordination

The single biggest unlock in agent-assisted development is running **several
sessions at once** — one per worktree, each on a different slice of work. The
single biggest hazard is the same thing: two sessions editing the same file, or
eight sessions each launching a full build at the same instant.

`tooling/workflow/` is the coordination layer that makes parallelism safe. It is
~650 lines of dependency-light Bash (`git` + `jq` + `flock`) and ships with keel.

## The shared heavy-job resource budget

`tooling/sandbox/with-heavy-lock` supervises **one heavy job per user account**
across repositories, worktrees, Claude Code, and Codex. It uses Python's kernel
file lock; a missing external `flock` executable cannot silently disable it.

```bash
with-heavy-lock pnpm test
with-heavy-lock npx cdk synth
with-heavy-lock --status
```

Defaults are one job, at most two Vitest/Jest workers, a 6 GiB aggregate resident
memory budget, a 20% available-memory admission threshold, and a two-hour job
limit. Vitest uses `forks`. Turbo's Node launcher receives concurrency one.
The 2 GiB V8 heap setting is a per-process aid; aggregate RSS is measured across
the job's process group every 0.5 seconds. On excess, only that group is stopped.
A small startup gate publishes ownership before the command can execute.

The host policy is `~/.keel/resource-policy.json`. Runtime environment can tighten
worker, RSS, sample, wall-time and admission budgets; it cannot increase them.
`KEEL_HEAVY_SLOTS`, `KEEL_HEAVY_LOCK_DIR` and an overridden `HOME` no longer change
admission. The account database determines the home for both policy and state.
State is always `~/.keel/heavy.slots`, including an atomic lease and `events.jsonl` with
job ids, terminal reasons and observed peak RSS. Nested calls verify a live
supervisor ancestor, process identity, job id and held lock. An ambient
`KEEL_HEAVY_LOCK_HELD=1` flag alone grants no access. If the supervisor dies,
the recorded process group keeps a surviving job excluded until it drains. Only
the supervisor holds the lock, so a daemon that leaves the group never keeps the
slot busy. Termination and normal cleanup target only the owned group.

This is a native process supervisor, **not a hard memory sandbox**. Sampling can
overshoot; detached processes can leave a process group; a SIGKILLed supervisor
cannot continue measuring memory. Use a separately bounded Linux VM/container
for workloads that require kernel-enforced CPU and memory ceilings. This change
does not start, resize or restart a VM, or wrap already-running processes.

### Bounded admission and results

A busy host waits at most 15 seconds, then returns **75 / DEFERRED** without
starting a command. `KEEL_HEAVY_WAIT_MAX=0` means immediate admission or deferral,
not an infinite wait. Deferred work is incomplete: continue other useful work,
and only retry after the resource state changes. Deferral grants no permission
to push, deploy or move the run to CI. The old CI budget/infinite-wait fallback
has been removed. Exit 137 means a resource/wall-time stop; exit 69 means the
resource controller could not safely operate. A normal command preserves its
exit status. Neither deferral nor interruption counts as a passing test.

### Install enforcement in both runtimes

```bash
python3 tooling/sandbox/install-resource-hooks.py --check
python3 tooling/sandbox/install-resource-hooks.py --apply
```

The opt-in installer backs up changed files, preserves unrelated settings, and
registers the shared `serialize-heavy-ops.py` hook for Claude's Bash tool and
Codex's native `PreToolUse` / `^Bash$` event (which covers unified exec). Codex
requires the exact new definition to be reviewed and trusted in `/hooks` before
it runs. Verify activation in each runtime; registration alone is not evidence
that a running session has loaded the new hook. The installer does not change
security approvals or fabricate trust. Other machines need their own install.

The hook refuses recognized unwrapped test/build/install/CDK commands, including
shell command segments after a wrapped invocation. Missing runner or an invalid
command/rule parse fails closed. Quoted documentation and heredoc bodies are
excluded from classification. Repository-specific entry points can be added in
`~/.keel/resource-commands.json`, for example `{"project-verify": ["*"]}`.
This shell classifier prevents common accidental bypasses; it cannot prove what
arbitrary scripts or interactive terminal input will execute.

Regression checks use small test-owned process groups and temporary homes:

```bash
python3 tooling/sandbox/test_with_heavy_lock.py
python3 tooling/sandbox/test_resource_budget.py
python3 -m unittest tooling/sandbox/test_install_resource_hooks.py
```

## Path ownership

Before an agent edits code, it claims its lane:

```bash
tooling/workflow/workflow claim-scope 'src/routes/sharing/**'
```

What happens under the hood:

1. **State location.** The claim is written under
   `$(git rev-parse --git-common-dir)/claude-workflow/`. Using `--git-common-dir`
   (not `--show-toplevel`) means **every worktree of the repo shares one state
   store** — claims are global across all your checkouts, which is exactly what you
   want when each session is in a different worktree.
2. **Collision check, under a lock.** The whole claim runs inside an exclusive
   `flock`. It compares the requested globs against every *other* live session's
   owned paths using **glob-overlap detection** — it enumerates representative files
   via `git ls-files` and checks for intersection, with a prefix-overlap fallback.
   If they'd collide, the claim is **refused** (exit 2) with the conflicting
   session named.
3. **Broad-glob guard.** Claiming something sweeping like `src/**` or `**` requires
   an explicit `--allow-broad "<reason>"`, so a careless wide claim doesn't lock out
   every other session by accident.
4. **Manifests + a derived view.** The claim writes `owned-paths/<sid>.json` and
   seeds `sessions/<sid>.json` with a heartbeat, then rebuilds a human-readable
   `WORKING.md` of all active claims.

Other subcommands: `claim --renew` (extend the 48h TTL), `claim --add <glob>`
(widen your lane), `claim --cross-cutting <glob> --reason <r>` (a short-TTL claim on
something shared), `release`, `status`, `stats` (telemetry summary from the
append-only `telemetry.jsonl`), and `heartbeat`.

## The in-flight registry

`inflight-registry.sh` runs as a SessionStart hook and injects a **repo-global
view** into every new session's context:

```
### Worktrees → branch → issue → PR
| Issue    | Branch                  | PR    | Behind | Worktree        |
| ACME-123 | feat/ACME-123-sharing   | #1187 |   2    | sharing-wt      |
...
### Open PRs not in a worktree
...
```

It joins three sources that always existed but were never shown together: `git
worktree list`, `gh pr list`, and a branch→issue match (configurable via
`ISSUE_KEY_RE`, default `[A-Z]+-[0-9]+`). The "Behind" column is each branch's
commit distance from trunk — a high number means a stale base, the most common
cause of divergence. The point: a new agent **continues existing work** instead of
opening a third branch for a ticket someone's already on.

It's fail-open by contract — `gh` missing, not a git repo, no worktrees: it stays
silent and never blocks a session.

## Lifecycle & the reaper

- `session-start.sh` registers the session and seeds its heartbeat.
- `session-end.sh` releases the session's claims on clean exit.
- `heartbeat-reaper.sh` (run on a 30-min timer — launchd/systemd templates in
  `tooling/workflow/install/`) is the safety net: it purges any session whose
  heartbeat is >24h old, or >4h old with a worktree that no longer exists. So a
  session killed by closing the terminal doesn't leave a stale claim forever.

The path-coordination hooks are fail-open: a broken hook, a missing tool, a non-git directory —
none of it ever blocks your session. Coordination should be invisible until the
moment it saves you from a collision.
