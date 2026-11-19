#!/usr/bin/env python3
"""The binding record: its strict schema, and the ONLY write path for manifest `bindings`.

Owner of: the binding schema (`validate_binding`), atomic manifest writes under flock
(`<slug>.json.lock`), bind / carrier / retire, the fold record and its only writers (absorb,
close_mission, reopen_mission under the graph lock `folds.lock`), the `<slug>.events.jsonl` append, the told-waiter
record (`<slug>.notices.json`, `claim_notices`), the lane row
(`~/.claude/state/lane-parents.jsonl`) writer and its incremental reader.

Every reader of `bindings` goes through work_state.py, which imports this module. Other manifest
keys keep hand edits; re-read the manifest after any engine write. Ticket ids are opaque strings.
"""
import datetime as dt
import fcntl
import json
import os
import re
import time

import program_family as pf

HOME = os.environ.get("S2C_CLAUDE_HOME") or os.path.expanduser("~/.claude")
PROGRAMS = os.environ.get("WORK_STATE_PROGRAMS") or os.path.join(HOME, "orchestrator/programs")
STATE_DIR = os.environ.get("WORK_STATE_DIR") or os.path.join(HOME, "state/work-state")
LANE_ROWS = os.environ.get("WORK_STATE_LANE_ROWS") or os.path.join(HOME, "state/lane-parents.jsonl")
MANIFEST_CAP = 8192

# Wakes and bake due times are events, not writers; each may carry many bindings.
SHARED_CARRIERS = frozenset({"wake", "bake"})
CARRIER_TYPES = ("session", "lane", "agent", "workflow", "bg", "card", "wake", "founder", "bake")
RUNTIMES = ("claude", "codex")
ROOT_GLOBS = {"**", "*", "/", "**/*", "/**", "./**", "."}
SHA40 = re.compile(r"^[0-9a-f]{40}$")
RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")

BINDING_KEYS = {  # key: (type, required)
    "ticket": (str, True), "carriers": (list, True), "bound_at": (str, True), "bake": (str, True),
    "branch": (str, False), "worktree": (str, False), "artifact": (str, False),
    "publication": (dict, False), "carve_out": (bool, False), "paths": (list, False), "lease_s": (int, False),
}
CARRIER_KEYS = {
    "type": (str, True), "id": (str, True), "bound_at": (str, True), "runtime": (str, False),
    "model": (str, False), "wave": (str, False), "pid": (int, False), "pid_start": (str, False),
    "outfile": (str, False),
}


FOLD_KEYS = {"id": (str, True), "since": (str, True), "by": (str, True), "closed": (object, True)}
FOLD_CLOSED_KEYS = {"at": (str, True), "reason": (str, True)}


class SchemaError(ValueError):
    pass


def now_iso(t=None):
    return dt.datetime.fromtimestamp(t if t is not None else time.time(), dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    if not s:
        return 0.0
    t = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return (t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)).timestamp()


def _check_keys(obj, spec, where):
    if not isinstance(obj, dict):
        raise SchemaError(f"{where}: expected an object")
    unknown = sorted(set(obj) - set(spec))
    if unknown:
        raise SchemaError(f"{where}: unknown key(s) {unknown}")
    for k, (typ, req) in spec.items():
        if k not in obj:
            if req:
                raise SchemaError(f"{where}: missing required key {k!r}")
            continue
        v = obj[k]
        if typ is int and (isinstance(v, bool) or not isinstance(v, int)):
            raise SchemaError(f"{where}.{k}: expected int")
        if typ is not int and not isinstance(v, typ):
            raise SchemaError(f"{where}.{k}: expected {typ.__name__}")


def validate_publication(p, where="publication"):
    if not isinstance(p, dict) or not isinstance(p.get("repo"), str) or "/" not in p["repo"]:
        raise SchemaError(f"{where}: needs repo 'owner/name'")
    if "pr" in p:
        _check_keys(p, {"repo": (str, True), "pr": (int, True)}, where)
        if p["pr"] <= 0:
            raise SchemaError(f"{where}.pr: must be positive")
    else:
        _check_keys(p, {"repo": (str, True), "sha": (str, True), "via": (str, True)}, where)
        if p["via"] != "push" or not SHA40.match(p["sha"]):
            raise SchemaError(f"{where}: a push publication is {{repo, sha: <40 hex>, via: push}}")


