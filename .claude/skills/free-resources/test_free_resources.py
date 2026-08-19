#!/usr/bin/env python3
"""Regression tests for free-resources.py — stdlib only (no pytest on this machine).

    python3 ~/.claude/skills/free-resources/test_free_resources.py

Anchor case (observed 2026-08-11): a live `vitest run infra/__tests__/` (pid 34085,
wrapped in `timeout --signal=KILL 900 pnpm --filter @cynap/backend exec vitest ...`)
was killed by the orphan reaper while its owning Claude session (pid 45287, worktree
suspicious-saha-49d499) was ALIVE and correctly flagged [ACTIVE-WORK] moments earlier.

The intermediate `/bin/zsh -c` wrapper (pid 34080) exited, reparenting the job to init.
That dropped it out of every session process tree, so the [ACTIVE-WORK] guard — which
only protects processes found WITHIN a session tree — stopped seeing it, and it fell
into the "orphan dev-servers (ppid=1)" bucket the tool treated as always-safe-to-reap.
It matched that bucket's `devre` because the bare `vite` alternative matches the `vite`
INSIDE `vitest`.

Positive control (run 2026-08-11, against `git show HEAD:...free-resources.py` at commit
143549e, i.e. the pre-fix engine): with the INCIDENT table below plus a control `next dev`,
the old classifier returned reap list [700, 34085] — it DID reap the live test run — while
the patched one returns [700] and reports 34085 as protected ('heavy op'). The fixture
therefore reproduces the real defect rather than asserting a tautology. Re-derive with:

    D=$(mktemp -d); cd ~/code/keel \
      && git show 143549e:.claude/skills/free-resources/free-resources.py > "$D/old.py"
    # then call old.orphans_and_zombies(ppid, cmd) with the INCIDENT table
"""
import importlib.util, os, re, signal, subprocess, sys, time, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(HERE, 'free-resources.py')
_spec = importlib.util.spec_from_file_location('free_resources', ENGINE)
fr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fr)

VITEST_CMD = ('timeout --signal=KILL 900 pnpm --filter @cynap/backend '
              'exec vitest run infra/__tests__/')
VITEST_CHILD = ('node /Users/roeealfasi/code/cynap-monorepo-next/node_modules/'
                'vitest/vitest.mjs run infra/__tests__/')


def table(procs):
    """procs: {pid: (ppid, command)} -> (ppid, children) in engine shape."""
    ppid, ch = {}, {}
    cmd = {p: c for p, (_, c) in procs.items()}
    for p, (pp, _) in procs.items():
        ppid[p] = pp
        ch.setdefault(pp, []).append(p)
    return ppid, ch, cmd


# The incident, with pid 34080 (the /bin/zsh -c wrapper) already gone and 34085
# reparented to init. Ancestry before the reparent was 34085 -> 34080 -> 45287.
INCIDENT = {
    26523: (1,     '/Applications/Claude.app/Contents/MacOS/Claude'),
    45286: (26523, 'claude-code-disclaimer'),
    45287: (45286, 'claude-code --session suspicious-saha-49d499'),
    34085: (1,     VITEST_CMD),          # reparented: was ppid=34080
    34257: (34085, VITEST_CHILD),
}


