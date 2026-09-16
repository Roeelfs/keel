#!/usr/bin/env python3
"""Real-process regressions: a job's budget, stop and lease cover every descendant.

Each fixture job forks a child that moves to its own process group, as turbo's tasks
do. The tests use temporary state directories and kill only processes they started.
"""
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from heavy_resources import processes
from resource_test_support import isolated_wrapper


# The job forks a child that leaves the job's process group, allocates, and waits.
# The child re-touches one byte per page so a loaded host cannot page the allocation out of RSS.
# PARENT_SECONDS=0 makes the parent exit at once, so the child is reparented.
FORKING_JOB = (
    "import os, pathlib, sys, time\n"
    "pid = os.fork()\n"
    "if pid == 0:\n"
    "    os.setpgid(0, 0)\n"
    "    pathlib.Path(os.environ['CHILD_PID']).write_text(str(os.getpid()))\n"
    "    blob = bytearray(os.urandom(int(os.environ['ALLOC_MB']) << 20))\n"
    "    pages = bytes(len(range(0, len(blob), 4096)))\n"
    "    for _ in range(400):\n"
    "        blob[::4096] = pages\n"
    "        time.sleep(0.05)\n"
    "    os._exit(0)\n"
    "time.sleep(float(os.environ['PARENT_SECONDS']))\n"
)


