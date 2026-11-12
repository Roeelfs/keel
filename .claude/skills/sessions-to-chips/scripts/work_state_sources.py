#!/usr/bin/env python3
"""The engine's inputs (§4): remote tiers behind the cache, local probes, and derive()'s context.

Remote: the tracker via the manifest's `map.snapshot_cmd` (TTL 300 s) and `gh pr list` per bound
repo (TTL 120 s), both kept in `~/.claude/state/work-state/<slug>.json` (disposable, atomic rename,
non-blocking flock: a reader never waits on it). On a rate limit the stale tier is kept and a
`linear-reset` pending event is emitted; nothing retries. Local: the incremental session index
(program_family), lane rows from their cached byte offset, one `ps`, one bounded git probe per
bound worktree (snapshot only; the guard runs no git and no network).
"""
import fcntl
import json
import os
import shlex
import subprocess
import time

import program_family as pf
import lane_proof
import work_state_store as st

ANALYTICS = os.environ.get("WORK_STATE_ANALYTICS") or os.path.join(st.HOME, "analytics/work-state.jsonl")
GUARD_SCRIPT = os.environ.get("WORK_STATE_GUARD_SCRIPT") or os.path.join(st.HOME, "scripts/manager_arm_guard.py")
TTL = {"tracker": 300, "gh": 120}
GH_FIELDS = "number,state,isDraft,mergedAt,headRefName,headRefOid,statusCheckRollup,reviewDecision,mergeStateStatus"
DEFAULT_RESET_S = 600
RATE_LIMITED_RC = 4  # the tracker adapter's documented rate-limit exit code


def _json_obj(text):
    try:
        v = json.loads(text or "{}")
    except ValueError:
        return {}
    return v if isinstance(v, dict) else {}


def telemetry(row):
    try:
        os.makedirs(os.path.dirname(ANALYTICS), exist_ok=True)
        with open(ANALYTICS, "a") as fh:
            fh.write(json.dumps(dict({"ts": st.now_iso()}, **row), sort_keys=True) + "\n")
    except OSError:
        pass


# ---------- cache (R24) ----------

def cache_path(slug):
    return os.path.join(st.STATE_DIR, f"{slug}.json")


def read_cache(slug):
    try:
        with open(cache_path(slug)) as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def write_cache(slug, cache):
    """Non-blocking: when another writer holds the lock this write is skipped (the cache is disposable)."""
    p = cache_path(slug)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + ".lock", "a") as lk:
        try:
            fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        tmp = f"{p}.{os.getpid()}.tmp"
        with open(tmp, "w") as fh:
            json.dump(cache, fh)
        os.replace(tmp, p)
        fcntl.flock(lk, fcntl.LOCK_UN)
    return True


# ---------- tracker ----------

def tracker_cmd(manifest):
    m = manifest.get("map") or {}
    cmd = m.get("snapshot_cmd")
    if not cmd:
        return None, None
    argv = shlex.split(cmd) if isinstance(cmd, str) else list(cmd)
    return [a.replace("{map}", str(m.get("issue") or "")) for a in argv], m.get("snapshot_cwd")


def load_tracker(slug, manifest, cache, now, *, refresh=False, offline=False, runner=subprocess.run,
                 check=None):
    """-> (data|None, age_s|None, notes, pending_events). Mutates cache['tracker'] on a fetch.
    `check(data)` raises on an unknown schema major (fail closed)."""
    argv, cwd = tracker_cmd(manifest)
    tier = cache.get("tracker") or {}
    data, fetched = tier.get("data"), tier.get("fetched_at")
    age = (now - fetched) if fetched else None
    notes, events = [], []
    if not argv:
        return None, None, notes, events
    rl = cache.get("rate_limited_until") or 0
    if rl > now:
        events.append({"event": "linear-reset", "at": st.now_iso(rl)})
        notes.append("tracker_rate_limited")
        return data, age, notes, events
    if offline or (data is not None and age is not None and age < TTL["tracker"] and not refresh):
        if data is not None and check:
            check(data)
        return data, age, notes, events
    try:
        r = runner(argv, cwd=cwd, capture_output=True, text=True, timeout=90)
        rc, out, err = r.returncode, r.stdout, r.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        notes.append(f"tracker_error:{type(e).__name__}")
        return data, age, notes, events
    if rc != 0:
        # Producer contract: exit 4 = rate limited; with --json, stderr carries {error, code, type[, status,
        # rate_limited_until]} (rate_limited_until: ISO-8601 or null).
        rec = _json_obj((err or "").strip().splitlines()[-1] if (err or "").strip() else "")
        if rc == RATE_LIMITED_RC or rec.get("type") == "rate_limited":
            reset = rec.get("rate_limited_until")
            until = (st.parse_iso(reset) if reset else None) or now + DEFAULT_RESET_S
            cache["rate_limited_until"] = until
            events.append({"event": "linear-reset", "at": st.now_iso(until)})
            notes.append("tracker_rate_limited")
            telemetry({"program": slug, "source": "tracker", "event": "rate_limited", "until": st.now_iso(until),
                       "status": rec.get("status")})
        else:
            notes.append(f"tracker_error:rc={rc}" + (f":{rec['type']}" if rec.get("type") else ""))
        return data, age, notes, events
    body = _json_obj(out)
    if check:
        check(body)
    cache["tracker"] = {"data": body, "fetched_at": now}
    cache.pop("rate_limited_until", None)
    reqs = body.get("requests") or []
    telemetry({"program": slug, "source": "tracker", "requests": len(reqs),
               "x_complexity": [q.get("x_complexity") for q in reqs], "children_count": body.get("children_count")})
    return body, 0.0, notes, events


