#!/usr/bin/env python3
"""state_sources.py - the state page's derived readers: PRs by ticket, deployed per surface, red main,
file overlap and the skills rules. Pure functions over an injectable runner, plus `collect`, which runs
them for one program under one deadline.

Rule: a fact is stated only when its proof was read. A source that failed, timed out or was never
configured reads as "unavailable" or "not established" with its fix, never as an absence.
Owners and rules: ../specs/2026-11-03-manager-state-viewer.md
"""
import concurrent.futures as cf
import hashlib
import json
import os
import re
import subprocess
import time

import work_state_sources as src
import work_state_store as st

SCHEMA = "state-sources/1"
TTL_S = 120
CALL_TIMEOUT_S = 20
SEARCH_BATCH = 6
SEARCH_LIMIT = 100
DEPLOY_PAGE = 10
RUN_PAGE = 20
RATE_RESET_S = 600
POOL = 6
PR_FIELDS = "number,title,headRefName,state,isDraft,mergedAt,mergeCommit,additions,deletions,updatedAt"
GENERATED = ("package-lock.json", "pnpm-lock.yaml", "yarn.lock", "*.lock", "**/*.generated.*", "**/generated/**",
             "**/__snapshots__/**", "**/*.snap", "**/dist/**", "**/*.min.js")
RED_STATES = ("green", "red", "outage", "pending")


# ---------- running commands under one deadline ----------

class Deadline:
    def __init__(self, seconds, clock=time.monotonic):
        self.clock, self.end = clock, clock() + seconds

    def left(self):
        return max(0.0, self.end - self.clock())


class Runner:
    """Runs one argv with the per-call timeout capped by the render deadline. -> (rc|None, stdout, stderr).
    rc None means it never finished (timeout, missing binary, or no time left)."""

    def __init__(self, deadline, run=subprocess.run):
        self.deadline, self.run = deadline, run

    def __call__(self, argv, cwd=None):
        budget = min(CALL_TIMEOUT_S, self.deadline.left())
        if budget < 1:
            return None, "", "no time left in the render deadline"
        try:
            r = self.run(argv, capture_output=True, text=True, timeout=budget, cwd=cwd)
            return r.returncode, r.stdout or "", r.stderr or ""
        except subprocess.TimeoutExpired:
            return None, "", f"timed out after {int(budget)} s"
        except OSError as exc:
            return None, "", str(exc)


def gh_failure(rc, err):
    """Classify a failed gh call. -> {kind, detail, fix}. kind 'rate' keeps the stale tier."""
    text = (err or "").strip()
    low = text.lower()
    if rc is None:
        return {"kind": "timeout", "detail": text or "did not finish", "fix": None}
    if "rate limit" in low or "http 429" in low or "abuse" in low:
        return {"kind": "rate", "detail": "GitHub rate limit reached", "fix": None}
    if "http 401" in low or "gh auth login" in low or "not logged" in low or "authentication" in low:
        return {"kind": "auth", "detail": "GitHub refused the login", "fix": "gh auth status, then sign gh in again"}
    if "http 404" in low or "could not resolve to a repository" in low or "not found" in low:
        return {"kind": "missing", "detail": "GitHub says not found", "fix": "check the repo name in the manifest `repos` and gh access"}
    if "http 403" in low or "resource not accessible" in low or "permission" in low:
        return {"kind": "denied", "detail": "GitHub denied the read", "fix": "grant this gh login read access to the repo"}
    return {"kind": "error", "detail": text[:300] or f"exit {rc}", "fix": None}


def _json(rc, out):
    if rc != 0:
        return None
    try:
        return json.loads(out)
    except ValueError:
        return None


# ---------- caches ----------

def repo_key(repo):
    return "repo-" + repo.replace("/", "__")


def read_tier(key):
    data = src.read_cache(key)
    return data if data.get("schema") == SCHEMA else {"schema": SCHEMA}


def save_tier(key, section, value):
    """Re-read, set one section, write. Each tier is written as it completes, so a killed render still advances it."""
    cur = read_tier(key)
    cur[section] = value
    src.write_cache(key, cur)
    return cur


def fresh(entry, now, ttl=TTL_S):
    return bool(entry) and entry.get("fetched_at") is not None and now - entry["fetched_at"] < ttl


