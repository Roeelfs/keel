#!/usr/bin/env python3
"""R36 migration: manifest `lanes` + `claims` -> `bindings` + `<slug>.events.jsonl`, no dual path.

`migrate --all --dry-run` prints the census per manifest that feeds V1. A real migrate writes a
program only when it has nothing left for a human-run tracker step: every live lane with no
ticket, every `Owed:` / `UNBAKED` ship, every `stacked_on` edge and every inferred-ship back-label
is a `todo` the manager completes with its tracker adapter, then re-runs with `--ticket-for` /
`--resolved`. The engine itself writes no tracker state (it reaches the tracker only through
`map.snapshot_cmd`). A `snapshot_cmd` naming a relative path needs `map.snapshot_cwd`: without it the adapter
runs from the caller's cwd and fails (`tracker_error:rc=1`), so that gap is a `todo` too.

Ticket identity: a lane entry's ticket is a map child id found in its `name`, `where` or
`artifact`; with no cached tracker tier the generic id shape is used and counted `unverified`.
"""
import glob
import json
import os
import re
import shlex
import time

import program_family as pf
import work_state_sources as src
import work_state_store as st

ID_SHAPE = re.compile(r"\b[A-Z][A-Z0-9]{0,9}-\d{1,6}\b")
TERMINAL = re.compile(r"^\s*(done|complete|completed|merged|retired|integrated|absorbed|transferred|terminal|"
                      r"accepted|closed|cancel)", re.I)
NOT_STARTED = re.compile(r"^\s*(proposed|not started|unspawned|definition)", re.I)
OWED = re.compile(r"\b(owed|unbaked|merged[- ]unbaked)\b", re.I)
STALE_S = 86400


def _lanes(m):
    lanes = m.get("lanes")
    if isinstance(lanes, dict):
        lanes = list(lanes.values())
    return [x for x in lanes or [] if isinstance(x, dict)]


def _ticket(entry, children):
    hay = " ".join(str(entry.get(k) or "") for k in ("name", "where", "artifact", "issue"))
    ids = ID_SHAPE.findall(hay)
    if children is not None:
        hits = [i for i in ids if i in children]
        return (hits[0], True) if hits else (None, True)
    return (ids[0], False) if ids else (None, False)


def _carrier(entry, now_iso):
    """Best-effort carrier from a lane entry: a recorded session / task / bash id. None when the entry
    names none (the binding starts with carriers [] and surfaces as STALLED(c) for salvage)."""
    where = str(entry.get("where") or entry.get("session_or_branch") or "")
    m = re.search(r"local_[0-9a-f-]{8,}", where)
    if m:
        return {"type": "session", "id": m.group(0), "bound_at": now_iso}
    for key, typ in (("task_id", "agent"), ("bash_id", "bg")):
        if entry.get(key):
            return {"type": typ, "id": str(entry[key]), "bound_at": now_iso}
    return None


def relative_snapshot_cmd(map_):
    """True when `snapshot_cmd` names a relative path and no `snapshot_cwd` anchors it."""
    cmd = (map_ or {}).get("snapshot_cmd")
    if not cmd or (map_ or {}).get("snapshot_cwd"):
        return False
    argv = shlex.split(cmd) if isinstance(cmd, str) else [str(a) for a in cmd]
    return any("/" in a and not a.startswith(("/", "~", "-", "{")) and "://" not in a for a in argv)


def _owed_tickets(state_text, children):
    out = []
    in_owed = False
    for ln in state_text.splitlines():
        if ln.startswith("## "):
            in_owed = ln.strip().lower().startswith("## owed")
            continue
        if in_owed or OWED.search(ln):
            for i in ID_SHAPE.findall(ln):
                if (children is None or i in children) and i not in out:
                    out.append(i)
    return out


def _children_from_cache(slug):
    data = (src.read_cache(slug).get("tracker") or {}).get("data")
    return ({c["ticket"] for c in data.get("children") or []}, data) if data else (None, None)


def _bake_owed(owed, tracker, bindings, gh_rows, unverified):
    """Keep only owed tickets that really owe a bake: an open ship (not Done, canceled or duplicate; an
    inferred kind is no evidence, since an unlabelled ship reads as an inferred task),
    with no bake child already filed, whose bound PR (when the gh tier has it) is merged.
    -> (kept, [(ticket, why skipped)]); a kept ticket with no merge evidence (no gh row, no push
    publication) is added to `unverified`. With no tracker tier nothing can be checked: all are kept."""
    if not tracker:
        unverified.update(owed)
        return list(owed), []
    kids = {c["ticket"]: c for c in tracker.get("children") or []}
    pub = {b["ticket"]: b.get("publication") or {} for b in bindings}
    keep, skipped = [], []
    for t in owed:
        c = kids.get(t) or {}
        stype = (c.get("state") or {}).get("type")
        bake = [k["ticket"] for k in kids.values() if k.get("kind") == "bake"
                and any(b.get("ticket") == t for b in k.get("blocked_by") or [])]
        p = pub.get(t) or {}
        row = (gh_rows or {}).get(f"{p.get('repo')}#{p.get('pr')}") if "pr" in p else None
        why = ("not a map ticket" if not c else
               f"kind {c.get('kind')}, not a ship" if c.get("kind") != "ship" and not c.get("kind_inferred") else
               f"ticket already {(c.get('state') or {}).get('name')}" if stype in ("completed", "canceled", "duplicate") else
               f"bake child {bake[0]} already filed" if bake else
               f"PR {p.get('repo')}#{p.get('pr')} not merged" if row is not None and not row.get("mergedAt") else None)
        if why:
            skipped.append((t, why))
        elif row is not None or p.get("via") == "push":
            keep.append(t)
        else:
            unverified.add(t)
            keep.append(t)
    return keep, skipped


