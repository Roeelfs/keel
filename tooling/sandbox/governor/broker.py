"""The wrapper broker (spec §6) — the dominant `resource_busy` fix.

A top-level wrapper script (`bash round5.sh`) holds a slot for its whole life today, even though
the heavy work happens in a nested call. `is_wrapper` decides, with no side effects, whether a
command should run without taking a slot at all; `heavy_runner` (wired separately) is the only
caller that acts on it.
"""
import json
import os
import sys
from pathlib import Path

_HOOKS_DIR = Path(__file__).resolve().parents[3] / '.claude' / 'hooks'
if str(_HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(_HOOKS_DIR))

from heavy_command import PACKAGE_MANAGERS, PACKAGE_VERBS, TEST_RUNNERS, is_self_locking

ALWAYS_HEAVY_NAMES = frozenset({'tsc', 'turbo', 'cdk', 'next', 'node'})


def custom_rules(home=None):
    path = (home or Path(os.path.expanduser('~/.keel'))) / 'resource-commands.json'
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def is_wrapper(command, policy, cwd=None, home=None):
    """True when `command` is a top-level shell/`.sh` wrapper that should take no slot."""
    if not command:
        return False
    basename = Path(command[0]).name
    is_shell_like = basename in policy.broker_shells or basename.endswith('.sh')
    if not is_shell_like:
        return False
    if basename in custom_rules(home):  # e.g. wt-verify.sh, wt-setup keep a slot
        return False
    if is_self_locking(command[0], cwd):
        return False
    return True


SHIMMED_NAMES = tuple(sorted(PACKAGE_MANAGERS | TEST_RUNNERS | ALWAYS_HEAVY_NAMES))


def shim_is_heavy(name, args):
    """Whether an invocation of `name` with `args` is heavy enough to need its own slot (§6)."""
    if name in ALWAYS_HEAVY_NAMES or name in TEST_RUNNERS:
        return True
    if name in PACKAGE_MANAGERS:
        return any(a in PACKAGE_VERBS for a in args)
    return False


SHIM_TEMPLATE = """#!/usr/bin/env python3
import os, sys
from pathlib import Path

REAL_NAME = {name!r}
HERE = Path(__file__).resolve().parent
SANDBOX = HERE.parent.parent / 'sandbox'
sys.path.insert(0, str(SANDBOX))


def real_path():
    parts = [p for p in os.environ.get('PATH', '').split(os.pathsep) if Path(p) != HERE]
    for part in parts:
        candidate = Path(part) / REAL_NAME
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    raise SystemExit(f'governor shim: {{REAL_NAME}} not found on PATH outside the shim directory')


def main():
    from governor.broker import shim_is_heavy
    argv = [REAL_NAME, *sys.argv[1:]]
    real = real_path()
    if shim_is_heavy(REAL_NAME, sys.argv[1:]):
        with_lock = str(SANDBOX / 'with-heavy-lock')
        os.execvpe(with_lock, [with_lock, real, *sys.argv[1:]], os.environ)
    os.execvpe(real, argv, os.environ)


if __name__ == '__main__':
    main()
"""


def write_shims(directory):
    """Writes one shim per heavy tool name (§6). Idempotent; returns the written paths."""
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    written = []
    for name in SHIMMED_NAMES:
        path = directory / name
        path.write_text(SHIM_TEMPLATE.format(name=name))
        path.chmod(0o700)
        written.append(path)
    return written
