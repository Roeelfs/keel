#!/usr/bin/env python3
"""serialize-heavy-ops — PreToolUse(Bash) guard: heavy ops must acquire a slot.

THE PROBLEM: when several agent sessions run in parallel (one per worktree), each
happily kicks off a full test suite, build, or `cdk synth` at the same time. N
concurrent heavy ops exhaust RAM -> macOS "Your system has run out of application
memory" kills processes. Measured 2026-09-04 on a 24 GB box with 16 live sessions:
8 concurrent cdk/vitest processes at 0.44-1.43 GB each.

THE FIX: `with-heavy-lock` holds one of KEEL_HEAVY_SLOTS (default 3) machine-global
slots for the command's whole lifetime; beyond that, heavy ops QUEUE and then run
locally. A hook is only a GATE -- it runs before the command and exits, so it cannot
hold a slot; its single job is to ENFORCE that heavy ops go through the wrapper.

WHY PYTHON, NOT grep: the shell version matched with `grep -Eq`, which tests
input LINE BY LINE, so the `^` command-position anchor also matched inside HEREDOC
BODIES. Writing a runbook whose text merely mentions `pnpm install` was DENIED --
56 of 85 fires over a 4000-call real-transcript corpus were this false positive.
A guard that fires on the negative set is worse than no guard, so heredoc bodies
are stripped before matching.

FAIL-OPEN: any parse error, missing wrapper, or unexpected exception -> exit 0.
Deny == exit 2 (Claude Code blocks the call; stderr is shown to the model).
"""
import json
import os
import re
import shutil
import sys

# Command position: line start, a shell separator, OR just inside a `-c` / `eval`
# quote -- `bash -c 'pnpm test'` genuinely runs the op. Scoped to those prefixes on
# purpose: treating ANY quote as a command position would flag `echo "pnpm test"`.
CMD_POS = r"(?:^|[;&|(]|(?:-l?c|eval)\s+['\"])\s*"
PM_PREFIX = r"(?:(?:npx|pnpm|npm|yarn|bunx)\s+(?:exec\s+|run\s+|dlx\s+)?)?"
# Flags (and one value each) permitted between the package manager and its
# subcommand, so `pnpm --filter @acme/backend build` is caught. Deliberately only
# flag-shaped tokens, never arbitrary words, to keep the negative set clean.
FLAGS = r"(?:\s+-{1,2}\S+(?:\s+[^-]\S*)?)*"
# Terminator after a heavy subcommand. Quotes/backtick count: `bash -c 'pnpm test'`
# really runs the op, and only the closing quote separated it from end-of-match.
# They are terminators, never openers, so `echo "pnpm test"` is still allowed --
# it has no command position before `pnpm`.
TERM = r"(?:[\s'\"`]|$)"
# ...and `:` too, for script names like `pnpm test:figma-site`.
TERMC = r"(?:[\s:'\"`]|$)"

HEAVY = [
    # cdk first: the largest measured consumer, and the shell version missed it.
    ("cdk", CMD_POS + PM_PREFIX + r"cdk\s+(?:synth|deploy|diff|watch)" + TERM),
    ("unit-tests", CMD_POS + PM_PREFIX + r"(?:vitest|jest)" + TERM),
    ("test-script", CMD_POS + r"(?:pnpm|npm|yarn)" + FLAGS + r"(?:\s+run)?" + FLAGS + r"\s+test" + TERMC),
    ("next-build", CMD_POS + r"(?:(?:npx|pnpm|npm|yarn|turbo)\s+(?:exec\s+|run\s+)?)?next\s+build" + TERM),
    ("build", CMD_POS + r"(?:pnpm|npm|yarn|turbo)" + FLAGS + r"(?:\s+run)?" + FLAGS + r"\s+build" + TERMC),
    ("turbo-build", CMD_POS + r"turbo\s+(?:run\s+)?[\w-]*build"),
    ("install", CMD_POS + r"(?:pnpm\s+(?:install|i)|npm\s+(?:install|ci)|yarn(?:\s+install)?)" + TERM),
]

