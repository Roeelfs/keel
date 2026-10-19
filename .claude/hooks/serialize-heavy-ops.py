#!/usr/bin/env python3
"""Shared Claude/Codex PreToolUse(Bash) resource admission guard."""
import json
import os
from pathlib import Path, PurePosixPath
import pwd
import re
import shlex
import shutil
import sys

try:
    from heavy_command import (background_required, classify, inspect_words, may_change_cwd,
                                segments as hc_segments, unparsed_heavy_token, unparsed_rule_name,
                                without_prefixes)
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

_HEAVY_LOCK_NAME = 'with-heavy-lock'

# spawn-lane.sh sets this on every headless lane. A rewrite swaps a deny for a queued, backgrounded
# run, which an interactive session can follow up on; a headless lane exits at turn end and would
# lose the queued job, so it keeps the deny. The Codex runtime never rewrites at all.
HEADLESS_LANE_ENV = 'CYNAP_HEADLESS_LANE'


def headless_lane():
    return bool(os.environ.get(HEADLESS_LANE_ENV))

# `heavy_command.segments()` treats a bare `&` as a control operator anywhere it appears,
# which also fires inside plain fd-redirection (`2>&1`, `&>log`) -- the overwhelmingly common
# shape for "run this and keep the log" (`cmd > log 2>&1; echo rc=$? >> log; tail -N log`).
# Mask known-safe redirection forms with EQUAL-LENGTH spaces before scanning for real control
# operators, so character offsets in the masked text still line up with the original string
# and a segment can be sliced back out byte-for-byte. The redirect target must stop at any
# shell metacharacter, not just whitespace -- otherwise `> out.log;` would swallow the `;`
# into the "target" and hide a real chain boundary.
_FD_DUP = re.compile(r'\d*>>?&\d+')
_FD_COMBINED = re.compile(r'&>>?')
_BAREWORD = r'[^\s;&|()<>]+'
_QUOTED_OR_WORD = r'(?:"[^"]*"|\'[^\']*\'|' + _BAREWORD + r')'
_REDIRECT = re.compile(r'\d*(?:>>?|<)\s*' + _QUOTED_OR_WORD)

# `heavy_command.without_prefixes()` skips a leading run of env assignments (`CI=true`) and
# shell keywords (`then`, `do`, `if`, `!`, `exec`, `command`, `time`) before deciding what a
# segment's real command is. The wrapper must be inserted AFTER that same run of prefix
# text, or `CI=true cmd` becomes `with-heavy-lock CI=true cmd` -- which execs a binary
# literally named "CI=true" and fails. This regex mirrors without_prefixes()'s word test
# exactly, applied to raw text so the insertion point lands on real original bytes.
_PREFIX_WORD = re.compile(r'(?:[A-Za-z_][A-Za-z0-9_]*=(?:"[^"]*"|\'[^\']*\'|\S*)'
                          r'|then|do|if|!|exec|command|time)(?:\s+|$)')


def _skip_prefixes(text):
    i = len(text) - len(text.lstrip())  # leading whitespace, prefix-word or not
    while True:
        match = _PREFIX_WORD.match(text, i)
        if not match:
            return i
        i = match.end()


def _mask(pattern, text):
    return pattern.sub(lambda m: ' ' * len(m.group(0)), text)


def _scrub_for_scan(command):
    scrubbed = _mask(_FD_DUP, command)
    scrubbed = _mask(_FD_COMBINED, scrubbed)
    return _mask(_REDIRECT, scrubbed)


def top_level_segments(command):
    """Split `command` into top-level `;`/`&&` segments, as a list of (start, end) byte
    offsets into the ORIGINAL string -- `command[start:end]` reproduces a segment's exact
    original text, whitespace and all, never a reconstruction from parsed tokens.

    Returns None if the command is anything riskier than a plain `;`/`&&` chain: a pipe
    (including `||`), a subshell, a heredoc, a backtick, a bare background `&`, or an
    unbalanced quote. `$(...)` command substitution is tolerated -- its interior is
    skipped over, never split into or mistaken for a top-level operator.
    """
    if '<<' in command or '`' in command:
        return None
    masked = _scrub_for_scan(command)
    i, n = 0, len(masked)
    quote = None
    spans = []
    seg_start = 0
    while i < n:
        c = masked[i]
        if quote:
            if quote == '"' and c == '\\' and i + 1 < n:
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in ('\'', '"'):
            quote = c
            i += 1
            continue
        if c == '\\' and i + 1 < n:
            i += 2
            continue
        if c == '$' and masked[i + 1:i + 2] == '(':
            depth = 1
            j = i + 2
            while j < n and depth > 0:
                if masked[j] == '(':
                    depth += 1
                elif masked[j] == ')':
                    depth -= 1
                j += 1
            i = j
            continue
        if c in '()' or c == '|':
            return None
        if c == '&':
            if masked[i:i + 2] != '&&':
                return None  # a bare background `&` -- not a shape this guard rewrites
            spans.append((seg_start, i))
            seg_start = i + 2
            i += 2
            continue
        if c == ';':
            spans.append((seg_start, i))
            seg_start = i + 1
            i += 1
            continue
        i += 1
    if quote:
        return None
    spans.append((seg_start, n))
    return spans


