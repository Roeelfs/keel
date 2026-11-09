#!/usr/bin/env python3
"""build_overview.py - refresh the deterministic parts of the founder overview page from the live programs.

Usage: build_overview.py [--force]
Rewrites only the marked regions of `<overview>/overview.html`: the "updated" stamp, the program table (slug, owner
session title, status, next proof owed, state page link), a "changed since last build" strip, and a banner when the
hand-built diagrams have drifted from the programs (a program added or removed, or a destination changed, since the
diagram files were last written). The goal sentence, the live-vs-gates boxes and the three diagrams are judgment and
are never written here. No LLM, stdlib only, no network.

The event: render_state.py calls build() after every successful program render. Debounced: a build within
DEBOUNCE_S of the page's last write is skipped (--force overrides). The program list is state_index.build_index, the
cross-program index's own rows and collapsed programs, so the two pages never disagree. Memory between builds: `<overview>/overview.last.json`.
"""
import argparse
import datetime as dt
import html
import json
import os
import pathlib
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import state_index as si  # noqa: E402
import state_view as sv  # noqa: E402
import work_state_store as st  # noqa: E402

DEBOUNCE_S = 60
PAGE = "overview.html"
LAST = "overview.last.json"
DIAGRAMS = ("overview.architecture.html", "overview.release.html", "overview.programs.html")
CHANGES_MAX = 12
REGIONS = ("head", "table")


def overview_dir():
    return os.environ.get("OVERVIEW_DIR") or os.path.join(os.path.dirname(st.PROGRAMS), "overview")


