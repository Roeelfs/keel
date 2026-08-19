---
license: MIT
name: free-resources
description: Use when the Mac is overloaded on CPU / RAM / swap / load average (not disk) — the machine is packed and slow, "free resources", "kill idle sessions", too many parallel Claude Code sessions thrashing. Safely reaps orphans, stale dev-servers, and long-idle Claude sessions (resolved to their canonical desktop titles), never touching active work or the invoking session. For DISK-full instead, use macos-storage-reclaim.
---

# Free Resources (CPU / RAM / swap relief)

## What this is for

A Mac running many parallel Claude Code sessions thrashes: **each session spawns
its own MCP-server constellation (~6 child node procs)**, so 20 sessions ≈ 120+
node processes → RAM exhausted → heavy swap → load average 20–45. The fix is to
reap dead weight and close **long-idle** sessions — *without* killing anything
actively running.

**First, confirm it's actually CPU/RAM, not disk.** If the complaint is "disk
full" / "where did my space go", use `macos-storage-reclaim` instead. This skill
is for load/swap/RAM.

```bash
uptime | sed 's/.*load/load/'      # load average — >12 sustained = overloaded
sysctl -n vm.swapusage             # used >> a few GB = thrashing (the real signal)
memory_pressure | grep 'free perc' # free RAM %
```

## The engine

`free-resources.py` (bundled here) does the whole safe scan+kill. **Dry-run by
default** — it prints what it *would* do; add `--apply` to execute.

```bash
python3 ~/.claude/skills/free-resources/free-resources.py               # report, 30-min default
python3 ~/.claude/skills/free-resources/free-resources.py --idle-mins 30 --apply
python3 ~/.claude/skills/free-resources/free-resources.py --json        # machine-readable
```

It lists every live session by **canonical Claude-desktop title** (see below),
marks `KILL` on those past the idle threshold, flags `[SELF]` and `[ACTIVE-WORK]`,
reaps `ppid=1` orphan dev-servers, and reports zombies. Always **run the dry-run
first, show the user the KILL list, then `--apply`** (or let the user pick).

## Canonical session names (the important bit)

Do **not** label sessions by worktree slug (`gracious-murdock`) or sid prefix — use the
title the user sees in the Claude app.

- Live session -> `~/.claude/sessions/<pid>.json` -> `sessionId` (+ `kind==interactive`, pid alive).
- **Title = the LAST `custom-title` record in that session's OWN transcript**,
  `~/.claude/projects/*/<sessionId>.jsonl`, field `customTitle`. Titles get rewritten as a
  session evolves, so last-one-wins. They arrive HTML-escaped (`&amp;`) — unescape them.
- That is the same file that supplies idle time, so title and idle can never disagree about
  which session they describe. No second store, no extra join key.
- Falls back to the worktree name when a session was never titled or has no transcript yet
  (both occur live: a brand-new session, and a session whose jsonl has not appeared).

### Do NOT join to the desktop app store (measured 2026-08-19)

`~/Library/Application Support/Claude{,-Work}/claude-code-sessions/*/*/local_*.json` looks
authoritative — every record carries `title`, `cliSessionId`, `bridgeSessionIds` — and this
engine used to join on `cliSessionId`. It is dead weight: the newest file was written
2026-08-16, and **0 of 26 live sessionIds matched any `cliSessionId` / `sessionId` /
`bridgeSessionIds` key across its 680 records**. Every row silently rendered `(untitled)`,
which reads as "the user never titled anything" rather than "the join is broken" — no error,
no receipt. Pinned by `TitleResolution` in the regression tests.

Re-derive the overlap claim before trusting either side of it:

```bash
python3 - <<'EOF'
import json, glob, os
S = os.path.expanduser('~/Library/Application Support/Claude/claude-code-sessions')
keys = set()
for f in glob.glob(os.path.join(S, '*', '*', 'local_*.json')):
    try: d = json.load(open(f))
    except Exception: continue
    keys |= {d.get('cliSessionId'), d.get('sessionId')} | set(d.get('bridgeSessionIds') or [])
live = {json.load(open(f)).get('sessionId')
        for f in glob.glob(os.path.expanduser('~/.claude/sessions/*.json'))}
print('overlap:', len(keys & live), 'of', len(live), 'live sessions')
EOF
```

If that ever reports a real overlap the store is alive again — but the transcript stays the
better source: the CLI writes it for **every** session, including ones the desktop app does
not own. (Inside a Claude session the `ccd_session_mgmt` MCP `list_sessions` is a third,
live view of the same titles; it is unavailable to this standalone script.)

## Safety model (never break running work)

Kill order, safest first: **orphans → stale dev-servers → (note zombies) → long-idle clean sessions.**