def plan(slug, manifest, *, state_text="", children=None, tracker=None, live_manager=False, now=None,
         ticket_for=None, resolved=(), gh_rows=None):
    """Pure plan for one manifest -> {bindings, events, todo, census}."""
    now = time.time() if now is None else now
    now_iso = st.now_iso(now)
    ticket_for, resolved = ticket_for or {}, set(resolved)
    map_id = (manifest.get("map") or {}).get("issue")
    stale = str(manifest.get("status") or "").lower() == "done" or (
        now - st.parse_iso(manifest.get("updated_at") or "1970-01-01T00:00:00Z") > STALE_S and not live_manager)
    bindings, events, todo = list(manifest.get("bindings") or []), [], []
    bound = {b["ticket"] for b in bindings}
    unverified = unbound = 0
    for e in _lanes(manifest):
        status = str(e.get("status") or "")
        terminal = bool(TERMINAL.match(status) or e.get("integratedAs") or e.get("integrated_as"))
        ticket, verified = _ticket(e, children)
        ticket = ticket_for.get(str(e.get("name") or "")) or ticket
        unverified += bool(ticket and not verified)
        if stale or terminal:
            events.append({"event": "lane-migrated", "lane": e.get("name"), "entry": e,
                           "note": "program stale or done" if stale and not terminal else "terminal entry"})
            continue
        if e.get("stacked_on") and f"blocks:{e['stacked_on']}:{ticket}" not in resolved:
            todo.append({"key": f"blocks:{e['stacked_on']}:{ticket}", "do": "ticket-adopt --blocked-by "
                         f"<ship of {e['stacked_on']}> on {ticket or e.get('name')} (ship -> ship relation)"})
        if not ticket:
            if not map_id:
                unbound += 1
                events.append({"event": "lane-migrated", "lane": e.get("name"), "entry": e,
                               "note": "no map: surfaces as UNBOUND with fix 'create the map'"})
                continue
            todo.append({"key": f"ticket:{e.get('name')}", "do": f"ticket-add under {map_id} for lane "
                         f"{e.get('name')!r}, then re-run migrate --ticket-for '{e.get('name')}=<id>'"})
            continue
        if NOT_STARTED.match(status):
            events.append({"event": "lane-migrated", "lane": e.get("name"), "entry": e,
                           "note": f"never dispatched: {ticket} stays a ready ticket"})
            continue
        if ticket in bound:
            events.append({"event": "lane-migrated", "lane": e.get("name"), "entry": e,
                           "note": f"second live entry on {ticket}: folded into its binding"})
            continue
        c = _carrier(e, now_iso)
        if e.get("model") and c:
            c["model"] = str(e["model"])
        b = {"ticket": ticket, "carriers": [c] if c else [], "bound_at": now_iso, "bake": "required"}
        if e.get("artifact"):
            b["artifact"] = str(e["artifact"])[:400]
        where = str(e.get("where") or "")
        if where.startswith("/"):
            b["worktree"] = where.split()[0]
        elif re.match(r"^[\w.-]+/[\w./-]+$", where):
            b["branch"] = where
        bindings.append(b)
        bound.add(ticket)
    owed = _owed_tickets(state_text, children)
    if stale and owed:
        events.append({"event": "owed-prose", "tickets": owed,
                       "note": "stale or done program: Owed/UNBAKED prose kept as an event, no bake tickets filed"})
        owed = []
    unverified = set()
    owed, bake_skipped = _bake_owed(owed, tracker, bindings, gh_rows, unverified)
    for t in owed:
        if f"bake:{t}" not in resolved:
            check = ("merge UNVERIFIED: confirm it merged and its bake is still owed; if not, --resolved it"
                     if t in unverified else "merge verified")
            todo.append({"key": f"bake:{t}", "do": f"R12 step 1 for merged ship {t}: adopt or ticket-add --kind bake "
                         f"--blocked-by {t} ({check}), then re-run with --resolved bake:{t}"})
    for c in (tracker or {}).get("children") or []:
        if c.get("kind_inferred") and c.get("kind") == "ship" and f"label:{c['ticket']}" not in resolved:
            todo.append({"key": f"label:{c['ticket']}", "do": f"ticket-adopt --kind ship on {c['ticket']}"})
    if relative_snapshot_cmd(manifest.get("map")) and "cwd:map" not in resolved:
        todo.append({"key": "cwd:map", "do": "set map.snapshot_cwd to the checkout the relative map.snapshot_cmd "
                     "runs from (without it the tracker read fails tracker_error:rc=1), then re-run"})
    out = {k: v for k, v in manifest.items() if k not in ("lanes", "claims")}
    out["bindings"] = bindings
    size = len((json.dumps(out, indent=2) + "\n").encode())
    census = {"bindings": len(bindings), "events_only": len(events),
              "tickets_to_file": sum(t["key"].startswith("ticket:") for t in todo),
              "bake_tickets_to_file": sum(t["key"].startswith("bake:") for t in todo),
              "bake_not_owed": len(bake_skipped),
              "bake_merge_unverified": sum(t in unverified for t in owed if f"bake:{t}" not in resolved),
              "stacked_on_edges": sum(t["key"].startswith("blocks:") for t in todo),
              "unbound": unbound, "ticket_ids_unverified": unverified, "still_over_8kb": int(size > st.MANIFEST_CAP),
              "size_after_b": size, "stale_or_done": int(stale), "has_map": int(bool(map_id)),
              "has_snapshot_cmd": int(bool((manifest.get("map") or {}).get("snapshot_cmd"))),
              "snapshot_cwd_missing": int(relative_snapshot_cmd(manifest.get("map")))}
    return {"manifest": out, "events": events, "todo": todo, "census": census,
            "bake_not_owed": [{"ticket": t, "why": why} for t, why in bake_skipped]}