def utc(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _read(path):
    try:
        with open(path) as fh:
            return fh.read()
    except OSError:
        return None


def _status(text, manifest, now):
    """The last AT-WAKE block's Status, read by the Stop guard (render_state.read_at_wake owns that read)."""
    import render_state  # lazy: render_state imports this module at call time, never at load
    status = render_state.read_at_wake(text, now, []).get("status") if text else None
    return status or manifest.get("status") or "unknown"


def _proof(view):
    for row in view.get("proof_owed") or []:
        if row.get("verdict", "owed") == "owed":
            return row["claim"] + (f" ({row['ticket']})" if row.get("ticket") else "")
    return None


def read_rows(programs_dir, now, titles):
    """-> (rows, quiet): the cross-program index's own rows and collapsed programs (state_index.build_index), each row
    joined with its state file's AT-WAKE Status and first owed proof. A missing state file reads as None, never a guess."""
    index = si.build_index(now, titles, programs_dir)
    rows = []
    for r in index["rows"]:
        slug = r["program"]
        text = _read(os.path.join(programs_dir, slug + ".state.md"))
        view = sv.read_view(text, now, [])["view"] if text else {}
        manifest = json.loads(_read(os.path.join(programs_dir, slug + ".json")) or "{}")
        rows.append({"program": slug, "owner": r["name"] if r["name"] != slug else None,
                     "status": _status(text, manifest, now), "proof": _proof(view),
                     "destination": view.get("destination"),
                     "page": pathlib.Path(os.path.join(programs_dir, r["page"])).absolute().as_uri()})
    quiet = [{"program": q["program"], "why": q["why"]} for q in index["quiet"]]
    return rows, quiet


def diff(prev_rows, rows):
    """-> list of one-line changes from the last build's rows to these."""
    before = {r["program"]: r for r in prev_rows}
    after = {r["program"]: r for r in rows}
    out = [f"{s} added" for s in sorted(set(after) - set(before))]
    out += [f"{s} removed" for s in sorted(set(before) - set(after))]
    for s in sorted(set(before) & set(after)):
        a, b = before[s], after[s]
        if a.get("status") != b.get("status"):
            out.append(f"{s}: status {a.get('status')} -> {b.get('status')}")
        if a.get("proof") != b.get("proof"):
            out.append(f"{s}: next proof owed changed")
        if a.get("destination") != b.get("destination"):
            out.append(f"{s}: destination changed")
        if a.get("owner") != b.get("owner"):
            out.append(f"{s}: owner session is now {b.get('owner') or 'unknown'}")
    return out


def diagrams_built(odir):
    """-> mtime of the newest diagram file, or None when none exists."""
    times = [os.path.getmtime(p) for p in (os.path.join(odir, d) for d in DIAGRAMS) if os.path.exists(p)]
    return max(times) if times else None


def diagram_drift(baseline, rows):
    """-> list of drift lines between the diagrams' baseline {slug: destination} and the current rows."""
    now = {r["program"]: r.get("destination") for r in rows}
    out = [f"{s} added" for s in sorted(set(now) - set(baseline))]
    out += [f"{s} removed" for s in sorted(set(baseline) - set(now))]
    out += [f"{s}: destination changed" for s in sorted(set(now) & set(baseline)) if now[s] != baseline[s]]
    return out


def _esc(v):
    return html.escape(str(v)) if v is not None else '<span class="unv">unknown</span>'


def render_head(now, rows, changes, changes_at, banner):
    parts = [f'<div class="mut">Program table updated <b>{utc(now)}</b> from {len(rows)} live program(s), '
             f'automatically on every program render. The goal, the two boxes and the diagrams are hand-built.</div>']
    if banner:
        parts.append(f'<div class="box gate"><b>Diagrams built {_esc(banner["built"])}; rebuild on request.</b> '
                     f'Since then: {_esc("; ".join(banner["drift"]))}.</div>')
    if changes:
        shown = changes[:CHANGES_MAX]
        more = f" (+{len(changes) - len(shown)} more)" if len(changes) > len(shown) else ""
        parts.append(f'<div class="mut">Last change between builds, detected {_esc(changes_at)}: '
                     f'{_esc("; ".join(shown))}{more}</div>')
    else:
        parts.append('<div class="mut">No change between builds recorded yet.</div>')
    return "\n  ".join(parts)


def render_table(rows, quiet):
    body = []
    for r in rows:
        body.append(f'<tr><td><b>{_esc(r["program"])}</b></td><td>{_esc(r["owner"])}</td><td>{_esc(r["status"])}</td>'
                    f'<td>{_esc(r["proof"])}</td><td><a href="{html.escape(r["page"])}">state</a></td></tr>')
    return ('<h2>Every live program</h2>\n  <table>\n    <thead><tr><th>Program</th><th>Owner session</th><th>Status</th>'
            '<th>Next proof owed</th><th>State page</th></tr></thead>\n    <tbody>\n      '
            + "\n      ".join(body) + "\n    </tbody>\n  </table>" + _quiet_line(quiet))


def _quiet_line(quiet):
    if not quiet:
        return ""
    whys = sorted({q["why"] for q in quiet})
    return (f'\n  <details class="mut"><summary>{len(quiet)} more live program(s) not shown ({_esc(", ".join(whys))}), '
            f'as on the index</summary>{_esc(", ".join(q["program"] for q in quiet))}</details>')


def _mark(name, body):
    return f"<!-- auto:{name} -->\n  {body}\n  <!-- /auto:{name} -->"


SKELETON = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Overview</title>
<style>body{font:15px/1.5 -apple-system,sans-serif;margin:24px}.mut{color:#666;font-size:13px}.unv{color:#b60}
table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #ddd}
.box{border:1px solid #c33;padding:8px 12px;margin:8px 0}</style></head>
<body>
<main>
  <h1>Overview</h1>
</main>
</body>
</html>
"""


def splice(page, regions):
    """Replace each marked region; on a page without markers, adopt its hand-built table and add the head after <h1>."""
    for name in REGIONS:
        block = _mark(name, regions[name])
        marked = re.compile(rf"<!-- auto:{name} -->.*?<!-- /auto:{name} -->", re.S)
        if marked.search(page):
            page = marked.sub(lambda _: block, page, count=1)
            continue
        if name == "table":
            legacy = re.compile(r"<h2>Every live program</h2>\s*<table>.*?</table>(?:\s*<p class=\"mut\">.*?</p>)?", re.S)
            if legacy.search(page):
                page = legacy.sub(lambda _: block, page, count=1)
                continue
            anchor = re.search(r"</main>|</body>", page)
        else:
            anchor = re.search(r"</h1>", page)
            if anchor:
                page = page[:anchor.end()] + "\n  " + block + page[anchor.end():]
                continue
            anchor = re.search(r"<main>|<body>", page)
            if anchor:
                page = page[:anchor.end()] + "\n  " + block + page[anchor.end():]
                continue
        at = anchor.start() if anchor else len(page)
        page = page[:at] + "  " + block + "\n" + page[at:]
    return page


def _write(path, text):
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w") as fh:
        fh.write(text)
    os.replace(tmp, path)


def build(now=None, odir=None, programs_dir=None, titles=None, force=False):
    """-> {"out", "rows", "changes", "banner"} or {"skipped": reason}. Raises on a failed read or write."""
    odir = odir or overview_dir()
    programs_dir = programs_dir or st.PROGRAMS
    page_path = os.path.join(odir, PAGE)
    if not force and os.path.exists(page_path) and time.time() - os.path.getmtime(page_path) < DEBOUNCE_S:
        return {"skipped": f"debounced: {PAGE} was written under {DEBOUNCE_S}s ago"}
    now = now or dt.datetime.now(dt.timezone.utc)
    rows, quiet = read_rows(programs_dir, now, titles)
    last_raw = _read(os.path.join(odir, LAST))
    last = json.loads(last_raw) if last_raw else {}
    changes = diff(last["rows"], rows) if "rows" in last else []
    changes_at = utc(now) if changes else last.get("changes_at")
    changes = changes or last.get("changes") or []
    built = diagrams_built(odir)
    diagrams = last.get("diagrams") or {}
    if built is not None and diagrams.get("built_mtime") != built:
        diagrams = {"built_mtime": built, "programs": {r["program"]: r.get("destination") for r in rows}}
    banner = None
    if built is not None:
        drift = diagram_drift(diagrams["programs"], rows)
        if drift:
            banner = {"built": dt.datetime.fromtimestamp(built, dt.timezone.utc).strftime("%Y-%m-%d"), "drift": drift}
    os.makedirs(odir, exist_ok=True)
    page = _read(page_path) or SKELETON
    page = splice(page, {"head": render_head(now, rows, changes, changes_at, banner), "table": render_table(rows, quiet)})
    _write(page_path, page)
    _write(os.path.join(odir, LAST), json.dumps({"built_at": utc(now), "rows": rows, "changes": changes,
                                                 "changes_at": changes_at, "diagrams": diagrams}, indent=1))
    return {"out": page_path, "rows": len(rows), "changes": len(changes), "banner": bool(banner)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--force", action="store_true", help="build even inside the debounce window")
    args = ap.parse_args(argv)
    print(json.dumps(build(force=args.force)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
