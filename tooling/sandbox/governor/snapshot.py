"""Host snapshot for the contended-admission arbiter (spec §4).

Budget: 300 ms total, 250 ms per subprocess probe. A failed or slow probe records `None` and its
name lands in `unknown[]` — never raises, so a partial snapshot still routes safely to rule D
(§5.3: "any unknown machine signal routes the decision to D and never to JEV").
"""
from datetime import datetime, timezone
import json
import os
import re
import subprocess
import sys
import time

from heavy_resources import event, free_percent, processes, read_record, total_memory_mb

PROBE_TIMEOUT_S = 0.25
SNAPSHOT_INTERVAL_S = 10
ROTATE_BYTES = 20 * 1024 * 1024
ROTATE_KEEP = 2


def _probe(name, fn, unknown):
    try:
        return fn()
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError):
        unknown.append(name)
        return None


def _sysctl(*names):
    out = subprocess.run(['/usr/sbin/sysctl', '-n', *names], capture_output=True, text=True,
                          check=True, timeout=PROBE_TIMEOUT_S)
    return out.stdout.strip().splitlines()


def cpu_and_load(unknown):
    def fn():
        ncpu = int(_sysctl('hw.ncpu')[0])
        load = [float(x) for x in re.findall(r'[\d.]+', _sysctl('vm.loadavg')[0])][:3]
        return {'ncpu': ncpu, 'load': load, 'load1_per_core': load[0] / ncpu if ncpu else None}
    result = _probe('cpu', fn, unknown)
    return result or {'ncpu': None, 'load': None, 'load1_per_core': None}


def memory(unknown):
    def fn():
        level_raw = _sysctl('kern.memorystatus_vm_pressure_level')[0]
        return {'mem_pressure_level': int(level_raw), 'mem_free_percent': free_percent(),
                'mem_total_mb': total_memory_mb()}
    result = _probe('memory', fn, unknown)
    return result or {'mem_pressure_level': None, 'mem_free_percent': None, 'mem_total_mb': None}


def swap(unknown, history=()):
    def fn():
        line = subprocess.run(['/usr/sbin/sysctl', '-n', 'vm.swapusage'], capture_output=True,
                               text=True, check=True, timeout=PROBE_TIMEOUT_S).stdout
        used = float(re.search(r'used = ([\d.]+)M', line)[1])
        total = float(re.search(r'total = ([\d.]+)M', line)[1])
        growth = None
        now = time.time()
        for sample in history:  # newest sample between 60s and 10min old (§4)
            age = now - sample.get('ts_epoch', 0)
            if 60 <= age <= 600 and sample.get('swap_used_mb') is not None:
                growth = (used - sample['swap_used_mb']) / (age / 60)
                break
        return {'swap_used_mb': used, 'swap_total_mb': total, 'swap_growth_mb_per_min': growth}
    result = _probe('swap', fn, unknown)
    return result or {'swap_used_mb': None, 'swap_total_mb': None, 'swap_growth_mb_per_min': None}


def disk(unknown, path='/System/Volumes/Data'):
    def fn():
        st = os.statvfs(path)
        free_gib = st.f_bavail * st.f_frsize / (1024 ** 3)
        total = st.f_blocks * st.f_frsize
        used_pct = 100 * (1 - st.f_bavail / st.f_blocks) if st.f_blocks else None
        return {'disk_free_gib': free_gib, 'disk_used_percent': used_pct}
    result = _probe('disk', fn, unknown)
    return result or {'disk_free_gib': None, 'disk_used_percent': None}


def hang_reports_recent(unknown, log_dir=None, now=None):
    # Shadow-only floor signal (§5.3, §18 Q2): unproven on Tahoe whether these files are written
    # for user-app hangs. Absence of the directory is `0`, not `unknown` — a missing log dir is a
    # legitimate observation on a machine that has never hung, not a probe failure.
    def fn():
        directory = log_dir or (os.path.expanduser('~/Library/Logs/DiagnosticReports'))
        if not os.path.isdir(directory):
            return 0
        cutoff = (now if now is not None else time.time()) - 600
        count = 0
        for name in os.listdir(directory):
            if name.endswith(('.hang', '.spin')):
                try:
                    if os.stat(os.path.join(directory, name)).st_mtime >= cutoff:
                        count += 1
                except OSError:
                    continue
        return count
    return _probe('hang_reports', fn, unknown)


