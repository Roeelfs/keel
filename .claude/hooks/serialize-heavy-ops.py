#!/usr/bin/env python3
"""Shared Claude/Codex PreToolUse(Bash) resource admission guard."""
import json
import os
from pathlib import Path
import pwd
import shutil
import sys

try:
    from heavy_command import classify
except ImportError:
    print('Resource guard installation is incomplete; command refused. Reinstall resource hooks.', file=sys.stderr)
    raise SystemExit(2)


def main():
    raw = sys.stdin.read()
    if not raw.strip():
        return 0
    try:
        request = json.loads(raw)
    except ValueError:
        return 0  # Not a valid tool invocation; no command exists to classify.
    command = (request.get('tool_input') or {}).get('command', '')
    if not isinstance(command, str) or not command:
        return 0
    try:
        account_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
        path = account_home / '.keel/resource-commands.json'
        custom = json.loads(path.read_text()) if path.exists() else {}
        if not isinstance(custom, dict) or any(not isinstance(k, str) or not isinstance(v, list)
                                              or any(not isinstance(x, str) for x in v)
                                              for k, v in custom.items()):
            raise ValueError('resource command rules must map command names to lists of verbs')
        kind = classify(command, custom)
    except (ValueError, OSError, TypeError) as error:
        print('Resource guard could not parse command: ' + str(error), file=sys.stderr)
        return 2
    if not kind:
        return 0
    wrapper = shutil.which('with-heavy-lock')
    fallback = account_home / '.local/bin/with-heavy-lock'
    if not wrapper and fallback.is_file():
        wrapper = str(fallback)
    if wrapper:
        reason = ('Heavy command (' + kind + ') requires the shared resource runner. '
                  'Run it through ' + wrapper + '. One job and two test workers are allowed. '
                  'A resource deferral is not a test failure or permission to push to CI.')
    else:
        reason = 'Resource runner is missing. Heavy command refused; install with-heavy-lock first.'
    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse',
                     'permissionDecision': 'deny', 'permissionDecisionReason': reason}}))
    print(reason, file=sys.stderr)
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
