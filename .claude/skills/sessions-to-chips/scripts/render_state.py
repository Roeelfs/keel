#!/usr/bin/env python3
"""render_state.py - write a program's state page by injecting one JSON payload into the one template.

Usage: render_state.py --program <slug> [--out <path>]
Pure render: it reads the owners, writes only the output file, and keeps no state. Every source that
is missing or refuses shows up on the page with its reason. Exit 0 = page written; 1 = unknown
program or failed write. Owners and rules: ../specs/2026-11-03-manager-state-viewer.md
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
import state_graph  # noqa: E402
import work_state_store as st  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "..", "references", "state-viewer", "template.html")
PLACEHOLDER = "__STATE_PAYLOAD__"
SCHEMA = "state-view/1"
SNAPSHOT_TIMEOUT_S = 90
EVENT_TAIL = 40
AT_WAKE_FIELDS = {"next action": "next_action", "owner": "owner", "prerequisite": "prerequisite",
                  "stop condition": "stop_condition", "mode": "mode"}
CHECKPOINT_FIELDS = {"accepted outcome": "accepted", "done when": "done_when", "verified": "verified",
                     "remaining": "remaining"}
VIEW_LISTS = {"next_steps": ("step", {"step", "owner"}), "upcoming": ("what", {"when", "what"}),
              "needs_you": ("ask", {"ask", "recommended"}),
              "decisions": ("decision", {"decision", "date", "why", "by"}),
              "proven": ("claim", {"claim", "evidence"}), "unproven": ("claim", {"claim", "owed"})}
VIEW_TEXT = {"updated_at", "explanation"}


def problem(source, detail, fix=None):
    return {"source": source, "detail": str(detail), "fix": fix}


def utc(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


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


def _wake_fire_at(guard, wake, now):
    """The soonest future time on the Wake line, else its latest past time, else None (event-bound)."""
    times = []
    for s in guard.ISO.findall(wake or ""):
        try:
            times.append(guard.parse_iso(s))
        except ValueError:
            continue
    future = sorted(t for t in times if t > now)
    return utc(future[0]) if future else (utc(max(times)) if times else None)


def read_at_wake(text, now, problems):
    try:
        guard = load_guard(guard_path())
    except (OSError, ImportError, AttributeError, SyntaxError) as exc:
        problems.append(problem("Stop guard", f"cannot load {guard_path()}: {exc}"))
        return {}
    facts = guard.state_facts(text, now)
    tail = guard.at_wake_tail(text)
    if not facts.get("has_at_wake"):
        problems.append(problem("AT-WAKE", "the state file has no ## AT-WAKE block"))
        return {}
    wake = facts.get("wake")
    on_fire = re.search(r"\bon fire:\s*(.+)$", wake or "", re.I)
    holds = [m.group(1).strip() for m in re.finditer(r"^\s*[-*]?\s*\**Hold\**:\s*(.+)$", tail, re.M | re.I)]
    return dict(_fields(tail, AT_WAKE_FIELDS), status=facts.get("status"), wake=wake,
                wake_armed=bool(facts.get("wake_armed")), wake_fire_at=_wake_fire_at(guard, wake, now),
                on_fire=on_fire.group(1).strip() if on_fire else None, holds=holds)


def read_checkpoint(text):
    idx = [m.end() for m in re.finditer(r"^##\s+Completion checkpoint\b.*$", text, re.M)]
    if not idx:
        return {}
    body = re.split(r"^##\s", text[idx[-1]:], maxsplit=1, flags=re.M)[0]
    return _fields(body, CHECKPOINT_FIELDS)


def _check_list(key, rows, problems):
    required, allowed = VIEW_LISTS[key]
    if not isinstance(rows, list):
        problems.append(problem("VIEW", f"`{key}` must be a list, got {type(rows).__name__}; it was not shown"))
        return []
    kept = []
    for n, row in enumerate(rows):
        where = f"{key}[{n}]"
        if not isinstance(row, dict) or not isinstance(row.get(required), str):
            problems.append(problem("VIEW", f"{where} needs a string `{required}`; it was not shown"))
            continue
        extra = sorted(set(row) - allowed)
        if extra:
            problems.append(problem("VIEW", f"{where} has unknown keys {extra}; those keys were not shown"))
        kept.append({k: str(v) for k, v in row.items() if k in allowed and v is not None})
    return kept


def read_view(text, problems):
    """The last fenced JSON block under `## VIEW`. Bad input is reported, never silently dropped."""
    heads = list(re.finditer(r"^##\s+VIEW\b.*$", text, re.M))
    if not heads:
        problems.append(problem("VIEW", "no ## VIEW block in the state file, so the narrative sections are empty",
                                "Add the block: references/manager-contract.md, Program state"))
        return {}
    body = re.split(r"^##\s", text[heads[-1].end():], maxsplit=1, flags=re.M)[0]
    fence = re.search(r"^```(?:json)?[ \t]*\n(.*?)^```", body, re.M | re.S)
    if not fence:
        problems.append(problem("VIEW", "the ## VIEW block has no fenced JSON"))
        return {}
    try:
        raw = json.loads(fence.group(1))
    except ValueError as exc:
        problems.append(problem("VIEW", f"the ## VIEW block is not valid JSON: {exc}"))
        return {}
    if not isinstance(raw, dict):
        problems.append(problem("VIEW", f"the ## VIEW block must be an object, got {type(raw).__name__}"))
        return {}
    unknown = sorted(set(raw) - VIEW_TEXT - set(VIEW_LISTS))
    if unknown:
        problems.append(problem("VIEW", f"unknown keys {unknown} were not shown"))
    view = {}
    for key in VIEW_TEXT & set(raw):
        if isinstance(raw[key], str):
            view[key] = raw[key]
        else:
            problems.append(problem("VIEW", f"`{key}` must be a string, got {type(raw[key]).__name__}; it was not shown"))
    for key in VIEW_LISTS.keys() & set(raw):
        view[key] = _check_list(key, raw[key], problems)
    return view


def read_events(path, problems):
    if not os.path.isfile(path):
        return {"rows": [], "total": 0, "bad_lines": 0}
    rows, bad = [], 0
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                rows.append(row) if isinstance(row, dict) else None
                bad += not isinstance(row, dict)
            except ValueError:
                bad += 1
    if bad:
        problems.append(problem("Events", f"{bad} line(s) of {os.path.basename(path)} are not JSON objects; not shown"))
    return {"rows": rows[-EVENT_TAIL:], "total": len(rows), "bad_lines": bad}


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
    return [dict(q, file=path, answer=answers.get(q["n"])) for q in questions]


def read_grills(slug, problems):
    """Founder decisions: a numbered question with no matching `Answers:` line is open."""
    pattern = re.compile(re.escape(slug) + r"-\d{4}-\d{2}-\d{2}.*\.md$")
    grills_dir = os.path.join(st.HOME, "orchestrator", "grills")
    open_q, answered = [], []
    for path in sorted(glob.glob(os.path.join(grills_dir, f"{slug}-*.md"))):
        if not pattern.match(os.path.basename(path)):
            continue
        try:
            for q in _parse_grill(path):
                (answered if q["answer"] else open_q).append(q)
        except OSError as exc:
            problems.append(problem("Grills", f"cannot read {path}: {exc}"))
    return {"open": open_q, "answered": answered}


def read_snapshot(slug, problems):
    """The engine's snapshot. Exit 0 and 4 both carry one; exit 1 carries {error, detail}."""
    cmd = [sys.executable, "-I", os.path.join(HERE, "work_state.py"), "snapshot", "--program", slug, "--json"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=SNAPSHOT_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as exc:
        problems.append(problem("Map snapshot", f"work_state.py snapshot did not finish: {exc}"))
        return None
    try:
        data = json.loads(r.stdout)
    except ValueError:
        problems.append(problem("Map snapshot", f"exit {r.returncode}: {(r.stderr or r.stdout).strip()[:400]}"))
        return None
    if r.returncode not in (0, 4) or "error" in data:
        problems.append(problem("Map snapshot", data.get("detail") or data.get("error") or f"exit {r.returncode}",
                                f"python3 {os.path.join(HERE, 'work_state.py')} migrate --program {slug}"
                                if "unmigrated" in str(data.get("detail")) else None))
        return None
    for note in data.get("notes") or []:
        problems.append(problem("Map snapshot", f"engine note: {note}"))
    return data


def map_progress(snap):
    if not snap:
        return None
    states = [i.get("state") for i in snap.get("items") or []]
    return {"closed": states.count("closed"), "active": states.count("active"), "blocked": states.count("blocked"),
            "ready": states.count("ready"), "total": len(states), "line": snap.get("map_line"),
            "frontier": snap.get("frontier") or [], "taken_at": snap.get("taken_at"),
            "tracker_age_s": (snap.get("remote_age_s") or {}).get("tracker"), "children_count": snap.get("children_count")}


def lane_rows(manifest, snap):
    """One row per carrier: the binding owns the detail, the snapshot owns liveness and title."""
    items = {i.get("ticket"): i for i in (snap or {}).get("items") or []}
    rows = []
    for b in manifest.get("bindings") or []:
        item = items.get(b.get("ticket")) or {}
        live = {(c.get("type"), c.get("id")): c.get("live") for c in item.get("carriers") or []}
        for c in b.get("carriers") or [{}]:
            rows.append({"ticket": b.get("ticket"), "title": item.get("title"), "state": item.get("state"),
                         "type": c.get("type"), "id": c.get("id"), "runtime": c.get("runtime"), "model": c.get("model"),
                         "wave": c.get("wave"), "outfile": c.get("outfile"), "live": live.get((c.get("type"), c.get("id"))),
                         "branch": b.get("branch"), "worktree": b.get("worktree"), "artifact": b.get("artifact"),
                         "publication": b.get("publication"), "bake": b.get("bake")})
    return rows


def graph_section(slug, snap, problems):
    if not snap:
        return {"html": None, "reason": "No graph, because the map snapshot is unavailable. See Problems."}
    spec, drawn = state_graph.build_spec(slug, snap)
    if not spec:
        return {"html": None, "reason": "No graph, because the map has no open ticket."}
    archify = os.path.join(st.HOME, "skills", "archify", "bin", "archify.mjs")
    html, why = state_graph.deliver(spec, archify)
    if why:
        problems.append(problem("Work graph", why))
        return {"html": None, "reason": "The graph could not be drawn. See Problems. The list under What is left is complete."}
    return {"html": html, "reason": None, "drawn": drawn}


def _source(name, path):
    exists = os.path.isfile(path)
    mtime = utc(dt.datetime.fromtimestamp(os.path.getmtime(path), dt.timezone.utc)) if exists else None
    return {"name": name, "path": path, "exists": exists, "modified": mtime}


def build_payload(slug, now):
    """Read every owner. Raises FileNotFoundError / ValueError only for an unreadable manifest."""
    problems = []
    base = st.manifest_path(slug)[:-5]
    manifest_file = base + ".json"
    with open(manifest_file, encoding="utf-8") as fh:
        manifest = json.load(fh)
    state_file = base + ".state.md"
    if os.path.isfile(state_file):
        with open(state_file, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    else:
        text = ""
        problems.append(problem("State file", f"{state_file} does not exist"))
    at_wake = read_at_wake(text, now, problems) if text else {}
    checkpoint = read_checkpoint(text)
    view = read_view(text, problems) if text else {}
    events = read_events(base + ".events.jsonl", problems)
    decisions = read_grills(slug, problems)
    snap = read_snapshot(slug, problems)
    lanes = lane_rows(manifest, snap)
    graph = graph_section(slug, snap, problems)
    return {"schema": SCHEMA, "program": slug, "generated_at": utc(now), "goal": manifest.get("goal"),
            "manager": manifest.get("manager_session") or manifest.get("orchestrator_session"),
            "map": manifest.get("map"), "forcing_function": manifest.get("next_forcing_function"),
            "manifest_status": manifest.get("status"), "manifest_updated_at": manifest.get("updated_at"),
            "gates": manifest.get("gates_held_by_manager") or manifest.get("gates_held_by_orchestrator") or [],
            "ceded": manifest.get("ceded") or [], "at_wake": at_wake, "checkpoint": checkpoint, "view": view,
            "progress": map_progress(snap), "items": (snap or {}).get("items") or [],
            "blocking": (snap or {}).get("blocking") or [], "awaiting": (snap or {}).get("awaiting_manager") or [],
            "holds": (snap or {}).get("holds") or [], "lanes": lanes, "decisions": decisions, "events": events,
            "graph": graph, "problems": problems,
            "sources": [_source("Manifest", manifest_file), _source("State file", state_file),
                        _source("Events", base + ".events.jsonl")]}


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


def show_in_chrome(path):
    """Keep one viewable Chrome tab on the page: reload it if open, else open it unfocused. Never raises."""
    if sys.platform != "darwin" or os.environ.get("RENDER_STATE_NO_OPEN"):
        return "skipped"
    url = "file://" + urllib.parse.quote(path)
    script = (
        'tell application "Google Chrome"\n'
        '  if it is not running then return "closed"\n'
        '  repeat with w in windows\n'
        '    repeat with t in tabs of w\n'
        f'      if URL of t starts with "{url}" then\n'
        '        tell t to reload\n'
        '        return "reloaded"\n'
        '      end if\n'
        '    end repeat\n'
        '  end repeat\n'
        '  return "none"\n'
        'end tell'
    )
    try:
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=15)
        state = res.stdout.strip() or "error"
        if state in ("none", "closed"):
            subprocess.run(["open", "-g", "-a", "Google Chrome", path], timeout=15, check=False)
            return "opened"
        return state
    except (OSError, subprocess.SubprocessError):
        return "error"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--program", required=True)
    ap.add_argument("--out", help="output path; default <programs>/<slug>.state.html")
    args = ap.parse_args(argv)
    now = dt.datetime.now(dt.timezone.utc)
    try:
        payload = build_payload(args.program, now)
    except (OSError, ValueError) as exc:
        print(f"render_state: cannot read program {args.program!r}: {exc}", file=sys.stderr)
        return 1
    out = args.out or st.manifest_path(args.program)[:-5] + ".state.html"
    try:
        with open(TEMPLATE, encoding="utf-8") as fh:
            write_atomic(out, inject(fh.read(), payload))
    except (OSError, ValueError) as exc:
        print(f"render_state: cannot write {out}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"out": out, "problems": len(payload["problems"]),
                      "graph": bool(payload["graph"]["html"]), "chrome": show_in_chrome(out)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
