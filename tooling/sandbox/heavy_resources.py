"""Host observations and policy for the shared heavy-job supervisor."""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import pwd
import re
import subprocess
import sys


@dataclass(frozen=True)
class Policy:
    slots: int = 1
    max_workers: int = 2
    max_rss_mb: float = 6144
    min_free_percent: float = 20
    wait_seconds: float = 15
    poll_seconds: float = 0.5
    max_seconds: float = 7200


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
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
            raise ValueError('invalid resource policy field: ' + key)
    policy = {**defaults, **values}
    # Runtime environment can tighten budgets, never grant extra slots or memory.
    variables = {'max_workers': 'KEEL_HEAVY_MAX_WORKERS',
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
    if policy['slots'] != 1:
        raise ValueError('this supervisor admits exactly one aggregate-budgeted job')
    if not 1 <= policy['max_workers'] <= 8 or policy['max_workers'] % 1:
        raise ValueError('max_workers must be between 1 and 8')
    if not 0 <= policy['min_free_percent'] <= 100 or policy['wait_seconds'] < 0:
        raise ValueError('invalid pressure or admission wait budget')
    if any(policy[k] <= 0 for k in ['poll_seconds', 'max_rss_mb', 'max_seconds']):
        raise ValueError('resource limits and sample interval must be positive')
    return Policy(**policy)


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
        text=True, capture_output=True, check=True, timeout=5)
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


def group_members(pgid, table):
    return [p for p in table.values() if p.pgid == pgid and not p.state.startswith('Z')]


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