class OrphanReaperSafety(unittest.TestCase):

    def classify(self, procs):
        ppid, ch, cmd = table(procs)
        orph, prot, _ = fr.orphans_and_zombies(ppid, ch, cmd)
        return orph, prot

    def test_reparented_vitest_run_is_protected_not_reaped(self):
        """THE regression: pid 34085 must never enter the reap list.

        Two independent layers must each hold, so neither alone is load-bearing:
        (a) it is no longer classified as a dev server at all, and
        (b) even if it were a candidate, the heavy-op veto is armed against it."""
        ppid, ch, cmd = table(INCIDENT)
        orph, prot, _ = fr.orphans_and_zombies(ppid, ch, cmd)
        self.assertNotIn(34085, orph, 'reparented in-flight vitest run was reaped')
        self.assertNotIn(34257, orph)

        # (a) narrowing: the incident command is not a dev server
        self.assertIsNone(fr.DEVSERVER.search(VITEST_CMD))
        # (b) veto: independently of (a), it reads as in-flight work
        hit = fr.heavy_hit(ch, cmd, 34085)
        self.assertIsNotNone(hit, 'heavy-op veto not armed against the incident command')
        self.assertEqual(hit[1], 'heavy op')

    def test_reparented_heavy_op_is_reported_even_when_not_a_dev_server(self):
        """Declining must leave a receipt. The scan is wider than the reap so that
        'nothing to see' and 'something is being protected' are never the same output —
        the dry-run in the incident printed `orphan dev-servers: none` and read as safe."""
        orph, prot = self.classify(INCIDENT)
        self.assertIsNone(fr.DEVSERVER.search(VITEST_CMD))   # not a dev-server candidate
        self.assertEqual([r['pid'] for r in prot], [34085],  # ...yet still reported
                         'reparented heavy op was silently ignored instead of reported')

    def test_orphaned_vitest_child_alone_is_protected(self):
        """If the reparent lands on the node child instead, it must still be vetoed —
        it matches devre's `node /Users.*vitest` clause directly."""
        procs = dict(INCIDENT)
        del procs[34085]
        procs[34257] = (1, VITEST_CHILD)
        orph, prot = self.classify(procs)
        self.assertEqual(orph, [])
        self.assertEqual([r['pid'] for r in prot], [34257])

    def test_timeout_wrapper_protects_even_without_a_heavy_leaf(self):
        """`timeout <n> ...` is a deliberately-bounded job; a daemon is never launched
        this way, so an orphaned one is in-flight work, not a stale server."""
        procs = {1: (0, 'launchd'),
                 900: (1, 'timeout --signal=KILL 600 node /Users/roee/repo/pnpm-runner.js')}
        orph, prot = self.classify(procs)
        self.assertEqual(orph, [])
        self.assertEqual(prot[0]['why'], 'timeout-wrapped job')

    def test_heavy_op_anywhere_in_the_subtree_vetoes_the_root(self):
        """The veto walks the whole subtree, not just the root command."""
        procs = {1: (0, 'launchd'),
                 500: (1, 'node /Users/roee/repo/pnpm-exec.js'),   # innocuous root
                 501: (500, 'node /Users/roee/repo/node_modules/.bin/esbuild --bundle')}
        orph, prot = self.classify(procs)
        self.assertEqual(orph, [])
        self.assertEqual(prot[0]['at'], 501)

    # --- no over-protection: the tool must still do its job -------------------

    def test_genuine_orphan_next_dev_is_still_reaped(self):
        procs = {1: (0, 'launchd'),
                 700: (1, 'node /Users/roee/repo/node_modules/.bin/next dev -p 3000'),
                 701: (700, 'next-server (v15.5.19)')}
        orph, prot = self.classify(procs)
        self.assertEqual(orph, [700])
        self.assertEqual(prot, [])

    def test_genuine_orphan_vite_dev_server_is_still_reaped(self):
        procs = {1: (0, 'launchd'),
                 710: (1, 'node /Users/roee/repo/node_modules/.bin/vite --host')}
        orph, prot = self.classify(procs)
        self.assertEqual(orph, [710])

    def test_vendor_daemons_are_still_excluded(self):
        procs = {1: (0, 'launchd'),
                 720: (1, '/usr/libexec/nodemon-lookalike')}
        orph, prot = self.classify(procs)
        self.assertEqual((orph, prot), ([], []))

    # --- the two regexes ------------------------------------------------------

    def test_bare_vite_no_longer_matches_vitest(self):
        """The substring match that put a test run in the dev-server bucket at all.
        The old pattern was `...|vite|...`; `vite` is a prefix of `vitest`."""
        self.assertIsNotNone(re.search(r'vite', VITEST_CMD, re.I),   # the old behaviour
                             'fixture no longer reproduces the substring hazard')
        self.assertIsNone(fr.DEVSERVER.search(VITEST_CMD))
        self.assertIsNone(fr.DEVSERVER.search('pnpm exec vitest run --coverage'))
        self.assertIsNotNone(fr.DEVSERVER.search('node /Users/r/x/node_modules/.bin/vite'))

    def test_timeout_wrapper_does_not_false_positive_on_a_timeout_flag(self):
        self.assertIsNone(fr.TIMEOUT_WRAPPER.search('node server.js --timeout 30 --port 3000'))
        self.assertIsNone(fr.TIMEOUT_WRAPPER.search('node server.js --request-timeout 5 x'))
        self.assertIsNotNone(fr.TIMEOUT_WRAPPER.search('timeout 900 pnpm test'))
        self.assertIsNotNone(fr.TIMEOUT_WRAPPER.search('/opt/homebrew/bin/gtimeout --signal=KILL 60 x'))

    def test_heavy_hit_mirrors_the_active_work_mcp_exclusion(self):
        """[ACTIVE-WORK] ignores commands containing `mcp`; the veto must match, or the
        two guards disagree about what counts as work."""
        ppid, ch, cmd = table({1: (0, 'launchd'), 800: (1, 'node mcp-server-vitest-bridge')})
        self.assertIsNone(fr.heavy_hit(ch, cmd, 800))


