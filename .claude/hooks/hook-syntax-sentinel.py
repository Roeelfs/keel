#!/usr/bin/env python3
"""PostToolUse(Edit|Write): a hook file that no longer parses must SAY SO, immediately.

WHY THIS EXISTS: `_run.sh` fails open, so a broken guard no longer takes the machine
down — it goes DARK instead, silently disabling every check it owns. That trades an
outage for a coverage hole, which is the right trade only if the hole is loud. It was
not: `_run.sh`'s own header claimed the risk was "covered at commit time by
replay-hook.sh syntax", but NOTHING invokes that script — it is a manual command, and a
gate nobody runs is not a gate.

WHY AT EDIT TIME rather than commit time: the break is live from the very next tool call,
not from the commit. Checking here closes the loop at its tightest point — the same turn
that broke it, while the fix is still one edit away.

CANNOT BLOCK: PostToolUse runs after the write, so this only reports. That is deliberate;
the blast radius of another blocking guard is not worth it for an advisory check.

Uses compile() rather than py_compile — py_compile writes __pycache__ next to the source,
which got committed once already this week.
"""
import sys
import json
import os
import re
import hashlib
import subprocess

HOOK_LINK_DIR = os.path.expanduser("~/.claude/hooks")
HOOK_DIR = os.path.realpath(HOOK_LINK_DIR)


def wired_hook(real):
    """True for a file in the machine-global hook dir, or one wired there by symlink (its body lives in a
    shared clone, e.g. keel's .claude/hooks): realpath alone would miss the symlinked ones."""
    if os.path.dirname(real) == HOOK_DIR:
        return True
    return os.path.realpath(os.path.join(HOOK_LINK_DIR, os.path.basename(real))) == real

# --- hash-pin staleness (added 2026-08-25) ---------------------------------------
# A guard gated on a hash pin goes DARK the instant its subject is edited: the wrapper
# is `if <hash matches>; then exec <script>; fi; exit 0`, so a drifted pin is a silent
# no-op that logs nothing and errors nothing. Measured this day: codex-session-meter.py
# was pinned at 55f301b3...ced1aa while hashing b7a41ecc...0ce29ab. A dark hook and a
# hook with nothing to say produce identical output, so only a mechanical check finds it.
#
# PAIRING IS EXACT, NOT NEAREST-HASH. One command line can carry several pins for
# several files (the PreToolUse group here pins two). Nearest-hash-wins misattributes
# a drift to the wrong script, which is worse than missing it. So follow the shell's own
# chain: NAME="$HOME/.claude/hooks/<file>" -> ACTUAL=$(shasum -a 256 "$NAME") -> [ "$ACTUAL" = '<hash>' ]
GATING_CONFIGS = [os.path.expanduser("~/.codex/hooks.json")]
RE_SRC = re.compile(r'(\w+)="\$HOME/\.claude/hooks/([^"]+)"')
RE_ACTUAL = re.compile(r'(\w+)=\$\(shasum -a 256 "\$(\w+)"')
RE_CMP = re.compile(r'\[ "\$(\w+)" = \'([0-9a-f]{64})\' \]')