# ---------- GitHub ----------

def load_gh(slug, bindings, cache, now, *, refresh=False, offline=False, runner=subprocess.run):
    """-> ({"repo#n": row}, age_s|None, notes)."""
    pubs = [b["publication"] for b in bindings if "pr" in (b.get("publication") or {})]
    repos = sorted({p["repo"] for p in pubs})
    tiers, notes, ages = cache.setdefault("gh", {}), [], []
    for repo in repos:
        tier = tiers.get(repo) or {}
        age = now - tier["fetched_at"] if tier.get("fetched_at") else None
        if offline or (age is not None and age < TTL["gh"] and not refresh):
            if age is not None:
                ages.append(age)
            continue
        try:
            r = runner(["gh", "pr", "list", "--repo", repo, "--state", "all", "--limit", "100", "--json", GH_FIELDS],
                       capture_output=True, text=True, timeout=30)
            rows = json.loads(r.stdout) if r.returncode == 0 else None
        except (OSError, ValueError, subprocess.TimeoutExpired):
            rows = None
        if rows is None:
            notes.append(f"gh_error:{repo}")
            if age is not None:
                ages.append(age)
            continue
        have = {x.get("number") for x in rows}
        calls = 1
        for p in pubs:
            if p["repo"] == repo and p["pr"] not in have:
                try:
                    v = runner(["gh", "pr", "view", str(p["pr"]), "--repo", repo, "--json", GH_FIELDS],
                               capture_output=True, text=True, timeout=30)
                    if v.returncode == 0:
                        rows.append(json.loads(v.stdout))
                    calls += 1
                except (OSError, ValueError, subprocess.TimeoutExpired):
                    notes.append(f"gh_view_error:{repo}#{p['pr']}")
        tiers[repo] = {"data": rows, "fetched_at": now}
        ages.append(0.0)
        telemetry({"program": slug, "source": "gh", "repo": repo, "requests": calls})
    # `_age_s` is how old this row's read is, so a reader can tell a fresh fact from one carried forward.
    prs = {f"{repo}#{row.get('number')}": dict(row, _age_s=(now - tier["fetched_at"]) if tier.get("fetched_at") else None)
           for repo, tier in tiers.items() for row in tier.get("data") or []}
    return prs, (max(ages) if ages else None), notes


# ---------- local probes ----------

def ps_pids(pids, runner=subprocess.run):
    """One `ps` for every recorded pid -> {pid: normalized lstart}."""
    pids = sorted({int(p) for p in pids if p})
    if not pids:
        return {}
    try:
        out = runner(["ps", "-o", "pid=,lstart=", "-p", ",".join(map(str, pids))], capture_output=True,
                     text=True, timeout=2).stdout
    except (OSError, subprocess.TimeoutExpired):
        return {}
    res = {}
    for ln in out.splitlines():
        parts = ln.split(None, 1)
        if len(parts) == 2 and parts[0].isdigit():
            res[int(parts[0])] = " ".join(parts[1].split())
    return res


