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
        env = self.env(ALLOC_MB=str(alloc_mb), PARENT_SECONDS=str(parent_seconds),
                       CHILD_PID=child_pid, **extra)
        # A file, never a pipe: a surviving child holds the pipe open and a read would wait on it.
        with open(os.path.join(self.tmp.name, "stderr"), "w") as stderr:
            supervisor = subprocess.Popen([self.wrapper, sys.executable, "-c", FORKING_JOB], env=env,
                                          stdout=subprocess.DEVNULL, stderr=stderr)
        self.children.append(supervisor)
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

    def stderr(self):
        with open(os.path.join(self.tmp.name, "stderr"), encoding="utf-8") as handle:
            return handle.read()

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
