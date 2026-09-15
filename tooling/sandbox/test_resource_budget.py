#!/usr/bin/env python3
"""Small black-box regressions for the resource-aware heavy-op runner.

Run directly with ``python3 tooling/sandbox/test_resource_budget.py``.  The tests
use only temporary state directories and short-lived children they create.
"""
import json
import os
import pwd
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from resource_test_support import isolated_wrapper


HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
WRAPPER = os.path.join(REPO, "tooling", "sandbox", "with-heavy-lock")


def wait_for(path, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if os.path.exists(path):
            return
        time.sleep(0.02)
    raise AssertionError("timed out waiting for %s" % path)


# Replaces the host memory observer with a scripted sequence, one value per call.
SCRIPTED_FREE_PERCENT = (
    "import json\n"
    "def _scripted_free_percent(path=Path(%r)):\n"
    "    state = json.loads(path.read_text())\n"
    "    calls = state['calls']\n"
    "    path.write_text(json.dumps({'values': state['values'], 'calls': calls + 1}))\n"
    "    return float(state['values'][min(calls, len(state['values']) - 1)])\n"
    "heavy_resources.free_percent = _scripted_free_percent\n"
)


def real_node():
    # Version-manager shims (asdf, nvm, volta) resolve the binary from $HOME, and
    # the tests override HOME; ask node for its own path under the ambient env.
    result = subprocess.run(["node", "-e", "process.stdout.write(process.execPath)"],
                            capture_output=True, text=True, timeout=10)
    if result.returncode != 0 or not result.stdout:
        raise unittest.SkipTest("node is unavailable: %s" % result.stderr.strip())
    return result.stdout


class ResourceBudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = os.path.join(self.tmp.name, ".keel", "heavy.slots")
        os.makedirs(os.path.dirname(self.state))
        with open(os.path.join(self.tmp.name, ".keel", "resource-policy.json"), "w") as handle:
            json.dump({"min_free_percent": 0}, handle)
        self.wrapper = isolated_wrapper(self.tmp.name)
        self.children = []

    def tearDown(self):
        # These are exclusively test-owned processes.  Never scan or kill by name.
        for child in self.children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)
            for stream in (child.stdin, child.stdout, child.stderr):
                if stream is not None:
                    stream.close()
        self.tmp.cleanup()

    def env(self, **extra):
        result = dict(os.environ)
        result.update({
            "HOME": self.tmp.name,
            "KEEL_HEAVY_POLL_SECONDS": "0.05",
            "KEEL_HEAVY_MIN_FREE_PERCENT": "0",
        })
        result.update(extra)
        return result

    def popen(self, args, env=None, **kwargs):
        child = subprocess.Popen([self.wrapper] + args, env=env or self.env(), **kwargs)
        self.children.append(child)
        return child

    def invoke(self, args, env=None, **kwargs):
        return subprocess.run([self.wrapper] + args, env=env or self.env(), **kwargs)

    def status(self, env=None):
        result = self.invoke(["--status"], env=env, capture_output=True, text=True,
                          timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def hold_slot(self):
        # The command body runs only after the wrapper holds the slot, so the
        # marker proves the lock is taken; a fixed sleep races under load.
        started = os.path.join(self.tmp.name, "holder-started")
        holder = self.popen([sys.executable, "-c", (
            "import pathlib,time; pathlib.Path(%r).touch(); time.sleep(5)" % started)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wait_for(started)
        return holder

    def event_rows(self):
        path = os.path.join(self.state, "events.jsonl")
        wait_for(path)
        with open(path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def test_default_is_one_slot_and_status_is_json(self):
        state = self.status(self.env())
        self.assertEqual(state["slots"], 1)

    def test_real_entrypoint_ignores_home_and_lock_dir_environment(self):
        account_root = pwd.getpwuid(os.getuid()).pw_dir
        state = os.path.join(account_root, ".keel", "heavy.slots")
        result = subprocess.run(
            [WRAPPER, "--status"], env=self.env(HOME=self.tmp.name,
                                                 KEEL_HEAVY_LOCK_DIR=self.tmp.name),
            capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["state_dir"], state)

    def test_one_slot_serializes_competing_commands(self):
        first_started = os.path.join(self.tmp.name, "first-started")
        first_finished = os.path.join(self.tmp.name, "first-finished")
        second_started = os.path.join(self.tmp.name, "second-started")
        first = self.popen([sys.executable, "-c", (
            "import pathlib,time; pathlib.Path(%r).touch(); time.sleep(.35); pathlib.Path(%r).touch()"
            % (first_started, first_finished))], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wait_for(first_started)
        second = self.popen([sys.executable, "-c", (
            "import pathlib,time; pathlib.Path(%r).touch(); time.sleep(.05)" % second_started)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.12)
        state = self.status()
        self.assertEqual(state["slots"], 1)
        self.assertTrue(state["live"], state)
        self.assertFalse(os.path.exists(second_started),
                         "second command body started before the first body finished")
        self.assertEqual(first.wait(timeout=5), 0)
        self.assertEqual(second.wait(timeout=5), 0)
        self.assertTrue(os.path.exists(first_finished))
        self.assertTrue(os.path.exists(second_started))

    def test_forged_marker_cannot_bypass_a_held_slot(self):
        holder = self.hold_slot()
        env = self.env(KEEL_HEAVY_WAIT_MAX="0.10", KEEL_CI_DEFER_BUDGET="0",
                       KEEL_HEAVY_LOCK_HELD="1")
        attempt = self.invoke(["true"], env=env, capture_output=True, text=True, timeout=5)
        self.assertEqual(attempt.returncode, 75, attempt.stderr)
        self.assertNotEqual(self.invoke(["--check-lease"], env=env).returncode, 0,
                            "an ambient marker is not a verified nested lease")
        holder.terminate()
        holder.wait(timeout=5)

    def test_verified_nested_wrapper_succeeds(self):
        result = self.invoke([self.wrapper, "true"], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        lease = self.invoke([self.wrapper, "--check-lease"], capture_output=True, text=True,
                            timeout=5)
        self.assertEqual(lease.returncode, 0, lease.stderr)

    def test_zero_wait_is_not_an_infinite_queue_after_ci_budget_is_spent(self):
        holder = self.hold_slot()
        env = self.env(KEEL_HEAVY_WAIT_MAX="0", KEEL_CI_DEFER_BUDGET="0")
        started = time.monotonic()
        result = self.invoke(["true"], env=env, capture_output=True, text=True, timeout=5)
        self.assertLess(time.monotonic() - started, 1.5, "zero is immediate deferral, never infinite")
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertNotIn("HAND THIS RUN TO CI", result.stderr)
        holder.terminate()
        holder.wait(timeout=5)

    def test_vitest_node_options_and_worker_flags_are_clamped(self):
        with tempfile.TemporaryDirectory(dir=self.tmp.name) as work:
            fake_vitest = os.path.join(work, "vitest.mjs")
            output = os.path.join(work, "args.json")
            with open(fake_vitest, "w", encoding="utf-8") as handle:
                handle.write(
                    "import { writeFileSync } from 'node:fs';\n"
                    "writeFileSync(process.env.OUT, JSON.stringify({argv: process.argv.slice(2), node: process.env.NODE_OPTIONS || ''}));\n"
                )
            env = self.env(OUT=output, NODE_OPTIONS="--trace-warnings")
            result = self.invoke([real_node(), fake_vitest, "--maxWorkers=99", "--pool=threads"],
                              env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            wait_for(output)
            with open(output, encoding="utf-8") as handle:
                observed = json.load(handle)
            self.assertIn("--maxWorkers=2", observed["argv"])
            self.assertIn("--pool=forks", observed["argv"])
            self.assertNotIn("--maxWorkers=99", observed["argv"])
            self.assertNotIn("--pool=threads", observed["argv"])
            self.assertRegex(observed["node"], r"--require[ =].*heavy_node\.cjs")

    def test_aggregate_memory_limit_kills_only_owned_group_and_logs_reason(self):
        pids = os.path.join(self.tmp.name, "owned-pids.json")
        ready = os.path.join(self.tmp.name, "ready")
        os.mkdir(ready)
        child_code = (
            "import os,pathlib,time; blob=bytearray(20*1024*1024); "
            "pathlib.Path(os.environ['READY'], str(os.getpid())).touch(); time.sleep(3)"
        )
        parent_code = (
            "import json,os,subprocess,sys,time; "
            "children=[subprocess.Popen([sys.executable,'-c',%r]) for _ in range(2)]; "
            "open(os.environ['PIDS'],'w').write(json.dumps([p.pid for p in children])); time.sleep(3)"
        ) % child_code
        unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3)"])
        self.children.append(unrelated)
        env = self.env(KEEL_HEAVY_MAX_RSS_MB="40", PIDS=pids, READY=ready)
        owned = self.popen([sys.executable, "-c", parent_code], env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        wait_for(pids)
        with open(pids, encoding="utf-8") as handle:
            member_pids = json.load(handle)
        for pid in member_pids:
            wait_for(os.path.join(ready, str(pid)))
        rss = [int(subprocess.check_output(["ps", "-o", "rss=", "-p", str(pid)], text=True).strip()) / 1024
               for pid in member_pids]
        self.assertLess(max(rss), 40, rss)
        self.assertGreater(sum(rss), 40, rss)
        self.assertNotEqual(owned.wait(timeout=12), 0, "aggregate budget must terminate the owned job")
        self.assertIsNone(unrelated.poll(), "resource enforcement must not kill unrelated sessions")
        rows = self.event_rows()
        terminal = [row for row in rows if row.get("reason") == "resource_limit"]
        self.assertTrue(terminal, rows)
        self.assertTrue(terminal[-1].get("job_id"), terminal[-1])
        self.assertGreater(terminal[-1].get("peak_rss_mb", 0), 40, terminal[-1])

    def test_killed_supervisor_keeps_slot_occupied_until_its_group_exits(self):
        started = os.path.join(self.tmp.name, "group-started")
        finished = os.path.join(self.tmp.name, "group-finished")
        command = [sys.executable, "-c", (
            "import pathlib,subprocess,sys,time; subprocess.Popen([sys.executable, '-c', %r]); "
            "pathlib.Path(%r).touch(); time.sleep(.15)"
            % ("import pathlib,time; time.sleep(.8); pathlib.Path(%r).touch()" % finished, started))]
        supervisor = self.popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wait_for(started)
        supervisor.kill()  # Kill only the test-owned wrapper supervisor, not its group.
        supervisor.wait(timeout=5)
        self.assertTrue(self.status()["live"], "a surviving group still occupies the slot")
        deferred = self.invoke(["true"], env=self.env(KEEL_HEAVY_WAIT_MAX="0.1"),
                               capture_output=True, text=True, timeout=5)
        self.assertEqual(deferred.returncode, 75, deferred.stderr)
        wait_for(finished, timeout=3)
        acquired = self.invoke(["true"], capture_output=True, text=True, timeout=5)
        self.assertEqual(acquired.returncode, 0, acquired.stderr)

    def test_daemon_that_leaves_the_group_does_not_keep_the_slot(self):
        daemon_pid = os.path.join(self.tmp.name, "daemon-pid")
        # fork keeps every inherited descriptor, as a Go daemon (limactl) does.
        command = [sys.executable, "-c", (
            "import os,pathlib,time\n"
            "if os.fork() == 0:\n"
            "    os.setsid()\n"
            "    null = os.open(os.devnull, os.O_RDWR)\n"
            "    for fd in (0, 1, 2): os.dup2(null, fd)\n"
            "    pathlib.Path(%r).write_text(str(os.getpid()))\n"
            "    time.sleep(10)\n"
            "    os._exit(0)\n"
            "while not os.path.exists(%r): time.sleep(.02)\n" % (daemon_pid, daemon_pid))]
        try:
            result = self.invoke(command, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            state = self.status()
            self.assertIsNone(state["lease"], state)
            self.assertFalse(state["live"], "a detached daemon must not keep the slot held")
            acquired = self.invoke(["true"], env=self.env(KEEL_HEAVY_WAIT_MAX="0"),
                                   capture_output=True, text=True, timeout=5)
            self.assertEqual(acquired.returncode, 0, acquired.stderr)
        finally:
            wait_for(daemon_pid)
            with open(daemon_pid, encoding="utf-8") as handle:
                os.kill(int(handle.read()), 9)  # The test-owned daemon only.

    def write_policy(self, **values):
        with open(os.path.join(self.tmp.name, ".keel", "resource-policy.json"), "w") as handle:
            json.dump({"min_free_percent": 0, **values}, handle)

    def tickets(self):
        queue = os.path.join(self.state, "queue")
        return sorted(n for n in os.listdir(queue) if n.endswith(".json")) if os.path.isdir(queue) else []

    def hold_until_released(self):
        started = os.path.join(self.tmp.name, "gated-started")
        release = os.path.join(self.tmp.name, "release")
        holder = self.popen([sys.executable, "-c", (
            "import os,pathlib,time\npathlib.Path(%r).touch()\n"
            "while not os.path.exists(%r): time.sleep(.02)" % (started, release))],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wait_for(started)
        return holder, release

    def waiter(self, args, **extra):
        # The first stderr line is QUEUED (or DEFERRED): reading it proves the ticket exists.
        return self.popen(args, env=self.env(**extra), stdout=subprocess.DEVNULL,
                          stderr=subprocess.PIPE, text=True)

    def release(self, holder, release):
        open(release, "w").close()
        self.assertEqual(holder.wait(timeout=5), 0)

    def test_staggered_waiters_acquire_in_enqueue_order(self):
        holder, release = self.hold_until_released()
        order = os.path.join(self.tmp.name, "order")
        waiters = []
        for position, label in enumerate(("first", "second", "third"), start=1):
            body = "open(%r, 'a').write(%r)" % (order, label + "\n")
            waiter = self.waiter([sys.executable, "-c", body], KEEL_HEAVY_WAIT_MAX="30")
            line = waiter.stderr.readline()
            self.assertIn("QUEUED at position %d;" % position, line)
            self.assertIn("slot held by " + os.path.basename(sys.executable), line)
            waiters.append(waiter)
        self.assertEqual(len(self.tickets()), 3)
        self.release(holder, release)
        for waiter in waiters:
            self.assertEqual(waiter.wait(timeout=15), 0)
        with open(order, encoding="utf-8") as handle:
            self.assertEqual(handle.read().split(), ["first", "second", "third"])
        self.assertEqual(self.tickets(), [])

    def test_sigkilled_waiter_ticket_is_pruned_and_blocks_nobody(self):
        holder, release = self.hold_until_released()
        killed = self.waiter(["true"], KEEL_HEAVY_WAIT_MAX="30")
        self.assertIn("QUEUED at position 1;", killed.stderr.readline())
        stale = self.tickets()
        self.assertEqual(len(stale), 1)
        killed.kill()  # SIGKILL runs no cleanup, so the ticket stays behind.
        killed.wait(timeout=5)
        self.assertEqual(self.tickets(), stale)
        waiter = self.waiter(["true"], KEEL_HEAVY_WAIT_MAX="30")
        self.assertIn("QUEUED at position 1;", waiter.stderr.readline(),
                      "a dead waiter's ticket must not hold a place in the queue")
        self.assertNotIn(stale[0], self.tickets())
        self.release(holder, release)
        self.assertEqual(waiter.wait(timeout=10), 0)
        self.assertEqual(self.tickets(), [])

    def test_signalled_waiter_removes_its_own_ticket(self):
        holder, release = self.hold_until_released()
        waiter = self.waiter(["true"], KEEL_HEAVY_WAIT_MAX="30")
        self.assertIn("QUEUED", waiter.stderr.readline())
        self.assertEqual(len(self.tickets()), 1)
        waiter.terminate()
        self.assertEqual(waiter.wait(timeout=5), 128 + signal.SIGTERM)
        self.assertEqual(self.tickets(), [])
        self.assertTrue(any(row.get("event") == "interrupted" for row in self.event_rows()))
        self.release(holder, release)

    def test_wait_max_environment_raises_and_lowers_the_policy_wait(self):
        self.assertEqual(self.status(self.env(KEEL_HEAVY_WAIT_MAX="1"))["wait_seconds"], 1)
        self.assertEqual(self.status(self.env(KEEL_HEAVY_WAIT_MAX="900"))["wait_seconds"], 900)
        self.write_policy(wait_seconds=0.1)
        holder, release = self.hold_until_released()
        waiter = self.waiter(["true"], KEEL_HEAVY_WAIT_MAX="30")
        self.assertIn("QUEUED", waiter.stderr.readline())
        time.sleep(0.5)  # Well past the 0.1s policy wait.
        self.release(holder, release)
        self.assertEqual(waiter.wait(timeout=10), 0, "a raised wait must outlast the policy wait")

    def test_worker_policy_accepts_one_to_eight_and_environment_cannot_raise_it(self):
        self.write_policy(max_workers=2)
        self.assertEqual(self.status(self.env(KEEL_HEAVY_MAX_WORKERS="8"))["max_workers"], 2)
        self.write_policy(max_workers=8)
        self.assertEqual(self.status()["max_workers"], 8)
        for rejected in (0, 9):
            self.write_policy(max_workers=rejected)
            result = self.invoke(["--status"], capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 69, result.stderr)
            self.assertIn("max_workers must be between 1 and 8", result.stderr)

    def test_node_worker_clamp_is_eight_and_the_runner_passes_the_policy_value(self):
        with tempfile.TemporaryDirectory(dir=self.tmp.name) as work:
            fake_vitest = os.path.join(work, "vitest.mjs")
            output = os.path.join(work, "args.json")
            with open(fake_vitest, "w", encoding="utf-8") as handle:
                handle.write("import { writeFileSync } from 'node:fs';\n"
                             "writeFileSync(process.env.OUT, JSON.stringify(process.argv.slice(2)));\n")
            def observed(argv, **extra):
                result = subprocess.run(argv, env=self.env(OUT=output, **extra),
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                with open(output, encoding="utf-8") as handle:
                    return json.load(handle)
            preload = "--require=" + os.path.join(HERE, "heavy_node.cjs")
            node = real_node()
            self.assertIn("--maxWorkers=8", observed([node, preload, fake_vitest], KEEL_HEAVY_MAX_WORKERS="12"))
            self.assertIn("--maxWorkers=5", observed([node, preload, fake_vitest], KEEL_HEAVY_MAX_WORKERS="5"))
            self.write_policy(max_workers=2)
            self.assertIn("--maxWorkers=2", observed([self.wrapper, node, fake_vitest], KEEL_HEAVY_MAX_WORKERS="8"))

    def scripted_pressure(self, values):
        script = os.path.join(self.tmp.name, "free-percent.json")
        with open(script, "w", encoding="utf-8") as handle:
            json.dump({"values": values, "calls": 0}, handle)
        self.wrapper = isolated_wrapper(self.tmp.name, SCRIPTED_FREE_PERCENT % script)
        return script

    def test_free_memory_low_for_two_polls_stops_the_running_job(self):
        # Call 0 is admission; calls 1 and 2 are consecutive polls of the running job.
        self.scripted_pressure([50, 10, 10, 50])
        result = self.invoke([sys.executable, "-c", "import time; time.sleep(10)"],
                             env=self.env(KEEL_HEAVY_MIN_FREE_PERCENT="20"),
                             capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 137, result.stderr)
        self.assertIn("memory_pressure_during_run", result.stderr)
        stops = [row for row in self.event_rows() if row.get("reason") == "memory_pressure_during_run"]
        self.assertEqual(len(stops), 1, stops)
        self.assertEqual(stops[0]["exit_code"], 137)

    def test_one_poll_free_memory_blip_does_not_stop_the_job(self):
        script = self.scripted_pressure([50, 10, 50])
        result = self.invoke([sys.executable, "-c", "import time; time.sleep(.6)"],
                             env=self.env(KEEL_HEAVY_MIN_FREE_PERCENT="20"),
                             capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        with open(script, encoding="utf-8") as handle:
            self.assertGreaterEqual(json.load(handle)["calls"], 4, "the blip and a recovery were sampled")
        self.assertFalse([row for row in self.event_rows()
                          if row.get("reason") == "memory_pressure_during_run"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