def validate_carrier(c, where="carrier"):
    _check_keys(c, CARRIER_KEYS, where)
    if c["type"] not in CARRIER_TYPES:
        raise SchemaError(f"{where}.type: one of {CARRIER_TYPES}")
    if not c["id"]:
        raise SchemaError(f"{where}.id: empty")
    if "runtime" in c and c["runtime"] not in RUNTIMES:
        raise SchemaError(f"{where}.runtime: one of {RUNTIMES}")
    if not RFC3339.match(c["bound_at"]):
        raise SchemaError(f"{where}.bound_at: RFC3339 UTC (…Z)")
    if c["type"] == "bake":
        if not RFC3339.fullmatch(c["id"]):
            raise SchemaError(f"{where}: a bake carrier id is its RFC3339 UTC due time")
        try:
            parse_iso(c["id"])
        except ValueError as exc:
            raise SchemaError(f"{where}: invalid bake due time") from exc
    if c["type"] == "founder" and not RFC3339.match(c["id"]):
        raise SchemaError(f"{where}: a founder carrier id is the RFC3339 UTC time of the grill round")


def validate_binding(b, where="binding"):
    """The strict validator: an unknown key, a missing required key or a wrong type refuses."""
    _check_keys(b, BINDING_KEYS, where)
    if not b["ticket"]:
        raise SchemaError(f"{where}.ticket: empty")
    if not RFC3339.match(b["bound_at"]):
        raise SchemaError(f"{where}.bound_at: RFC3339 UTC (…Z)")
    bake = b["bake"]
    if bake != "required" and not (bake.startswith("none:") and bake[5:].strip()):
        raise SchemaError(f"{where}.bake: 'required' or 'none:<reason>' (reason non-empty)")
    for i, c in enumerate(b["carriers"]):
        validate_carrier(c, f"{where}.carriers[{i}]")
    if "publication" in b:
        validate_publication(b["publication"], f"{where}.publication")
    for p in b.get("paths") or []:
        if not isinstance(p, str) or p.strip() in ROOT_GLOBS:
            raise SchemaError(f"{where}.paths: root glob {p!r} refused (it collides with everything)")
    if "lease_s" in b and b["lease_s"] <= 0:
        raise SchemaError(f"{where}.lease_s: must be positive")


def validate_fold(f, where="fold"):
    """The strict fold-record validator. Writers only (absorb and the mission setters): the read path turns a bad
    record into the note `fold_malformed:<slug>` (program_family.fold_note) and never raises."""
    _check_keys(f, FOLD_KEYS, where)
    if not f["id"] or not f["by"]:
        raise SchemaError(f"{where}: id and by must be non-empty")
    if not RFC3339.match(f["since"]):
        raise SchemaError(f"{where}.since: RFC3339 UTC (…Z)")
    c = f["closed"]
    if c is not None:
        _check_keys(c, FOLD_CLOSED_KEYS, f"{where}.closed")
        if not RFC3339.match(c["at"]) or not c["reason"].strip():
            raise SchemaError(f"{where}.closed: {{at: RFC3339 UTC, reason: non-empty}} or null")


def validate_bindings(bindings):
    if not isinstance(bindings, list):
        raise SchemaError("bindings: expected a list")
    seen_t, seen_c, seen_pub = set(), {}, {}
    for i, b in enumerate(bindings):
        validate_binding(b, f"bindings[{i}]")
        if b["ticket"] in seen_t:
            raise SchemaError(f"bindings[{i}]: ticket {b['ticket']} already has an open binding")
        seen_t.add(b["ticket"])
        for c in b["carriers"]:
            k = (c["type"], c["id"])
            if c["type"] in SHARED_CARRIERS:
                continue  # one armed wake may carry several tickets
            if k in seen_c:
                raise SchemaError(f"carrier {k} sits in two open bindings ({seen_c[k]}, {b['ticket']})")
            seen_c[k] = b["ticket"]
        if b.get("publication"):
            pk = publication_key(b["publication"])
            if pk in seen_pub:
                raise SchemaError(f"publication {pk} sits in two open bindings ({seen_pub[pk]}, {b['ticket']})")
            seen_pub[pk] = b["ticket"]