A session is safe to close only if ALL hold:
1. **Idle ≥ threshold** — idle = seconds since its transcript jsonl was last written
   (`~/.claude/projects/*/<sessionId>.jsonl` mtime). Prefer a **natural break** in the
   idle distribution (e.g. a cluster at 8–24h vs an active cluster <30m) over a round number.
2. **Tree is clean** — no `vitest|cdk|esbuild|tsc|deploy|build|seed|install|playwright`
   process anywhere in its subtree. A session can be conversation-idle but still running a
   deploy/verify in the background — that is `[ACTIVE-WORK]`, **skip it**.
3. **Not [SELF]** — never kill the session invoking this (detected: `os.getpid()` inside its tree).

Hard guards baked into the engine:
- Kills the whole **process tree** per session (parent+worker claude + MCP children) via
  `session_root()`, which ascends **at most one level** and only to a `claude-code` parent —
  **never to the disclaimer / desktop app** (`/Applications/Claude.app/...`), which would take
  everything down.
- Asserts the kill set never intersects a protected tree (self + every sub-threshold/active session).
- Asserts **no HEAVY command reaches the kill set by any route** — the invariant the whole
  safety model rests on.
- `SIGTERM`, wait 2s, then `SIGKILL` stragglers.

### ppid==1 is NOT a licence to kill (2026-08-11 regression)

`[ACTIVE-WORK]` only protects processes found **inside a session's process tree**. When an
intermediate `/bin/zsh -c` wrapper exits, the in-flight job under it is **reparented to init**
— which drops it out of every session tree, so the guard that protected it a moment earlier
stops seeing it and it lands in the "orphan" bucket. That killed a live
`timeout --signal=KILL 900 pnpm … vitest run infra/__tests__/` (pid 34085) whose owning
session (45287) was alive and had just been flagged `[ACTIVE-WORK]`. It matched the orphan
pattern because the bare `vite` alternative matches the `vite` **inside `vitest`**.

Both halves are fixed, and neither is load-bearing alone:
1. **Heavy-op veto** — an orphan candidate is skipped if it *or anything in its subtree*
   matches `HEAVY` (the same regex `[ACTIVE-WORK]` uses, same `mcp` exclusion) or the
   `timeout [--flags] <secs>` wrapper. Nobody launches a daemon under `timeout`, so an
   orphaned one is in-flight work whose shell died — never a stale server.
2. **Pattern narrowing** — `\bvite\b`, so `vitest` is never read as a dev server.

The orphan **scan is deliberately wider than the reap**: a reparented heavy op is picked up
even when it looks nothing like a dev server, so declining to kill it prints a
`! PROTECTED orphan <pid>` receipt with the matched command and cwd. Silence was the real
problem in the incident — the dry-run printed `orphan dev-servers (ppid=1): none` while the
job was still parented, so "nothing to see" and "something is being protected" produced
identical output.

**cwd is reported, not enforced.** A repo-worktree cwd is *not* a protection trigger: on a
machine with ~100 worktrees, every legitimate orphan `next dev` also lives in one, so
promoting it to a guard would silently empty the orphan bucket. It is printed for every
candidate (reaped and protected) so a human can override the call.

An orphaned `next dev` / `vite` / `nodemon` is still genuinely safe and still gets reaped —
the veto only fires on in-flight work.

**Closing a session loses nothing durable** — worktree, uncommitted files, and the
resumable transcript all persist on disk; only the live process tree ends. Say this
to reassure the user.

## Regression tests

```bash
python3 ~/.claude/skills/free-resources/test_free_resources.py   # stdlib only, no pytest
```

Pins the 2026-08-11 reparent hole (synthetic ps-table fixtures of the real pids/commands,
plus a live scenario that spawns a wrapped heavy op, kills its shell parent, and asserts the
engine reports it PROTECTED and leaves it running) **and** the no-over-protection side:
orphan `next dev` / `vite` must still be reaped.

## Orphans / stale / zombies

- **Orphan dev-servers** (`ppid==1`, e.g. `next dev` whose parent session died) — safe to reap
  **only after the heavy-op veto clears them** (see the safety model above; `ppid==1` alone is
  not enough). Exclude vendor daemons (Logitech, `/usr/libexec/*`, `/System/*`).
- **Zombies** (`<defunct>`) — harmless, cannot be killed directly; they self-reap when their
  live parent waits/exits. Just report the count.

## Reporting

Show before/after `swap used`, `RAM free`, `load`, and session count. **Swap-used is the
truest signal** — free-RAM% bounces because active sessions immediately reuse freed pages;
swap draining down is the real win. Be honest when the win is modest (little idle cruft) —
the residual load is active work, and the only further lever is the user finishing/closing it.
```