# ---------- PRs by ticket ----------

def ticket_regex(ticket):
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(ticket) + r"(?![A-Za-z0-9])", re.I)


def _search(gh, repo, batch):
    rc, out, err = gh(["gh", "pr", "list", "--repo", repo, "--state", "all", "--search", " OR ".join(batch),
                       "--limit", str(SEARCH_LIMIT), "--json", PR_FIELDS])
    rows = _json(rc, out)
    return (rows, None) if isinstance(rows, list) else (None, gh_failure(rc, err))


def search_batch(gh, repo, batch):
    """-> (rows, failure, incomplete tickets). A 100-row page is split and re-run, never read as complete."""
    rows, fail = _search(gh, repo, batch)
    if fail:
        return None, fail, []
    if len(rows) < SEARCH_LIMIT:
        return rows, None, []
    if len(batch) == 1:
        return rows, None, list(batch)
    half = len(batch) // 2
    out, short = [], []
    for part in (batch[:half], batch[half:]):
        r, f, s = search_batch(gh, repo, part)
        if f:
            return None, f, []
        out += r
        short += s
    return out, None, short


def keep_rows(rows, batch):
    """Keep a row only when a ticket id is a whole token of its title or head branch."""
    kept = {}
    for row in rows:
        hay = f"{row.get('title') or ''} {row.get('headRefName') or ''}"
        hits = [t for t in batch if ticket_regex(t).search(hay)]
        if hits:
            kept[row["number"]] = dict(row, tickets=sorted(hits))
    return kept


def ticket_prs(repo, tickets, gh, cache, now, pool=POOL):
    """-> ({number: row}, [problem]). cache is the program's own `searches` dict for this repo."""
    batches = [tickets[i:i + SEARCH_BATCH] for i in range(0, len(tickets), SEARCH_BATCH)]
    todo = [b for b in batches if not fresh(cache.get(" OR ".join(b)), now)]
    problems = []
    with cf.ThreadPoolExecutor(max_workers=pool) as ex:
        for b, (rows, fail, short) in zip(todo, ex.map(lambda b: search_batch(gh, repo, b), todo)):
            key = " OR ".join(b)
            if fail:
                problems.append(_problem_for(fail, f"PRs for {', '.join(b)}", cache.get(key), now))
                continue
            cache[key] = {"fetched_at": now, "data": rows, "incomplete": short}
    merged = {}
    for b in batches:
        entry = cache.get(" OR ".join(b)) or {}
        for t in entry.get("incomplete") or []:
            problems.append({"source": "Pull requests", "detail": f"{t} matches more than {SEARCH_LIMIT} PRs, so its list is incomplete",
                             "fix": None})
        for n, row in keep_rows(entry.get("data") or [], b).items():
            prev = merged.get(n)
            merged[n] = dict(row, tickets=sorted(set(row["tickets"]) | set((prev or {}).get("tickets") or [])))
    return merged, problems


def _problem_for(fail, what, stale, now):
    age = f"; showing the copy from {int(now - stale['fetched_at'])} s ago" if stale and stale.get("fetched_at") else ""
    return {"source": "GitHub", "detail": f"{what}: {fail['detail']}{age}", "fix": fail.get("fix"), "kind": fail["kind"]}


def view_pr(gh, repo, number):
    rc, out, err = gh(["gh", "pr", "view", str(number), "--repo", repo, "--json", PR_FIELDS])
    row = _json(rc, out)
    return (row, None) if isinstance(row, dict) else (None, gh_failure(rc, err))


def merged_files(gh, repo, numbers, tier, deadline, pool=POOL):
    """Files of each merged PR, read once and kept forever (a merged PR never changes)."""
    have = tier.setdefault("merged_files", {})
    need = [n for n in numbers if str(n) not in have]

    def one(n):
        if deadline.left() < 5:
            return n, None
        rc, out, _ = gh(["gh", "pr", "view", str(n), "--repo", repo, "--json", "files"])
        data = _json(rc, out)
        return n, (data or {}).get("files") if isinstance(data, dict) else None

    with cf.ThreadPoolExecutor(max_workers=pool) as ex:
        for n, files in ex.map(one, need):
            if isinstance(files, list):
                paths = [f.get("path") for f in files if isinstance(f, dict) and f.get("path")]
                have[str(n)] = {"files": paths, "complete": len(paths) < 100}
    return have


