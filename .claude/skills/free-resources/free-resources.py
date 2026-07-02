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


def orphans_and_zombies(ppid, cmd):
    """ppid==1 dev-servers / node scripts (excluding vendor daemons) + zombie count."""
    orph = []
    devre = re.compile(r'next dev|next-server|vite|webpack|nodemon|opencode|daytona|'
                       r'node /Users.*(pnpm|sandbox|vitest)', re.I)
    vend  = re.compile(r'Logitech|logi_|/usr/libexec|loginwindow|/System/', re.I)
    for pid, pp in ppid.items():
        if pp == 1 and devre.search(cmd.get(pid, '')) and not vend.search(cmd.get(pid, '')):
            orph.append(pid)
    zc = subprocess.run("ps -Ao stat | grep -c '^Z'", shell=True,
                        capture_output=True, text=True).stdout.strip()
    return orph, zc


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

    orph, zc = orphans_and_zombies(ppid, cmd)
    print(f"\norphan dev-servers (ppid=1): {orph or 'none'}   zombies: {zc} (self-reap)")

    kill = set()
    for s in targets:
        if s['tree'] & protected:                    # safety: never cross into a protected tree
            print(f"  ! skip {s['title'][:30]} — tree overlaps a protected session")
            continue
        kill |= s['tree']
    if args.reap_orphans:
        for o in orph:
            kill |= subtree(ch, o)

    print(f"\n{'APPLY' if args.apply else 'DRY-RUN'} — "
          f"{len(targets)} idle sessions + {len(orph)} orphans = {len(kill)} procs")
    assert mypid not in kill, "REFUSING: self in kill set"

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
