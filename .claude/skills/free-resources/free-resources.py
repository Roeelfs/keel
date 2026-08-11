#!/usr/bin/env python3
"""
free-resources: safely reclaim CPU/RAM/swap on an overloaded Mac by reaping
orphans/stale dev-servers and CLOSING long-idle Claude Code sessions — never
touching a session that is actively running work or the one invoking this.

Sessions are resolved to their CANONICAL Claude-desktop title (the name the user
sees in the app), read from:
    ~/Library/Application Support/Claude/claude-code-sessions/*/*/local_*.json  (field: title)
joined by sessionId to the live process from:
    ~/.claude/sessions/<pid>.json                                              (kind==interactive)

Idle time = seconds since the session's transcript jsonl was last written
    ~/.claude/projects/*/<sessionId>.jsonl

DRY-RUN by default. Pass --apply to actually SIGTERM (then SIGKILL stragglers).

Usage:
    free-resources.py                     # report only (dry run), 30-min threshold
    free-resources.py --idle-mins 30 --apply
    free-resources.py --json              # machine-readable session list
"""
import argparse, json, os, glob, subprocess, collections, re, signal, time

APP_SESSIONS  = os.path.expanduser("~/.claude/sessions")
DESKTOP_STORE = os.path.expanduser("~/Library/Application Support/Claude/claude-code-sessions")
PROJECTS      = os.path.expanduser("~/.claude/projects")

# heavy = genuinely-running work that must NOT be interrupted even if idle
HEAVY = re.compile(r'vitest|cdk|esbuild|\btsc\b|turbo run|next build|webpack|jest|'
                   r'playwright|deploy|seed|pnpm install|npm install|\btsx ', re.I)

# `timeout [--flags] <secs> <cmd>` (GNU coreutils / homebrew `gtimeout`): a deliberately
# BOUNDED job. Nobody launches a daemon this way, so an orphaned one is in-flight work
# whose shell parent exited — never a stale server.
TIMEOUT_WRAPPER = re.compile(r'(?:^|[\s/])g?timeout\s+(?:-\S+\s+)*\d+\s', re.I)

# long-running servers that are safe to reap once orphaned. \bvite\b, NOT bare `vite`:
# the unanchored form matched the `vite` INSIDE `vitest`, which is how an in-flight test
# run entered the always-safe orphan bucket in the first place.
DEVSERVER = re.compile(r'next dev|next-server|\bvite\b|webpack|nodemon|opencode|daytona|'
                       r'node /Users.*(pnpm|sandbox|vitest)', re.I)
VENDOR    = re.compile(r'Logitech|logi_|/usr/libexec|loginwindow|/System/', re.I)


def load_ps():
    out = subprocess.run(['ps', '-Ao', 'pid=,ppid=,pcpu=,rss=,command='],
                         capture_output=True, text=True).stdout
    ppid, ch, cpu, rss, cmd = {}, collections.defaultdict(list), {}, {}, {}
    for ln in out.splitlines():
        a = ln.split(None, 4)
        if len(a) < 4:
            continue
        pid, pp = int(a[0]), int(a[1])
        ppid[pid] = pp; ch[pp].append(pid)
        cpu[pid] = float(a[2]); rss[pid] = int(a[3]); cmd[pid] = a[4] if len(a) > 4 else ''
    return ppid, ch, cpu, rss, cmd


def subtree(ch, root):
    seen, stack = set(), [root]
    while stack:
        x = stack.pop()
        if x in seen:
            continue
        seen.add(x); stack += ch.get(x, [])
    return seen


def heavy_hit(ch, cmd, root):
    """First in-flight heavy op at or under `root` -> (pid, why, command), else None.

    Mirrors the [ACTIVE-WORK] test exactly: same HEAVY regex, same `mcp` exclusion. This
    is the single predicate both kill routes must clear, so a process cannot become
    reapable merely by changing WHERE it hangs in the tree."""
    for p in sorted(subtree(ch, root)):
        c = cmd.get(p, '')
        if 'mcp' in c.lower():
            continue
        if HEAVY.search(c):
            return p, 'heavy op', c
        if TIMEOUT_WRAPPER.search(c):
            return p, 'timeout-wrapped job', c
    return None