def open_pr_files(gh, repo, tier, now):
    """One list of open PRs with their files, shared by every program on the repo (TTL)."""
    entry = tier.get("open") or {}
    if fresh(entry, now) or _rate_blocked(tier, now):
        return entry, None
    rc, out, err = gh(["gh", "pr", "list", "--repo", repo, "--state", "open", "--limit", "100",
                       "--json", "number,files,additions,deletions"])
    rows = _json(rc, out)
    if not isinstance(rows, list):
        fail = gh_failure(rc, err)
        _note_rate(tier, fail, now)
        return entry, fail
    prs = {str(r["number"]): {"files": [f.get("path") for f in r.get("files") or [] if f.get("path")],
                              "sizes": {f["path"]: (f.get("additions") or 0) + (f.get("deletions") or 0)
                                        for f in r.get("files") or [] if f.get("path")},
                              "additions": r.get("additions"), "deletions": r.get("deletions")} for r in rows}
    return {"fetched_at": now, "data": prs, "complete": len(rows) < 100}, None


def _rate_blocked(tier, now):
    return (tier.get("rate_reset_at") or 0) > now


def _note_rate(tier, fail, now):
    if fail and fail["kind"] == "rate":
        tier["rate_reset_at"] = now + RATE_RESET_S


# ---------- deployed per surface ----------

JOB_ID = re.compile(r"/actions/runs/(\d+)/job/(\d+)")
RUN_ID = re.compile(r"/actions/runs/(\d+)")


def _step_ok(steps, name):
    """-> True (ran, success), False (absent, skipped or failed)."""
    for s in steps or []:
        if s.get("name") == name:
            return s.get("conclusion") == "success"
    return False


def proof_step_ran(gh, repo, url, step):
    """The deploying step ran and succeeded in the very job that recorded the deployment. -> (bool|None, why)."""
    m = JOB_ID.search(url or "")
    if m:
        rc, out, err = gh(["gh", "api", f"repos/{repo}/actions/jobs/{m.group(2)}"])
        job = _json(rc, out)
        if not isinstance(job, dict):
            return None, gh_failure(rc, err)["detail"]
        return _step_ok(job.get("steps"), step), None
    m = RUN_ID.search(url or "")
    if not m:
        return False, "no run link on the deployment"
    rc, out, err = gh(["gh", "run", "view", m.group(1), "--repo", repo, "--json", "jobs"])
    run = _json(rc, out)
    if not isinstance(run, dict):
        return None, gh_failure(rc, err)["detail"]
    return any(_step_ok(j.get("steps"), step) for j in run.get("jobs") or []), None


def deployment_walk(gh, repo, surface):
    """`deployment` kind. -> {proven, pending, failed, walked, exhausted, skipped} or raises SourceError."""
    rc, out, err = gh(["gh", "api", f"repos/{repo}/deployments?environment={surface['environment']}&per_page={DEPLOY_PAGE}"])
    deps = _json(rc, out)
    if not isinstance(deps, list):
        raise SourceError(gh_failure(rc, err))
    res = {"proven": None, "pending": [], "failed": None, "walked": 0, "skipped": [], "exhausted": False}
    for d in deps:
        rc, out, err = gh(["gh", "api", f"repos/{repo}/deployments/{d['id']}/statuses", "--jq", ".[0]"])
        status = _json(rc, out)
        if not isinstance(status, dict):
            raise SourceError(gh_failure(rc, err))
        res["walked"] += 1
        state, url = status.get("state"), status.get("log_url") or status.get("target_url")
        rec = {"sha": d.get("sha"), "id": d.get("id"), "url": url, "at": status.get("created_at") or d.get("created_at")}
        if state in ("in_progress", "queued", "pending"):
            res["pending"].append(rec)
            continue
        if state in ("failure", "error"):
            res["failed"] = res["failed"] or rec
            continue
        if state != "success":
            continue
        if surface.get("proof_step"):
            ok, why = proof_step_ran(gh, repo, url, surface["proof_step"])
            if ok is None:
                raise SourceError({"kind": "error", "detail": f"cannot read the deploy job: {why}", "fix": None})
            if not ok:
                res["skipped"].append(dict(rec, why=f"'{surface['proof_step']}' did not run"))
                continue
        res["proven"] = rec
        return res
    res["exhausted"] = True
    return res


