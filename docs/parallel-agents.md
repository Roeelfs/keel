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

Defaults are one job, at most two Vitest/Jest workers (policy may allow up to
eight), a 6 GiB aggregate resident memory budget, a 20% available-memory
admission threshold, and a two-hour job limit. Vitest uses `forks`. Turbo's Node
launcher receives concurrency one. Turbo's strict environment drops `KEEL_*`
variables but keeps `NODE_OPTIONS`, so while a lease exists the Node preload reads
`max_workers` from the policy file; an unreadable policy means two.
The 2 GiB V8 heap setting is a per-process aid; aggregate RSS is measured every 0.5
seconds across every process in the job's session: its process group plus any
descendant that moved to its own group (Turbo's tasks do) or outlived its parent.
Only `setsid` leaves a job, so a daemon is not counted. On excess, only the job's
processes are stopped: a group whose leader belongs to the job as a group, any
other member by pid.
Free memory is sampled on the same interval. If it stays below
`run_min_free_percent` (default 10%) for `run_pressure_seconds` (default 15) of
continuous samples, the group is stopped with `memory_pressure_during_run`; a
shorter dip does not stop it. A failed memory sample counts as not low.
A small startup gate publishes ownership before the command can execute.

The host policy is `~/.keel/resource-policy.json`. Runtime environment can tighten
worker, RSS, sample, wall-time and free-memory budgets; it cannot increase them.
The admission wait is not a resource grant, so `KEEL_HEAVY_WAIT_MAX` may raise or
lower it.
`command_max_seconds` tightens the wall-time budget per command, for example
`{"project-verify verify": 3600}`. A key is the executable basename followed by
leading arguments, matched word by word; the longest match wins and the budget
never exceeds `max_seconds`. A value above the file's `max_seconds` is clamped to
it. An entry that is not a positive whole number, or whose key starts with a path,
is skipped with a warning; only a `command_max_seconds` that is not an object
refuses the policy. A stop records `wall_time_budget` with `budget_seconds`.
`KEEL_HEAVY_SLOTS`, `KEEL_HEAVY_LOCK_DIR` and an overridden `HOME` no longer change
admission. The account database determines the home for both policy and state.
State is always `~/.keel/heavy.slots`, including an atomic lease and `events.jsonl` with
job ids, terminal reasons and observed peak RSS. A `started` event records `args`, the
first three arguments after the executable; an argument containing `=` or longer
than 120 characters is recorded as `<redacted>`. A `queued` event records the same
`args` with `cwd`, `executable`, the effective `wait_seconds` and `caller` (`claude` or
`codex`, the nearest such ancestor process, else null). A `deferred` event adds
`waited_seconds`, the queue `position` and the `holder`'s executable and cwd, so a
deferral names both the command that gave up and the job it waited on. Nested calls verify a live
supervisor ancestor, process identity, job id and held lock. An ambient
`KEEL_HEAVY_LOCK_HELD=1` flag alone grants no access. The lease records the job
leader's start time and its live members. If the supervisor dies, any surviving
process of the job's session, in any group, keeps the slot excluded until it
drains; a reused leader pid does not. Only the supervisor holds the lock, so a
daemon that starts its own session never keeps the slot busy. Termination and
normal cleanup target only the job's own processes. After SIGKILL the supervisor
re-samples for up to two seconds. If any job process survives, or sampling fails,
it keeps the lease and records `survivors` in the completed event, so the next job
waits until they exit. A failed lease rewrite is logged and never stops supervision.

This is a native process supervisor, **not a hard memory sandbox**. Sampling can
overshoot; detached processes can leave a process group; a SIGKILLed supervisor
cannot continue measuring memory. Use a separately bounded Linux VM/container
for workloads that require kernel-enforced CPU and memory ceilings. This change
does not start, resize or restart a VM, or wrap already-running processes.

Known follow-ups:
- A job process the command left running (for example a backgrounded helper) keeps the supervisor, and the slot, busy until `max_seconds` stops it.
- A tighter `KEEL_HEAVY_MAX_WORKERS` set by the caller is lost under Turbo's strict environment; the Node preload then uses the policy's `max_workers`.

### Bounded admission and results

Waiters queue in arrival order. Each writes a ticket under
`~/.keel/heavy.slots/queue/`, and only the oldest live ticket may take the slot.
A waiter that exits, is signalled, or is SIGKILLed stops holding its place: its
own cleanup or the next waiter's process-identity check removes the ticket. Every
waiter refreshes its ticket's modification time on each poll; a live waiter that
is stopped or hung stops refreshing and is skipped, not deleted. A
waiter prints one `QUEUED` line with its position and the holder's executable
and directory, then progress every 30 seconds.

By default a busy host waits 15 seconds, then returns **75 / DEFERRED** without
starting a command. Only a caller that already runs in the background should set
a long `KEEL_HEAVY_WAIT_MAX`; a foreground tool call has its own timeout.
`KEEL_HEAVY_WAIT_MAX=0` means immediate admission or deferral, not an infinite wait. Deferred work is incomplete: continue other useful work,
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
registers the shared `serialize-heavy-ops.py` hook with `--runtime claude` for
Claude's Bash tool and without a runtime argument for Codex's native
`PreToolUse` / `^Bash$` event (which covers unified exec). Both runtimes send the
same request shape, so only a registration argument can name the runtime. Codex
trusts a hook by its exact command, so the installer never rewrites an existing
Codex entry: a changed command leaves Codex unguarded until it is re-trusted. Codex
requires a new definition to be reviewed and trusted in `/hooks` before it runs. Verify activation in each runtime; registration alone is not evidence
that a running session has loaded the new hook. The installer does not change
security approvals or fabricate trust. Other machines need their own install.

The hook refuses recognized unwrapped test/build/install/CDK commands, including
shell command segments after a wrapped invocation. A missing runner or an invalid
rules file fails closed. A command the classifier cannot split (unbalanced
quoting) runs unless a heavy command name appears anywhere in its text, and is
refused if one does. Quoted documentation and heredoc bodies are
excluded from classification. Repository-specific entry points can be added in
`~/.keel/resource-commands.json`, for example `{"project-verify": ["*"]}`.
A listed project-command is exempt from the shared runner only when the exact
script the payload resolves (an absolute path as-is, or a relative path against
the tool call's `cwd`; a bare name found via PATH is never exempt) is a regular
file whose first 8KiB carries a `# keel:self-locking` line, and only if that
script really takes the lock itself elsewhere (e.g. its own lint-enforced
wrapper). Anything in the command that may move the cwd removes the exemption for
the whole command: `cd`, `pushd`, `popd`, `builtin`, `source`, `.`, `eval`, `{`,
`}`, a function definition, `git -C`, or a cwd flag on `env` or a package manager
(including after `exec`/`run`/`dlx`). So do a missing `cwd` and anything else
ambiguous about resolution. The marker is read through a non-blocking open that
must be a regular file. This shell
classifier prevents common accidental bypasses; it cannot prove what arbitrary
scripts or interactive terminal input will execute.

Commands that outlast a foreground tool call can be listed in the same file under
`background_required`, for example
`{"project-verify": ["verify"], "background_required": {"project-verify": ["verify"]}}`.
Choose entries from measured job durations in `events.jsonl`, never from command
names. Matching looks through a leading `with-heavy-lock` and compares the first
argument, so a listed verb covers all of its flags. An entry starting with `!`
excludes arguments that begin with its words: `["verify", "e2e", "!verify --quick"]`
covers `verify` and `verify --full` but not `verify --quick`. Both maps accept
exclusions. With `--runtime claude`,
a listed command is denied unless the Bash call sets `run_in_background: true`.
`--runtime codex` is opt-in and needs a manual re-trust in Codex `/hooks`: the
command runs and the hook adds context to keep reading the running cell until it
exits, and never start a second copy. Without `--runtime`, the list is ignored. A hook older than this rule rejects a file that
contains `background_required`, so install the hook before adding the list.

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