LOCK_AWARE = re.compile(r"(?:^|[\s;&|(/])with-heavy-lock(?:\s|$)")
# `<<` / `<<-`, delimiter optionally quoted. Backing `<<<` (herestring) is excluded:
# it has no body to strip.
HEREDOC_OP = re.compile(r"<<-?\s*(?![<])(?:'([^']+)'|\"([^\"]+)\"|([A-Za-z_][\w-]*))")


def strip_heredoc_bodies(cmd):
    """Drop heredoc BODY lines, keeping the operator lines (which are real commands).

    A body is data being written, not commands being run -- matching inside one
    blocks documents that merely mention a heavy op.
    """
    lines = cmd.split("\n")
    out = []
    pending = []          # delimiters whose bodies we are still consuming
    for line in lines:
        if pending:
            # Closing delimiter line? (<<- allows leading tabs; be lenient and
            # accept any surrounding whitespace.)
            if line.strip() == pending[0]:
                pending.pop(0)
            continue      # body line (or the terminator) -> never matched
        out.append(line)
        found = [m.group(1) or m.group(2) or m.group(3) for m in HEREDOC_OP.finditer(line)]
        pending.extend(found)
    return "\n".join(out)



def strip_quoted_data(cmd):
    """Blank the inside of quoted strings, EXCEPT `-c` / `eval` shell payloads.

    Quoted text is data, not commands: `grep -E "cynap-sandbox|vitest"` and
    `grep -n "...\\|turbo run build\\|..." .githooks/pre-push` are greps, but the
    `|` inside them reads as a shell pipe -- i.e. a command position -- so they
    were DENIED. Measured: 3 such fires in a 4000-call real-transcript corpus.
    A `-c`/`eval` payload is kept, because `bash -c 'pnpm test'` genuinely runs it.
    """
    out = ""
    i = 0
    n = len(cmd)
    while i < n:
        ch = cmd[i]
        if ch in "'\"":
            close = cmd.find(ch, i + 1)
            if close == -1:                      # unbalanced: leave the rest alone
                out += cmd[i:]
                break
            is_payload = re.search(r"(?:-l?c|eval)\s*$", out) is not None
            if is_payload:
                out += cmd[i:close + 1]
            else:
                out += ch + (" " * (close - i - 1)) + ch
            i = close + 1
            continue
        out += ch
        i += 1
    return out

def main():
    try:
        raw = sys.stdin.read()
    except Exception:
        return 0
    if not raw.strip():
        return 0
    try:
        cmd = (json.loads(raw).get("tool_input") or {}).get("command") or ""
    except Exception:
        return 0
    if not cmd:
        return 0

    # Already lock-aware -> it serializes itself, always allow.
    if LOCK_AWARE.search(cmd):
        return 0

    scan = strip_quoted_data(strip_heredoc_bodies(cmd))

    kind = None
    for name, pat in HEAVY:
        if re.search(pat, scan, re.MULTILINE):
            kind = name
            break
    if not kind:
        return 0

    # Rollout safety: only ENFORCE once the wrapper is installed. Refusing before
    # that would hard-break a machine that has not run install.sh yet.
    if not shutil.which("with-heavy-lock"):
        return 0

    slots = os.environ.get("KEEL_HEAVY_SLOTS", "3")
    sys.stderr.write(
        "🚦 Heavy op (%s) must run under the machine-global heavy-op semaphore so "
        "parallel agent sessions don't exhaust RAM.\n"
        "Up to %s run concurrently; beyond that it QUEUEs (wait-then-run locally), "
        "never refused. Prefix it:\n\n"
        "    with-heavy-lock %s\n\n"
        "Light ops stay parallel and need no wrapper: reads, grep, edits, git/gh, "
        "typecheck, lint.\n" % (kind, slots, cmd)
    )
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)   # fail open, always