def job_walk(gh, repo, surface, main):
    """`job` kind: recent runs of one workflow, filtered here to main (a filtered search has returned stale pages)."""
    rc, out, err = gh(["gh", "run", "list", "--repo", repo, "--workflow", surface["workflow"], "--limit", str(RUN_PAGE),
                       "--json", "databaseId,headSha,headBranch,conclusion,status,createdAt,url"])
    runs = _json(rc, out)
    if not isinstance(runs, list):
        raise SourceError(gh_failure(rc, err))
    res = {"proven": None, "pending": [], "failed": None, "walked": 0, "skipped": [], "exhausted": False}
    for r in (x for x in runs if x.get("headBranch") == main):
        res["walked"] += 1
        rec = {"sha": r.get("headSha"), "id": r.get("databaseId"), "url": r.get("url"), "at": r.get("createdAt")}
        if r.get("status") != "completed":
            res["pending"].append(rec)
            continue
        if r.get("conclusion") == "failure":
            res["failed"] = res["failed"] or rec
            continue
        if r.get("conclusion") != "success":
            continue
        rc, out, err = gh(["gh", "run", "view", str(r["databaseId"]), "--repo", repo, "--json", "jobs"])
        view = _json(rc, out)
        if not isinstance(view, dict):
            raise SourceError(gh_failure(rc, err))
        job = next((j for j in view.get("jobs") or [] if j.get("name") == surface["job"]), None)
        if not job or not _step_ok(job.get("steps"), surface["proof_step"]):
            res["skipped"].append(dict(rec, why=f"'{surface['proof_step']}' did not run in '{surface['job']}'"))
            continue
        res["proven"] = dict(rec, url=job.get("url") or rec["url"])
        return res
    res["exhausted"] = True
    return res


class SourceError(Exception):
    def __init__(self, fail):
        super().__init__(fail.get("detail"))
        self.fail = fail


def surface_hash(surface):
    return hashlib.sha256(json.dumps(surface, sort_keys=True).encode()).hexdigest()[:12]


def deploy_tier(gh, repo_cfg, surface, tier, now):
    """-> (entry, failure). The entry is cached per repo with TTL; a rate limit keeps the stale one."""
    deploys = tier.setdefault("deploys", {})
    entry = deploys.get(surface["name"]) or {}
    if entry.get("config") == surface_hash(surface) and (fresh(entry, now) or _rate_blocked(tier, now)):
        return entry, None
    try:
        walk = (deployment_walk(gh, repo_cfg["repo"], surface) if surface["kind"] == "deployment"
                else job_walk(gh, repo_cfg["repo"], surface, repo_cfg["main"]))
    except SourceError as exc:
        _note_rate(tier, exc.fail, now)
        return (entry if entry.get("config") == surface_hash(surface) else {}), exc.fail
    entry = {"fetched_at": now, "config": surface_hash(surface), "data": walk}
    deploys[surface["name"]] = entry
    return entry, None


class Ancestry:
    """Is merge M inside deploy D? Local git first; GitHub compare when the local clone lacks the objects."""

    def __init__(self, gh, repo, path, tier):
        self.gh, self.repo, self.path = gh, repo, os.path.expanduser(path)
        self.memo = tier.setdefault("ancestry", {})

    def __call__(self, m, d):
        if not m or not d:
            return None
        if m == d:
            return True
        key = f"{m}..{d}"
        if key in self.memo:
            return self.memo[key]
        rc, _, _ = self.gh(["git", "-C", self.path, "merge-base", "--is-ancestor", m, d])
        if rc in (0, 1):
            ans = rc == 0
        else:
            rc, out, _ = self.gh(["gh", "api", f"repos/{self.repo}/compare/{m}...{d}", "--jq", ".status"])
            ans = {"identical": True, "ahead": True, "behind": False, "diverged": False}.get(out.strip()) if rc == 0 else None
        if ans is not None and len(self.memo) < 4000:
            self.memo[key] = ans
        return ans