def _sha256(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def pinned_hashes(text):
    """basename -> pinned hash, resolved through the shell's own variable chain."""
    src = {v: b for v, b in RE_SRC.findall(text)}           # var  -> basename
    actual = {a: v for a, v in RE_ACTUAL.findall(text)}     # avar -> var
    out = {}
    for avar, h in RE_CMP.findall(text):
        base = src.get(actual.get(avar, ""), "")
        if base:
            out.setdefault(base, set()).add(h)
    return out


def _commands(cfg):
    """Every hook command string in a gating config.

    Parse the JSON and read the DECODED command. Scanning the raw file text fails: inside
    JSON the shell string is escaped (`=\\"$HOME/...\\"`), so a regex written against real
    shell syntax matches nothing and the check silently passes. Caught by the live fixture
    2026-08-25 — the first version of this returned a false negative on a known drift.
    """
    try:
        with open(cfg, "r", errors="replace") as f:
            conf = json.load(f)
    except (OSError, ValueError):
        return []
    out = []
    for groups in (conf.get("hooks") or {}).values():
        for g in groups or []:
            for h in g.get("hooks", []) or []:
                c = h.get("command")
                if isinstance(c, str):
                    out.append(c)
    return out


def stale_pin(basename):
    """(config_path, pinned, live) for the first drifted pin naming `basename`, else None."""
    live = _sha256(os.path.join(HOOK_LINK_DIR, basename))
    if not live:
        return None
    for cfg in GATING_CONFIGS:
        for cmd in _commands(cfg):
            for h in pinned_hashes(cmd).get(basename, ()):
                if h != live:
                    return cfg, h, live
    return None

# An apostrophe anywhere inside `python3 -c '...'` terminates the shell string and turns
# the hook into a syntax error. bash -n catches it, but only AFTER it is written; a long
# embedded block is the standing hazard, so flag it even while it still parses.
EMBEDDED_PY = re.compile(r"python3?\s+-c\s+'")
MAX_EMBEDDED_LINES = 40


def embedded_python_span(src):
    """Longest run of lines inside a `python3 -c '` block. 0 if there is none."""
    longest = 0
    run = 0
    inside = False
    for line in src.splitlines():
        if not inside:
            if EMBEDDED_PY.search(line):
                inside, run = True, 1
        else:
            run += 1
            if "'" in line:
                inside = False
                longest = max(longest, run)
    return max(longest, run if inside else 0)


def check(path):
    """Return (fatal, message) — fatal means the file will not parse."""
    try:
        with open(path, "r", errors="replace") as f:
            src = f.read()
    except OSError:
        # Absent or unreadable is NOT a parse failure — a deleted or never-written file
        # has no broken guard to report, and saying so is pure noise.
        return False, ""

    if path.endswith(".py"):
        try:
            compile(src, path, "exec")
        except SyntaxError as e:
            return True, "SyntaxError line {}: {}".format(e.lineno, e.msg)
        return False, ""

    if path.endswith(".sh"):
        try:
            r = subprocess.run(["bash", "-n", path], capture_output=True,
                               text=True, timeout=10)
        except (OSError, subprocess.SubprocessError) as e:
            return False, "could not run bash -n: " + str(e)
        if r.returncode != 0:
            return True, (r.stderr or r.stdout or "bash -n failed").strip()[:400]
        n = embedded_python_span(src)
        if n > MAX_EMBEDDED_LINES:
            return False, ("parses now, but carries a {}-line embedded `python3 -c '...'` "
                           "block. One apostrophe in a comment inside it silently darkens "
                           "this hook. Move the logic to a real .py behind a two-line "
                           "shim.".format(n))
    return False, ""


def main() -> int:
    try:
        d = json.load(sys.stdin)
    except Exception:
        return 0

    ti = d.get("tool_input")
    if not isinstance(ti, dict):
        return 0
    fp = ti.get("file_path")
    if not isinstance(fp, str) or not fp:
        return 0
    if not (fp.endswith(".sh") or fp.endswith(".py")):
        return 0

    # A NUL byte in the path raises ValueError, not OSError — catch broadly. Every
    # failure here must leave no stdout: this hook reports, it never obstructs.
    try:
        real = os.path.realpath(fp)
        # Only guard hooks the machine runs: the hook dir itself, or a file it links to.
        if not wired_hook(real) or not os.path.isfile(real):
            return 0
    except (OSError, ValueError):
        return 0

    try:
        fatal, msg = check(real)
    except Exception:
        fatal, msg = False, ""

    name = os.path.basename(real)

    # A drifted pin is reported even when the file parses fine — parsing is not the
    # failure mode here. This runs AFTER the syntax check so a file that is both broken
    # and unpinned still leads with the parse error.
    pin_msg = ""
    try:
        drift = stale_pin(name)
    except Exception:
        drift = None
    if drift:
        cfg, pinned, live = drift
        pin_msg = (
            "[hash-pin] " + name + " is HASH-PINNED in " + cfg + " and the pin no longer "
            "matches, so that hook is now DARK — its wrapper is `if <hash>; then exec; fi; "
            "exit 0`, which fails silently and logs nothing.\n"
            "  pinned: " + pinned + "\n"
            "  actual: " + live + "\n"
            "  Re-pin in the SAME change that edited the file, never as a follow-up:\n"
            "    shasum -a 256 ~/.claude/hooks/" + name + " | awk '{print $1}'\n"
            "  then replace the old literal in " + cfg + ". NOTE: the generalized installer "
            "does not yet cover every pinned hook, so a re-pin may be manual — check before "
            "assuming a script did it."
        )

    if not msg and not pin_msg:
        return 0
    if fatal:
        text = (
            "[hook-syntax] " + name + " NO LONGER PARSES and is DARK as of this edit — "
            "every check it owns is silently disabled right now, and _run.sh will let "
            "calls through unguarded until it is fixed. Fix it before doing anything "
            "else.\n" + msg
        )
    elif msg:
        text = "[hook-syntax] " + name + ": " + msg
    else:
        text = ""

    if pin_msg:
        text = (text + "\n" + pin_msg) if text else pin_msg

    print(json.dumps({
        "systemMessage": text,
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": text,
        },
    }))
    return 0


sys.exit(main())