REPO_KEYS = {
    "repo": (str, True), "path": (str, True), "ticket_pattern": (str, True), "main": (str, True),
    "surfaces": (list, True), "red_main_cmd": (object, False), "red_main_unproven": (str, False),
    "security_paths": (list, False),
}
SURFACE_KEYS = {
    "name": (str, True), "kind": (str, True), "environment": (str, False), "proof_step": (str, False),
    "workflow": (str, False), "job": (str, False), "paths": (list, True), "unproven": (str, False),
}


def _str_list(v, where):
    if not all(isinstance(x, str) and x.strip() for x in v):
        raise SchemaError(f"{where}: every entry must be a non-empty string")
    bad = [x for x in v if x != x.strip() or re.search(r"[\s'\"]", x) or x.startswith(("- ", "/", "./"))]
    if bad:
        raise SchemaError(f"{where}: {bad[0]!r} is not a repo-relative glob (quotes, spaces or a list marker would match nothing)")


def validate_repo(r, where="repos[0]"):
    """One manifest `repos` entry: the only place a repo, its surfaces and its red-main command are named.
    Strict like validate_binding. Called by the state renderer only, never inside _Locked.write, so a bad
    hand edit shows as a Problems row and never blocks bind or retire."""
    _check_keys(r, REPO_KEYS, where)
    if "/" not in r["repo"] or r["repo"].count("/") != 1:
        raise SchemaError(f"{where}.repo: 'owner/name'")
    try:
        re.compile(r["ticket_pattern"])
    except re.error as exc:
        raise SchemaError(f"{where}.ticket_pattern: not a regex ({exc})") from None
    cmd = r.get("red_main_cmd")
    if cmd is not None and not (isinstance(cmd, list) and cmd and all(isinstance(x, str) for x in cmd)):
        raise SchemaError(f"{where}.red_main_cmd: null or an argv list of strings")
    _str_list(r.get("security_paths") or [], f"{where}.security_paths")
    names = set()
    for i, s in enumerate(r["surfaces"]):
        sw = f"{where}.surfaces[{i}]"
        _check_keys(s, SURFACE_KEYS, sw)
        if s["name"] in names:
            raise SchemaError(f"{sw}.name: {s['name']!r} is listed twice")
        names.add(s["name"])
        _str_list(s["paths"], f"{sw}.paths")
        if s["kind"] == "deployment":
            if not s.get("environment"):
                raise SchemaError(f"{sw}: a deployment surface needs `environment`")
        elif s["kind"] == "job":
            if not (s.get("workflow") and s.get("job") and s.get("proof_step")):
                raise SchemaError(f"{sw}: a job surface needs `workflow`, `job` and `proof_step`")
        else:
            raise SchemaError(f"{sw}.kind: 'deployment' or 'job'")


def validate_repos(repos):
    """-> (valid entries, [error text]). Each entry is judged alone, so one bad entry hides only itself."""
    if not isinstance(repos, list):
        return [], ["repos: expected a list"]
    good, errors, seen = [], [], set()
    for i, r in enumerate(repos):
        try:
            validate_repo(r, f"repos[{i}]")
            if r["repo"] in seen:
                raise SchemaError(f"repos[{i}]: {r['repo']} is listed twice")
            seen.add(r["repo"])
            good.append(r)
        except SchemaError as exc:
            errors.append(str(exc))
    return good, errors


def publication_key(p):
    return f"{p['repo']}#{p['pr']}" if "pr" in p else f"{p['repo']}@{p['sha']}"


# ---------- manifest IO ----------

def manifest_path(slug, programs=None):
    return os.path.join(programs or PROGRAMS, f"{slug}.json")


def events_path(slug, programs=None):
    return os.path.join(programs or PROGRAMS, f"{slug}.events.jsonl")


