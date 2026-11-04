#!/usr/bin/env python3
"""render_state.py - write a program's state page, its sidecar and the cross-program index.

Usage: render_state.py --program <slug> [--out <path>] [--context]
Reads every owner (manifest, work-state snapshot, AT-WAKE through the Stop guard, grills, events, the
`## VIEW` block, `<slug>.arch.json`) and the derived sources in state_sources.py, then injects one JSON
payload into the one template. Never writes a source. Prints one compact JSON line for the manager.
--context prints the same payload as a short plain-text brief instead (state_brief.py) and writes no page: the
manager reads it at every wake and session start, works the map from it, updates `## VIEW` and re-renders.
Exit 0 = page written; 1 = unknown program or failed write. RENDER_STATE_NO_OPEN=1 skips Chrome; otherwise the one
Chrome tab on the state pages shows the index.
Owners and rules: ../specs/2026-11-03-manager-state-viewer.md
"""
import argparse
import datetime as dt
import glob
import importlib.util
import json
import os
import re
import subprocess
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import program_family as pf  # noqa: E402
import state_arch  # noqa: E402
import state_brief  # noqa: E402
import state_index as si  # noqa: E402
import state_sources as ss  # noqa: E402
import state_story  # noqa: E402
import state_view as sv  # noqa: E402
import work_state_sources as wsrc  # noqa: E402
import work_state_store as st  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "..", "references", "state-viewer", "template.html")
PLACEHOLDER = "__STATE_PAYLOAD__"
SCHEMA = si.SCHEMA
VIEWER_SCHEMA = "state-viewer-cache/1"
DEADLINE_S = 45
PAGE_BUDGET = 200_000
AUTHOR_MAX = 5
AT_WAKE_FIELDS = {"next action": "next_action", "owner": "owner", "prerequisite": "prerequisite",
                  "stop condition": "stop_condition"}
problem = sv.problem