def _live_manager(slug, rows, programs, now):
    mgrs, _, _ = src.program_scope(slug, rows, programs)
    return any(pf.session_present(rows[s], now, STALE_S) for s in mgrs if s in rows)


def _state_text(slug, programs):
    try:
        return open(st.manifest_path(slug, programs)[:-5] + ".state.md").read()
    except OSError:
        return ""


def migrate_program(slug, *, dry_run=False, ticket_for=None, resolved=(), programs=None, rows=None, now=None):
    now = time.time() if now is None else now
    rows = pf.session_index() if rows is None else rows
    m = st.read_manifest(slug, programs)
    children, tracker = _children_from_cache(slug)
    gh = {f"{repo}#{r.get('number')}": r for repo, tier in (src.read_cache(slug).get("gh") or {}).items()
          for r in tier.get("data") or []}
    p = plan(slug, m, state_text=_state_text(slug, programs), children=children, tracker=tracker,
             live_manager=_live_manager(slug, rows, programs, now), now=now, ticket_for=ticket_for, resolved=resolved,
             gh_rows=gh)
    res = {"program": slug, "census": p["census"], "todo": p["todo"], "bake_not_owed": p["bake_not_owed"]}
    if dry_run or ("lanes" not in m and "claims" not in m and not p["events"]):
        return dict(res, written=False)
    if p["todo"]:
        return dict(res, written=False, error="todo_open: complete each todo with the tracker adapter, then re-run")
    st.validate_bindings(p["manifest"]["bindings"])
    with st._Locked(slug, programs) as lk:
        n = lk.write(dict({k: v for k, v in lk.manifest.items() if k not in ("lanes", "claims")},
                          bindings=p["manifest"]["bindings"]))
    if st.migration_floor(slug, programs) is None:
        st.append_event(slug, {"event": "migrated", "note": "UNBOUND floor (R36)"}, programs)
    for ev in p["events"]:
        st.append_event(slug, ev, programs)
    return dict(res, written=True, size_after_b=n)


def migrate_all(*, dry_run=True, programs=None, now=None):
    now = time.time() if now is None else now
    programs = programs or st.PROGRAMS
    rows = pf.session_index()
    out, totals = [], {}
    for f in sorted(glob.glob(os.path.join(programs, "*.json"))):
        slug = os.path.basename(f)[:-5]
        if "." in slug:
            continue
        try:
            m = json.load(open(f))
        except (OSError, ValueError):
            out.append({"program": slug, "error": "unreadable"})
            continue
        if not isinstance(m, dict) or not m.get("program"):
            continue
        r = migrate_program(slug, dry_run=dry_run, programs=programs, rows=rows, now=now)
        out.append({"program": slug, **r["census"], "todo": len(r["todo"]), "written": r.get("written", False),
                    **({"error": r["error"]} if r.get("error") else {})})
        for k, v in r["census"].items():
            if isinstance(v, bool):
                totals[k] = totals.get(k, 0) + int(v)
            elif isinstance(v, int) and k != "size_after_b":
                totals[k] = totals.get(k, 0) + v
    return {"dry_run": dry_run, "programs": len(out), "totals": totals, "per_program": out}
