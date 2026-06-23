# Parallel agents: path ownership & coordination

The single biggest unlock in agent-assisted development is running **several
sessions at once** — one per worktree, each on a different slice of work. The
single biggest hazard is the same thing: two sessions editing the same file, or
eight sessions each launching a full build at the same instant.

`tooling/workflow/` is the coordination layer that makes parallelism safe. It is
~650 lines of dependency-light Bash (`git` + `jq` + `flock`) and ships with keel.

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

## The machine-global heavy-op lock

Parallel sessions are CPU-cheap until they all run `vitest` or `next build` at
once. `tooling/sandbox/with-heavy-lock` serializes heavy ops by **queuing** them:

```bash
with-heavy-lock pnpm test
```

It holds a `flock` on a single machine-global lock file for the *entire* lifetime
of the wrapped command (via an inherited fd), releasing it the instant the process
exits — even if a test runner segfaults on teardown. Nested heavy ops see
`KEEL_HEAVY_LOCK_HELD=1` and skip re-locking, so wrapping a command that itself
self-locks won't deadlock.

The `serialize-heavy-ops.sh` PreToolUse hook **enforces** it: it detects heavy
commands (test runners, builds, installs) and, if `with-heavy-lock` is on PATH but
the command isn't wrapped, refuses with a one-line fix. Crucially it does **not**
suggest "push to CI" — the old anti-pattern that just moves the cost. Heavy ops
queue and run *locally*, one at a time.

## Lifecycle & the reaper

- `session-start.sh` registers the session and seeds its heartbeat.
- `session-end.sh` releases the session's claims on clean exit.
- `heartbeat-reaper.sh` (run on a 30-min timer — launchd/systemd templates in
  `tooling/workflow/install/`) is the safety net: it purges any session whose
  heartbeat is >24h old, or >4h old with a worktree that no longer exists. So a
  session killed by closing the terminal doesn't leave a stale claim forever.

Every piece here is fail-open: a broken hook, a missing tool, a non-git directory —
none of it ever blocks your session. Coordination should be invisible until the
moment it saves you from a collision.
