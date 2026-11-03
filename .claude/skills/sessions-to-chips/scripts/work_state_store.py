#!/usr/bin/env python3
"""The binding record: its strict schema, and the ONLY write path for manifest `bindings`.

Owner of: the binding schema (`validate_binding`), atomic manifest writes under flock
(`<slug>.json.lock`), bind / carrier / retire, the `<slug>.events.jsonl` append, the lane row
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

HOME = os.environ.get("S2C_CLAUDE_HOME") or os.path.expanduser("~/.claude")
PROGRAMS = os.environ.get("WORK_STATE_PROGRAMS") or os.path.join(HOME, "orchestrator/programs")
STATE_DIR = os.environ.get("WORK_STATE_DIR") or os.path.join(HOME, "state/work-state")
LANE_ROWS = os.environ.get("WORK_STATE_LANE_ROWS") or os.path.join(HOME, "state/lane-parents.jsonl")
MANIFEST_CAP = 8192

CARRIER_TYPES = ("session", "lane", "agent", "workflow", "bg", "card", "wake", "founder")
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
            if k in seen_c:
                raise SchemaError(f"carrier {k} sits in two open bindings ({seen_c[k]}, {b['ticket']})")
            seen_c[k] = b["ticket"]
        if b.get("publication"):
            pk = publication_key(b["publication"])
            if pk in seen_pub:
                raise SchemaError(f"publication {pk} sits in two open bindings ({seen_pub[pk]}, {b['ticket']})")
            seen_pub[pk] = b["ticket"]


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
    """R2: append a launched carrier. Idempotent on (type, id); a carrier sits in at most one binding."""
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


def append_lane_row(lane, parent, runtime, model, pid, outfile, worktree, path=None, now=None):
    """The ONE lane-row writer (spawn-lane.sh and codex-dispatch.sh call `work_state.py lane-row`)."""
    row = {"lane": lane, "parent": parent, "runtime": runtime, "model": model, "pid": int(pid),
           "pid_start": pid_start(pid), "outfile": outfile or "", "worktree": worktree or "",
           "ts": now_iso(now)}
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
