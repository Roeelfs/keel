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
    # Per-class override of max_rss_mb, keyed by job class (executable basename). Read ONLY through
    # heavy_runner.effective_rss_cap; absent = every class gets max_rss_mb.
    class_max_rss_mb: dict = field(default_factory=dict)
    # Machine-governor fields (docs/specs/2026-09-29-machine-governor.md §5.5). Deleted 2026-11-15
    # along with governor_mode/jev_admission if phase 1b has not been promoted by then.
    governor_mode: str = 'shadow'  # 'shadow' | 'enforce'; no 'off' value — shadow enforces the fixed policy.
    jev_admission: str = 'shadow'  # 'shadow' | 'enforce'
    max_slots: int = 6  # governor-side ceiling for the D/JEV arbiter; MAX_SLOTS still bounds claim_slot.
    cheap_rss_seconds: float = 131072  # RSS x seconds gate for the +1 cheap-class slot (§5.2)
    disk_floor_gib: float = 10
    disk_reclaim_gib: float = 25
    swap_growth_floor_mb_per_min: float = 256
    jev_deadline_ms: float = 1500
    decision_ttl_s: float = 20
    admit_p_hi: float = 0.60
    admit_p_lo: float = 0.40
    saturation_deny: float = 3.5
    broker_shells: tuple = ('bash', 'zsh', 'sh', 'dash')
    # CPU admission (2026-10-19: a game lagged at load 34.8 on 12 cores while the memory-only gate
    # admitted two ~300% CPU suites). 0 disables the load gate.
    max_load_per_core: float = 0.85
    # Interactive foreground load, learned at runtime and never named: the frontmost GUI app, plus
    # any process outside a heavy job whose decaying %CPU is at least interactive_busy_cores. When
    # the frontmost app uses interactive_min_cores or more, its load is reserved (at least
    # interactive_reserve_cores) and concurrent heavy jobs are capped at interactive_max_jobs.
    interactive_min_cores: float = 0.5
    interactive_busy_cores: float = 0.5
    interactive_reserve_cores: float = 2
    interactive_max_jobs: float = 1
    # Protected foreground apps (2026-10-27: a heavy suite was admitted while MapleStory ran, and the
    # game lagged). A running process whose executable path contains one of these names defers every
    # heavy job with reason `protected_app:<name>`. Empty tuple disables the check.
    protected_apps: tuple = ('MapleStory',)
    # idle_kill_hours/reclaim_min_interval_s/reclaim_daily_max/reclaim_max_runtime_s (r2) are gone:
    # they rate-limited the tick/lane reclaim engine, which the 2026-09-29 founder rescope dropped
    # in favor of machine-steward (docs/machine-steward.md). Nothing in this repo reads them.


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
    string_fields = {'governor_mode', 'jev_admission'}
    list_fields = {'broker_shells', 'protected_apps'}
    for key, value in values.items():
        if key in ('command_max_seconds', 'class_max_rss_mb'):
            continue
        if key in string_fields:
            if value not in ('shadow', 'enforce'):
                raise ValueError('invalid resource policy field: ' + key)
            continue
        if key in list_fields:
            if not isinstance(value, (list, tuple)) or not all(isinstance(v, str) for v in value):
                raise ValueError('invalid resource policy field: ' + key)
            continue
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
            raise ValueError('invalid resource policy field: ' + key)
    policy = {**defaults, **values}
    commands = policy.pop('command_max_seconds')
    class_caps = policy.pop('class_max_rss_mb')
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
    if os.environ.get('KEEL_GOVERNOR_MODE') == 'shadow':  # may only move enforce -> shadow, never the reverse
        policy['governor_mode'] = 'shadow'
    if any(not math.isfinite(value) for key, value in policy.items()
           if key not in string_fields and key not in list_fields):
        raise ValueError('resource policy values must be finite')
    if policy['governor_mode'] not in ('shadow', 'enforce') or policy['jev_admission'] not in ('shadow', 'enforce'):
        raise ValueError('governor_mode and jev_admission must be shadow or enforce')
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
    return Policy(**policy, command_max_seconds=command_budgets(commands, policy_max_seconds),
                  class_max_rss_mb=class_rss_caps(class_caps))


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