def wait_until(predicate, timeout=8, message="condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError("timed out waiting for " + message)


def alive(pid, identity):
    process = processes().get(pid)
    return bool(process and process.identity == identity and not process.state.startswith("Z"))


def reparented(pid):
    process = processes().get(pid)
    return bool(process and process.ppid == 1)


class DescendantBudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = os.path.join(self.tmp.name, ".keel", "heavy.slots")
        os.makedirs(os.path.dirname(self.state))
        with open(os.path.join(self.tmp.name, ".keel", "resource-policy.json"), "w") as handle:
            json.dump({"min_free_percent": 0}, handle)
        self.wrapper = isolated_wrapper(self.tmp.name)
        self.children = []
        self.owned = []  # (pid, identity) of fixture processes outside any Popen handle.

    def tearDown(self):
        for pid, identity in self.owned:  # Identity-checked: never a reused pid.
            if alive(pid, identity):
                os.kill(pid, signal.SIGKILL)
        for child in self.children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)
        self.tmp.cleanup()

    def env(self, **extra):
        return {**os.environ, "HOME": self.tmp.name, "KEEL_HEAVY_POLL_SECONDS": "0.05",
                "KEEL_HEAVY_MIN_FREE_PERCENT": "0", **extra}

    def start_forking_job(self, alloc_mb=10, parent_seconds=20, **extra):
        child_pid = os.path.join(self.tmp.name, "child-pid")
        supervisor = self.launch([sys.executable, "-c", FORKING_JOB], ALLOC_MB=str(alloc_mb),
                                 PARENT_SECONDS=str(parent_seconds), CHILD_PID=child_pid, **extra)
        wait_until(lambda: os.path.exists(child_pid) and os.path.getsize(child_pid),
                   message="the forked child")
        with open(child_pid, encoding="utf-8") as handle:
            pid = int(handle.read())
        process = processes().get(pid)
        identity = process.identity if process else None  # A memory stop may already have ended it.
        if process:
            self.owned.append((pid, identity))
            self.assertEqual(process.pgid, pid, "the fixture child leads its own process group")
        return supervisor, pid, identity

    def launch(self, command, **extra):
        # A file, never a pipe: a surviving child holds the pipe open and a read would wait on it.
        with open(os.path.join(self.tmp.name, "stderr"), "w") as stderr:
            supervisor = subprocess.Popen([self.wrapper, *command], env=self.env(**extra),
                                          stdout=subprocess.DEVNULL, stderr=stderr)
        self.children.append(supervisor)
        return supervisor

    def job_leader(self):
        root = wait_until(lambda: self.lease().get("pgid"), message="the published lease")
        identity = processes()[root].identity
        self.owned.append((root, identity))
        return root, identity

    def stderr(self):
        with open(os.path.join(self.tmp.name, "stderr"), encoding="utf-8") as handle:
            return handle.read()

    def test_lease_write_failure_still_stops_the_job_at_its_budget(self):
        locked = os.path.join(self.tmp.name, "locked")
        child_pid = os.path.join(self.tmp.name, "child-pid")
        job = ("import os, pathlib, subprocess, sys, time\n"
               "while not os.path.exists(os.environ['LOCKED']): time.sleep(0.02)\n"
               "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)'])\n"
               "pathlib.Path(os.environ['CHILD_PID']).write_text(str(child.pid))\n"
               "time.sleep(20)\n")
        supervisor = self.launch([sys.executable, "-c", job], KEEL_HEAVY_MAX_SECONDS="2",
                                 LOCKED=locked, CHILD_PID=child_pid)
        root, identity = self.job_leader()
        os.chmod(self.state, 0o500)  # From here every lease rewrite fails with EACCES.
        try:
            open(locked, "w").close()  # The job now adds a member, so the supervisor must rewrite.
            wait_until(lambda: os.path.exists(child_pid) and os.path.getsize(child_pid), message="the new member")
            with open(child_pid, encoding="utf-8") as handle:
                child = processes().get(int(handle.read()))
            if child:
                self.owned.append((child.pid, child.identity))
            self.assertEqual(supervisor.wait(timeout=15), 137, self.stderr())
        finally:
            os.chmod(self.state, 0o700)
        wait_until(lambda: not alive(root, identity), timeout=5, message="the job leader to be stopped")
        if child:
            wait_until(lambda: not alive(child.pid, child.identity), timeout=5, message="the member to be stopped")
        self.assertIn("lease", self.stderr())

    def test_a_member_that_survives_the_kill_keeps_the_lease(self):
        # Fault injection: the stop spares one member, as a process forked after the last sample or stuck
        # in uninterruptible I/O escapes a real one.
        child_pid = os.path.join(self.tmp.name, "child-pid")
        self.wrapper = isolated_wrapper(self.tmp.name, (
            "import heavy_runner\n"
            "_real_signal_members = heavy_runner.signal_members\n"
            "def _spare_the_child(members, root, sig):\n"
            "    survivor = int(open(%r).read())\n"
            "    _real_signal_members([p for p in members if p.pid != survivor], root, sig)\n"
            "heavy_runner.signal_members = _spare_the_child\n") % child_pid)
        supervisor, pid, identity = self.start_forking_job(KEEL_HEAVY_MAX_SECONDS="1")
        self.assertEqual(supervisor.wait(timeout=20), 137, self.stderr())
        self.assertTrue(alive(pid, identity), "the fixture member escaped the stop")
        stops = self.events("wall_time_budget")
        self.assertEqual(len(stops), 1, self.events())
        self.assertEqual(stops[0].get("survivors"), 1, stops[0])
        self.assertTrue(os.path.exists(os.path.join(self.state, "lease.json")), "a survivor keeps the lease")
        self.assertTrue(self.live())
        self.assertEqual(self.attempt().returncode, 75, "the next job must not run beside a survivor")
        os.kill(pid, signal.SIGKILL)
        wait_until(lambda: not alive(pid, identity), timeout=5, message="the survivor to exit")
        acquired = subprocess.run([self.wrapper, "true"], env=self.env(), capture_output=True,
                                  text=True, timeout=10)
        self.assertEqual(acquired.returncode, 0, "the slot is reclaimed once the survivor is gone")

    def test_sustained_sampling_failure_still_signals_the_job_group(self):
        # A transient failure is tolerated (test_resource_budget); only unbroken blindness
        # past SAMPLE_BLIND_SECONDS ends the job, shortened here from 60s.
        broken = os.path.join(self.tmp.name, "ps-broken")
        self.wrapper = isolated_wrapper(self.tmp.name, (
            "import os, subprocess, heavy_runner\n"
            "heavy_runner.SAMPLE_BLIND_SECONDS = 0.5\n"
            "_real_processes = heavy_runner.processes\n"
            "def _processes():\n"
            "    if os.path.exists(%r):\n"
            "        raise subprocess.TimeoutExpired(['ps'], 5)\n"
            "    return _real_processes()\n"
            "heavy_runner.processes = _processes\n") % broken)
        supervisor = self.launch([sys.executable, "-c", "import time; time.sleep(20)"])
        root, identity = self.job_leader()
        open(broken, "w").close()  # Every process sample from here raises, as a hung `ps` would.
        supervisor.wait(timeout=15)
        wait_until(lambda: not alive(root, identity), timeout=5, message="the job group to be signalled")

    def events(self, reason=None):
        path = os.path.join(self.state, "events.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as handle:
            rows = [json.loads(line) for line in handle if line.strip()]
        return [row for row in rows if reason is None or row.get("reason") == reason]

    def lease(self):
        try:
            with open(os.path.join(self.state, "lease.json"), encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, ValueError):
            return {}

    def lease_records(self, pid, identity):
        return [pid, pid, identity] in self.lease().get("members", [])

    def write_lease(self, **fields):
        os.makedirs(self.state, exist_ok=True)
        with open(os.path.join(self.state, "lease.json"), "w", encoding="utf-8") as handle:
            json.dump({"job_id": "fixture", "cwd": "/", "executable": "python3", **fields}, handle)

    def attempt(self):
        return subprocess.run([self.wrapper, "true"], env=self.env(KEEL_HEAVY_WAIT_MAX="0.1"),
                              capture_output=True, text=True, timeout=10)

    def live(self):
        result = subprocess.run([self.wrapper, "--status"], env=self.env(),
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)["live"]

    def sleeping_session(self):
        leader = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"],
                                  start_new_session=True)
        self.children.append(leader)
        wait_until(lambda: leader.pid in processes(), message="the session leader")
        return leader, processes()[leader.pid].identity

    def test_memory_budget_counts_and_stops_a_child_in_another_group(self):
        supervisor, pid, identity = self.start_forking_job(alloc_mb=200, KEEL_HEAVY_MAX_RSS_MB="150")
        self.assertEqual(supervisor.wait(timeout=15), 137, self.stderr())
        stops = self.events("resource_limit")
        self.assertEqual(len(stops), 1, self.events())
        self.assertGreater(stops[0]["peak_rss_mb"], 150, stops[0])
        wait_until(lambda: not alive(pid, identity), timeout=5, message="the stopped child to exit")

    def test_wall_budget_stops_a_child_in_another_group(self):
        supervisor, pid, identity = self.start_forking_job(KEEL_HEAVY_MAX_SECONDS="1")
        self.assertEqual(supervisor.wait(timeout=15), 137, self.stderr())
        self.assertEqual(len(self.events("wall_time_budget")), 1, self.events())
        wait_until(lambda: not alive(pid, identity), timeout=5, message="the stopped child to exit")

    def test_reparented_child_keeps_the_job_and_its_slot_alive(self):
        supervisor, pid, identity = self.start_forking_job(parent_seconds=0)
        wait_until(lambda: reparented(pid), message="the child to be reparented")
        wait_until(lambda: self.lease_records(pid, identity), message="the lease to record the child")
        time.sleep(0.3)  # Several samples after the parent exited.
        self.assertIsNone(supervisor.poll(), "the job is not complete while its child runs")
        self.assertEqual(self.attempt().returncode, 75, "a waiter must not take the slot")
        self.assertEqual(self.events("exit"), [])
        os.kill(pid, signal.SIGKILL)
        self.assertEqual(supervisor.wait(timeout=10), 0, self.stderr())

    def test_killed_supervisor_lease_stays_alive_while_a_child_in_another_group_runs(self):
        supervisor, pid, identity = self.start_forking_job(parent_seconds=0)
        wait_until(lambda: reparented(pid), message="the child to be reparented")
        wait_until(lambda: self.lease_records(pid, identity), message="the lease to record the child")
        supervisor.kill()  # SIGKILL: only the lease can now keep the slot occupied.
        supervisor.wait(timeout=5)
        self.assertTrue(self.live(), "a surviving child still occupies the slot")
        deferred = self.attempt()
        self.assertEqual(deferred.returncode, 75, deferred.stderr)
        self.assertIn("previous_job_alive", deferred.stderr)
        os.kill(pid, signal.SIGKILL)
        wait_until(lambda: not alive(pid, identity), timeout=5, message="the child to exit")
        acquired = subprocess.run([self.wrapper, "true"], env=self.env(), capture_output=True,
                                  text=True, timeout=10)
        self.assertEqual(acquired.returncode, 0, acquired.stderr)

    def test_lease_from_an_older_runner_is_alive_through_its_group(self):
        leader, _identity = self.sleeping_session()
        self.write_lease(pgid=leader.pid)  # No leader identity and no members, as the old runner wrote.
        self.assertTrue(self.live())
        self.assertEqual(self.attempt().returncode, 75)
        leader.kill()
        leader.wait(timeout=5)
        self.assertFalse(self.live())
        self.assertEqual(self.attempt().returncode, 0)

    def test_reused_leader_pid_does_not_keep_the_slot(self):
        leader, identity = self.sleeping_session()
        self.write_lease(pgid=leader.pid, leader_identity=identity)
        self.assertTrue(self.live(), "the recorded leader keeps the slot")
        # Same pid, other start time: the recorded job is gone and its pid was reused.
        self.write_lease(pgid=leader.pid, leader_identity="Thu Jan  1 00:00:00 1970")
        self.assertFalse(self.live(), "a reused pid must not keep the slot")


if __name__ == "__main__":
    unittest.main(verbosity=2)