class LiveReparentScenario(unittest.TestCase):
    """Constructs the real thing: a heavy op under an intermediate shell, shell killed,
    job reparented to init — then runs the actual engine and reads its verdict."""

    def test_engine_reports_reparented_heavy_op_as_protected(self):
        if not (os.path.exists('/opt/homebrew/bin/timeout') or
                subprocess.run(['which', 'timeout'], capture_output=True).returncode == 0):
            self.skipTest('no coreutils `timeout` on PATH')

        # trailing `; true` matters: zsh EXECs a lone command, replacing itself, which
        # would leave no intermediate shell parent to kill — the whole point here.
        inner = ('timeout --signal=KILL 300 perl -e '
                 '\'$0 = "pnpm --filter @cynap/backend exec vitest run infra/__tests__/"; '
                 'sleep 300\'; true')
        # own process group so the teardown can guarantee no strays survive the test
        shell = subprocess.Popen(['/bin/zsh', '-c', inner], start_new_session=True)
        job = None
        try:
            # find the timeout child of our zsh, then kill the zsh to force the reparent
            for _ in range(50):
                out = subprocess.run(['ps', '-Ao', 'pid=,ppid=,command='],
                                     capture_output=True, text=True).stdout
                for ln in out.splitlines():
                    a = ln.split(None, 2)
                    if len(a) == 3 and int(a[1]) == shell.pid and 'timeout' in a[2]:
                        job = int(a[0])
                        break
                if job:
                    break
                time.sleep(0.1)
            self.assertIsNotNone(job, 'could not spawn the wrapped job')

            os.kill(shell.pid, signal.SIGKILL)
            shell.wait(timeout=5)
            for _ in range(50):                       # wait for ppid to become 1
                pp = subprocess.run(['ps', '-o', 'ppid=', '-p', str(job)],
                                    capture_output=True, text=True).stdout.strip()
                if pp == '1':
                    break
                time.sleep(0.1)
            self.assertEqual(pp, '1', 'job did not reparent to init')

            # --idle-mins huge so no real session is ever a target; dry run regardless
            r = subprocess.run([sys.executable, ENGINE, '--idle-mins', '999999'],
                               capture_output=True, text=True, timeout=180)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn(f'PROTECTED orphan {job}', r.stdout,
                          f'engine did not protect the reparented job:\n{r.stdout}')
            self.assertNotIn(f'reap {job}:', r.stdout)
            # and it must be alive after the engine ran
            self.assertEqual(subprocess.run(['ps', '-p', str(job)],
                                            capture_output=True).returncode, 0)
        finally:
            # GNU `timeout` setpgid()s itself, so its child sits in a DIFFERENT process
            # group from the shell — killpg(shell.pid) alone leaks the leaf. Kill both
            # groups, then sweep by command string as a backstop.
            for leader in filter(None, [job, shell.pid]):
                try:
                    os.killpg(os.getpgid(leader), signal.SIGKILL)
                except OSError:
                    pass
            for p in filter(None, [job, shell.pid]):
                try:
                    os.kill(p, signal.SIGKILL)
                except OSError:
                    pass
            subprocess.run(['pkill', '-9', '-f', 'exec vitest run infra/__tests__/'],
                           capture_output=True)


