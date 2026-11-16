#!/usr/bin/env python3
"""Find state an account switch leaves behind. Sends nothing and edits no app-owned file; the only
write is `git fetch origin <main>`, which updates remote-tracking refs.

Owns "state left pointing at the other account". Ancestry walks the FULL store, so a child of a
quiet manager still has an owner; --since windows only which findings are reported.

  1. Worktrees of sessions active since --since: commits whose CONTENT is not on main (landed():
     merged-PR head, merge-tree, then cherry; never ancestry alone), commits not on the remote
     branch (informational), untracked and modified files, gutted checkouts (mass deletions).
  2. Story maps and wrap-up notes written since --since that no handoff file names.
  3. Scheduled tasks left on, or aimed at, another account (stranded_schedules).
  4. PR Auto-fix bindings held only by another account's session (stranded_bindings).
Every row carries ownerSessionId, its program root (program_family.root_manager over --roots);
mine_report routes it into that program's catch-up, and an owner-less row becomes a founder line.

Usage:
  python3 -I handoff_sweep.py --account all --since 2026-10-18T20:00 [--here ACCT]
      [--roots <work>/candidates.json] [--handoff-dir ~/.claude/sessions-to-chips/handoff]
  python3 -I handoff_sweep.py --repo <path> --since 2026-10-18T20:00 [--roots ...]
      (one repo: every worktree's HEAD, plus local branches with no worktree whose upstream is
      missing or gone and whose last commit is newer than --since)
"""
import argparse
import datetime
import glob
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import program_family as pf  # noqa: E402

STORE = os.environ.get("S2C_STORE") or os.path.expanduser("~/Library/Application Support/Claude/claude-code-sessions")
S2C = os.path.join((os.environ.get("S2C_CLAUDE_HOME") or os.path.expanduser("~/.claude")), "sessions-to-chips")
GUTTED = 100  # tracked deletions above this mean the checkout itself is broken
MAIN_BRANCHES = ("main", "master")
MERGE_TREE_MIN = (2, 38)
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
FULL_RX = re.compile(rf"local_({UUID})")
BARE_RX = re.compile(rf"(?<![\w-])({UUID})(?![\w-])")
SHORT_RX = re.compile(r"local_([0-9a-f]{8})(?![0-9a-f-])")


def git_rc(cwd, *args):
    r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def git(cwd, *args):
    return git_rc(cwd, *args)[1]


def gh_json(args):
    """`gh <args>` -> parsed JSON, or None when gh fails (the caller says the state is unverified)."""
    try:
        r = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode:
        return None
    try:
        return json.loads(r.stdout)
    except ValueError:
        return None


# ---------- 1. has this branch's content landed on main? ----------