def glob_re(pattern):
    """`**` crosses directories, `*` and `?` do not."""
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += r"(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            out += r".*"
            i += 2
        elif pattern[i] == "*":
            out += r"[^/]*"
            i += 1
        elif pattern[i] == "?":
            out += r"[^/]"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile(out + r"\Z")


def matches(path, patterns):
    return any(glob_re(p).match(path) for p in patterns)


def surface_state(merge_sha, files, surface, walk, ancestor):
    """One PR on one surface. -> {state, ...proof}. States: deployed, deploying, failed, not_established,
    na, cannot_tell, unavailable."""
    if files is None or files.get("files") is None:
        applies = None
    else:
        hit = matches_any(files["files"], surface["paths"])
        applies = True if hit else (False if files.get("complete") and files["files"] else None)
    if applies is False:
        return {"state": "na"}
    if walk is None:
        return {"state": "unavailable"}
    proven = walk.get("proven")
    if proven:
        inside = ancestor(merge_sha, proven["sha"])
        if inside:
            if applies is None:
                return {"state": "cannot_tell", "why": "files not read yet", "deploy": proven}
            return {"state": "deployed", "deploy": proven}
        if inside is None:
            return {"state": "cannot_tell", "why": "cannot compare commits"}
    for rec in walk.get("pending") or []:
        if ancestor(merge_sha, rec["sha"]):
            return {"state": "deploying", "deploy": rec}
    failed = walk.get("failed")
    if failed and ancestor(merge_sha, failed["sha"]):
        return {"state": "failed", "deploy": failed}
    if applies is None:
        return {"state": "cannot_tell", "why": "files not read yet"}
    return {"state": "not_established", "walked": walk.get("walked"), "exhausted": walk.get("exhausted")}


def matches_any(files, patterns):
    compiled = [glob_re(p) for p in patterns]
    return any(c.match(f) for f in files for c in compiled)


# ---------- red main ----------

def red_main(gh, repo_cfg, tier, now):
    """-> {state, sha, owners, claim} or {state: 'unavailable', why, fix}. Never reads a workflow conclusion."""
    cmd = repo_cfg.get("red_main_cmd")
    if not cmd:
        return {"state": "unavailable", "why": repo_cfg.get("red_main_unproven") or "this repo names no red-main command",
                "fix": "add `red_main_cmd` to this repo's manifest entry"}
    entry = tier.get("red_main") or {}
    if fresh(entry, now):
        return entry["data"]
    rc, out, err = gh(list(cmd), cwd=os.path.expanduser(repo_cfg["path"]))
    data = _json(rc, out) if rc == 0 else None
    if not (isinstance(data, dict) and data.get("schema") == 1 and data.get("state") in RED_STATES
            and isinstance(data.get("owners", []), list)):
        why = "printed nothing" if rc == 0 and not out.strip() else (
            "printed output outside the contract" if rc == 0 else f"failed: {(err or '').strip()[:200] or rc}")
        return {"state": "unavailable", "why": f"the red-main command {why}", "fix": "fix `red_main_cmd` so it prints the contract",
                "problem": True}
    data = {"state": data["state"], "sha": data.get("sha"), "claim": data.get("claim"),
            "owners": [o for o in data.get("owners") or [] if isinstance(o, dict)]}
    tier["red_main"] = {"fetched_at": now, "data": data}
    return data


# ---------- file overlap ----------

def is_generated(path):
    return matches(path, GENERATED) or os.path.basename(path) in GENERATED


def _literal_prefix(pattern):
    m = re.search(r"[*?\[]", pattern)
    return pattern if not m else pattern[:m.start()]


def paths_overlap(a, b):
    """Two paths or globs touch: equal, one glob matches the other path, or two globs share a literal prefix."""
    ga, gb = bool(re.search(r"[*?\[]", a)), bool(re.search(r"[*?\[]", b))
    if not ga and not gb:
        return a == b
    if ga and not gb:
        return bool(glob_re(a).match(b))
    if gb and not ga:
        return bool(glob_re(b).match(a))
    pa, pb = _literal_prefix(a), _literal_prefix(b)
    return pa.startswith(pb) or pb.startswith(pa)


