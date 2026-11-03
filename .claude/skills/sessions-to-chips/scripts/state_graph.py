#!/usr/bin/env python3
"""state_graph.py - the program work graph: map tickets -> carriers -> PRs -> bakes, via Archify.

Pure builder plus one subprocess. Colors come from Archify component types, relabelled through the
legend, so every state color has a printed name. Scope and failure rules:
../specs/2026-11-03-manager-state-viewer.md
"""
import json
import os
import subprocess
import tempfile

MAX_ROWS = 12
TIMEOUT_S = 60
TICKET_WIDTH, CELL_WIDTH = 190, 140  # px: Archify refuses a sublabel its node cannot hold at legible size
# Archify paints these types blue, grey, rose, green and orange: the same state colors as the page.
RUNNING, READY, BLOCKED, PROVEN, UNPROVEN = "frontend", "external", "security", "backend", "messagebus"
LEGEND = {RUNNING: "Running", READY: "Ready", BLOCKED: "Blocked or failed", PROVEN: "Closed, merged or passed",
          UNPROVEN: "Unproven or owed"}
SUMMARY_WORD = {"active": "more running", "blocked": "blocked", "ready": "ready", "closed": "closed"}
RANK = {"active": 0, "blocked": 1, "ready": 2}
ROW_LABEL = {"active": "Running", "blocked": "Blocked", "ready": "Ready"}
TICKET_TYPE = {"active": RUNNING, "blocked": BLOCKED, "ready": READY}
BAKE = {"pass": (PROVEN, "Bake passed"), "fail": (BLOCKED, "Bake failed"), "pending": (UNPROVEN, "Bake owed")}


def short(text, n):
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 3].rstrip() + "..."


def _carrier_node(carriers):
    live = [c for c in carriers if c.get("live") is True]
    first = (live or carriers)[0]
    extra = f" (+{len(carriers) - 1})" if len(carriers) > 1 else ""
    if first["type"] == "founder":
        return UNPROVEN, "founder", "waits on you" + extra
    if live:
        return RUNNING, first["type"], short(first["id"], 18) + extra
    if first.get("live") is False:
        return BLOCKED, first["type"], "not live" + extra
    return UNPROVEN, first["type"], short(first["id"], 18) + extra


def _publication_node(pub, state):
    label = f"PR #{pub['pr']}" if pub.get("pr") else f"Push {str(pub.get('sha') or '')[:8]}"
    return (PROVEN, label, "closed ticket") if state == "closed" else (UNPROVEN, label, "not merged")


def _row_cells(item):
    """The cells after the ticket node, left to right, each with its own column."""
    cells = []
    if item.get("carriers"):
        cells.append((1, _carrier_node(item["carriers"])))
    if item.get("publication"):
        cells.append((2, _publication_node(item["publication"], item["state"])))
    verdict = item.get("bake_verdict")
    if verdict in BAKE:
        kind, label = BAKE[verdict]
        cells.append((3, (kind, label, item.get("kind") or "")))
    elif "BAKE_OWED" in (item.get("flags") or []):
        cells.append((3, (UNPROVEN, "Bake owed", "flagged")))
    return cells


def build_spec(slug, snapshot):
    """-> (Archify workflow spec, tickets drawn), or (None, 0) when the map has no open ticket."""
    items = [i for i in (snapshot or {}).get("items") or [] if i.get("state") in RANK]
    if not items:
        return None, 0
    ordered = sorted(items, key=lambda i: RANK[i["state"]])  # stable: map order inside each state
    carried = [i for i in ordered if _row_cells(i)]
    drawn = carried[:MAX_ROWS]
    lanes, nodes, edges = [], [], []
    for n, item in enumerate(drawn):
        lane = f"row{n}"
        lanes.append({"id": lane, "label": ROW_LABEL[item["state"]]})
        previous = f"{lane}t"
        nodes.append({"id": previous, "lane": lane, "col": 0, "type": TICKET_TYPE[item["state"]], "width": TICKET_WIDTH,
                      "label": str(item["ticket"]), "sublabel": short(item.get("title") or item.get("kind"), 38)})
        for col, (ctype, label, sub) in _row_cells(item):
            node = f"{lane}c{col}"
            spec = {"id": node, "lane": lane, "col": col, "type": ctype, "label": label, "width": CELL_WIDTH}
            if sub:
                spec["sublabel"] = sub
            nodes.append(spec)
            edges.append({"from": previous, "to": node})
            previous = node
    rest = [i for i in ordered if i not in drawn]
    closed = sum(i.get("state") == "closed" for i in snapshot.get("items") or [])
    summary = [(state, [i for i in rest if i["state"] == state]) for state in RANK] + [("closed", [])]
    for state, rows in summary:
        count = closed if state == "closed" else len(rows)
        if count:
            lanes.append({"id": f"rest{state}", "label": "Not drawn"})
            nodes.append({"id": f"rest{state}t", "lane": f"rest{state}", "col": 0, "width": TICKET_WIDTH,
                          "type": TICKET_TYPE.get(state, PROVEN), "label": f"{count} {SUMMARY_WORD[state]}",
                          "sublabel": short(", ".join(str(i["ticket"]) for i in rows) or "listed under What is left", 38)})
    spec = {"schema_version": 2, "diagram_type": "workflow",
            "meta": {"title": f"{slug} work graph", "output": "graph.html", "quality_profile": "showcase",
                     "legend": {"mode": "auto", "entries": {k: {"label": v} for k, v in LEGEND.items()}}},
            "lanes": lanes,
            "phases": [{"id": f"p{col}", "label": label, "fromCol": col, "toCol": col}
                       for col, label in enumerate(("Ticket", "Lane or session", "PR or push", "Bake"))],
            "nodes": nodes, "edges": edges}
    return spec, len(drawn)


def _refusal(stdout, stderr):
    try:
        receipt = json.loads(stdout)
    except ValueError:
        return short(stderr or stdout or "no output", 400)
    if isinstance(receipt.get("error"), str):
        return short(receipt["error"], 400)
    validation = receipt.get("validation") or {}
    issues = [i for i in validation.get("compositionIssues") or [] if i.get("severity") == "error"]
    issues += receipt.get("errors") or validation.get("issues") or []
    first = issues[0] if issues else receipt
    return short(first.get("detail") or first.get("message") or json.dumps(first), 400) if isinstance(first, dict) \
        else short(first, 400)


def deliver(spec, archify, runner=subprocess.run):
    """-> (html, None) or (None, the exact reason). Never raises for a tool failure."""
    if not os.path.isfile(archify):
        return None, f"Archify not found at {archify}"
    with tempfile.TemporaryDirectory(prefix="state-graph-") as tmp:
        src = os.path.join(tmp, "graph.json")
        out = os.path.join(tmp, "graph.html")
        with open(src, "w", encoding="utf-8") as fh:
            json.dump(spec, fh)
        try:
            r = runner(["node", archify, "deliver", "workflow", src, out, "--quality", "showcase", "--json"],
                       capture_output=True, text=True, timeout=TIMEOUT_S, cwd=tmp)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return None, f"Archify did not finish: {exc}"
        if r.returncode != 0 or not os.path.isfile(out):
            return None, f"Archify refused the graph (exit {r.returncode}): {_refusal(r.stdout, r.stderr)}"
        with open(out, encoding="utf-8") as fh:
            return fh.read(), None