def proc_cwd(pid):
    """Working directory of a pid (reporting only), '' if it cannot be read."""
    try:
        out = subprocess.run(['lsof', '-a', '-p', str(pid), '-d', 'cwd', '-Fn'],
                             capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return ''
    for ln in out.splitlines():
        if ln.startswith('n'):
            return ln[1:]
    return ''


def session_root(pid, ppid, cmd):
    """Ascend at most one level to the parent claude-code CLI (the pair), never to
    the disclaimer/desktop-app (which would take down everything)."""
    par = ppid.get(pid)
    if par and 'claude-code' in cmd.get(par, ''):
        return par
    return pid


def title_map():
    """Map every id a live session might present (cliSessionId primary, plus the
    desktop sessionId and any bridgeSessionIds) -> {title, ...}. The desktop store
    keys sessions by its own `sessionId` (a `local_*` id); the CLI's sessionId — the
    one in ~/.claude/sessions/<pid>.json — is stored as `cliSessionId`. Prefer the
    newest file per key so a stale empty-title duplicate never clobbers a good title."""
    m = {}
    for f in glob.glob(os.path.join(DESKTOP_STORE, '*', '*', 'local_*.json')):
        try:
            d = json.load(open(f))
        except Exception:
            continue
        rec = {'title': (d.get('title') or '').strip(),
               'titleSource': d.get('titleSource'),
               'worktreeName': d.get('worktreeName') or '',
               'isArchived': bool(d.get('isArchived')),
               '_at': d.get('lastActivityAt') or os.path.getmtime(f)}
        keys = [d.get('cliSessionId'), d.get('sessionId')] + list(d.get('bridgeSessionIds') or [])
        for k in filter(None, keys):
            prev = m.get(k)
            # keep the record that actually has a title, else the newest
            if prev is None or (rec['title'] and not prev['title']) or \
               (bool(rec['title']) == bool(prev['title']) and rec['_at'] > prev['_at']):
                m[k] = rec
    return m


def jsonl_age_seconds(sid):
    cands = glob.glob(os.path.join(PROJECTS, '*', sid + '.jsonl'))
    if not cands:
        return None
    return time.time() - max(os.path.getmtime(p) for p in cands)


def live_sessions(ppid):
    """live interactive sessions: {pid, sid, cwd}"""
    out = []
    for f in glob.glob(os.path.join(APP_SESSIONS, '*.json')):
        try:
            d = json.load(open(f))
        except Exception:
            continue
        if d.get('kind') != 'interactive':
            continue
        pid = d.get('pid')
        if pid and pid in ppid:                     # in ps table == alive
            out.append({'pid': pid, 'sid': d.get('sessionId'), 'cwd': d.get('cwd') or ''})
    return out


def hms(s):
    if s is None:
        return '  ?  '
    s = int(s); h, m = s // 3600, (s % 3600) // 60
    return f'{h//24}d{h%24}h' if h >= 24 else (f'{h}h{m:02d}m' if h else f'{m}m')


def diagnostics():
    def sh(c):
        return subprocess.run(c, shell=True, capture_output=True, text=True).stdout.strip()
    load = sh("uptime | sed 's/.*load/load/'")
    swap = sh("sysctl -n vm.swapusage")
    ram  = sh("memory_pressure 2>/dev/null | grep -i 'free perc' | grep -oE '[0-9]+%'")
    return load, swap, ram


def orphans_and_zombies(ppid, ch, cmd):
    """ppid==1 dev-servers / node scripts (excluding vendor daemons) + zombie count.

    ppid==1 is NOT by itself a licence to kill. When an intermediate `/bin/zsh -c`
    wrapper exits, the in-flight `timeout`/vitest job under it is reparented to init —
    which drops it out of every session process tree, so the [ACTIVE-WORK] guard that
    protected it a moment earlier stops seeing it. Reaping on ppid==1 alone therefore
    kills exactly the class this tool promises never to touch (observed 2026-08-11:
    a live vitest run destroyed while its owning session was alive and flagged
    [ACTIVE-WORK]). Every candidate is vetoed if it — or anything in its subtree — is a
    heavy op or a `timeout`-wrapped job.

    The scan is deliberately WIDER than the reap: a reparented heavy op is picked up even
    when it looks nothing like a dev server, so that declining to kill it produces a
    visible receipt. Staying silent about it is what made the incident unreadable — the
    dry-run printed `orphan dev-servers (ppid=1): none` while the job was still parented,
    so "nothing to see" and "something is being protected" looked identical.

    Returns (reapable_pids, protected_records, zombie_count)."""
    orph, prot = [], []
    for pid, pp in sorted(ppid.items()):
        c = cmd.get(pid, '')
        if pp != 1 or VENDOR.search(c):
            continue
        # Scan arm matches the ROOT command only. Walking the whole subtree here swept in
        # every GUI app (Chrome/Roam/Claude renderers loosely match HEAVY), which reported
        # "reparented in-flight work" about a browser — noise that discredits the receipt.
        root_is_job = 'mcp' not in c.lower() and bool(HEAVY.search(c) or
                                                      TIMEOUT_WRAPPER.search(c))
        if not (DEVSERVER.search(c) or root_is_job):
            continue
        # Veto arm stays full-subtree: a benign-looking root can front a heavy child.
        hit = heavy_hit(ch, cmd, pid)
        if hit:
            hpid, why, hcmd = hit
            prot.append({'pid': pid, 'why': why, 'at': hpid, 'cmd': hcmd,
                         'cwd': proc_cwd(pid)})
        else:
            orph.append(pid)
    zc = subprocess.run("ps -Ao stat | grep -c '^Z'", shell=True,
                        capture_output=True, text=True).stdout.strip()
    return orph, prot, zc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--idle-mins', type=float, default=30,
                    help='close sessions idle >= this many minutes (default 30)')
    ap.add_argument('--apply', action='store_true', help='actually kill (default: dry run)')
    ap.add_argument('--reap-orphans', action='store_true', default=True)
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()
    TH = args.idle_mins * 60

    ppid, ch, cpu, rss, cmd = load_ps()
    titles = title_map()
    mypid = os.getpid()

    sessions = []
    for s in live_sessions(ppid):
        root = session_root(s['pid'], ppid, cmd)
        tree = subtree(ch, root)
        meta = titles.get(s['sid'], {})
        wt = ''
        if '/worktrees/' in s['cwd']:
            wt = s['cwd'].split('/worktrees/')[-1].split('/')[0]
        heavy = [cmd[p][:46] for p in tree
                 if HEAVY.search(cmd.get(p, '')) and 'mcp' not in cmd.get(p, '').lower()]
        sessions.append({
            'pid': s['pid'], 'root': root, 'sid': s['sid'],
            'title': meta.get('title') or '(untitled)',
            'title_source': meta.get('title_source') or meta.get('titleSource'),
            'worktree': wt or meta.get('worktreeName') or '(main)',
            'idle_s': jsonl_age_seconds(s['sid']),
            'tree_procs': len(tree), 'tree': tree,
            'tree_cpu': round(sum(cpu.get(p, 0) for p in tree), 1),
            'tree_rss_mb': round(sum(rss.get(p, 0) for p in tree) / 1024),
            'active_work': heavy[0] if heavy else None,
            'is_self': mypid in tree,
        })
    sessions.sort(key=lambda x: -(x['idle_s'] or 0))

    if args.json:
        print(json.dumps([{k: v for k, v in s.items() if k != 'tree'} for s in sessions],
                         indent=2, default=str))
        return

    load, swap, ram = diagnostics()
    print(f"load: {load}\nswap: {swap}\nRAM free: {ram}\n")

    # protected trees = self + every session under threshold (active) + those with active work
    protected = set()
    for s in sessions:
        if s['is_self'] or (s['idle_s'] or 0) < TH or s['active_work']:
            protected |= s['tree']

    targets = [s for s in sessions
               if not s['is_self'] and (s['idle_s'] or 0) >= TH and not s['active_work']]

    print(f"{'IDLE':>7}  {'CANONICAL TITLE':<40} {'PID':>6} {'CPU':>5} {'RSSm':>5}  worktree")
    print('-' * 104)
    for s in sessions:
        flag = ' [SELF]' if s['is_self'] else (' [ACTIVE-WORK]' if s['active_work'] else '')
        mark = 'KILL ' if s in targets else '     '
        print(f"{mark}{hms(s['idle_s']):>6}  {s['title'][:40]:<40} {s['pid']:>6} "
              f"{s['tree_cpu']:>5} {s['tree_rss_mb']:>5}  {s['worktree'][:22]}{flag}")

    orph, prot_orph, zc = orphans_and_zombies(ppid, ch, cmd)
    print(f"\norphan dev-servers (ppid=1): {orph or 'none'}   zombies: {zc} (self-reap)")
    for o in orph:
        print(f"    reap {o}: {cmd.get(o,'')[:60]}  [cwd {proc_cwd(o) or '?'}]")
    for r in prot_orph:
        print(f"  ! PROTECTED orphan {r['pid']} — {r['why']} at pid {r['at']}: "
              f"{r['cmd'][:60]}\n      reparented in-flight work, not a stale server"
              f"  [cwd {r['cwd'] or '?'}]")
    if not prot_orph:
        print("    (no reparented in-flight work found — heavy-op veto had nothing to hold)")

    # One gate for BOTH kill routes. A tree is reaped only if nothing at or under its
    # root is a heavy op — so reparenting can no longer launder work into the kill set.
    kill, roots = set(), []
    for s in targets:
        if s['tree'] & protected:                    # safety: never cross into a protected tree
            print(f"  ! skip {s['title'][:30]} — tree overlaps a protected session")
            continue
        roots.append((f"session {s['title'][:30]}", s['root'], s['tree']))
    if args.reap_orphans:
        roots += [(f"orphan {o}", o, subtree(ch, o)) for o in orph]
    for label, root, tree in roots:
        hit = heavy_hit(ch, cmd, root)
        if hit:
            print(f"  ! skip {label} — {hit[1]} in tree (pid {hit[0]}): {hit[2][:60]}")
            continue
        kill |= tree

    print(f"\n{'APPLY' if args.apply else 'DRY-RUN'} — "
          f"{len(targets)} idle sessions + {len(orph)} orphans = {len(kill)} procs"
          f"{f' ({len(prot_orph)} orphan(s) protected)' if prot_orph else ''}")
    assert mypid not in kill, "REFUSING: self in kill set"
    # Belt-and-braces: by construction no HEAVY command can reach `kill` via either
    # route. Assert it anyway — this is the invariant the whole safety model rests on.
    stray = sorted(p for p in kill if 'mcp' not in cmd.get(p, '').lower()
                   and HEAVY.search(cmd.get(p, '')))
    assert not stray, ("REFUSING: heavy op in kill set: " +
                       '; '.join(f"{p} {cmd.get(p,'')[:60]}" for p in stray))

    if not args.apply:
        print("(re-run with --apply to execute)")
        return
    for p in sorted(kill):
        try:
            os.kill(p, signal.SIGTERM)
        except ProcessLookupError:
            pass
    time.sleep(2)
    for p in sorted(kill):
        try:
            os.kill(p, 0); os.kill(p, signal.SIGKILL)
        except OSError:
            pass
    load2, swap2, ram2 = diagnostics()
    print(f"killed {len(kill)} procs.\nafter -> {load2} | {swap2} | RAM free {ram2}")


if __name__ == '__main__':
    main()
