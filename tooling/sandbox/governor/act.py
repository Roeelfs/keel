"""governor-kill: the one tiny, always-safe kill helper (founder rescope, 2026-09-29).

Everything else in spec §9 (tier-0/lane reclaim, storage rows, worktree-remove, red-main) is
dropped for phase 1. The machine-steward desktop session owns killing, archiving, storage and
red-main coordination; this helper exists only so *it* (or a human) has one safety-checked verb
that never blind-kills: refuses on a pid-reuse identity mismatch, or on a shared process group
with a live registry session or its `claude -p` bridge (§9.3 B1).
"""
from datetime import datetime, timezone
import json
import os
import signal
import time
from pathlib import Path

from heavy_resources import job_members, processes
from heavy_runner import signal_members


def live_registry_pgids(sessions_dir=None, table=None):
    """pgids of every live registry session — the never-kill-this-group set (B1.6)."""
    sessions_dir = sessions_dir or Path(os.path.expanduser('~/.claude/sessions'))
    if not sessions_dir.is_dir():
        return set()
    table = table if table is not None else processes()
    pgids = set()
    for entry_path in sessions_dir.glob('*.json'):
        try:
            entry = json.loads(entry_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        pid = entry.get('pid')
        if isinstance(pid, int) and pid in table:
            try:
                os.kill(pid, 0)
            except (OSError, ProcessLookupError, PermissionError):
                continue
            pgids.add(table[pid].pgid)
    return pgids


def governor_kill(pid, identity, why, table=None, live_pgids=None, leader_pgid=None, dry_run=True):
    """Refuses on identity mismatch or a shared live-session pgid; otherwise TERM then KILL.

    Returns a receipt dict. `dry_run=True` (the phase-1 shadow default) computes and reports the
    victim set without signalling anything.
    """
    table = table if table is not None else processes()
    live_pgids = live_registry_pgids(table=table) if live_pgids is None else live_pgids
    receipt = {'verb': 'governor_kill', 'ts': datetime.now(timezone.utc).isoformat(),
               'target': {'pid': pid, 'identity': identity}, 'why': why, 'dry_run': dry_run}
    entry = table.get(pid)
    if not entry or entry.identity != identity:
        return {**receipt, 'result': 'refused:identity_mismatch'}
    members = job_members(leader_pgid if leader_pgid is not None else entry.pgid, identity, table)
    if not members:
        members = [entry]
    member_pgids = {m.pgid for m in members} | {entry.pgid}
    if member_pgids & live_pgids:
        return {**receipt, 'result': 'refused:shared_session_pgid'}
    victims = [m.pid for m in members]
    if dry_run:
        return {**receipt, 'result': 'would_kill', 'members': victims}
    signal_members(members, entry.pgid, signal.SIGTERM)
    time.sleep(10)
    still_alive = [m for m in members if m.pid in processes()]
    if still_alive:
        signal_members(still_alive, entry.pgid, signal.SIGKILL)
    return {**receipt, 'result': 'killed', 'members': victims}


def main(argv=None):
    import argparse
    import sys

    parser = argparse.ArgumentParser(prog='governor-kill')
    parser.add_argument('pid', type=int)
    parser.add_argument('lstart', help='the process identity (ps lstart) to pin against, closing the TOCTOU')
    parser.add_argument('--why', default='manual')
    parser.add_argument('--live', action='store_true', help='actually signal; default is a dry-run report')
    args = parser.parse_args(argv)
    record = governor_kill(args.pid, args.lstart, args.why, dry_run=not args.live)
    print(json.dumps(record, sort_keys=True))
    return 0 if not record['result'].startswith('refused') else 1


if __name__ == '__main__':
    import sys
    sys.exit(main())
