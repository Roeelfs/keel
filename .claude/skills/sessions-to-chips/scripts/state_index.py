#!/usr/bin/env python3
"""state_index.py - the cross-program surface: each program's sidecar (a small projection of its page, read by
the index and by other programs' overlap check) and `index.state.html`, built from every sidecar with no
network. A failed source reads "unknown" on the index, never zero. Rules: ../specs/2026-11-03-manager-state-viewer.md
"""
import glob
import json
import os

import work_state_store as st

SCHEMA = "state-view/2"
SIDECAR_SCHEMA = "state-sidecar/1"
SIDECAR_BUDGET = 64_000
STALE_SIDECAR_S = 86400


def utc(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def ts(iso):
    try:
        return st.parse_iso(iso) if iso else None
    except ValueError:
        return None


def holdings(manifest, derived):
    """This program's open-PR files and bound paths, per repo. Missing files read 'unknown', never 'none'."""
    out = {}
    for r in derived["repos"]:
        mine = {str(p["number"]) for p in r["prs"] if p.get("state") == "OPEN" and p.get("number")}
        out[r["repo"]] = {"prs": {n: (r["open"].get(n) or {}).get("files") for n in sorted(mine)},
                          "files_known": bool(r["open"]) and bool(r.get("open_complete")), "paths": []}
    for b in manifest.get("bindings") or []:
        repo = (b.get("publication") or {}).get("repo") or (next(iter(out)) if len(out) == 1 else None)
        if b.get("paths") and repo:
            out.setdefault(repo, {"prs": {}, "files_known": False, "paths": []})["paths"] += b["paths"]
    return out


def live_program(manifest):
    return not manifest.get("absorbed_by") and str(manifest.get("status") or "").lower() not in ("done", "closed")


def other_sidecars(slug, now):
    rows = []
    for path in glob.glob(os.path.join(st.PROGRAMS, "*.state.json")):
        name = os.path.basename(path)[:-len(".state.json")]
        if name == slug:
            continue
        try:
            with open(path) as fh:
                data = json.load(fh)
            with open(st.manifest_path(name)) as fh:
                manifest = json.load(fh)
        except (OSError, ValueError):
            continue
        if data.get("schema") == SIDECAR_SCHEMA and live_program(manifest):
            rows.append(data)
    return rows


def compact_holdings(h):
    """Fit the sidecar budget: collapse file lists to their directories (a superset, so overlap stays honest)."""
    out = {}
    for repo, v in h.items():
        prs = {}
        for n, files in (v.get("prs") or {}).items():
            prs[n] = None if files is None else sorted({(os.path.dirname(f) or ".") + "/**" for f in files})
        out[repo] = dict(v, prs=prs, collapsed=True)
    return out


def sidecar(payload, hold):
    s = {"schema": SIDECAR_SCHEMA, "program": payload["program"], "generated_at": payload["generated_at"],
         "goal": payload.get("goal"), "next_landing": (payload["now"]["outcomes"] or [{}])[0].get("outcome"),
         "needs_you": len(payload["now"]["needs_you"]), "counts": payload["now"]["production"]["counts"],
         "problems": len(payload["problems"]), "held_by": [_held_text(h) for h in payload["now"]["held_by"]
                                                          if h["kind"] not in ("main",)][:5],
         "held_ids": sorted({x for h in payload["now"]["held_by"] for x in _held_ids(h)}),
         "tickets": sorted({i["ticket"] for i in payload["machinery"].get("items") or []}),
         "open_prs": sorted({f"{r['repo']}#{r['pr']}" for r in payload["now"]["production"]["rows"]
                             if r["ladder"]["step"] == "open"}),
         "overlap": payload["now"]["overlap"], "health": payload["machinery"]["health"], "holdings": hold,
         "stale": payload["stale"]["stale"]}
    text = json.dumps(s)
    if len(text) > SIDECAR_BUDGET:
        s["holdings"] = compact_holdings(hold)
        text = json.dumps(s)
    if len(text) > SIDECAR_BUDGET:
        s["holdings"] = {repo: dict(v, prs={n: None for n in v["prs"]}) for repo, v in s["holdings"].items()}
        s["holdings_dropped"] = True
    return s


def _held_text(h):
    if h["kind"] == "flag":
        return f"{h['flag']}:{h['id']}"
    if h["kind"] == "overlap":
        return f"overlap:{h['program']}"
    return f"{h['kind']}:{h.get('id') or h.get('what') or ''}"


def _held_ids(h):
    ids = [h.get("id")] + list(h.get("by") or [])
    return [x for x in ids if isinstance(x, str) and x]


def build_index(now):
    """Every sidecar, no network. One row per live program; stale and unrendered ones collapse."""
    rows, quiet, blockers = [], [], []
    sidecars = {}
    for path in sorted(glob.glob(os.path.join(st.PROGRAMS, "*.state.json"))):
        try:
            with open(path) as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        if data.get("schema") == SIDECAR_SCHEMA:
            sidecars[data["program"]] = data
    owners = {}
    for s in sidecars.values():
        for t in s.get("tickets") or []:
            owners.setdefault(t, s["program"])
        for pr in s.get("open_prs") or []:
            owners.setdefault(pr, s["program"])
    for path in sorted(glob.glob(os.path.join(st.PROGRAMS, "*.json"))):
        name = os.path.basename(path)[:-5]
        if "." in name:
            continue
        try:
            with open(path) as fh:
                manifest = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(manifest, dict) or "goal" not in manifest or not live_program(manifest):
            continue
        s = sidecars.get(name)
        if not s:
            quiet.append({"program": name, "why": "never rendered"})
            continue
        age = now.timestamp() - (ts(s["generated_at"]) or 0)
        busy = s.get("needs_you") or s.get("open_prs")
        if age > STALE_SIDECAR_S and not busy:
            quiet.append({"program": name, "why": "not rendered in 24 h", "age_s": int(age)})
            continue
        failed = [h["name"] for h in s.get("health") or [] if not h.get("ok")]
        rows.append({"program": name, "page": f"{name}.state.html", "age_s": int(age), "goal": s.get("goal"),
                     "next_landing": s.get("next_landing"), "needs_you": s.get("needs_you"), "counts": s.get("counts"),
                     "held_by": s.get("held_by") or [], "problems": s.get("problems"), "failed_sources": failed,
                     "stale": s.get("stale"), "aged": age > STALE_SIDECAR_S})
        for o in s.get("overlap") or []:
            if o["program"] in sidecars and s["program"] < o["program"]:
                blockers.append({"kind": "overlap", "a": s["program"], "b": o["program"], "repo": o["repo"],
                                 "paths": o["paths"][:5], "path_count": o["path_count"]})
        for x in s.get("held_ids") or []:
            other = owners.get(x)
            if other and other != name:
                blockers.append({"kind": "held", "a": name, "b": other, "id": x})
    return {"schema": SCHEMA, "kind": "index", "generated_at": utc(now), "rows": rows, "quiet": quiet,
            "blockers": blockers, "problems": []}