def git_probe(wt, runner=subprocess.run):
    if not wt or not os.path.isdir(wt):
        return {"gone": True}
    try:
        head = runner(["git", "-C", wt, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=2).stdout.strip()
        por = runner(["git", "-C", wt, "status", "--porcelain"], capture_output=True, text=True, timeout=2).stdout
    except (OSError, subprocess.TimeoutExpired):
        return {"timeout": True}
    return {"head": head, "paths": sorted(ln[3:] for ln in por.splitlines() if len(ln) > 3)}


def state_facts_file(state_path, runner=subprocess.run):
    """AT-WAKE facts via the guard's one parser (`manager_arm_guard.py --state-facts`), never a copy."""
    if not state_path or not os.path.isfile(state_path):
        return {}, ["no_state_file"]
    try:
        r = runner([sys_python(), "-I", GUARD_SCRIPT, "--state-facts", state_path], capture_output=True,
                   text=True, timeout=5)
        return json.loads(r.stdout), []
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {}, ["state_facts_unavailable"]


def sys_python():
    import sys
    return sys.executable or "python3"


# ---------- program context ----------

def program_scope(slug, rows, programs=None):
    """-> (manager sids, manager ids incl. CLI ids, family non-manager sids). Program identity is
    program_family's: exact-id resolution, plus the family's instances; absorbed programs' children
    count toward their absorber."""
    manifests = pf.load_manifests(programs)
    by_slug = {m["slug"]: m for m in manifests}
    fams = pf.families(rows, manifests)

    def managers_of(s):
        out = set((fams.get(s) or {}).get("managers") or [])
        for sid, row in rows.items():
            if pf.is_manager(row) and (pf.resolve_program(row, manifests) or {}).get("slug") == s:
                out.add(sid)
        return out

    slugs = [slug] + [a for a in ((by_slug.get(slug) or {}).get("absorbs") or []) if isinstance(a, str)]
    mgrs = set().union(*(managers_of(s) for s in slugs))
    lineage = set()
    for sid in rows:
        m = pf.root_manager(sid, rows)
        if m and m != sid and m in mgrs:
            lineage.add(sid)
    ids = set(mgrs) | {rows[s].get("cliSessionId") for s in mgrs if rows[s].get("cliSessionId")}
    return mgrs, ids, lineage


def build_ctx(slug, *, mode="snapshot", refresh=False, stdin_facts=None, programs=None, runner=subprocess.run,
              now=None, check=None):
    """-> (ctx, cache, manifest). mode 'guard': no network, no git, cached remote tiers at any age."""
    now = time.time() if now is None else now
    manifest = st.read_manifest(slug, programs)
    if "lanes" in manifest or "claims" in manifest:
        raise st.SchemaError("unmigrated: the manifest still holds `lanes` or `claims`; run work_state.py migrate")
    bindings = manifest.get("bindings") or []
    st.validate_bindings(bindings)
    cache = read_cache(slug)
    offline = mode == "guard"
    tracker, t_age, notes, events = load_tracker(slug, manifest, cache, now, refresh=refresh, offline=offline,
                                                 runner=runner, check=check)
    prs, gh_age, gh_notes = load_gh(slug, bindings, cache, now, refresh=refresh, offline=offline, runner=runner)
    notes += gh_notes
    rows = pf.session_index()
    mgrs, mgr_ids, lineage = program_scope(slug, rows, programs)
    lanes = st.read_lane_rows(now=now)
    pids = [r.get("pid") for r in lanes.values()] + [c.get("pid") for b in bindings for c in b["carriers"]]
    pmap = ps_pids(pids, runner=runner)
    outs = {c.get("outfile") for b in bindings for c in b["carriers"] if c.get("outfile")}
    outs |= {r.get("outfile") for r in lanes.values() if r.get("outfile")}
    outfiles = {o: os.path.exists(o) for o in outs}
    git = None
    if mode != "guard":
        wts = {b.get("worktree") for b in bindings if b.get("worktree")}
        for b in bindings:
            for c in b["carriers"]:
                if c["type"] == "lane":
                    wts.add((lanes.get(c["id"]) or {}).get("worktree"))
                if c["type"] == "session":
                    r = rows.get(c["id"]) or {}
                    wts.add(r.get("worktreePath") or r.get("cwd"))
        git = {}
        for wt in sorted(w for w in wts if w):
            git[wt] = git_probe(wt, runner=runner)
            if git[wt].get("gone"):
                notes.append(f"worktree_gone:{wt}")
    if stdin_facts is not None:
        facts, live_bg = stdin_facts.get("state_facts") or {}, stdin_facts.get("live_bg")
        live_bg = set(live_bg) if isinstance(live_bg, list) else None
    else:
        facts, fnotes = state_facts_file(st.manifest_path(slug, programs)[:-5] + ".state.md", runner=runner)
        notes += fnotes
        live_bg = None
    cli = {r.get("cliSessionId"): sid for sid, r in rows.items() if r.get("cliSessionId")}
    ownership = []
    for p in pf.load_manifests(programs or st.PROGRAMS):
        try:
            ownership.append(st.read_manifest(p["slug"], programs))
        except (OSError, ValueError):
            continue  # An unreadable owner must never manufacture a recipient.
    ctx = {"now": now, "slug": slug, "map_id": (manifest.get("map") or {}).get("issue"),
           "exit_criteria": (manifest.get("map") or {}).get("exit_criteria"),
           "absorbed": bool(manifest.get("absorbed_by")), "bindings": bindings, "tracker": tracker,
           "programs": ownership, "manager_session": manifest.get("manager_session") or manifest.get("orchestrator_session"),
           "tracker_age_s": t_age, "has_tracker_cmd": bool(tracker_cmd(manifest)[0]), "prs": prs, "gh_age_s": gh_age,
           "sessions": rows, "cli": cli, "family_sessions": lineage, "manager_ids": mgr_ids, "lanes": lanes, "proof_failures": lane_proof.failure_counts(),
           "pids": pmap, "outfiles": outfiles, "git": git, "state": facts, "live_bg": live_bg,
           "fp_cache": cache.get("fp") or {}, "ready_since": cache.get("ready_since") or {},
           "floor": st.migration_floor(slug, programs), "pending_events": events, "notes": notes}
    if ctx["floor"] is None:
        ctx["floor"] = now - 86400
        notes.append("no_migration_floor:using_24h")
    return ctx, cache, manifest