def main_ref(repo):
    """-> (remote ref like "origin/main", short branch "main") or (None, None)."""
    rc, out = git_rc(repo, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    if rc == 0 and out.startswith("refs/remotes/origin/"):
        ref = out[len("refs/remotes/"):]
        return ref, ref.split("/", 1)[1]
    for ref in ("origin/main", "origin/master"):
        if git_rc(repo, "rev-parse", "--verify", "--quiet", f"refs/remotes/{ref}")[0] == 0:
            return ref, ref.split("/", 1)[1]
    return None, None


def merge_tree_ok(cache):
    if "merge_tree" not in cache:
        m = re.search(r"(\d+)\.(\d+)", subprocess.run(["git", "--version"], capture_output=True, text=True).stdout)
        cache["merge_tree"] = bool(m) and (int(m.group(1)), int(m.group(2))) >= MERGE_TREE_MIN
    return cache["merge_tree"]


def landed(repo, ref, prs=(), cache=None):
    """-> {"verdict", "evidence"}. Content, not ancestry: a squash-merged or cherry-picked branch is
    LANDED. Verdicts: LANDED | LANDED (PR #n merged) | UNPUSHED <n> [(conflicts with main)] |
    UNKNOWN (no main ref). A merge-tree conflict is never read as landed (fails toward keeping work).
    prs: the store's prs[] entries for this branch. cache: one dict per run (fetch once per repo)."""
    cache = cache if cache is not None else {}
    main, branch = main_ref(repo)
    if not main:
        return {"verdict": "UNKNOWN (no main ref)", "evidence": ["no origin/HEAD, origin/main or origin/master"]}
    notes = []
    common = git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    fetched = cache.setdefault("fetched", {})
    if common not in fetched:
        fetched[common] = git_rc(repo, "fetch", "origin", branch, "--quiet")[0] == 0
    if not fetched[common]:
        notes.append("main ref stale (fetch failed)")
    head = git(repo, "rev-parse", ref)
    for p in prs:
        if not (p.get("repo") and p.get("prNumber")):
            continue
        info = gh_json(["pr", "view", str(p["prNumber"]), "--repo", p["repo"], "--json", "state,headRefOid"])
        if info and info.get("state") == "MERGED" and info.get("headRefOid") == head:
            return {"verdict": f"LANDED (PR #{p['prNumber']} merged)", "evidence": notes + [f"{ref} is the merged head {head[:12]}"]}
    conflict = False
    if merge_tree_ok(cache):
        rc, out = git_rc(repo, "merge-tree", "--write-tree", main, ref)
        if rc == 0 and out.splitlines()[:1] == [git(repo, "rev-parse", f"{main}^{{tree}}")]:
            return {"verdict": "LANDED", "evidence": notes + [f"merge-tree: {ref} adds nothing to {main}"]}
        conflict = rc == 1
    plus = [ln[2:] for ln in git(repo, "cherry", main, ref).splitlines() if ln.startswith("+ ")]
    if not plus and not conflict:
        return {"verdict": "LANDED", "evidence": notes + [f"cherry: every commit's patch is on {main}"]}
    n = len(plus) or int(git(repo, "rev-list", "--count", f"{main}..{ref}") or 0)
    return {"verdict": f"UNPUSHED {n}" + (" (conflicts with main)" if conflict else ""),
            "evidence": notes + [git(repo, "log", "-1", "--format=%h %s", c) for c in plus]}


def tree_row(path, ref, prs, cache, worktree=True):
    """-> (issues, at_risk, landing) for one worktree (or, worktree=False, one branch ref)."""
    issues, at_risk = [], False
    status = [ln for ln in git(path, "status", "--porcelain").splitlines() if "node_modules" not in ln] if worktree else []
    deleted = sum(1 for ln in status if ln[:2].strip() == "D")
    if deleted >= GUTTED:
        issues.append(f"GUTTED ({deleted} tracked files deleted): continue from the remote branch in a fresh worktree")
        at_risk = True
    land = landed(path, ref, prs, cache)
    rc, upstream = git_rc(path, "rev-parse", "--abbrev-ref", f"{ref}@{{u}}") if worktree else (1, "")
    upstream = upstream if rc == 0 else ""
    if not land["verdict"].startswith("LANDED"):
        issues.append(f"{land['verdict']}{'' if upstream else ' (no upstream)'}: " + "; ".join(land["evidence"][:4]))
        at_risk = True
    if upstream:
        ahead = git(path, "log", "--oneline", f"{upstream}..{ref}").splitlines()
        if ahead:
            issues.append(f"{len(ahead)} not on the remote branch {upstream} (a push may be owed): " + "; ".join(ahead[:4]))
    if deleted < GUTTED:
        untracked = [ln[3:] for ln in status if ln.startswith("??")]
        modified = [ln[3:] for ln in status if not ln.startswith("??")]
        if untracked:
            issues.append("untracked: " + ", ".join(untracked[:5]))
            at_risk = True
        if modified:
            issues.append("modified: " + ", ".join(modified[:5]))
            at_risk = True
    return issues, at_risk, land


def prs_by_branch(rows):
    out = {}
    for r in rows.values():
        for p in r.get("prs") or []:
            if isinstance(p, dict) and p.get("branch"):
                out.setdefault(p["branch"], []).append(p)
    return out


def owner_row(owner, rows):
    return {"ownerSessionId": owner, "manager": rows[owner].get("title", "") if owner in rows else "(unmanaged)"}


def worktree_findings(window, rows, roots, cache=None):
    """Worktrees of the windowed sessions; owners walk the full store. Several sessions can share
    one worktree: attribute it to one with an owner when any has one."""
    cache = cache if cache is not None else {}
    by_cwd = {}
    for sid, d in window.items():
        cwd = d.get("cwd", "")
        if cwd and (cwd not in by_cwd or pf.root_manager(by_cwd[cwd], rows, roots) is None):
            by_cwd[cwd] = sid
    prs = prs_by_branch(rows)
    out = []
    for cwd, sid in by_cwd.items():
        if not os.path.isdir(cwd) or git(cwd, "rev-parse", "--show-toplevel") == "":
            continue  # reaped: only its pushed branch/PR survives
        branch = git(cwd, "branch", "--show-current")
        if branch in MAIN_BRANCHES:
            continue  # the main checkout, not a lane
        issues, at_risk, land = tree_row(cwd, "HEAD", prs.get(branch, ()), cache)
        if issues:
            out.append(dict(owner_row(pf.root_manager(sid, rows, roots), rows), session=window[sid].get("title", ""),
                            sessionId=sid, worktree=cwd, branch=branch, landed=land, issues=issues, atRisk=at_risk))
    return sorted(out, key=lambda r: r["manager"])


def repo_findings(repo, since_ts, rows, roots, cache=None):
    """--repo: every worktree's HEAD, plus every local branch with no worktree whose upstream is
    missing or gone and whose last commit is newer than since_ts. main/master are skipped."""
    cache = cache if cache is not None else {}
    prs = prs_by_branch(rows)
    by_cwd, by_branch = {}, {}
    for sid, d in sorted(rows.items(), key=lambda kv: pf.parse_last(kv[1])):
        if d.get("cwd"):
            by_cwd[d["cwd"]] = sid
        for b in [p.get("branch") for p in d.get("prs") or [] if isinstance(p, dict)] + \
                 [str(b).split("\u0000")[-1] for b in d.get("writtenBranches") or []]:
            if b:
                by_branch[b] = sid
    out, with_wt, block = [], set(), {}
    for ln in git(repo, "worktree", "list", "--porcelain").splitlines() + [""]:
        if ln:
            k, _, v = ln.partition(" ")
            block[k] = v
            continue
        path, branch = block.get("worktree"), block.get("branch", "").replace("refs/heads/", "")
        block = {}
        if not path:
            continue
        with_wt.add(branch)
        if branch in MAIN_BRANCHES or not os.path.isdir(path):
            continue
        issues, at_risk, land = tree_row(path, "HEAD", prs.get(branch, ()), cache)
        if issues:
            sid = by_cwd.get(path) or by_branch.get(branch)
            out.append(dict(owner_row(pf.root_manager(sid, rows, roots) if sid else None, rows), kind="worktree",
                            sessionId=sid, worktree=path, branch=branch, landed=land, issues=issues, atRisk=at_risk))
    fmt = "%(refname:short)\t%(upstream)\t%(upstream:track)\t%(committerdate:unix)"
    for ln in git(repo, "for-each-ref", f"--format={fmt}", "refs/heads").splitlines():
        name, up, track, ts = (ln.split("\t") + ["", "", "", "0"])[:4]
        if name in with_wt or name in MAIN_BRANCHES or (up and "gone" not in track) or int(ts or 0) < since_ts:
            continue
        issues, at_risk, land = tree_row(repo, f"refs/heads/{name}", prs.get(name, ()), cache, worktree=False)
        if issues:
            sid = by_branch.get(name)
            out.append(dict(owner_row(pf.root_manager(sid, rows, roots) if sid else None, rows), kind="branch",
                            sessionId=sid, worktree=None, branch=name, landed=land, issues=issues, atRisk=at_risk))
    return out


def unreferenced_maps(since_ts, handoff_dir):
    handoffs = ""
    for f in glob.glob(os.path.join(handoff_dir, "*.md")):
        with open(f) as fh:
            handoffs += fh.read()
    missing = []
    for sub in ("maps", "wrapup"):
        for f in glob.glob(f"{S2C}/{sub}/*.md"):
            if os.path.getmtime(f) >= since_ts and os.path.basename(f) not in handoffs:
                missing.append(f)
    return sorted(missing)


# ---------- 3. scheduled tasks ----------

def registries(store):
    """-> [(account, path, [task])] for every <store>/<account>/<org>/scheduled-tasks.json. Only
    .scheduledTasks[] is read; a file without it (seen live) holds no tasks."""
    out = []
    for f in sorted(glob.glob(os.path.join(store, "*", "*", "scheduled-tasks.json"))):
        try:
            with open(f) as fh:
                tasks = (json.load(fh) or {}).get("scheduledTasks") or []
        except (OSError, ValueError, AttributeError):
            continue
        out.append((os.path.relpath(f, store).split(os.sep)[0], f, [t for t in tasks if isinstance(t, dict)]))
    return out


def task_ids(task):
    """-> (resolvable ids, raw tokens) from notifySessionId plus the SKILL.md body at filePath."""
    body = ""
    try:
        with open(task.get("filePath") or "", errors="ignore") as fh:
            body = fh.read()
    except OSError:
        pass
    tokens = [("full", task["notifySessionId"])] if task.get("notifySessionId") else []
    tokens += [("full", "local_" + m) for m in FULL_RX.findall(body)]
    rest = FULL_RX.sub(" ", body)
    tokens += [("bare", m) for m in BARE_RX.findall(rest)]
    tokens += [("short", m) for m in SHORT_RX.findall(rest)]
    return tokens


def resolve_targets(tokens, rows):
    """-> (resolved session ids, unresolved tokens). Bare UUIDs match sessionId or cliSessionId;
    short local_<8 hex> ids match a unique sessionId prefix. Nothing is dropped silently."""
    by_cli = {r.get("cliSessionId"): sid for sid, r in rows.items() if r.get("cliSessionId")}
    found, unresolved = [], []
    for kind, tok in tokens:
        if kind == "full":
            sid = tok if tok in rows else None
        elif kind == "bare":
            sid = ("local_" + tok) if ("local_" + tok) in rows else by_cli.get(tok)
        else:
            hits = [s for s in rows if s.startswith("local_" + tok)]
            sid = hits[0] if len(hits) == 1 else None
        if sid and sid not in found:
            found.append(sid)
        elif not sid and tok not in unresolved:
            unresolved.append(tok if kind != "short" else "local_" + tok)
    return found, unresolved


def iso_ms(ms):
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if ms else None


def stranded_schedules(store, here, rows, roots=None, now_ms=None):
    """Enabled scheduled tasks that will not reach their target from this account. Classes:
    registry-elsewhere | target-elsewhere | missed | no-target. Suppressed once the here registry
    holds an enabled, due task with the same filePath or naming the row's owner. Never edits a
    registry: the app owns that file."""
    roots, now_ms = roots or {}, now_ms or int(time.time() * 1000)
    entries = []
    for acct, path, tasks in registries(store):
        for t in tasks:
            if t.get("enabled") is not True:
                continue
            fire = t.get("fireAt")
            if t.get("cronExpression") or (isinstance(fire, (int, float)) and fire > now_ms):
                timing = "due"
            elif isinstance(fire, (int, float)) and not t.get("lastRunAt"):
                timing = "missed"
            else:
                continue  # a one-shot that has run
            tokens = task_ids(t)
            targets, unresolved = resolve_targets(tokens, rows)
            owner = next((o for o in (pf.root_manager(s, rows, roots) for s in targets) if o), None)
            entries.append({"acct": acct, "registry": path, "task": t, "timing": timing, "tokens": tokens,
                            "targets": targets, "unresolved": unresolved, "owner": owner})
    live_here = lambda e: all(rows[s].get("_acct") == here and not rows[s].get("isArchived")  # noqa: E731
                              for s in e["targets"])
    # a here task counts as the re-creation only if it reaches here itself; a stranded one would
    # otherwise hide every other stranded task with the same owner
    here_due = [e for e in entries if e["acct"] == here and e["timing"] == "due" and live_here(e)]
    out = []
    for e in entries:
        t, classes = e["task"], []
        if e["acct"] != here:
            classes.append("registry-elsewhere")
        if any(rows[s].get("_acct") != here or rows[s].get("isArchived") for s in e["targets"]):
            classes.append("target-elsewhere")
        if e["timing"] == "missed":
            classes.append("missed")
        if e["timing"] == "due" and not e["tokens"]:
            classes.append("no-target")
        if not classes:
            continue
        if any(h is not e and (h["task"].get("filePath") == t.get("filePath")
                               or (e["owner"] and e["owner"] in h["targets"])) for h in here_due):
            continue  # the owner already re-created it here
        fix = ("owner: re-create this task on this account with the scheduled-task tool, naming your own full "
               "session id, then disable the old task where you can reach it")
        if "missed" in classes:
            fix += "; it missed its wake: decide whether that wake's work is still owed"
        out.append({"taskId": t.get("id"), "class": classes, "displayName": t.get("displayName"),
                    "schedule": t.get("cronExpression") or "once", "fireAt": iso_ms(t.get("fireAt")),
                    "registryAccount": e["acct"], "filePath": t.get("filePath"),
                    "targets": [{"sessionId": s, "account": rows[s].get("_acct"), "title": rows[s].get("title", ""),
                                 "archived": bool(rows[s].get("isArchived"))} for s in e["targets"]],
                    "unresolved": e["unresolved"], "ownerSessionId": e["owner"], "fix": fix})
    return out


# ---------- 4. PR Auto-fix bindings ----------

def live_binding(p):
    return isinstance(p, dict) and p.get("autoFix") is True and p.get("dismissed") is not True and p.get("prNumber")


def stranded_bindings(rows, here, since_ms, roots=None):
    """PRs live-bound (autoFix true, not dismissed) only on another account's session, whose live
    state is OPEN, or MERGED while the binding row was active since since_ms (held until main is
    green past the merge). A here binding on any non-archived row, at any age, clears it."""
    roots = roots or {}
    key = lambda p: ((p.get("repo") or "").lower(), p["prNumber"])  # noqa: E731
    here_keys = {key(p) for r in rows.values() if r.get("_acct") == here and not r.get("isArchived")
                 for p in r.get("prs") or [] if live_binding(p)}
    cands = {}
    for sid, r in rows.items():
        if r.get("_acct") == here:
            continue
        for p in r.get("prs") or []:
            if live_binding(p) and key(p) not in here_keys:
                cands.setdefault(key(p), []).append((sid, p))
    out = []
    for k, binds in sorted(cands.items()):
        sid, p = max(binds, key=lambda b: pf.parse_last(rows[b[0]]))
        active = pf.parse_last(rows[sid]) * 1000 >= since_ms
        stored = p.get("state")
        if stored != "OPEN" and not active:
            continue  # cannot qualify: an old MERGED or CLOSED binding
        info = gh_json(["pr", "view", str(p["prNumber"]), "--repo", p.get("repo") or "", "--json", "state"])
        state = (info or {}).get("state") or stored
        if not (state == "OPEN" or (state == "MERGED" and active)):
            continue
        row = {"repo": p.get("repo"), "pr": p["prNumber"], "state": state, "branch": p.get("branch"),
               "boundSession": {"sessionId": sid, "title": rows[sid].get("title", ""), "account": rows[sid].get("_acct")},
               "ownerSessionId": pf.root_manager(sid, rows, roots),
               "fix": ("owner: bind_pr, then set_monitor with auto_fix true" if state == "OPEN" else
                       "owner: bind until main is green past the merge, then unbind")
               + "; the other account's binding cannot be removed from here and dies with that session"}
        if state != stored:
            row["storedState"] = stored
        if info is None:
            row["stateUnverified"] = True
        out.append(row)
    return out


def resolve_here(here, rows):
    if not here:
        return None
    accts = {r["_acct"] for r in rows.values() if r["_acct"].startswith(here)}
    return accts.pop() if len(accts) == 1 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", default="all", help="account dir prefix, comma list, or 'all' (preferred: programs hop accounts)")
    ap.add_argument("--since", required=True, help="ISO time of the last checkpoint, e.g. 2026-10-18T20:00")
    ap.add_argument("--handoff-dir", default=f"{S2C}/handoff")
    ap.add_argument("--here", help="account dir (or prefix) this session runs on; enables checks 3 and 4")
    ap.add_argument("--roots", help="<work>/candidates.json from mine_all.py")
    ap.add_argument("--repo", help="sweep one repo's worktrees and worktree-less branches instead")
    args = ap.parse_args()
    since = datetime.datetime.fromisoformat(args.since).replace(tzinfo=datetime.timezone.utc)
    since_ms = int(since.timestamp() * 1000)
    rows, _, _ = pf.load_store(STORE)
    roots = pf.load_roots(args.roots)
    if args.repo:
        print(json.dumps({"repo": args.repo, "rows": repo_findings(args.repo, since.timestamp(), rows, roots)}, indent=1))
        return
    accts = None if args.account in ("all", "*") else [a.strip() for a in args.account.split(",")]
    window = {s: d for s, d in rows.items() if d.get("lastActivityAt", 0) >= since_ms
              and (not accts or any(d["_acct"].startswith(a) for a in accts))}
    here = resolve_here(args.here, rows)
    print(json.dumps({
        "sessionsScanned": len(window),
        "here": here,
        "worktrees": worktree_findings(window, rows, roots),
        "unreferencedMapsAndNotes": unreferenced_maps(since.timestamp(), os.path.expanduser(args.handoff_dir)),
        "staleSchedules": stranded_schedules(STORE, here, rows, roots) if here else [],
        "strandedBindings": stranded_bindings(rows, here, since_ms, roots) if here else [],
    }, indent=1))


if __name__ == "__main__":
    main()