def claims_of(holdings):
    """holdings: {repo: {"prs": {n: [files]}, "paths": [globs]}} -> [(repo, pr|None, path)] minus generated."""
    out = []
    for repo, h in (holdings or {}).items():
        for n, files in (h.get("prs") or {}).items():
            out += [(repo, str(n), f) for f in files or [] if not is_generated(f)]
        out += [(repo, None, p) for p in h.get("paths") or []]
    return out


def overlap(mine, others):
    """-> [{program, repo, paths: [...], ours: [pr], theirs: [pr]}]. Same-PR pairs are dropped."""
    my = claims_of(mine)
    rows = []
    for other in others:
        hits = {}
        for repo, pr, path in my:
            for orepo, opr, opath in claims_of(other.get("holdings")):
                if orepo != repo or (pr and pr == opr) or not paths_overlap(path, opath):
                    continue
                h = hits.setdefault(repo, {"paths": set(), "ours": set(), "theirs": set()})
                concrete = [x for x in (path, opath) if not re.search(r"[*?\[]", x)]
                h["paths"].add(concrete[0] if concrete else min(path, opath, key=len))
                h["ours"].add(pr or "bound paths")
                h["theirs"].add(opr or "bound paths")
        for repo, h in hits.items():
            rows.append({"program": other["program"], "repo": repo, "paths": sorted(h["paths"])[:20],
                         "path_count": len(h["paths"]), "ours": sorted(h["ours"]), "theirs": sorted(h["theirs"])})
    return rows


# ---------- skills worth running ----------

def skills(prs, view, repos_cfg, items, now, done):
    """The rules table. One row per (skill, ref); a matching `skills_done` row silences it."""
    out, seen = [], set()

    def fire(skill, ref, why):
        if (skill, ref) in seen or (skill, ref) in done:
            return
        seen.add((skill, ref))
        out.append({"skill": skill, "ref": ref, "why": why})

    by_ticket = {}
    for p in prs:
        for t in p.get("tickets") or []:
            by_ticket.setdefault(t, []).append(p)
    closed = {i["ticket"] for i in items if i.get("state") == "closed"}
    for t, rows in by_ticket.items():
        merged = [p for p in rows if p.get("mergedAt")]
        fixes = [p for p in merged if re.match(r"^fix(\(|:|!)", p.get("title") or "")]
        if len(fixes) >= 3:
            fire("/improve-codebase-architecture", t, f"{len(fixes)} fix PRs merged on one ticket")
        size = sum((p.get("additions") or 0) + (p.get("deletions") or 0) for p in merged)
        if t in closed and size >= 800:
            fire("/standards-spec-review", t, f"closed ticket with {size} changed lines merged")
            fire("/simplify", t, f"closed ticket with {size} changed lines merged")
    for d in view.get("design") or []:
        if d.get("kind") == "spec" and (d.get("tier") == "none" or not d.get("review")):
            fire("/spec-review", d.get("ref") or d.get("what"), "a spec with no review at its tier")
        ref_pr = _pr_of_ref(d.get("ref"), prs)
        if d.get("kind") == "spec" and ref_pr and ref_pr.get("mergedAt") and now - st.parse_iso(ref_pr["mergedAt"]) < 7 * 86400:
            fire("/spec-visualization", d.get("ref"), "a spec merged in the last 7 days")
    incidents = view.get("incidents") or []
    causes = {}
    for inc in incidents:
        causes.setdefault((inc.get("cause") or "").strip().lower(), []).append(inc)
    names = {k: (rows[0].get("cause") or "").strip() for k, rows in causes.items()}
    for inc in incidents:
        if not inc.get("rca"):
            fire("/root-cause-analysis", inc.get("what"), "an incident with no complete RCA")
    for cause, rows in causes.items():
        if cause and len(rows) >= 2:
            fire("/root-cause-analysis", names[cause], f"{len(rows)} incidents share one cause")
    sec = {r["repo"]: r.get("security_paths") or [] for r in repos_cfg}
    for p in prs:
        globs = sec.get(p.get("repo")) or []
        if globs and p.get("files") and matches_any(p["files"], globs) and p.get("state") != "CLOSED":
            fire("/security-review", f"#{p['number']}", "the PR touches a security path")
    return out


