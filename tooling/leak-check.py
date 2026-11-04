#!/usr/bin/env python3
"""leak-check.py - keep private facts out of this public repo.

keel is public (AGENTS.md "Public and marker-free"). This scans text for what must never land here:
  - email addresses (placeholder domains such as example.com are allowed),
  - absolute home paths (/Users/<name>/, /home/<name>/) unless <name> is a placeholder like `x` or `dev`,
  - credential formats (Anthropic/OpenAI `sk-` keys, AWS access keys, GitHub tokens, Slack tokens, JWTs,
    private-key blocks),
  - every regex in the machine's PRIVATE denylist: ticket prefixes, customer and org names.

The denylist lives outside the repo, because a list of private names committed here would itself be the
leak. Default path: ~/.claude/scripts/keel-leak-denylist.txt (override with KEEL_LEAK_DENYLIST). One
case-insensitive regex per line; a line starting with `#` is a comment. A missing denylist is reported on every run: the
generic checks still run, and the receipt says the private ones did not.

Modes:
  leak-check.py --staged        added lines of the staged diff (the pre-commit hook)
  leak-check.py --all           every tracked file at its working-tree state (an audit)
  leak-check.py FILE...         the named files

A line carrying the marker `leak-check: allow` is skipped (for a deliberate example). Exit 0 clean, 1 hits,
2 usage or git error.
"""
import os
import re
import subprocess
import sys

ALLOW_MARK = "leak-check: allow"
PLACEHOLDER_USERS = {"x", "r", "dev", "me", "you", "user", "username", "name", "someone", "example",
                     "runner", "alice", "bob", "<name>", "<user>", "$user", "${user}"}
PLACEHOLDER_EMAIL = re.compile(
    r"@(?:[\w.-]+\.)?(?:example\.(?:com|org|net)|[\w-]+\.(?:invalid|test|example|localhost))$"
    r"|^noreply@anthropic\.com$|@users\.noreply\.github\.com$|^git@github\.com$", re.I)
EMAIL = re.compile(r"(?<![\w.%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b")
HOME = re.compile(r"/(?:Users|home)/([^/\s`'\"()<>]+)/")
SECRETS = [
    ("anthropic or openai key", re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}")),
    ("aws access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})")),
    ("slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("private key", re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----")),
]


def denylist_path():
    return os.environ.get("KEEL_LEAK_DENYLIST") or os.path.expanduser("~/.claude/scripts/keel-leak-denylist.txt")


def load_denylist(path):
    """-> list of compiled regexes, or None when the file is absent. A bad regex is a usage error."""
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return None
    out = []
    for raw in lines:
        line = raw.strip()
        if line and not line.startswith("#"):
            out.append(re.compile(line, re.I))
    return out


def scan_line(text, private):
    """-> list of (kind, match) for one line."""
    if ALLOW_MARK in text:
        return []
    hits = []
    for m in EMAIL.finditer(text):
        if not PLACEHOLDER_EMAIL.search(m.group(0)):
            hits.append(("email", m.group(0)))
    for m in HOME.finditer(text):
        if m.group(1).lower() not in PLACEHOLDER_USERS:
            hits.append(("home path", m.group(0)))
    for kind, rx in SECRETS:
        hits += [(kind, m.group(0)[:12] + "...") for m in rx.finditer(text)]
    for rx in private or []:
        hits += [("private denylist", m.group(0)) for m in rx.finditer(text)]
    return hits


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def staged_lines():
    """(path, line_no, text) for every ADDED line in the staged diff."""
    diff = git("diff", "--cached", "--no-color", "--no-ext-diff", "-U0", "--diff-filter=ACMR")
    path, num = None, 0
    for row in diff.splitlines():
        if row.startswith("+++ "):
            path = row[6:] if row.startswith("+++ b/") else None
        elif row.startswith("@@"):
            m = re.search(r"\+(\d+)", row)
            num = int(m.group(1)) if m else 0
        elif row.startswith("+") and path:
            yield path, num, row[1:]
            num += 1


def file_lines(paths):
    for path in paths:
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                for num, text in enumerate(fh, 1):
                    yield path, num, text.rstrip("\n")
        except (OSError, IsADirectoryError):
            continue


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0 if argv else 2
    dpath = denylist_path()
    try:
        private = load_denylist(dpath)
    except re.error as exc:
        print(f"leak-check: bad regex in {dpath}: {exc}", file=sys.stderr)
        return 2
    try:
        if argv[0] == "--staged":
            rows, scope = staged_lines(), "staged added lines"
        elif argv[0] == "--all":
            tracked = [p for p in git("ls-files", "-z").split("\0") if p and not os.path.islink(p)]
            rows, scope = file_lines(tracked), f"{len(tracked)} tracked files"
        else:
            rows, scope = file_lines(argv), f"{len(argv)} named files"
        found, scanned = [], 0
        for path, num, text in rows:
            scanned += 1
            found += [(path, num, kind, hit) for kind, hit in scan_line(text, private)]
    except subprocess.CalledProcessError as exc:
        print(f"leak-check: git failed: {(exc.stderr or '').strip()}", file=sys.stderr)
        return 2
    receipt = f"leak-check: scanned {scanned} lines ({scope}); private denylist: " + (
        f"{len(private)} patterns from {dpath}" if private is not None else f"NOT FOUND at {dpath}, generic checks only")
    for path, num, kind, hit in found:
        print(f"{path}:{num}: {kind}: {hit}")
    print(receipt, file=sys.stderr)
    if found:
        print(f"leak-check: {len(found)} hit(s). Replace with generic wording, a placeholder or a relative path; "
              f"for a deliberate example add `{ALLOW_MARK}` to that line.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