def chain_is_safe(command):
    """True if `command` is a `;`/`&&` chain with no pipe, subshell, heredoc, or backtick --
    the shape where setting run_in_background on the WHOLE call is safe regardless of how
    many statements it has, since the flag never touches the command text."""
    return top_level_segments(command) is not None


def wrap_heavy_segment(command, rules, cwd, wrapper):
    """If `command` is a safe `;`/`&&` chain (see `chain_is_safe`) with EXACTLY ONE segment
    that classifies as heavy, and that segment does not already invoke the wrapper, return
    the command with the wrapper prefixed onto just that segment -- every other segment,
    separator, and byte of whitespace stays untouched. Else return None.
    """
    spans = top_level_segments(command)
    if not spans:
        return None
    try:
        full_parsed = list(hc_segments(command))
    except ValueError:
        return None
    allow_exempt = not may_change_cwd(command, full_parsed)
    heavy_idx = None
    for idx, (start, end) in enumerate(spans):
        seg_text = command[start:end]
        try:
            words = shlex.split(seg_text)
        except ValueError:
            return None
        real_words = without_prefixes(words)
        if not real_words or PurePosixPath(real_words[0]).name == _HEAVY_LOCK_NAME:
            continue  # empty segment, or already wrapped -- nothing to rewrite here
        if inspect_words(words, rules, cwd, allow_exempt):
            if heavy_idx is not None:
                return None  # more than one heavy segment -- ambiguous, leave it denied
            heavy_idx = idx
    if heavy_idx is None:
        return None
    start, end = spans[heavy_idx]
    seg = command[start:end]
    lead = _skip_prefixes(seg)
    if not seg[lead:].strip():
        return None  # nothing left to wrap after the prefix run -- refuse rather than guess
    new_seg = seg[:lead] + wrapper + ' ' + seg[lead:]
    return command[:start] + new_seg + command[end:]


def valid_rules(value):
    return isinstance(value, dict) and all(isinstance(k, str) and isinstance(v, list)
                                           and all(isinstance(x, str) for x in v)
                                           for k, v in value.items())


def deny(reason):
    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse',
                     'permissionDecision': 'deny', 'permissionDecisionReason': reason}}))
    print(reason, file=sys.stderr)
    return 2


def allow_rewrite(tool_input, new_command, background, note):
    """Rewrite tool_input in place and let the call through instead of denying it.

    `updatedInput` carries the FULL tool_input (every original key, not a partial patch) --
    the documented PreToolUse contract replaces the tool's input wholesale, so dropping a
    key here would silently lose it (e.g. an author-supplied `description` or `timeout`).
    """
    updated = dict(tool_input)
    updated['command'] = new_command
    if background:
        updated['run_in_background'] = True
    print(json.dumps({'hookSpecificOutput': {
        'hookEventName': 'PreToolUse',
        'permissionDecision': 'allow',
        'additionalContext': note,
        'updatedInput': updated,
    }}))
    return 0


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
            needs_background = runtime == 'claude' and 'with-heavy-lock' in background
            if runtime == 'claude' and not headless_lane():
                new_command = wrap_heavy_segment(command, rules, cwd, wrapper)
                if new_command is not None:
                    note = ('Heavy command (' + kind + ') rewritten to run through the shared '
                            'resource runner (' + wrapper + '); it will queue if another heavy '
                            'job is running. Every other statement in the command is untouched.')
                    if needs_background:
                        note += ' Queued to run in background: true, since a queued job can wait minutes.'
                    return allow_rewrite(tool_input, new_command, needs_background, note)
            reason = ('Heavy command (' + kind + ') requires the shared resource runner. '
                      'Run it through ' + wrapper + '. One heavy job runs at a time; the rest queue. '
                      'A resource deferral is not a test failure or permission to push to CI.')
            if needs_background:
                # Said up front, so the retry is not denied a second time for holding the foreground.
                reason += ' A queued job can wait minutes, so set run_in_background: true.'
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
    if chain_is_safe(command) and not headless_lane():
        # run_in_background is a flag on the whole Bash call, not a text edit -- it is safe
        # for any `;`/`&&` chain regardless of how many statements it has. A pipe stays
        # denied above (chain_is_safe returns None), since backgrounding the whole pipeline
        # doesn't fix "piping the slow command's own output into another command".
        note = ('Long-running command (' + slow + ') queued to run in background '
                '(run_in_background: true) automatically; the harness re-invokes you when it exits.')
        return allow_rewrite(tool_input, command, True, note)
    return deny(guidance)


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