def _pr_of_ref(ref, prs):
    m = re.match(r"^(?:.*?)#(\d+)$", str(ref or ""))
    return next((p for p in prs if m and p.get("number") == int(m.group(1))), None)


# ---------- one runner ----------

def _health(name, fail=None, entry=None, now=None, extra=None):
    age = int(now - entry["fetched_at"]) if entry and entry.get("fetched_at") and now else None
    return dict({"name": name, "ok": fail is None, "age_s": age, "detail": (fail or {}).get("detail"),
                 "fix": (fail or {}).get("fix")}, **(extra or {}))


def collect_repo(repo_cfg, tickets, pubs, gh, deadline, searches, now, pool=POOL):
    """Every derived read for one repo. -> {repo, prs: [row], open, red_main, surfaces, health, problems}.
    `searches` is this repo's slice of the program cache; the repo tier is shared by every program."""
    repo = repo_cfg["repo"]
    key = repo_key(repo)
    tier = read_tier(key)
    problems, health = [], []
    mine = [t for t in tickets if re.fullmatch(repo_cfg["ticket_pattern"], t)]
    prs, probs = ticket_prs(repo, mine, gh, searches, now, pool)
    problems += probs
    health.append(_health("Pull requests by ticket", probs[0] if any(p.get("kind") for p in probs) else None))
    for n in sorted({p["pr"] for p in pubs if p.get("repo") == repo and p.get("pr")} - set(prs)):
        row, fail = view_pr(gh, repo, n)
        if fail:
            problems.append({"source": "GitHub", "detail": f"bound PR #{n}: {fail['detail']}", "fix": fail.get("fix")})
            continue
        prs[n] = dict(row, tickets=sorted({b for b in (p.get("ticket") for p in pubs if p.get("pr") == n) if b}))
    for p in pubs:
        if p.get("repo") == repo and p.get("sha") and not p.get("pr"):
            prs[f"push:{p['sha'][:12]}"] = {"number": None, "push_sha": p["sha"], "title": "Direct push",
                                            "state": "MERGED", "mergedAt": p.get("at") or "unknown", "mergeCommit": {"oid": p["sha"]},
                                            "tickets": [p.get("ticket")] if p.get("ticket") else []}
    entry, fail = open_pr_files(gh, repo, tier, now)
    if entry:
        tier["open"] = entry
        save_tier(key, "open", entry)
    health.append(_health("Open PR files", fail, entry, now))
    if fail:
        problems.append(_problem_for(fail, "open PR files", entry, now))
    merged_nums = [r["number"] for r in prs.values() if r.get("mergedAt") and r.get("number")]
    merged_nums.sort(reverse=True)
    files = merged_files(gh, repo, merged_nums, tier, deadline, pool)
    save_tier(key, "merged_files", files)
    walks, surfaces = {}, []
    for s in repo_cfg["surfaces"]:
        entry, fail = deploy_tier(gh, repo_cfg, s, tier, now)
        save_tier(key, "deploys", tier.get("deploys") or {})
        walks[s["name"]] = entry.get("data") if entry else None
        surfaces.append({"name": s["name"], "kind": s["kind"], "unproven": s.get("unproven"),
                         "walk": walks[s["name"]], "age_s": int(now - entry["fetched_at"]) if entry.get("fetched_at") else None,
                         "error": (fail or {}).get("detail"), "fix": (fail or {}).get("fix")})
        health.append(_health(f"Deploys: {s['name']}", fail, entry, now))
        if fail:
            problems.append(_problem_for(fail, f"deploys of {s['name']}", entry, now))
    if tier.get("rate_reset_at"):
        save_tier(key, "rate_reset_at", tier["rate_reset_at"])
    red = red_main(gh, repo_cfg, tier, now)
    if tier.get("red_main"):
        save_tier(key, "red_main", tier["red_main"])
    if red.get("problem"):
        problems.append({"source": "Main health", "detail": f"{repo}: {red['why']}", "fix": red.get("fix")})
    ancestor = Ancestry(gh, repo, repo_cfg["path"], tier)
    open_files = (tier.get("open") or {}).get("data") or {}
    rows = []
    for r in prs.values():
        n = r.get("number")
        f = files.get(str(n)) if r.get("mergedAt") else (
            {"files": open_files[str(n)]["files"], "complete": True} if str(n) in open_files else None)
        row = dict(r, repo=repo, files=(f or {}).get("files"), files_complete=bool((f or {}).get("complete")))
        if r.get("mergedAt"):
            sha = (r.get("mergeCommit") or {}).get("oid")
            row["surfaces"] = [dict(surface_state(sha, f, s, walks[s["name"]], ancestor), surface=s["name"],
                                    unproven=s.get("unproven")) for s in repo_cfg["surfaces"]]
        rows.append(row)
    save_tier(key, "ancestry", tier.get("ancestry") or {})
    return {"repo": repo, "prs": rows, "open": open_files, "open_complete": (tier.get("open") or {}).get("complete"),
            "red_main": red, "surfaces": surfaces, "health": health, "problems": problems,
            "has_surfaces": bool(repo_cfg["surfaces"])}


