"""Host observations and policy for the shared heavy-job supervisor."""
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import pwd
import re
import subprocess
import sys

MAX_SLOTS = 4


@dataclass(frozen=True)
class Policy:
    slots: int = 1
    max_workers: int = 2
    turbo_concurrency: int = 1
    max_rss_mb: float = 6144
    min_free_percent: float = 20
    run_min_free_percent: float = 10
    run_pressure_seconds: float = 15
    wait_seconds: float = 15
    poll_seconds: float = 0.5
    max_seconds: float = 7200
    command_max_seconds: dict = field(default_factory=dict)


def account_home():
    return Path(pwd.getpwuid(os.getuid()).pw_dir)


def load_policy():
    path = account_home() / '.keel' / 'resource-policy.json'
    values = json.loads(path.read_text()) if path.exists() else {}
    if not isinstance(values, dict):
        raise ValueError('resource policy must be an object')
    unknown = set(values) - set(Policy.__dataclass_fields__)
    if unknown:
        raise ValueError('unknown resource policy fields: ' + ', '.join(sorted(unknown)))
    defaults = asdict(Policy())
    for key, value in values.items():
        if key == 'command_max_seconds':
            continue
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
            raise ValueError('invalid resource policy field: ' + key)
    policy = {**defaults, **values}
    commands = policy.pop('command_max_seconds')
    policy_max_seconds = policy['max_seconds']  # Commands are checked against the file, not a tightened run.
    # Runtime environment can tighten budgets, never grant extra slots or memory.
    variables = {'max_workers': 'KEEL_HEAVY_MAX_WORKERS',
                 'turbo_concurrency': 'KEEL_HEAVY_TURBO_CONCURRENCY',
                 'max_rss_mb': 'KEEL_HEAVY_MAX_RSS_MB',
                 'max_seconds': 'KEEL_HEAVY_MAX_SECONDS'}
    for key, variable in variables.items():
        if variable in os.environ:
            policy[key] = min(policy[key], float(os.environ[variable]))
    # wait is not a resource grant — this one field is deliberately override-both-ways
    if 'KEEL_HEAVY_WAIT_MAX' in os.environ:
        policy['wait_seconds'] = float(os.environ['KEEL_HEAVY_WAIT_MAX'])
    if 'KEEL_HEAVY_POLL_SECONDS' in os.environ:
        policy['poll_seconds'] = min(policy['poll_seconds'], float(os.environ['KEEL_HEAVY_POLL_SECONDS']))
    if 'KEEL_HEAVY_MIN_FREE_PERCENT' in os.environ:
        policy['min_free_percent'] = max(policy['min_free_percent'], float(os.environ['KEEL_HEAVY_MIN_FREE_PERCENT']))
    if any(not math.isfinite(value) for value in policy.values()):
        raise ValueError('resource policy values must be finite')
    if not 1 <= policy['slots'] <= MAX_SLOTS or policy['slots'] % 1:
        raise ValueError(f'slots must be between 1 and {MAX_SLOTS}')
    policy['slots'] = int(policy['slots'])
    if not 1 <= policy['max_workers'] <= 8 or policy['max_workers'] % 1:
        raise ValueError('max_workers must be between 1 and 8')
    if not 1 <= policy['turbo_concurrency'] <= 4 or policy['turbo_concurrency'] % 1:
        raise ValueError('turbo_concurrency must be between 1 and 4')
    if (not 0 <= policy['min_free_percent'] <= 100 or not 0 <= policy['run_min_free_percent'] <= 100
            or policy['wait_seconds'] < 0):
        raise ValueError('invalid pressure or admission wait budget')
    if any(policy[k] <= 0 for k in ['poll_seconds', 'max_rss_mb', 'max_seconds', 'run_pressure_seconds']):
        raise ValueError('resource limits and sample interval must be positive')
    return Policy(**policy, command_max_seconds=command_budgets(commands, policy_max_seconds))


def command_budgets(value, max_seconds):
    """The usable `command_max_seconds` entries, each clamped to max_seconds.

    One bad entry is skipped with a warning: it must never refuse every heavy command on the machine.
    """
    if not isinstance(value, dict):
        raise ValueError('command_max_seconds must be an object mapping a command prefix to seconds')
    budgets = {}
    for prefix, seconds in value.items():
        words = prefix.split()
        if not words or '/' in words[0]:
            problem = 'the key must start with an executable basename'
        elif (isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds)
              or seconds % 1 or seconds <= 0):
            problem = 'the value must be a positive whole number of seconds'
        else:
            budgets[prefix] = min(int(seconds), max_seconds)
            continue
        print('with-heavy-lock: ignoring command_max_seconds entry ' + repr(prefix) + ': ' + problem,
              file=sys.stderr)
    return budgets