def leases(heavy_directory, max_slots=6):
    """`{slot, job_id, class, age_s, rss_mb, members}` per live lease (§4)."""
    result = []
    table = None
    now = time.time()
    for slot in range(1, max_slots + 1):
        try:
            lease = read_record(heavy_directory / f'lease.{slot}.json')
        except (OSError, ValueError):
            continue
        if not lease:
            continue
        if table is None:
            table = processes()
        members = [p.pid for p in table.values()
                   if p.pgid == lease.get('pgid') and not p.state.startswith('Z')]
        rss_mb = sum(table[m].rss_mb for m in members if m in table)
        result.append({'slot': slot, 'job_id': lease.get('job_id'), 'class': lease.get('class'),
                        'age_s': max(0, now - lease.get('started', now)), 'rss_mb': rss_mb,
                        'members': members, 'cwd': lease.get('cwd')})
    return result


def queued_and_deferrals(heavy_directory, window_s=3600):
    queue_dir = heavy_directory / 'queue'
    queued = len(list(queue_dir.glob('*.json'))) if queue_dir.is_dir() else 0
    deferrals = 0
    events_path = heavy_directory / 'events.jsonl'
    if events_path.exists():
        cutoff = time.time() - window_s
        for line in events_path.read_text().splitlines()[-5000:]:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get('event') != 'deferred':
                continue
            try:
                ts = datetime.fromisoformat(record['ts']).timestamp()
            except (KeyError, ValueError):
                continue
            if ts >= cutoff:
                deferrals += 1
    return queued, deferrals


def load_class_stats(directory):
    path = directory / 'class-stats.json'
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _recent_snapshots(directory, limit=20):
    path = directory / 'snapshots.jsonl'
    if not path.exists():
        return []
    lines = path.read_text().splitlines()[-limit:]
    result = []
    for line in lines:
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return result


def _rotate(path):
    if path.exists() and path.stat().st_size > ROTATE_BYTES:
        for generation in range(ROTATE_KEEP - 1, 0, -1):
            older = path.with_suffix(f'.{generation}.jsonl')
            newer = path if generation == 1 else path.with_suffix(f'.{generation - 1}.jsonl')
            if newer.exists():
                newer.replace(older)


def take(directory, heavy_directory, disk_path='/System/Volumes/Data', persist=True):
    """One full host snapshot. Never raises; failed probes land in `unknown[]`."""
    started = time.monotonic()
    unknown = []
    history = _recent_snapshots(directory)
    result = {
        'ts': datetime.now(timezone.utc).isoformat(),
        **cpu_and_load(unknown),
        **memory(unknown),
        **swap(unknown, history),
        **disk(unknown, disk_path),
        'hang_reports_recent': hang_reports_recent(unknown),
        'leases': leases(heavy_directory),
        'class_stats': load_class_stats(directory),
    }
    queued, deferrals = queued_and_deferrals(heavy_directory)
    result['queued'] = queued
    result['deferrals_last_60m'] = deferrals
    result['unknown'] = unknown
    result['took_ms'] = round((time.monotonic() - started) * 1000, 1)
    if persist:
        path = directory / 'snapshots.jsonl'
        last = _recent_snapshots(directory, limit=1)
        should_write = not last or (
            datetime.fromisoformat(result['ts']).timestamp()
            - datetime.fromisoformat(last[-1]['ts']).timestamp() >= SNAPSHOT_INTERVAL_S)
        if should_write:
            _rotate(path)
            with path.open('a') as stream:
                persisted = dict(result)
                persisted['ts_epoch'] = datetime.fromisoformat(result['ts']).timestamp()
                persisted['swap_used_mb'] = result['swap_used_mb']
                stream.write(json.dumps(persisted, sort_keys=True) + '\n')
    return result


def main(argv=None):
    import argparse
    from governor.state import governor_directory
    from heavy_runner import state_directory

    parser = argparse.ArgumentParser()
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    result = take(governor_directory(), state_directory())
    if args.json:
        print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
