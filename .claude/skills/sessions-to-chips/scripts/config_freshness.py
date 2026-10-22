#!/usr/bin/env python3
"""Which live sessions run on config older than what is on disk, and what refreshes each.

Read-only. Maps every desktop session to its running CLI process (`--resume=<cliSessionId>`),
then compares the process start time with the last change to each config class:

  live     hook registrations + hook scripts, permissions, agents, skill listing.
           Claude Code watches these; nothing to do.
  reread   ~/.claude/CLAUDE.md, output styles, the session repo's AGENTS.md/CLAUDE.md, and
           skill BODIES (a skill invoked before the edit stays frozen in the conversation).
           Fix: a message naming the files to Read again, or the next compaction.
  restart  enabledPlugins / mcpServers / model keys in settings.json, installed plugins, a
           newer CLI build on disk. Only a new CLI process loads them.
           Fix: end the process; the next message resumes it from current disk.

A session with no process is FRESH-ON-RESUME: its next message spawns a CLI from current disk.

  config_freshness.py                       # every non-archived [Manager] session
  config_freshness.py --grep "Apps" --json
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from list_sessions import load_all  # noqa: E402

HOME = os.path.expanduser("~")
CLAUDE = os.path.join(HOME, ".claude")
KEEL_SKILLS = os.path.join(HOME, "code", "keel", ".claude", "skills")
CLI_ROOT = os.path.join(HOME, "Library", "Application Support", "Claude", "claude-code")
RESTART_KEY = re.compile(r'^[+-].*("enabledPlugins"|"mcpServers"|"model"|"effortLevel"|"[\w.-]+@[\w.-]+"\s*:\s*(true|false))')


def sh(*cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def processes():
    """cliSessionId -> {pid, start (epoch), version} for live CLI processes."""
    out = {}
    for line in sh("ps", "-Ao", "pid=,lstart=,command=").splitlines():
        m = re.match(r"\s*(\d+)\s+(\w{3} \w{3}\s+\d+ [\d:]+ \d{4})\s+(.*)$", line)
        if not m or "MacOS/claude --output" not in m.group(3) or "disclaimer" in m.group(3):
            continue
        rid = re.search(r"--resume=([0-9a-f-]{36})", m.group(3))
        ver = re.search(r"claude-code/([\d.]+)/", m.group(3))
        if rid:
            start = datetime.strptime(" ".join(m.group(2).split()), "%a %b %d %H:%M:%S %Y").timestamp()
            out[rid.group(1)] = {"pid": int(m.group(1)), "start": start,
                                 "version": ver.group(1) if ver else "?"}
    return out


def newest_cli():
    vers = [os.path.basename(p) for p in glob.glob(os.path.join(CLI_ROOT, "[0-9]*"))]
    return max(vers, key=lambda v: tuple(int(x) for x in v.split(".")), default="?")


def git_changes(repo, since, paths, rev="HEAD"):
    """[(sha, epoch, subject)] for commits touching paths after `since`."""
    fmt = sh("git", "-C", repo, "log", rev, f"--since=@{int(since)}", "--format=%h %ct %s", "--", *paths)
    return [(l.split(" ", 2)[0], int(l.split(" ", 2)[1]), l.split(" ", 2)[2])
            for l in fmt.splitlines() if l.count(" ") >= 2]


def settings_restart_changes(since):
    hits = []
    for sha, ts, subj in git_changes(CLAUDE, since, ["settings.json"]):
        diff = sh("git", "-C", CLAUDE, "show", "--format=", sha, "--", "settings.json")
        if any(RESTART_KEY.match(l) for l in diff.splitlines()):
            hits.append(f"{sha} {subj}")
    return hits


def mtime_after(path, since):
    return os.path.exists(path) and os.path.getmtime(path) > since


def repo_root(cwd):
    return sh("git", "-C", cwd, "rev-parse", "--path-format=absolute", "--git-common-dir").strip().removesuffix("/.git") if cwd and os.path.isdir(cwd) else ""


def assess(row, proc, cli_newest):
    if not proc:
        return {"verdict": "FRESH-ON-RESUME", "reread": [], "restart": [], "fix": "none: next message starts a CLI from current disk"}
    t = proc["start"]
    reread = [f"~/.claude {c[0]} {c[2]}" for c in git_changes(CLAUDE, t, ["CLAUDE.md", "output-styles"])]
    reread += [f"keel {c[0]} {c[2]}" for c in git_changes(os.path.dirname(os.path.dirname(KEEL_SKILLS)), t, [".claude/skills"])]
    root = repo_root(row["worktree"])
    if root:
        reread += [f"repo {c[0]} {c[2]}" for c in git_changes(root, t, ["AGENTS.md", "CLAUDE.md"], rev="origin/main")]
    restart = settings_restart_changes(t)
    if mtime_after(os.path.join(CLAUDE, "plugins", "installed_plugins.json"), t):
        restart.append("plugins/installed_plugins.json changed")
    if cli_newest != "?" and proc["version"] != cli_newest:
        restart.append(f"CLI {proc['version']} running, {cli_newest} on disk")
    verdict = "STALE-RESTART" if restart else "STALE-REREAD" if reread else "FRESH"
    fix = {"STALE-RESTART": "end the CLI process when idle; resume loads current disk (then re-read files)",
           "STALE-REREAD": "send a refresh message naming the changed files to Read",
           "FRESH": "none"}[verdict]
    return {"verdict": verdict, "reread": reread, "restart": restart, "fix": fix}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--grep", default="[Manager]", help="title substring (default: [Manager])")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    procs, cli_newest = processes(), newest_cli()
    rows = [r for r in load_all() if not r["archived"] and a.grep.lower() in r["title"].lower()]
    newest = {}
    for r in rows:
        if r["title"] not in newest or (r["lastActivityAt"] or "") > (newest[r["title"]]["lastActivityAt"] or ""):
            newest[r["title"]] = r
    report = []
    for r in sorted(rows, key=lambda r: r["title"]):
        p = procs.get(r["cli"])
        row = {"title": r["title"], "sessionId": r["sessionId"], "account": r["account"][:8],
               "pid": p and p["pid"], "version": p and p["version"],
               "started": p and datetime.fromtimestamp(p["start"]).isoformat(timespec="seconds"),
               **assess(r, p, cli_newest)}
        if newest[r["title"]] is not r:
            row.update(verdict="OLDER-TWIN", fix="a newer live session has this title: hygiene candidate, not a refresh target")
        report.append(row)
    if a.json:
        print(json.dumps({"cliNewest": cli_newest, "sessions": report}, indent=2))
        return
    print(f"CLI on disk: {cli_newest}")
    for s in report:
        print(f"{s['verdict']:16} {s['title'][:48]:48} pid={s['pid']} v={s['version']} start={s['started']}")
        for x in s["restart"]:
            print(f"    restart: {x}")
        for x in s["reread"][:8]:
            print(f"    reread:  {x}")
        if len(s["reread"]) > 8:
            print(f"    reread:  +{len(s['reread']) - 8} more")


if __name__ == "__main__":
    main()