def command_seconds(policy, command):
    """The wall budget for one command: max_seconds, tightened by its longest matching prefix.

    A prefix is the executable basename followed by leading arguments, matched word by word.
    """
    words = [Path(command[0]).name, *command[1:]]
    matches = [(len(prefix.split()), seconds) for prefix, seconds in policy.command_max_seconds.items()
               if words[:len(prefix.split())] == prefix.split()]
    return min(policy.max_seconds, max(matches)[1]) if matches else policy.max_seconds


@dataclass(frozen=True)
class Process:
    pid: int
    ppid: int
    pgid: int
    rss_mb: float
    identity: str
    state: str


def processes():
    result = subprocess.run(
        ['ps', '-axo', 'pid=,ppid=,pgid=,rss=,stat=,lstart='],
        text=True, capture_output=True, check=True, timeout=5,
        env={**os.environ, 'LC_ALL': 'C', 'TZ': 'UTC'})  # lstart is an identity: fix its format.
    result_rows = {}
    for line in result.stdout.splitlines():
        fields = line.split(None, 5)
        if len(fields) == 6:
            pid, ppid, pgid, rss, state, started = fields
            result_rows[int(pid)] = Process(int(pid), int(ppid), int(pgid),
                                           int(rss) / 1024, started, state)
    return result_rows


def ancestors(pid, table):
    seen = set()
    while pid in table and pid not in seen:
        seen.add(pid)
        pid = table[pid].ppid
    return seen


def session_of(pid):
    try:
        return os.getsid(pid)
    except OSError:  # Exited after the table was sampled.
        return None


def job_members(root, leader_identity, table):
    """Live processes of the job started as session leader `root`.

    Every descendant stays in the job's session, including one that moves to its own process
    group (turbo's tasks do) or is reparented when its parent exits, even between two samples.
    Only setsid (a daemon) leaves it. The kernel never reuses `root` as a pid while its session
    has members, so a live `root` with another start time means the job is gone.
    """
    leader = table.get(root)
    if not isinstance(root, int) or (leader and leader_identity and leader.identity != leader_identity):
        return []
    return [p for p in table.values() if not p.state.startswith('Z') and session_of(p.pid) == root]


def free_percent():
    if sys.platform == 'darwin':
        result = subprocess.run(['/usr/bin/memory_pressure', '-Q'], capture_output=True,
                                text=True, check=True, timeout=5)
        match = re.search(r'free percentage:\s*(\d+)%', result.stdout)
        if not match:
            raise ValueError('memory_pressure did not report a free percentage')
        return float(match[1])
    if sys.platform.startswith('linux'):
        entries = dict(re.findall(r'^(MemTotal|MemAvailable):\s*(\d+)',
                                  Path('/proc/meminfo').read_text(), re.M))
        return 100 * int(entries['MemAvailable']) / int(entries['MemTotal'])
    raise ValueError('resource admission requires a supported host memory observer')


def total_memory_mb():
    if sys.platform == 'darwin':
        result = subprocess.run(['/usr/sbin/sysctl', '-n', 'hw.memsize'], capture_output=True,
                                text=True, check=True, timeout=5)
        return int(result.stdout) / 1024 / 1024
    if sys.platform.startswith('linux'):
        match = re.search(r'^MemTotal:\s*(\d+)', Path('/proc/meminfo').read_text(), re.M)
        return int(match[1]) / 1024
    raise ValueError('resource admission requires a supported host memory observer')


def read_record(path):
    if not path.exists():
        return None
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError('invalid resource lease')
    return value


def write_record(path, value):
    temporary = path.with_suffix('.tmp.' + str(os.getpid()))
    temporary.write_text(json.dumps(value, sort_keys=True) + '\n')
    temporary.chmod(0o600)
    temporary.replace(path)


def event(directory, event_name, **fields):
    value = {'event': event_name, 'ts': datetime.now(timezone.utc).isoformat(), **fields}
    with (directory / 'events.jsonl').open('a') as stream:
        stream.write(json.dumps(value, sort_keys=True) + '\n')