import json, shutil, tempfile


class TitleResolution(unittest.TestCase):
    """The 2026-08-19 SILENT regression: every session rendered "(untitled)".

    The engine joined live sessions to the Claude desktop store
    (~/Library/Application Support/Claude/claude-code-sessions/*/*/local_*.json)
    on `cliSessionId`. That store stopped being written on this machine — newest
    file 2026-08-16 — and 0 of 26 live sessionIds matched ANY of its
    cliSessionId / sessionId / bridgeSessionIds keys across 680 records. The join
    degraded to "(untitled)" for every row with no error and no receipt, which
    reads exactly like "the user never titled anything".

    Titles now come from the LAST `custom-title` record in the session's OWN
    transcript — the same file already used for idle time.
    """

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._orig = fr.PROJECTS
        fr.PROJECTS = self._tmp

    def tearDown(self):
        fr.PROJECTS = self._orig
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write(self, sid, lines, project='-Users-roee-repo'):
        d = os.path.join(self._tmp, project)
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, sid + '.jsonl')
        with open(p, 'w', encoding='utf-8') as fh:
            for ln in lines:
                fh.write((ln if isinstance(ln, str) else json.dumps(ln)) + '\n')
        return p

    def test_no_desktop_store_dependency(self):
        """THE regression: a titled session resolves from ~/.claude/projects ALONE,
        so the dead desktop store can never again silently blank every title."""
        sid = 'aaaaaaaa-0000-0000-0000-000000000001'
        self._write(sid, [{'type': 'custom-title', 'customTitle': 'Free resources'}])
        self.assertEqual(fr.session_title(sid), 'Free resources')
        self.assertFalse(hasattr(fr, 'DESKTOP_STORE'),
                         "engine still binds the dead desktop session store")

    def test_last_custom_title_wins(self):
        """Titles are rewritten as a session evolves; only the newest is current."""
        sid = 'aaaaaaaa-0000-0000-0000-000000000002'
        self._write(sid, [{'type': 'custom-title', 'customTitle': 'First guess'},
                          {'type': 'user', 'message': 'irrelevant'},
                          {'type': 'custom-title', 'customTitle': 'Root cause analysis'}])
        self.assertEqual(fr.session_title(sid), 'Root cause analysis')

    def test_html_entities_are_unescaped(self):
        """Observed live: 'Spec the account &amp; authorization surface'."""
        sid = 'aaaaaaaa-0000-0000-0000-000000000003'
        self._write(sid, [{'type': 'custom-title',
                           'customTitle': 'Spec the account &amp; authorization surface'}])
        self.assertEqual(fr.session_title(sid),
                         'Spec the account & authorization surface')

    def test_untitled_session_returns_empty_so_caller_falls_back(self):
        """Empty (not '(untitled)') — main() falls back to the worktree name."""
        sid = 'aaaaaaaa-0000-0000-0000-000000000004'
        self._write(sid, [{'type': 'user', 'message': 'hello'}])
        self.assertEqual(fr.session_title(sid), '')

    def test_missing_transcript_returns_empty(self):
        self.assertEqual(fr.session_title('no-such-session-id'), '')

    def test_malformed_lines_do_not_break_resolution(self):
        """A live transcript's last line is often half-written."""
        sid = 'aaaaaaaa-0000-0000-0000-000000000005'
        self._write(sid, ['{"type": "custom-title", "customTitle": "Good title"}',
                          '{"type": "custom-title", TRUNCA',
                          'not json at all'])
        self.assertEqual(fr.session_title(sid), 'Good title')

    def test_idle_and_title_read_the_same_transcript(self):
        """One file backs both signals, so they can never describe different sessions."""
        sid = 'aaaaaaaa-0000-0000-0000-000000000006'
        p = self._write(sid, [{'type': 'custom-title', 'customTitle': 'Same file'}])
        self.assertEqual(fr.transcript_path(sid), p)
        self.assertIsNotNone(fr.jsonl_age_seconds(sid))
        self.assertEqual(fr.session_title(sid), 'Same file')


if __name__ == '__main__':
    unittest.main(verbosity=2)