def read_manifest(slug, programs=None):
    with open(manifest_path(slug, programs)) as fh:
        return json.load(fh)


class _Locked:
    """Exclusive flock on <slug>.json.lock for one read-modify-write of the manifest."""

    def __init__(self, slug, programs=None):
        self.path = manifest_path(slug, programs)
        self.lock = self.path + ".lock"

    def __enter__(self):
        self.fh = open(self.lock, "a")
        fcntl.flock(self.fh, fcntl.LOCK_EX)
        with open(self.path) as fh:
            self.manifest = json.load(fh)
        return self

    def write(self, manifest):
        if "bindings" in manifest:
            validate_bindings(manifest["bindings"])
        text = json.dumps(manifest, indent=2) + "\n"
        tmp = f"{self.path}.{os.getpid()}.tmp"
        with open(tmp, "w") as fh:
            fh.write(text)
        os.replace(tmp, self.path)
        self.manifest = manifest
        return len(text.encode())

    def __exit__(self, *exc):
        fcntl.flock(self.fh, fcntl.LOCK_UN)
        self.fh.close()


def append_event(slug, row, programs=None):
    row = dict({"ts": now_iso()}, **row)
    with open(events_path(slug, programs), "a") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
    return row


def notices_path(slug, programs=None):
    return os.path.join(programs or PROGRAMS, f"{slug}.notices.json")


