#!/usr/bin/env python3
"""Consolidation check: is this program's progress somewhere durable? Read-only except --record.

Run at every manager wake and before any chip is started, handed off or archived
(references/consolidation.md). Three checks:
  worktrees  every family worktree is clean and pushed, or carries a named reason.
             Family = manifest binding worktrees + worktrees of manifest `repos[].path`
             whose branch names a bound ticket. States: OK, DIRTY, UNPUSHED, DETACHED, MISSING.
  memory     ~/.claude/scripts/memory_link_check.py --gate (links resolve, files indexed, caps).
  claims     a handoff's commit/PR claim checked by git/gh, never by memory:
             --claim <repo-path>:<sha>   exists, on a remote branch, on origin's default branch
             --pr <owner/name>#<n>      state + mergedAt from gh

Usage:
  consolidation_check.py [--program SLUG] [--worktree PATH]... [--reason PATH=TEXT]...
                         [--claim REPO:SHA]... [--pr OWNER/NAME#N]... [--no-memory]
                         [--record STATE.md] [--strict]
Prints one JSON object. --record appends a `## Consolidation` block to the state file.
--strict exits 1 when anything is owed (a DIRTY/UNPUSHED/DETACHED worktree with no reason,
a failing memory gate, or a claim git/gh does not confirm).
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys

PROGRAMS = os.environ.get("S2C_PROGRAMS") or os.path.expanduser("~/.claude/orchestrator/programs")
MEMORY_CHECK = os.environ.get("S2C_MEMORY_CHECK") or os.path.expanduser("~/.claude/scripts/memory_link_check.py")


def git(path, *args):
    r = subprocess.run(["git", "-C", path, *args], capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def family_worktrees(slug):
    try:
        with open(os.path.join(PROGRAMS, f"{slug}.json"), encoding="utf-8") as f:
            m = json.load(f)
    except (OSError, ValueError) as exc:
        return [], f"manifest unreadable: {exc}"
    paths, tickets = [], set()
    for b in m.get("bindings") or []:
        if b.get("worktree"):
            paths.append(os.path.expanduser(b["worktree"]))
        if b.get("ticket"):
            tickets.add(b["ticket"].lower())
    for r in m.get("repos") or []:
        root = os.path.expanduser(r.get("path") or "")
        if not tickets or not os.path.isdir(root):
            continue
        rc, out = git(root, "worktree", "list", "--porcelain")
        wt = None
        for line in out.splitlines() if rc == 0 else []:
            if line.startswith("worktree "):
                wt = line[9:]
            elif line.startswith("branch ") and wt:
                br = line[7:].lower()
                if any(re.search(rf"(?<![0-9a-z]){re.escape(t)}(?![0-9])", br) for t in tickets):
                    paths.append(wt)
    return sorted(dict.fromkeys(paths)), None


def worktree_state(path):
    if not os.path.isdir(path):
        return dict(path=path, state="MISSING")
    rc, top = git(path, "rev-parse", "--show-toplevel")
    if rc:
        return dict(path=path, state="MISSING", note="not a git worktree")
    _, porcelain = git(path, "status", "--porcelain")
    dirty = len([x for x in porcelain.splitlines() if x.strip()])
    rc, branch = git(path, "symbolic-ref", "--quiet", "--short", "HEAD")
    if rc:
        _, head = git(path, "rev-parse", "--short", "HEAD")
        return dict(path=path, state="DETACHED", head=head, dirty=dirty)
    rc, n = git(path, "rev-list", "--count", "@{u}..HEAD")
    if rc:  # no upstream: count commits no remote branch holds
        rc, n = git(path, "rev-list", "--count", "HEAD", "--not", "--remotes")
    unpushed = int(n) if rc == 0 and n.isdigit() else -1
    state = "DIRTY" if dirty else ("UNPUSHED" if unpushed != 0 else "OK")
    return dict(path=path, state=state, branch=branch, dirty=dirty, unpushed=unpushed)


def check_claim(spec):
    repo, _, sha = spec.rpartition(":")
    repo = os.path.expanduser(repo)
    out = dict(claim=spec, exists=False, on_remote=False, on_default=False)
    if git(repo, "cat-file", "-e", f"{sha}^{{commit}}")[0]:
        return out | dict(verdict="UNCONFIRMED", note="commit not in this repo")
    out["exists"] = True
    _, remotes = git(repo, "branch", "-r", "--contains", sha)
    out["on_remote"] = bool(remotes.strip())
    rc, default = git(repo, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    for ref in ([default] if rc == 0 and default else []) + ["origin/main", "origin/master"]:
        if git(repo, "rev-parse", "--verify", "--quiet", ref)[0] == 0:
            out["on_default"] = git(repo, "merge-base", "--is-ancestor", sha, ref)[0] == 0
            out["default_ref"] = ref
            break
    out["verdict"] = "CONFIRMED" if out["on_remote"] else "UNCONFIRMED"
    return out


def check_pr(spec):
    m = re.fullmatch(r"([\w.-]+/[\w.-]+)#(\d+)", spec)
    if not m:
        return dict(claim=spec, verdict="UNCONFIRMED", note="expected owner/name#N")
    r = subprocess.run(["gh", "pr", "view", m.group(2), "-R", m.group(1), "--json", "state,mergedAt,headRefOid"],
                       capture_output=True, text=True)
    if r.returncode:
        return dict(claim=spec, verdict="UNCONFIRMED", note=r.stderr.strip()[:200])
    return dict(claim=spec, verdict="CONFIRMED", **json.loads(r.stdout))


def memory_gate():
    if not os.path.exists(MEMORY_CHECK):
        return dict(state="NOT-RUN", note=f"{MEMORY_CHECK} missing")
    r = subprocess.run([sys.executable, MEMORY_CHECK, "--gate", "--summary"], capture_output=True, text=True)
    if r.returncode not in (0, 1):
        return dict(state="NOT-RUN", note=r.stderr.strip()[-200:])
    reasons = [x[len("memory-gate: "):] for x in r.stderr.splitlines() if x.startswith("memory-gate: ")]
    return dict(state="OK" if r.returncode == 0 else "FAIL", reasons=reasons)


def owed(report):
    items = [w for w in report["worktrees"] if w["state"] in ("DIRTY", "UNPUSHED", "DETACHED") and not w.get("reason")]
    if report["memory"]["state"] == "FAIL":
        items.append(report["memory"])
    items += [c for c in report["claims"] if c["verdict"] != "CONFIRMED"]
    return items


def record(path, report):
    now = report["at"]
    lines = [f"## Consolidation {now}"]
    for w in report["worktrees"]:
        extra = f" reason: {w['reason']}" if w.get("reason") else ""
        detail = f" dirty={w.get('dirty', 0)} unpushed={w.get('unpushed', 0)}" if w["state"] != "MISSING" else ""
        lines.append(f"- worktree {w['state']} {w['path']} {w.get('branch', w.get('head', ''))}{detail}{extra}".rstrip())
    mem = report["memory"]
    lines.append(f"- memory {mem['state']}" + (f": {'; '.join(mem.get('reasons') or [])}" if mem.get("reasons") else ""))
    for c in report["claims"]:
        lines.append(f"- claim {c['verdict']} {c['claim']}")
    lines.append(f"Consolidation: {'OK' if not report['owed'] else 'OWED'} ({report['owed']} owed)")
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n" + "\n".join(lines) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--program")
    ap.add_argument("--worktree", action="append", default=[])
    ap.add_argument("--reason", action="append", default=[], help="PATH=TEXT: why this worktree may stay unpushed")
    ap.add_argument("--claim", action="append", default=[])
    ap.add_argument("--pr", action="append", default=[])
    ap.add_argument("--no-memory", action="store_true")
    ap.add_argument("--record")
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args(argv)
    paths, err = (family_worktrees(a.program) if a.program else ([], None))
    paths = sorted(dict.fromkeys(paths + [os.path.expanduser(p) for p in a.worktree]))
    reasons = dict(r.split("=", 1) for r in a.reason if "=" in r)
    reasons = {os.path.realpath(os.path.expanduser(k)): v for k, v in reasons.items()}
    wts = []
    for p in paths:
        w = worktree_state(p)
        if os.path.realpath(p) in reasons:
            w["reason"] = reasons[os.path.realpath(p)]
        wts.append(w)
    report = dict(at=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), program=a.program,
                  manifest_error=err, worktrees=wts,
                  memory=dict(state="NOT-RUN", note="--no-memory") if a.no_memory else memory_gate(),
                  claims=[check_claim(c) for c in a.claim] + [check_pr(p) for p in a.pr])
    report["owed"] = len(owed(report))
    if a.record:
        record(a.record, report)
    print(json.dumps(report, indent=1))
    return 1 if a.strict and report["owed"] else 0


if __name__ == "__main__":
    sys.exit(main())