def utc(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def ts(iso):
    try:
        return st.parse_iso(iso) if iso else None
    except ValueError:
        return None


# ---------- owners read as-is ----------

def guard_path():
    return os.environ.get("WORK_STATE_GUARD_SCRIPT") or os.path.join(st.HOME, "scripts", "manager_arm_guard.py")


def load_guard(path):
    """The Stop guard's module: the one owner of what the last AT-WAKE block says."""
    spec = importlib.util.spec_from_file_location("manager_arm_guard_for_view", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fields(text, wanted):
    out = {}
    for line in text.splitlines():
        m = re.match(r"\s*[-*]?\s*\**([A-Za-z ]+?)\**:\s*\**\s*(.+)$", line)
        if m and m.group(1).strip().lower() in wanted:
            out[wanted[m.group(1).strip().lower()]] = m.group(2).strip()
    return out


def read_at_wake(text, now, problems):
    try:
        guard = load_guard(guard_path())
    except (OSError, ImportError, AttributeError, SyntaxError) as exc:
        problems.append(problem("Stop guard", f"cannot load {guard_path()}: {exc}"))
        return {}
    facts = guard.state_facts(text, now)
    if not facts.get("has_at_wake"):
        problems.append(problem("AT-WAKE", "the state file has no ## AT-WAKE block"))
        return {}
    tail = guard.at_wake_tail(text)
    holds = [m.group(1).strip() for m in re.finditer(r"^\s*[-*]?\s*\**Hold\**:\s*(.+)$", tail, re.M | re.I)]
    return dict(_fields(tail, AT_WAKE_FIELDS), status=facts.get("status"), wake=facts.get("wake"),
                wake_armed=bool(facts.get("wake_armed")), holds=holds)


def _parse_grill(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    head, _, tail = text.partition("\nAnswers:")
    answers = {m.group(1): m.group(2).strip() for m in re.finditer(r"^(\d+)\.\s+(.+)$", tail, re.M)}
    questions, current = [], None
    for line in head.splitlines():
        m = re.match(r"^(\d+)\.\s+(.+)$", line)
        if m:
            current = {"n": m.group(1), "question": m.group(2).strip(), "detail": []}
            questions.append(current)
        elif current and line.strip():
            current["detail"].append(line.strip().lstrip("- "))
    return [dict(q, file=os.path.basename(path), answer=answers.get(q["n"])) for q in questions]


def read_grills(slug, problems):
    """Founder decisions: a numbered question with no matching `Answers:` line is open."""
    pattern = re.compile(re.escape(slug) + r"-\d{4}-\d{2}-\d{2}.*\.md$")
    open_q, answered = [], []
    for path in sorted(glob.glob(os.path.join(st.HOME, "orchestrator", "grills", f"{slug}-*.md"))):
        if not pattern.match(os.path.basename(path)):
            continue
        try:
            for q in _parse_grill(path):
                (answered if q["answer"] else open_q).append(q)
        except OSError as exc:
            problems.append(problem("Grills", f"cannot read {path}: {exc}"))
    return {"open": open_q, "answered": answered}


def read_snapshot(slug, deadline, problems):
    """The engine's snapshot under the remaining deadline; on timeout, its cached tier with no network."""
    base = [sys.executable, "-I", os.path.join(HERE, "work_state.py")]
    budget = max(1.0, deadline.left() - 20)
    try:
        r = subprocess.run(base + ["snapshot", "--program", slug, "--json"], capture_output=True, text=True,
                           timeout=budget)
        cached = False
    except (OSError, subprocess.TimeoutExpired) as exc:
        problems.append(problem("Map snapshot", f"the live snapshot did not finish ({exc}); showing the cached copy"))
        try:
            r = subprocess.run(base + ["guard", "--program", slug], input="{}", capture_output=True, text=True, timeout=10)
            cached = True
        except (OSError, subprocess.TimeoutExpired) as exc2:
            problems.append(problem("Map snapshot", f"the cached snapshot did not finish either: {exc2}"))
            return None
    try:
        data = json.loads(r.stdout)
    except ValueError:
        problems.append(problem("Map snapshot", f"exit {r.returncode}: {(r.stderr or r.stdout).strip()[:400]}"))
        return None
    if r.returncode not in (0, 4) or "error" in data:
        detail = data.get("detail") or data.get("error") or f"exit {r.returncode}"
        problems.append(problem("Map snapshot", detail, f"python3 {os.path.join(HERE, 'work_state.py')} migrate --program {slug}"
                                if "unmigrated" in str(detail) else None))
        return None
    for note in data.get("notes") or []:
        problems.append(problem("Map snapshot", f"engine note: {note}"))
    data["cached"] = cached
    return data


def read_events(path, problems):
    if not os.path.isfile(path):
        return []
    rows, bad = [], 0
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                bad += 1
                continue
            if isinstance(row, dict):
                rows.append(row)
            else:
                bad += 1
    if bad:
        problems.append(problem("Events", f"{bad} line(s) of {os.path.basename(path)} are not JSON objects; not shown"))
    return rows


def publications(events):
    """History's shipped list from `binding-retired`, deduplicated by repo plus PR or push SHA, never cut."""
    seen, out = set(), []
    for e in events:
        if e.get("event") != "binding-retired":
            continue
        b = e.get("binding") or {}
        p = b.get("publication") or {}
        if not p.get("repo"):
            continue
        key = f"{p['repo']}#{p['pr']}" if p.get("pr") else f"{p['repo']}@{p.get('sha')}"
        if key in seen:
            continue
        seen.add(key)
        out.append({"repo": p["repo"], "pr": p.get("pr"), "sha": p.get("sha") or e.get("merge_sha"),
                    "ticket": b.get("ticket") or e.get("lane"), "at": e.get("ts"), "verdict": e.get("verdict"),
                    "artifact": b.get("artifact"), "note": e.get("note")})
    return out


# ---------- derived facts for the page ----------

def program_name(slug, manifest, problems, titles=None):
    """The program as people call it: its manager's session title without "[Manager] ". Without a readable
    session, the manifest's own `title`, else the slug, plus one Problems row."""
    try:
        titles = pf.program_titles(st.PROGRAMS) if titles is None else titles
    except OSError as exc:
        titles, why = {}, f"the session index could not be read ({exc})"
    else:
        why = "no manager session for this program is in the session index"
    if titles.get(slug):
        return titles[slug]
    fallback = manifest.get("title") if isinstance(manifest.get("title"), str) and manifest["title"].strip() else slug
    problems.append(problem("Name", f"{why}, so the page is named {fallback!r}",
                            None if fallback != slug else "add a `title` to the manifest, as its manager session is titled"))
    return fallback


def read_repos(manifest, problems):
    if "repos" not in manifest:
        problems.append(problem("Repos", "the manifest names no repos, so PRs, deploys and main health are not read",
                                "add a `repos` entry to the manifest: references/manager-contract.md, State page"))
        return []
    good, errors = st.validate_repos(manifest["repos"])
    for e in errors:
        problems.append(problem("Repos", f"{e}; that repo was skipped", "fix the manifest `repos` entry"))
    return good


def viewer_cache_key(slug):
    return f"{slug}.viewer"


def read_viewer_cache(slug):
    data = wsrc.read_cache(viewer_cache_key(slug))
    return data if data.get("schema") == VIEWER_SCHEMA else {"schema": VIEWER_SCHEMA}


def derive(slug, manifest, snap, events, deadline, now, problems, run=subprocess.run):
    """Per repo, every derived read. -> {repos: [...], prs: [...], cache}."""
    cache = read_viewer_cache(slug)
    repos_cfg = read_repos(manifest, problems)
    tickets = sorted({i["ticket"] for i in (snap or {}).get("items") or []}
                     | {b["ticket"] for b in manifest.get("bindings") or []})
    pubs = [dict(b["publication"], ticket=b["ticket"]) for b in manifest.get("bindings") or [] if b.get("publication")]
    pubs += [dict(p, at=p.get("at")) for p in publications(events)]
    gh = ss.Runner(deadline, run)
    out, searches = [], cache.setdefault("searches", {})
    for r in repos_cfg:
        res = ss.collect_repo(r, tickets, pubs, gh, deadline, searches.setdefault(r["repo"], {}), now.timestamp())
        problems += [problem(p["source"], p["detail"], p.get("fix")) for p in res["problems"]]
        out.append(res)
        wsrc.write_cache(viewer_cache_key(slug), cache)
    prs = [p for r in out for p in r["prs"]]
    return {"repos": out, "repos_cfg": repos_cfg, "prs": prs, "cache": cache}


def production(derived, view, snap, manifest):
    """One row per change on the ladder. -> (now rows, shipped rows, counts)."""
    exposure = {}
    for e in view.get("exposure") or []:
        exposure[e["ref"].split("#")[-1] if "#" in e["ref"] else e["ref"]] = e
    items = (snap or {}).get("items") or []
    has = {r["repo"]: r["has_surfaces"] for r in derived["repos"]}
    bindings = manifest.get("bindings") or []
    now_rows, shipped = [], []
    counts = {"open": 0, "merged": 0, "deployed": 0, "exposed": 0, "baked": 0}
    ready = {(i["pr"]["pr"], ((i.get("publication") or {}).get("repo"))): i["pr"] for i in items if i.get("pr")}
    for p in sorted(derived["prs"], key=lambda p: p.get("mergedAt") or p.get("updatedAt") or "", reverse=True):
        ref = str(p.get("number") or (p.get("push_sha") or "")[:12])
        bake = ss.bake_of(p.get("tickets") or [], items, bindings)
        lad = ss.ladder(p, exposure.get(ref), bake, has.get(p["repo"], False))
        if lad["step"] == "closed":
            continue
        row = {"repo": p["repo"], "pr": p.get("number"), "sha": p.get("push_sha"), "title": p.get("title"),
               "tickets": p.get("tickets") or [], "ladder": lad, "additions": p.get("additions"),
               "deletions": p.get("deletions"), "merged_at": p.get("mergedAt"), "draft": p.get("isDraft"),
               "readiness": readiness(p, ready.get((p.get("number"), p["repo"]))),
               "files_known": p.get("files") is not None}
        done = lad["final"] or _closed_and_shipped(p, lad, items)
        if not done:
            counts[lad["step"]] = counts.get(lad["step"], 0) + 1
        (shipped if done else now_rows).append(row)
    return now_rows, shipped, counts


def readiness(p, eng):
    """An open PR's merge readiness for this render. Draft comes from this render's own gh read and wins; a block
    reason comes only from this tick's engine view of the same PR, else it is unknown. -> {state, why} | None."""
    if p.get("mergedAt") or p.get("state") != "OPEN":
        return None
    if p.get("isDraft"):
        return {"state": "draft", "why": "draft: mark it ready before any merge"}
    if p.get("isDraft") is None:
        return {"state": "unknown", "why": "gh returned no isDraft"}
    if eng and eng.get("readiness") not in (None, "draft"):
        return {"state": eng["readiness"], "why": eng.get("why")}
    return {"state": "unknown", "why": "not bound to a map ticket, so the engine read no merge state this tick"
            if not eng else "the engine read it as a draft; this render did not: re-read next tick"}


def _closed_and_shipped(pr, lad, items):
    """Work on closed tickets leaves Now once every affected surface is proven deployed and no bake is open.
    Its ladder keeps any unstated exposure in History, so nothing is ever upgraded to 'live'."""
    states = {i["ticket"]: i for i in items}
    tickets = pr.get("tickets") or []
    if not tickets or any((states.get(t) or {}).get("state") != "closed" for t in tickets):
        return False
    bake = (lad["steps"].get("bake") or {})
    return lad["step"] in ("deployed", "exposed", "baked") and not bake.get("owed")


def outcomes(view, snap, problems):
    """Open outcomes stay on Now; an outcome moves to History only when every ticket closed and no bake is open."""
    items = {i["ticket"]: i for i in (snap or {}).get("items") or []}
    now_rows, done = [], []
    for o in view.get("outcomes") or []:
        tickets = o.get("tickets") or []
        known = [items[t] for t in tickets if t in items]
        if not tickets or len(known) != len(tickets):
            missing = [t for t in tickets if t not in items]
            if snap is not None:
                problems.append(problem("VIEW", f"outcome '{o['outcome'][:60]}' names " +
                                        (f"tickets not on the map: {', '.join(missing)}" if tickets else "no tickets"),
                                        "list the outcome's map tickets in `tickets`"))
            now_rows.append(dict(o, tickets=[_ticket(items.get(t), t) for t in tickets], state="unknown"))
            continue
        closed = all(i["state"] == "closed" for i in known)
        bake_open = any(i.get("bake_verdict") in ("pending", "fail") for i in known)
        row = dict(o, tickets=[_ticket(i, i["ticket"]) for i in known],
                   state="done" if closed and not bake_open else ("bake" if closed else "open"))
        (done if row["state"] == "done" else now_rows).append(row)
    return now_rows, done


def _ticket(item, tid):
    item = item or {}
    return {"id": tid, "state": item.get("state"), "title": item.get("title"), "ended": item.get("ended"),
            "bake": item.get("bake_verdict"), "bake_ended": item.get("bake_ended")}


def proof_owed(view, snap, problems):
    items = {i["ticket"]: i for i in (snap or {}).get("items") or []}
    rows = []
    for r in view.get("proof_owed") or []:
        derived = (items.get(r.get("ticket")) or {}).get("bake_verdict")
        if not r.get("ticket"):
            problems.append(problem("VIEW", f"proof_owed '{r['claim'][:60]}' names no ticket", "add its `ticket`"))
        elif derived and r.get("verdict") and derived != r["verdict"]:
            problems.append(problem("VIEW", f"proof_owed for {r['ticket']} says {r['verdict']}, the ticket records {derived}; "
                                    "the ticket wins", "edit `proof_owed` to match"))
        rows.append(dict(r, verdict=derived or r.get("verdict") or "owed", derived=bool(derived)))
    return rows


TICKET_ID = re.compile(r"^[A-Z][A-Z0-9]*-\d+$")


def flag_rows(snap):
    """Every engine flag as a row. -> (on tickets, on anything else such as a worker id)."""
    rows = [{"kind": "flag", "flag": x.get("flag"), "id": x.get("item"), "fix": x.get("fix")}
            for x in (snap or {}).get("blocking") or []]
    rows += [{"kind": "flag", "flag": fl, "id": x.get("item"), "fix": x.get("fix")}
             for fl in ("STALLED", "BAKE_OWED", "PROOF_FAILED") for x in ((snap or {}).get("flags") or {}).get(fl) or []]
    on_ticket = [r for r in rows if TICKET_ID.match(str(r["id"] or ""))]
    return on_ticket, [r for r in rows if r not in on_ticket]


def held_by(snap, derived, overlap_rows, view):
    """Everything stopping progress, named by what holds it. A flag on a worker rather than a ticket belongs to
    the machinery footer, never here."""
    rows = [dict(w, kind="waiter") for w in (snap or {}).get("waiters") or []] + list(flag_rows(snap)[0])
    for h in (snap or {}).get("holds") or []:
        rows.append({"kind": "hold", "id": h.get("ticket"), "reason": h.get("reason"), "text": " ".join(h.get("args") or []),
                     "valid": h.get("valid"), "why": h.get("why")})
    for i in (snap or {}).get("items") or []:
        if i.get("state") == "blocked":
            rows.append({"kind": "blocked", "id": i["ticket"], "by": [b.get("ticket") if isinstance(b, dict) else b
                                                                       for b in i.get("blocked_by") or []]})
    for r in derived["repos"]:
        red = r["red_main"]
        rows.append({"kind": "main", "repo": r["repo"], "state": red["state"], "why": red.get("why"), "fix": red.get("fix"),
                     "owners": red.get("owners"), "sha": red.get("sha")})
    for o in overlap_rows:
        rows.append(dict(o, kind="overlap"))
    for d in view.get("design") or []:
        if d.get("stop"):
            rows.append({"kind": "design", "what": d["what"], "ref": d.get("ref"), "stop": d["stop"]})
    return rows


def codebase(derived):
    """Modules this program is changing, from its open PRs' file lists, sized by diff."""
    mods = {}
    for r in derived["repos"]:
        for p in r["prs"]:
            if p.get("mergedAt") or p.get("state") != "OPEN":
                continue
            entry = r["open"].get(str(p["number"])) or {}
            for f in entry.get("files") or p.get("files") or []:
                parts = [x for x in f.split("/")[:-1] if x != "src"][:3] or ["(repo root)"]
                key = (r["repo"], "/".join(parts))
                m = mods.setdefault(key, {"repo": r["repo"], "module": key[1], "files": 0, "prs": set(), "size": 0})
                m["files"] += 1
                m["prs"].add(p["number"])
                m["size"] += (entry.get("sizes") or {}).get(f, 0)
    rows = [dict(m, prs=sorted(m["prs"])) for m in mods.values()]
    return sorted(rows, key=lambda m: (-m["size"], -m["files"]))[:24]


def needs_you(view, grills, snap):
    rows = [{"ask": q["ask"], "recommended": q.get("recommended"), "where": q.get("grill"), "from": "view"}
            for q in view.get("needs_you") or []]
    for q in grills["open"]:
        rec = next((d for d in q.get("detail") or [] if re.search(r"recommend", d, re.I)), None)
        rows.append({"ask": q["question"], "recommended": rec, "where": q["file"], "n": q["n"], "from": "grill"})
    for i in (snap or {}).get("items") or []:
        if i.get("state") != "closed" and any(c.get("type") == "founder" for c in i.get("carriers") or []):
            rows.append({"ask": i.get("title") or "Waits on you", "ticket": i["ticket"], "from": "ticket"})
    return rows


# ---------- events, staleness, since you last looked ----------

def derived_events(slug, prod_rows, shipped, snap, grills, outcome_rows, cache, now):
    """Each event: a stable id, a kind, and a time. Merges and deploys carry their own proof times; the rest carry
    a first-seen time from the program cache. After cache loss, first-seen times are unknown, never "new"."""
    seen = cache.setdefault("seen", {})
    baseline = bool(cache.get("baseline_at"))
    stamp = utc(now)
    events = []

    def first_seen(eid):
        if eid not in seen:
            seen[eid] = stamp if baseline else None
        return seen[eid]

    for row in prod_rows + shipped:
        ref = f"{row['repo']}#{row['pr']}" if row.get("pr") else f"{row['repo']}@{row.get('sha')}"
        label = f"#{row['pr']}" if row.get("pr") else "direct push"
        steps = row["ladder"].get("steps") or {}
        if row.get("merged_at") and ts(row["merged_at"]):
            events.append({"id": f"merge:{ref}", "kind": "merge", "at": row["merged_at"], "label": label})
        for s in steps.get("deploy") or []:
            if s.get("state") == "deployed":
                at = (s.get("deploy") or {}).get("at") or first_seen(f"deploy:{s['surface']}:{ref}")
                events.append({"id": f"deploy:{s['surface']}:{ref}", "kind": "deploy", "at": at,
                               "label": f"{label} on {s['surface']}"})
    for x in (snap or {}).get("blocking") or []:
        eid = f"blocker:{x.get('item')}:{x.get('flag')}"
        events.append({"id": eid, "kind": "blocker", "at": first_seen(eid), "label": x.get("item")})
    for q in grills["open"]:
        eid = f"grill:{q['file']}:{q['n']}"
        events.append({"id": eid, "kind": "question", "at": first_seen(eid), "label": q["question"][:80]})
    for o in outcome_rows:
        for t in o.get("tickets") or []:
            if t.get("state") == "closed":
                eid = f"closed:{t['id']}"
                events.append({"id": eid, "kind": "closed", "at": first_seen(eid), "label": t["id"]})
    if not baseline:
        cache["baseline_at"] = stamp
    return events, baseline


def staleness(view, events):
    """The narrative is stale when any derived event is newer than VIEW updated_at."""
    updated = ts(view.get("updated_at"))
    if updated is None:
        return {"stale": bool(events), "since": None, "counts": {}, "reason": "no valid updated_at"}
    newer = [e for e in events if e.get("at") and ts(e["at"]) and ts(e["at"]) > updated]
    counts = {}
    for e in newer:
        counts[e["kind"]] = counts.get(e["kind"], 0) + 1
    return {"stale": bool(newer), "since": view["updated_at"], "counts": counts, "ids": [e["id"] for e in newer]}


def author_line(view, legacy, prod_rows, outcome_rows, stale, problems_rows, told=None):
    """At most 5 exact keys to edit, drawn only from what is unresolved on Now."""
    out = []
    pending = [u for u in ((told or {}).get("unsummarized") or [])]
    if pending:
        refs = [f"#{u['pr']}" if u.get("pr") else str(u.get("sha") or "")[:10] for u in pending]
        out.append(f"done: summarize {', '.join(refs[:3])}{f' and {len(refs) - 3} more' if len(refs) > 3 else ''}"
                   " (what changed for the product, and why)")
    unstated = [r for r in prod_rows if (r["ladder"]["steps"].get("exposure") or {}).get("state") == "unstated"]
    if unstated:
        refs = [f"#{r['pr']}" for r in unstated if r.get("pr")]
        out.append(f"exposure: {refs[0]}{f' and {len(refs) - 1} more' if len(refs) > 1 else ''} deployed, no row"
                   if refs else "exposure: a deployed push, no row")
    for o in outcome_rows:
        for t in o.get("tickets") or []:
            if t.get("state") == "closed" and f"closed:{t['id']}" in (stale.get("ids") or []):
                out.append(f"outcomes: {t['id']} closed")
    if not view.get("destination"):
        out.append("destination: not written")
    if not view.get("outcomes"):
        out.append("outcomes: none written")
    if not view.get("decisions"):
        out.append("decisions: none written")
    for leg in legacy:
        out.append(f"{leg['key']}: move to {leg['home']}")
    if any(p["source"] == "VIEW" and "proof_owed for" in p["detail"] for p in problems_rows):
        out.append("proof_owed: a verdict disagrees with its ticket")
    if stale.get("stale"):
        out.append("updated_at: set it after the edits")
    return out[:AUTHOR_MAX]


# ---------- the payload ----------

def build_payload(slug, now, run=subprocess.run, deadline=None):
    """Read every owner. Raises FileNotFoundError / ValueError only for an unreadable manifest."""
    deadline = deadline or ss.Deadline(DEADLINE_S)
    problems = []
    base = st.manifest_path(slug)[:-5]
    with open(base + ".json", encoding="utf-8") as fh:
        manifest = json.load(fh)
    if not isinstance(manifest, dict):
        raise ValueError("the manifest is not a JSON object")
    text = ""
    if os.path.isfile(base + ".state.md"):
        with open(base + ".state.md", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    else:
        problems.append(problem("State file", f"{base}.state.md does not exist"))
    at_wake = read_at_wake(text, now, problems) if text else {}
    parsed = sv.read_view(text, now, problems) if text else {"view": {}, "legacy": []}
    view = parsed["view"]
    events = read_events(base + ".events.jsonl", problems)
    grills = read_grills(slug, problems)
    snap = read_snapshot(slug, deadline, problems)
    derived = derive(slug, manifest, snap, events, deadline, now, problems, run)
    prod_rows, shipped, counts = production(derived, view, snap, manifest)
    out_now, out_done = outcomes(view, snap, problems)
    others = si.other_sidecars(slug, now)
    names = {o["program"]: o.get("name") or o["program"] for o in others}
    overlap_rows = [dict(o, name=names.get(o["program"], o["program"]))
                    for o in ss.overlap(si.holdings(manifest, derived), others)]
    arch = state_arch.page_section(slug)
    problems += [problem("System diagram", p) for p in arch["problems"]]
    name = program_name(slug, manifest, problems)
    decisions = (view.get("decisions") or []) + [
        {"decision": q["question"], "why": q["answer"], "by": "founder", "grill": q["file"]} for q in grills["answered"]]
    told = state_story.story(view, prod_rows + shipped, publications(events), decisions, now)
    evts, baseline = derived_events(slug, prod_rows, shipped, snap, grills, out_now + out_done, derived["cache"], now)
    wsrc.write_cache(viewer_cache_key(slug), derived["cache"])
    stale = staleness(view, evts)
    done = {(d["skill"], d.get("ref")) for d in view.get("skills_done") or []}
    files_of = {(p["repo"], p.get("number")): p for p in derived["prs"]}
    skill_rows = ss.skills([dict(p, files=(files_of.get((p["repo"], p.get("number"))) or {}).get("files")) for p in derived["prs"]],
                           view, derived["repos_cfg"], (snap or {}).get("items") or [], now.timestamp(), done)
    health = [dict(h, repo=r["repo"]) for r in derived["repos"] for h in r["health"]]
    health.append({"name": "Map snapshot", "ok": snap is not None and not snap.get("cached"),
                   "age_s": ((snap or {}).get("remote_age_s") or {}).get("tracker")})
    payload = {
        "schema": SCHEMA, "kind": "program", "program": slug, "name": name, "generated_at": utc(now), "goal": manifest.get("goal"),
        "map": manifest.get("map"), "destination": view.get("destination"), "updated_at": view.get("updated_at"),
        "status": at_wake.get("status"),
        "now": {"outcomes": out_now, "needs_you": needs_you(view, grills, snap),
                "held_by": held_by(snap, derived, overlap_rows, view), "overlap": overlap_rows,
                "system": arch, "production": {"rows": prod_rows, "counts": counts,
                                               "repos": [{"repo": r["repo"], "surfaces": [
                                                   {k: s[k] for k in ("name", "unproven", "age_s", "error", "fix")}
                                                   for s in r["surfaces"]], "has_surfaces": r["has_surfaces"]}
                                                   for r in derived["repos"]],
                                               "configured": bool(derived["repos_cfg"])},
                "proof_owed": proof_owed(view, snap, problems),
                "codebase": codebase(derived), "skills": skill_rows, "legacy": parsed["legacy"]},
        "story": told,
        "history": {"shipped": shipped, "publications": publications(events), "outcomes": out_done,
                    "decisions": decisions,
                    "dead_ends": view.get("dead_ends") or [], "incidents": view.get("incidents") or [],
                    "events": [e for e in events if e.get("event") not in ("binding-retired",)][-300:],
                    "architecture": arch["archived"], "dropped": 0},
        "since": {"events": [e for e in evts if e.get("at")], "unknown": sum(1 for e in evts if not e.get("at")),
                  "baseline": baseline},
        "stale": stale,
        "machinery": {"at_wake": at_wake, "lanes": lane_rows(manifest, snap), "health": health,
                      "worker_flags": [{"flag": r["flag"], "id": r["id"]} for r in flag_rows(snap)[1]],
                      "awaiting": [{"ticket": a.get("ticket"), "category": a.get("category")}
                                   for a in (snap or {}).get("awaiting_manager") or []],
                      "items": [{"ticket": i["ticket"], "state": i["state"], "title": i.get("title"), "flags": i.get("flags"),
                                 "ended": i.get("ended")} for i in (snap or {}).get("items") or []],
                      "map_line": (snap or {}).get("map_line"), "gates": manifest.get("gates_held_by_manager") or [],
                      "sources": [_source("Manifest", base + ".json"), _source("State file", base + ".state.md"),
                                  _source("Events", base + ".events.jsonl"), _source("System diagram", base + ".arch.json")]},
        "problems": problems,
    }
    payload["author"] = author_line(view, parsed["legacy"], prod_rows, out_now, stale, problems, told["history"])
    return payload, si.holdings(manifest, derived)


def lane_rows(manifest, snap):
    """Carriers for the machinery footer: the binding owns the detail, the snapshot owns liveness."""
    items = {i.get("ticket"): i for i in (snap or {}).get("items") or []}
    rows = []
    for b in manifest.get("bindings") or []:
        item = items.get(b.get("ticket")) or {}
        live = {(c.get("type"), c.get("id")): c.get("live") for c in item.get("carriers") or []}
        for c in b.get("carriers") or []:
            rows.append({"ticket": b.get("ticket"), "type": c.get("type"), "id": c.get("id"), "runtime": c.get("runtime"),
                         "model": c.get("model"), "live": live.get((c.get("type"), c.get("id")))})
    return rows


def _source(name, path):
    exists = os.path.isfile(path)
    mtime = utc(dt.datetime.fromtimestamp(os.path.getmtime(path), dt.timezone.utc)) if exists else None
    return {"name": name, "file": os.path.basename(path), "exists": exists, "modified": mtime}


def fit_budget(payload):
    """Past the page budget, drop the oldest History rows and say how many."""
    order = (("history", "events"), ("history", "publications"), ("history", "shipped"), ("story", "unsummarized"),
             ("history", "decisions"), ("history", "dead_ends"), ("history", "incidents"), ("story", "done"))
    dropped = 0
    room = PAGE_BUDGET - os.path.getsize(TEMPLATE) - 2_000
    while len(json.dumps(payload, ensure_ascii=False, default=str).encode()) > room:
        where = next(((a, k) for a, k in order if (payload["story"]["history"] if a == "story" else payload["history"])[k]), None)
        if not where:
            break
        box = payload["story"]["history"] if where[0] == "story" else payload["history"]
        cut = max(1, len(box[where[1]]) // 4)
        box[where[1]] = box[where[1]][cut:] if where[1] == "events" else box[where[1]][:-cut]
        dropped += cut
    payload["history"]["dropped"] = dropped
    return payload


# ---------- writing ----------

def inject(template, payload):
    """Exactly one placeholder; `<` and the JS line separators are escaped so data cannot end the script."""
    if template.count(PLACEHOLDER) != 1:
        raise ValueError(f"template must hold {PLACEHOLDER} exactly once, found {template.count(PLACEHOLDER)}")
    data = json.dumps(payload, ensure_ascii=False, default=str)
    data = data.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return template.replace(PLACEHOLDER, data)


def write_atomic(path, text):
    tmp = f"{path}.tmp.{os.getpid()}"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def write_page(path, payload):
    with open(TEMPLATE, encoding="utf-8") as fh:
        write_atomic(path, inject(fh.read(), payload))


def relocate_diagrams(payload, out):
    """Diagram iframes are relative siblings; a page written elsewhere links them by absolute path instead."""
    arch = payload["now"]["system"]
    here = os.path.dirname(os.path.abspath(out))
    sibling = os.path.abspath(here) == os.path.abspath(os.path.dirname(arch["dir"]))
    payload["now"]["system"] = dict({k: v for k, v in arch.items() if k not in ("dir", "problems")}, sibling=sibling,
                                    base_url=None if sibling else "file://" + urllib.parse.quote(os.path.dirname(arch["dir"])) + "/")
    payload["history"]["architecture"] = payload["now"]["system"]["archived"]
    return payload


REAL_PROGRAMS = os.path.expanduser("~/.claude/orchestrator/programs")
TAB_SEP = "\t"
LIST_TABS = ('if application "Google Chrome" is not running then return "closed"\n'
             'tell application "Google Chrome"\n  set out to ""\n  repeat with w in windows\n'
             '    repeat with t in tabs of w\n'
             '      set out to out & (id of w) & (ASCII character 9) & (id of t) & (ASCII character 9) & (URL of t) & linefeed\n'
             '    end repeat\n  end repeat\n  return out\nend tell')


def file_url(path, program=None):
    return "file://" + urllib.parse.quote(path) + (f"#program={urllib.parse.quote(program)}" if program else "")


def state_page(url, programs_dir):
    """The page name when a tab shows a `.state.html` directly under the programs dir, else None."""
    parts = urllib.parse.urlsplit(url or "")
    if parts.scheme != "file":
        return None
    path = urllib.parse.unquote(parts.path)
    name = os.path.basename(path)
    return name if os.path.dirname(path) == programs_dir.rstrip(os.sep) and name.endswith(".state.html") else None


def parse_tabs(text):
    rows = []
    for line in (text or "").splitlines():
        bits = line.split(TAB_SEP, 2)
        if len(bits) == 3 and bits[0].strip().isdigit() and bits[1].strip().isdigit():
            rows.append((int(bits[0]), int(bits[1]), bits[2]))
    return rows


def tab_plan(tabs, programs_dir, index_path):
    """One tab for every state page: reload the index if open, else repoint the first state tab to it, close the rest.
    `tabs` is [(window id, tab id, url)] in Chrome's order. Tabs that are not state pages are never named."""
    index_name = os.path.basename(index_path)
    matches = [(w, t, state_page(u, programs_dir)) for w, t, u in tabs]
    matches = [m for m in matches if m[2]]
    if not matches:
        return {"action": "open", "url": file_url(index_path), "close": []}
    keep = next((m for m in matches if m[2] == index_name), None)
    if keep:
        plan = {"action": "reload", "tab": keep[:2]}
    else:
        keep = matches[0]
        program = keep[2][:-len(".state.html")]
        plan = {"action": "repoint", "tab": keep[:2], "url": file_url(index_path, program)}
    plan["close"] = [m[:2] for m in matches if m is not keep]
    return plan


def _as_string(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def plan_script(plan):
    """The AppleScript for a reload or repoint plan. It never activates Chrome or selects a tab."""
    ref = lambda wt: f"tab id {wt[1]} of window id {wt[0]}"  # noqa: E731
    lines = ['tell application "Google Chrome"']
    if plan["action"] == "reload":
        lines.append(f"  tell {ref(plan['tab'])} to reload")
    else:
        lines.append(f"  set URL of {ref(plan['tab'])} to {_as_string(plan['url'])}")
    lines += [f"  close {ref(wt)}" for wt in plan["close"]]
    return "\n".join(lines + ["end tell"])


def show_in_chrome(path, run=subprocess.run):
    """Keep exactly one Chrome tab on the state pages, showing the index. Returns what it did. Never raises."""
    if sys.platform != "darwin" or os.environ.get("RENDER_STATE_NO_OPEN"):
        return {"action": "skipped"}
    if os.path.dirname(os.path.abspath(path)) != REAL_PROGRAMS:
        return {"action": "skipped"}
    try:
        res = run(["osascript", "-e", LIST_TABS], capture_output=True, text=True, timeout=15)
        if res.returncode != 0:
            return {"action": "error", "detail": (res.stderr or "").strip()[:200]}
        if res.stdout.strip() == "closed":
            return {"action": "chrome closed"}
        plan = tab_plan(parse_tabs(res.stdout), REAL_PROGRAMS, os.path.abspath(path))
        if plan["action"] == "open":
            res = run(["open", "-g", "-a", "Google Chrome", plan["url"]], capture_output=True, text=True, timeout=15)
        else:
            res = run(["osascript", "-e", plan_script(plan)], capture_output=True, text=True, timeout=15)
        if res.returncode != 0:
            return {"action": "error", "detail": (res.stderr or "").strip()[:200]}
        return {"action": {"open": "opened", "reload": "reloaded", "repoint": "repointed"}[plan["action"]],
                "closed": len(plan["close"])}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"action": "error", "detail": str(exc)[:200]}


def main(argv=None, run=subprocess.run):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--program", required=True)
    ap.add_argument("--out", help="page path; default <programs>/<slug>.state.html (sidecar and index stay in programs)")
    ap.add_argument("--context", action="store_true", help="print the plain-text state brief; write no page")
    args = ap.parse_args(argv)
    now = dt.datetime.now(dt.timezone.utc)
    try:
        payload, hold = build_payload(args.program, now, run)
    except (OSError, ValueError) as exc:
        print(f"render_state: cannot read program {args.program!r}: {exc}", file=sys.stderr)
        return 1
    if args.context:
        print(state_brief.brief(payload))
        return 0
    base = st.manifest_path(args.program)[:-5]
    out = os.path.abspath(args.out or base + ".state.html")
    payload = fit_budget(relocate_diagrams(payload, out))
    try:
        write_page(out, payload)
        write_atomic(base + ".state.json", json.dumps(si.sidecar(payload, hold), default=str))
    except (OSError, ValueError) as exc:
        print(f"render_state: cannot write {out}: {exc}", file=sys.stderr)
        return 1
    index_path = os.path.join(st.PROGRAMS, "index.state.html")
    index_note = write_index(index_path, now)
    _, arch_problems = state_arch.build(args.program)
    section = state_arch.page_section(args.program)
    if (section["current"] or {}).get("built") != (payload["now"]["system"].get("current") or {}).get("built") \
            or arch_problems:
        payload["now"]["system"] = dict(section, dir=section["dir"])
        payload["problems"] = [p for p in payload["problems"] if p["source"] != "System diagram"] + \
            [problem("System diagram", p) for p in arch_problems]
        payload = fit_budget(relocate_diagrams(payload, out))
        try:
            write_page(out, payload)
        except (OSError, ValueError) as exc:
            print(f"render_state: cannot rewrite {out} with its diagram: {exc}", file=sys.stderr)
    print(json.dumps({"out": out, "problems": len(payload["problems"]), "stale": payload["stale"]["stale"],
                      "author": payload["author"], "index": index_note,
                      "chrome": show_in_chrome(index_path)}))
    return 0


def write_index(path, now):
    try:
        write_page(path, si.build_index(now))
        return path
    except (OSError, ValueError) as exc:
        return f"not written: {exc}"


if __name__ == "__main__":
    sys.exit(main())