def class_rss_caps(value):
    """The usable `class_max_rss_mb` entries (class name -> positive finite MiB).

    A bad entry, or a field that is not an object, is dropped with a warning: it must never refuse
    every heavy command on the machine. A dropped entry falls back to `max_rss_mb`.
    """
    if not isinstance(value, dict):
        print('with-heavy-lock: ignoring class_max_rss_mb: it must be an object mapping a class to MiB',
              file=sys.stderr)
        return {}
    caps = {}
    for name, mb in value.items():
        if not isinstance(name, str) or not name or name != name.strip() or '/' in name or ' ' in name:
            problem = 'the key must be a non-empty executable basename'
        elif isinstance(mb, bool) or not isinstance(mb, (int, float)) or not math.isfinite(mb) or mb <= 0:
            problem = 'the value must be a positive finite number of MiB'
        else:
            caps[name] = float(mb)
            continue
        print('with-heavy-lock: ignoring class_max_rss_mb entry ' + repr(name) + ': ' + problem,
              file=sys.stderr)
    return caps


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


def frontmost_pid():
    """The frontmost GUI app's pid, or None where there is no window server to ask."""
    if sys.platform != 'darwin':
        return None
    front = subprocess.run(['/usr/bin/lsappinfo', 'front'], text=True, capture_output=True,
                           check=True, timeout=5).stdout.strip()
    info = subprocess.run(['/usr/bin/lsappinfo', 'info', '-only', 'pid', front], text=True,
                          capture_output=True, check=True, timeout=5).stdout
    match = re.search(r'"pid"\s*=\s*(\d+)', info)
    return int(match[1]) if match else None


def interactive_load(policy, job_sessions):
    """(frontmost app's cores, all interactive cores) -- anonymous figures, no names or pids.

    Interactive = the frontmost app plus every busy process that is not a member of a heavy job
    (its session is a lease's session). ps %CPU is a decaying average, so a busy process is a
    sustained one, not a single spike.
    """
    front = frontmost_pid()
    result = subprocess.run(['ps', '-axo', 'pid=,pcpu='], text=True, capture_output=True,
                            check=True, timeout=5, env={**os.environ, 'LC_ALL': 'C'})
    front_cores = total = 0.0
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) != 2:
            continue
        pid, cores = int(fields[0]), float(fields[1]) / 100
        if pid == front:
            front_cores = cores
            total += cores
        elif cores >= policy.interactive_busy_cores and session_of(pid) not in job_sessions:
            total += cores
    return front_cores, total


def protected_app_running(policy):
    """The first configured protected app name found in a running process's path, else None."""
    if not policy.protected_apps:
        return None
    result = subprocess.run(['ps', '-axo', 'comm='], text=True, capture_output=True,
                            check=True, timeout=5, env={**os.environ, 'LC_ALL': 'C'})
    for name in policy.protected_apps:
        if name and name in result.stdout:
            return name
    return None


def cpu_state(policy, running_jobs, job_sessions=frozenset()):
    """The CPU admission decision for one more heavy job beside `running_jobs` held slots.

    Capacity is `max_load_per_core x ncpu`. While the frontmost app is busy, the interactive load
    (at least interactive_reserve_cores) is reserved from it and heavy jobs are capped at
    interactive_max_jobs. The load average already contains that load, so the reserve is headroom
    kept for it, not a double count. Read errors fail open.
    """
    try:
        load1 = os.getloadavg()[0]
        ncpu = os.cpu_count() or 1
        front_cores, interactive_cores = interactive_load(policy, set(job_sessions))
        protected = protected_app_running(policy)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        return {'reason': None, 'error': type(error).__name__}
    foreground_busy = front_cores >= policy.interactive_min_cores
    reserve = max(policy.interactive_reserve_cores, interactive_cores) if foreground_busy else 0.0
    capacity = policy.max_load_per_core * ncpu - reserve
    reason = None
    if protected:
        reason = 'protected_app:' + protected
    elif foreground_busy and running_jobs >= policy.interactive_max_jobs:
        reason = 'interactive_foreground'
    elif policy.max_load_per_core and load1 > capacity:
        reason = 'cpu_pressure'
    return {'reason': reason, 'load1': round(load1, 2), 'ncpu': ncpu, 'capacity': round(capacity, 2),
            'reserve_cores': round(reserve, 2), 'foreground_busy': foreground_busy,
            'interactive_cores': round(interactive_cores, 2), 'running_jobs': running_jobs}


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
