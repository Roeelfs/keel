#!/usr/bin/env python3
"""Shared Claude/Codex PreToolUse(Bash) resource admission guard."""
import json
import os
from pathlib import Path
import pwd
import shutil
import sys

try:
    from heavy_command import background_required, classify, unparsed_heavy_token, unparsed_rule_name
except ImportError:
    print('Resource guard installation is incomplete; command refused. Reinstall resource hooks.', file=sys.stderr)
    raise SystemExit(2)

# The registration names its runtime; the request payload is never used to guess it. The
# installer registers `--runtime claude` only. `--runtime codex` is opt-in: Codex trusts a hook
# by its exact command, so adding the argument needs a manual re-trust in Codex `/hooks`.
BACKGROUND_GUIDANCE = {
    'claude': ('Long-running command ({name}) must not hold the foreground: '
               're-run with run_in_background: true; the harness re-invokes you when it exits.'),
    'codex': ('Long-running command ({name}) outlives one exec yield and keeps running as a cell. '
              'Keep reading the running cell until it exits; never start a second copy.'),
}


def valid_rules(value):
    return isinstance(value, dict) and all(isinstance(k, str) and isinstance(v, list)
                                           and all(isinstance(x, str) for x in v)
                                           for k, v in value.items())


def deny(reason):
    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse',
                     'permissionDecision': 'deny', 'permissionDecisionReason': reason}}))
    print(reason, file=sys.stderr)
    return 2


def main(arguments):
    runtime = arguments[1] if len(arguments) == 2 and arguments[0] == '--runtime' else None
    if arguments and runtime not in BACKGROUND_GUIDANCE:
        print('Resource guard registration is invalid; command refused. Reinstall resource hooks. '
              'usage: serialize-heavy-ops.py [--runtime claude|codex]', file=sys.stderr)
        return 2
    raw = sys.stdin.read()
    if not raw.strip():
        return 0
    try:
        request = json.loads(raw)
    except ValueError:
        return 0  # Not a valid tool invocation; no command exists to classify.
    tool_input = request.get('tool_input') or {}
    command = tool_input.get('command', '')
    if not isinstance(command, str) or not command:
        return 0
    cwd = request.get('cwd')
    cwd = cwd if isinstance(cwd, str) and cwd else None
    try:
        account_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
        path = account_home / '.keel/resource-commands.json'
        custom = json.loads(path.read_text()) if path.exists() else {}
        if not isinstance(custom, dict):
            raise ValueError('resource command rules must map command names to lists of verbs')
        background = custom.get('background_required', {})
        rules = {k: v for k, v in custom.items() if k != 'background_required'}
        if not valid_rules(rules):
            raise ValueError('resource command rules must map command names to lists of verbs')
        if not valid_rules(background):
            raise ValueError('background_required must map command names to lists of verbs')
    except (ValueError, OSError, TypeError) as error:
        print('Resource guard could not read resource command rules: ' + str(error), file=sys.stderr)
        return 2
    try:
        kind = classify(command, rules, cwd)
        slow = background_required(command, background) if runtime and not kind else None
    except ValueError as error:
        # Unsplittable shell text is usually a quoting slip in a light command, so it runs
        # unless a heavy token appears anywhere in it.
        token = unparsed_heavy_token(command, rules)
        if token:
            return deny('Resource guard could not parse this command (' + str(error) + ') and it '
                        'names heavy command ' + token + '. Fix the shell quoting so it can be classified.')
        kind = None
        slow = unparsed_rule_name(command, background) if runtime else None
    if kind:
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
        return deny(reason)
    if not slow:
        return 0
    guidance = BACKGROUND_GUIDANCE[runtime].format(name=slow)
    if runtime == 'codex':
        # A Codex payload has no background switch to retry with, so a deny could never be
        # satisfied; the command runs and the guidance rides along with it.
        print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse',
                                                 'additionalContext': guidance}}))
        return 0
    if tool_input.get('run_in_background') is True:
        return 0
    return deny(guidance)


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