def claim_notices(slug, closed, keep, programs=None):
    """Once per blocker closure. `closed` maps 'waiter|blocker' -> how the blocker ended, for every edge
    whose blocker is closed now; `keep(key, ended)` says whether an already-told edge stays told. Under an
    exclusive lock: return the keys not told yet, append one `waiter-notice` event each, and write the
    record (kept told keys plus `closed`). A forgotten edge (its blocker reopened) is told again on its
    next closure."""
    path = notices_path(slug, programs)
    with open(path + ".lock", "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            with open(path) as fh:
                told = json.load(fh)
        except (OSError, ValueError):
            told = {}
        fresh = sorted(k for k in closed if k not in told)
        for k in fresh:
            waiter, blocker = k.split("|", 1)
            append_event(slug, {"event": "waiter-notice", "waiter": waiter, "blocker": blocker,
                                "ended": closed[k]}, programs)
        record = dict({k: v for k, v in told.items() if keep(k, v)}, **closed)
        if record != told:
            tmp = f"{path}.{os.getpid()}.tmp"
            with open(tmp, "w") as fh:
                json.dump(record, fh, indent=2, sort_keys=True)
            os.replace(tmp, path)
        fcntl.flock(lk, fcntl.LOCK_UN)
    return fresh


def size_note(nbytes):
    return f"manifest {nbytes} B is over 85% of {MANIFEST_CAP} B" if nbytes > 0.85 * MANIFEST_CAP else None


def _with_bindings(m):
    if "lanes" in m or "claims" in m:
        raise SchemaError("unmigrated: the manifest still holds `lanes` or `claims`; run work_state.py migrate first")
    return [dict(b) for b in m.get("bindings") or []]


def bind(slug, ticket, *, children, map_id, bake="required", branch=None, worktree=None, artifact=None,
         publication=None, carve_out=False, paths=None, lease_s=None, cont=False, programs=None, now=None):
    """R2: write the binding with carriers [] BEFORE launch. `children` is the set of map child ids
    from the tracker snapshot (or None when the tracker is unavailable: then only the map itself and
    tickets already bound are accepted). Returns (binding, notes)."""
    now = time.time() if now is None else now
    if ticket != map_id and (children is None or ticket not in children):
        raise SchemaError(f"bind: {ticket} is not a child of map {map_id}" +
                          (" (tracker snapshot unavailable)" if children is None else ""))
    other = family_duplicate(slug, ticket, programs)
    if other:
        raise SchemaError(f"bind: {ticket} is already bound open in {other}, in the same fold family")
    with _Locked(slug, programs) as lk:
        bs = _with_bindings(lk.manifest)
        cur = next((b for b in bs if b["ticket"] == ticket), None)
        if cur and not cont:
            raise SchemaError(f"bind: {ticket} already has an open binding (pass --continue to update it)")
        new = dict(cur) if cur else {"ticket": ticket, "carriers": [], "bound_at": now_iso(now), "bake": bake}
        if not cur or bake != "required":
            new["bake"] = bake
        for k, v in (("branch", branch), ("worktree", worktree), ("artifact", artifact),
                     ("publication", publication), ("paths", paths), ("lease_s", lease_s)):
            if v is not None:
                new[k] = v
        if carve_out:
            new["carve_out"] = True
        validate_binding(new)
        bs = [new if b["ticket"] == ticket else b for b in bs] if cur else bs + [new]
        m = dict(lk.manifest, bindings=bs)
        n = lk.write(m)
    return new, [x for x in (size_note(n),) if x]


def carrier(slug, ticket, ctype, cid, *, programs=None, now=None, **fields):
    """R2: append a launched carrier. Idempotent on (type, id); a carrier sits in at most one binding,
    except event carriers (SHARED_CARRIERS), which may carry several."""
    now = time.time() if now is None else now
    c = {"type": ctype, "id": cid, "bound_at": now_iso(now)}
    c.update({k: v for k, v in fields.items() if v is not None})
    validate_carrier(c)
    with _Locked(slug, programs) as lk:
        bs = _with_bindings(lk.manifest)
        b = next((x for x in bs if x["ticket"] == ticket), None)
        if not b:
            raise SchemaError(f"carrier: {ticket} has no open binding (bind it first)")
        if any((x["type"], x["id"]) == (ctype, cid) for x in b["carriers"]):
            return b, ["carrier already bound (idempotent)"]
        b = dict(b, carriers=b["carriers"] + [c])
        bs = [b if x["ticket"] == ticket else x for x in bs]
        n = lk.write(dict(lk.manifest, bindings=bs))
    return b, [x for x in (size_note(n),) if x]


def retire(slug, ticket, *, carrier_ids=None, merge_sha=None, verdict=None, reason="", allow=None,
           programs=None):
    """R5. With carrier_ids: retire only those carriers (program-overhead pruning, R4). Otherwise the
    whole binding goes to `<slug>.events.jsonl` as `binding-retired` with its merge SHA and verdict.
    `allow(binding)` is the caller's R5 predicate (closed ticket, or the bake binding exists)."""
    with _Locked(slug, programs) as lk:
        bs = _with_bindings(lk.manifest)
        b = next((x for x in bs if x["ticket"] == ticket), None)
        if not b:
            raise SchemaError(f"retire: {ticket} has no open binding")
        if carrier_ids:
            keep = [c for c in b["carriers"] if c["id"] not in set(carrier_ids)]
            gone = [c for c in b["carriers"] if c["id"] in set(carrier_ids)]
            b2 = dict(b, carriers=keep)
            lk.write(dict(lk.manifest, bindings=[b2 if x["ticket"] == ticket else x for x in bs]))
            append_event(slug, {"event": "carrier-retired", "lane": ticket, "carriers": gone, "note": reason}, programs)
            return b2
        if allow is not None:
            ok, why = allow(b)
            if not ok:
                raise SchemaError(f"retire refused: {why}")
        lk.write(dict(lk.manifest, bindings=[x for x in bs if x["ticket"] != ticket]))
    append_event(slug, {"event": "binding-retired", "lane": ticket, "binding": b, "merge_sha": merge_sha,
                        "verdict": verdict, "note": reason}, programs)
    return b


# ---------- the fold record (row 11): `absorbed_by` + `fold` on the absorbed manifest ----------

class _GraphLock:
    """Exclusive flock on <programs>/folds.lock, taken FIRST by every fold writer (absorb, the mission setters,
    each `migrate --folds` write pass), so the fold graph is read and changed by one writer at a time. Re-entrant
    within a process: a migration pass holds it across many absorb calls. Binding writers never take it."""
    _held = {}

    def __init__(self, programs=None):
        self.path = os.path.join(programs or PROGRAMS, "folds.lock")

    def __enter__(self):
        depth = self._held.get(self.path)
        if depth:
            self._held[self.path] = (depth[0], depth[1] + 1)
            return self
        fh = open(self.path, "a")
        fcntl.flock(fh, fcntl.LOCK_EX)
        self._held[self.path] = (fh, 1)
        return self

    def __exit__(self, *exc):
        fh, n = self._held[self.path]
        if n > 1:
            self._held[self.path] = (fh, n - 1)
            return
        del self._held[self.path]
        fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()


def read_all(programs=None):
    """{slug: manifest} for every program manifest, read fresh (variant snapshots `<slug>.<x>.json` skipped)."""
    import glob
    out = {}
    for f in sorted(glob.glob(os.path.join(programs or PROGRAMS, "*.json"))):
        slug = os.path.basename(f)[:-5]
        if "." in slug:
            continue
        try:
            with open(f) as fh:
                m = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(m, dict) and m.get("program"):
            out[slug] = dict(m, program=slug)
    return out


def destination_ok(owner, manifests):
    """-> (ok, why). An owner may hold an open mission only when its manifest exists, is not absorbed, is not
    DONE or CLOSED, and names a manager_session. Runs on every mutation that leaves an open mission under it."""
    m = manifests.get(owner) if owner else None
    if m is None:
        return False, f"{owner or '(no owner)'} has no manifest"
    if m.get("absorbed_by"):
        return False, f"{owner} is itself absorbed by {m['absorbed_by']}"
    if str(m.get("status") or "").strip().upper() in ("DONE", "CLOSED"):
        return False, f"{owner} is {str(m.get('status')).upper()}"
    if not (m.get("manager_session") or "").strip():
        return False, f"{owner} names no manager_session"
    return True, ""


def _log_rows(slug, programs=None):
    try:
        with open(events_path(slug, programs)) as fh:
            lines = fh.read().splitlines()
    except OSError:
        return []
    out = []
    for ln in lines:
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if isinstance(r, dict):
            out.append(r)
    return out


def _absorb_events(absorbed, absorber, fold, programs=None):
    """Append the `absorb` row carrying fold.id to whichever of the two logs lacks it. -> slugs appended to."""
    row = {"event": "absorb", "fold_id": fold["id"], "from": absorbed, "into": absorber, "by": fold["by"],
           "closed": fold["closed"]}
    done = []
    for slug in (absorbed, absorber):
        if not any(r.get("event") == "absorb" and r.get("fold_id") == fold["id"] for r in _log_rows(slug, programs)):
            append_event(slug, row, programs)
            done.append(slug)
    return done


def _valid_fold(m):
    try:
        validate_fold(m.get("fold"))
        return True
    except SchemaError:
        return False


def absorb(absorber, absorbed, *, by, closed_reason=None, now=None, programs=None):
    """Fold `absorbed` into `absorber`: the ONE writer of `absorbed_by`, `fold` and the `absorbs` mirror.
    Under the graph lock: a committed fold (absorbed_by == absorber with a valid fold) only completes its events;
    otherwise admission, then (1) the string mirror on the terminal owner, (2) absorbed_by + fold on the absorbed
    manifest (the commit point), (3) one `absorb` row per log. -> {fold_id, wrote, events, notes}."""
    now = time.time() if now is None else now
    if not (by or "").strip():
        raise SchemaError("absorb: --by <session id> is required")
    with _GraphLock(programs):
        ms = read_all(programs)
        if absorbed not in ms:
            raise SchemaError(f"absorb: no manifest for {absorbed}")
        if absorber not in ms:
            raise SchemaError(f"absorb: no manifest for {absorber}")
        src = ms[absorbed]
        if src.get("absorbed_by") == absorber and _valid_fold(src):
            return {"fold_id": src["fold"]["id"], "wrote": False, "notes": ["retry: fold already committed"],
                    "events": _absorb_events(absorbed, absorber, src["fold"], programs)}
        repair = src.get("absorbed_by") == absorber  # the pre-spec hand edit: pointer present, no valid fold
        if absorbed == absorber:
            raise SchemaError("absorb refused: a program cannot absorb itself")
        chain, note = pf.fold_chain(absorber, ms)
        if absorbed in chain:
            raise SchemaError(f"absorb refused: cycle ({' -> '.join(chain)} -> {absorbed} already)")
        if note:
            raise SchemaError(f"absorb refused: {absorber}'s fold chain is broken ({note})")
        owner = chain[-1]
        if owner != absorber and not repair:
            raise SchemaError(f"absorb refused: {absorber} is itself absorbed; fold into {owner} instead")
        if src.get("absorbed_by") and not repair:
            raise SchemaError(f"absorb refused: {absorbed} is already absorbed by {src['absorbed_by']}")
        if not (src.get("goal") or "").strip():
            raise SchemaError(f"absorb refused: {absorbed} has no goal, so there is no mission to carry")
        family = pf.fold_family(absorbed, ms)
        inherited = [s for s in family if pf.mission_open(ms[s])]
        if closed_reason is None or inherited:
            ok, why = destination_ok(owner, ms)
            if not ok:
                missions = ([absorbed] if closed_reason is None else []) + inherited
                raise SchemaError(f"absorb refused: open mission(s) {', '.join(missions)} cannot move under {owner} "
                                  f"({why}). Close each first (work_state.py mission-close), or pick another absorber.")
        notes = [] if (src.get("map") or {}).get("snapshot_cmd") else [f"fold_no_tracker:{absorbed}"]
        since = now_iso(now)
        fold = {"id": f"{absorbed}@{since}", "since": since, "by": by,
                "closed": None if closed_reason is None else {"at": since, "reason": closed_reason}}
        validate_fold(fold)
        with _Locked(owner, programs) as lk:
            cur = list(lk.manifest.get("absorbs") or [])
            add = [s for s in [absorbed] + family if s not in cur]
            if add:
                lk.write(dict(lk.manifest, absorbs=cur + add))
        with _Locked(absorbed, programs) as lk:
            lk.write(dict(lk.manifest, absorbed_by=absorber, fold=fold))
        return {"fold_id": fold["id"], "wrote": True, "notes": notes + (["repair: fold record written"] if repair else []),
                "events": _absorb_events(absorbed, absorber, fold, programs)}


MISSION_EVENTS = ("mission-close", "mission-reopen")


def _set_mission(mission, reason, closing, now=None, programs=None):
    now = time.time() if now is None else now
    if not (reason or "").strip():
        raise SchemaError("mission: --reason is required (evidence for a close, why for a reopen)")
    with _GraphLock(programs):
        ms = read_all(programs)
        m = ms.get(mission)
        if m is None:
            raise SchemaError(f"mission: no manifest for {mission}")
        if not m.get("absorbed_by") or not _valid_fold(m):
            raise SchemaError(f"mission: {mission} has no fold record; run work_state.py absorb --program "
                              f"<owner> --from {mission} first")
        is_closed = m["fold"]["closed"] is not None
        wrote = False
        if is_closed != closing:
            if not closing:
                owner = pf.terminal_owner(mission, ms)
                ok, why = destination_ok(owner, ms)
                if not ok:
                    raise SchemaError(f"mission-reopen refused: {why}. Fold {mission} into a live owner first.")
            closed = {"at": now_iso(now), "reason": reason} if closing else None
            fold = dict(m["fold"], closed=closed)
            validate_fold(fold)
            with _Locked(mission, programs) as lk:
                lk.write(dict(lk.manifest, fold=fold))
            wrote = True
        name = MISSION_EVENTS[0] if closing else MISSION_EVENTS[1]
        logged = []
        for slug in (mission, m["absorbed_by"]):
            last = [r for r in _log_rows(slug, programs) if r.get("event") in MISSION_EVENTS
                    and r.get("mission") == mission]
            if not last or last[-1]["event"] != name:
                append_event(slug, {"event": name, "mission": mission, "fold_id": m["fold"]["id"],
                                    "reason": reason}, programs)
                logged.append(slug)
        return {"mission": mission, "closed": closing, "wrote": wrote, "events": logged}


def close_mission(mission, reason, *, now=None, programs=None):
    """Idempotent setter of fold.closed. A founder decision to park the goal is a close naming the founder."""
    return _set_mission(mission, reason, True, now, programs)


def reopen_mission(mission, reason, *, now=None, programs=None):
    """Idempotent setter of fold.closed = null, only under an owner destination_ok accepts."""
    return _set_mission(mission, reason, False, now, programs)


def family_duplicate(slug, ticket, programs=None):
    """The other manifest of `slug`'s fold family that already holds `ticket` open, or None. An unlocked
    best-effort read: a race only yields the engine's `fold_duplicate` note."""
    ms = read_all(programs)
    owner = pf.terminal_owner(slug, ms)
    if owner is None:
        return None
    for s in [owner] + pf.fold_family(owner, ms):
        if s != slug and any(b.get("ticket") == ticket for b in ms[s].get("bindings") or []):
            return s
    return None


def migration_floor(slug, programs=None):
    """The first `migrated` event's time: the UNBOUND floor (R22, R36). None when never migrated."""
    try:
        with open(events_path(slug, programs)) as fh:
            for ln in fh:
                if '"migrated"' not in ln:
                    continue
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                if r.get("event") == "migrated":
                    return parse_iso(r.get("ts"))
    except OSError:
        pass
    return None


# ---------- lane rows (R34) ----------

def pid_start(pid):
    """`ps -o lstart=` for one pid, whitespace-normalized; '' when gone."""
    import subprocess
    try:
        out = subprocess.run(["ps", "-o", "lstart=", "-p", str(int(pid))], capture_output=True, text=True,
                             timeout=2).stdout
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return ""
    return " ".join(out.split())


def append_lane_row(lane, parent, runtime, model, pid, outfile, worktree, path=None, now=None,
                    account_preferred=None):
    """The ONE lane-row writer (spawn-lane.sh and codex-dispatch.sh call `work_state.py lane-row`).
    `account_preferred` is a boolean only (is the lane's terminal Claude login the preferred
    account?); None means unknown and is omitted. Never an email: the account name stays private."""
    row = {"lane": lane, "parent": parent, "runtime": runtime, "model": model, "pid": int(pid),
           "pid_start": pid_start(pid), "outfile": outfile or "", "worktree": worktree or "",
           "ts": now_iso(now)}
    if account_preferred is not None:
        row["account_preferred"] = bool(account_preferred)
    path = path or LANE_ROWS
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.write(json.dumps(row) + "\n")
        fcntl.flock(fh, fcntl.LOCK_UN)
    return row


def read_lane_rows(path=None, cache_path=None, now=None, keep_days=30):
    """-> {lane: row}, full rows only (legacy rows without a pid are ignored). Reads from the cached
    byte offset; a truncated or rotated file restarts from 0."""
    path, cache_path = path or LANE_ROWS, cache_path or os.path.join(STATE_DIR, "lanes.json")
    now = time.time() if now is None else now
    try:
        with open(cache_path) as fh:
            cache = json.load(fh)
    except (OSError, ValueError):
        cache = {}
    try:
        st = os.stat(path)
    except OSError:
        return {}
    off, rows = int(cache.get("offset") or 0), dict(cache.get("rows") or {})
    if cache.get("ino") != st.st_ino or off > st.st_size:
        off, rows = 0, {}
    if off < st.st_size:
        with open(path, "rb") as fh:
            fh.seek(off)
            chunk = fh.read()
        end = chunk.rfind(b"\n") + 1
        for ln in chunk[:end].splitlines():
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if isinstance(r, dict) and r.get("lane") and isinstance(r.get("pid"), int):
                rows[r["lane"]] = r
        off += end
        floor = now - keep_days * 86400
        rows = {k: v for k, v in rows.items() if parse_iso(v.get("ts")) >= floor}
        try:
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            tmp = f"{cache_path}.{os.getpid()}.tmp"
            with open(tmp, "w") as fh:
                json.dump({"offset": off, "ino": st.st_ino, "rows": rows}, fh)
            os.replace(tmp, cache_path)
        except OSError:
            pass
    return rows
