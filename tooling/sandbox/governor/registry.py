"""Session-registry join for the CONTEXT block (spec §4 "Session and worktree joins").

Best-effort and time-boxed: a malformed session file, a missing transcript, or a slow disk each
degrade a field to `None` rather than aborting the whole build or raising. Never touches
`~/.claude/sessions` for writing -- read-only throughout.
"""
import json
import os
from pathlib import Path
import time

from heavy_resources import processes

SESSIONS_DIR = Path(os.path.expanduser('~/.claude/sessions'))
PROJECTS_DIR = Path(os.path.expanduser('~/.claude/projects'))
DEFAULT_BUDGET_S = 0.8


def _is_live(pid, proc_start, table):
    entry = table.get(pid)
    return bool(entry and proc_start and entry.identity.strip() == proc_start.strip())


def _transcript_idle_minutes(session_id, projects_dir, now):
    if not session_id:
        return None
    try:
        matches = list(projects_dir.glob(f'*/{session_id}.jsonl'))
    except OSError:
        return None
    if not matches:
        return None
    try:
        mtime = matches[0].stat().st_mtime
    except OSError:
        return None
    return round((now - mtime) / 60, 1)


def build(sessions_dir=None, projects_dir=None, table=None, budget_s=DEFAULT_BUDGET_S):
    """`{pid: {identity, sessionId, name, cwd, status, idle_minutes, live}}` for registry entries.

    Time-boxed to `budget_s`: on a large/slow registry it returns whatever it managed rather than
    ever blocking a deferral. Any single bad entry is skipped, never fatal.
    """
    sessions_dir = sessions_dir or SESSIONS_DIR
    projects_dir = projects_dir or PROJECTS_DIR
    started = time.monotonic()
    result = {}
    try:
        if not sessions_dir.is_dir():
            return result
        entries = sorted(sessions_dir.glob('*.json'))
    except OSError:
        return result
    table = table if table is not None else processes()
    now = time.time()
    for entry_path in entries:
        if time.monotonic() - started > budget_s:
            break
        try:
            data = json.loads(entry_path.read_text())
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        pid = data.get('pid')
        if not isinstance(pid, int):
            continue
        try:
            live = _is_live(pid, data.get('procStart'), table)
            session_id = data.get('sessionId')
            idle_minutes = _transcript_idle_minutes(session_id, projects_dir, now)
            result[pid] = {
                'identity': table[pid].identity if pid in table else None,
                'sessionId': session_id, 'name': data.get('name'), 'cwd': data.get('cwd'),
                'status': data.get('status'), 'idle_minutes': idle_minutes, 'live': live,
            }
        except (KeyError, AttributeError, TypeError):
            continue
    return result


def owner_of(pid, cwd, table, registry):
    """The owning session for a candidate pid: ancestry to a registered pid, else a cwd match.

    Never raises: an unknown pid, a missing table entry or an empty registry all degrade to None.
    `unknown` never means dead (spec §4) -- callers keep the candidate, just without an owner.
    """
    if not registry or table is None:
        return None
    try:
        seen = set()
        current = pid
        while current in table and current not in seen:
            if current in registry:
                return registry[current]
            seen.add(current)
            current = table[current].ppid
    except (KeyError, AttributeError, TypeError):
        pass
    if cwd:
        for owner in registry.values():
            owner_cwd = owner.get('cwd')
            if owner_cwd and (cwd == owner_cwd or cwd.startswith(owner_cwd.rstrip('/') + '/')
                               or owner_cwd.startswith(cwd.rstrip('/') + '/')):
                return owner
    return None