# ---------- the ladder ----------

STEP_ORDER = ("open", "merged", "deployed", "exposed", "baked")


def ladder(pr, exposure, bakes, has_surfaces):
    """One change on `PR open -> merged -> deployed -> dark or live -> baked`. -> {step, final, steps}.
    `step` is how far it has PROVABLY got; `final` means nothing is owed and it belongs in History."""
    if pr.get("state") == "CLOSED" and not pr.get("mergedAt"):
        return {"step": "closed", "final": True, "steps": {}}
    if not pr.get("mergedAt"):
        return {"step": "open", "final": False, "steps": {"open": {"draft": bool(pr.get("isDraft"))}}}
    steps = {"merged": {"at": pr["mergedAt"], "sha": (pr.get("mergeCommit") or {}).get("oid")}}
    if not has_surfaces:
        return {"step": "merged", "final": _bake_final(bakes), "steps": dict(steps, bake=bakes), "no_deploy_step": True}
    states = [s for s in pr.get("surfaces") or [] if s["state"] != "na"]
    steps["deploy"] = pr.get("surfaces") or []
    if not states:
        return {"step": "merged", "final": _bake_final(bakes), "steps": dict(steps, bake=bakes), "deploy_na": True}
    if not all(s["state"] == "deployed" for s in states):
        return {"step": "merged", "final": False, "steps": dict(steps, bake=bakes)}
    steps["exposure"] = exposure or {"state": "unstated"}
    if not exposure:
        return {"step": "deployed", "final": False, "steps": dict(steps, bake=bakes)}
    if exposure.get("state") == "dark":
        return {"step": "deployed", "final": False, "steps": dict(steps, bake=bakes), "dark": True}
    final = _bake_final(bakes)
    return {"step": "baked" if bakes.get("verdict") == "pass" else "exposed", "final": final, "steps": dict(steps, bake=bakes)}


def _bake_final(bakes):
    return bakes.get("verdict") in ("pass", "none", None) and not bakes.get("owed")


def bake_of(tickets, items, bindings):
    """The derived bake verdict for a change's tickets: the worst of their bake children; `none:<why>` bindings
    read as no bake. A pass reads 'ticket records pass', never 'proven': no bake artifact is read."""
    by = {i["ticket"]: i for i in items}
    binds = {b["ticket"]: b for b in bindings}
    verdicts, ended, why_none = [], [], []
    for t in tickets:
        i = by.get(t) or {}
        if i.get("bake_verdict"):
            verdicts.append(i["bake_verdict"])
            ended.append(i.get("bake_ended"))
        elif str((binds.get(t) or {}).get("bake", "")).startswith("none:"):
            why_none.append(binds[t]["bake"][5:])
    rank = {"fail": 0, "pending": 1, "pass": 2}
    if verdicts:
        worst = min(verdicts, key=lambda v: rank.get(v, 1))
        return {"verdict": worst, "owed": worst != "pass", "canceled": "canceled" in ended or "duplicate" in ended}
    if why_none:
        return {"verdict": "none", "why": sorted(set(why_none))}
    return {"verdict": None}
