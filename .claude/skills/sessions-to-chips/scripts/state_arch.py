#!/usr/bin/env python3
"""state_arch.py - the one owner of "architecture over time" for a program's state page.

Validates `<slug>.arch.json` (schema state-arch/1), archives each new version append-only to
`<slug>.arch/<sha12>.json`, renders its views with Archify to `<slug>.arch/<sha12>/<view-id>.html` only when
the hash changed, an output is missing or the last build failed, and lists versions in
`<slug>.arch/index.json`. A version is marked built only on success. `--repo-root` is never passed,
`ARCHIFY_BRAND_ALLOW_PRIVATE` is stripped from Archify's environment, and any input carrying
`meta.repository` is refused (both would leak private paths into a diagram).

Usage: state_arch.py --program <slug>   (build now; the renderer calls `build` after writing the page)
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import work_state_store as st  # noqa: E402

SCHEMA = "state-arch/1"
TYPES = ("architecture", "workflow", "sequence", "dataflow", "lifecycle")
VIEW_KEYS = {"id", "title", "type", "base", "head", "note"}
VIEW_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
BUILD_TIMEOUT_S = 120
AUTHORING = "references/manager-contract.md, State page: the system diagram"


def archify_bin():
    return os.environ.get("STATE_ARCH_ARCHIFY") or os.path.join(st.HOME, "skills", "archify", "bin", "archify.mjs")


def paths(slug, programs=None):
    base = st.manifest_path(slug, programs)[:-5]
    return base + ".arch.json", base + ".arch"


def _carries_repository(obj):
    if isinstance(obj, dict):
        if isinstance(obj.get("meta"), dict) and "repository" in obj["meta"]:
            return True
        return any(_carries_repository(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_carries_repository(v) for v in obj)
    return False


def validate(doc):
    """-> [problem text]. Empty means valid."""
    if not isinstance(doc, dict):
        return ["the file must hold one JSON object"]
    errs = []
    unknown = sorted(set(doc) - {"updated_at", "views"})
    if unknown:
        errs.append(f"unknown keys {unknown}")
    views = doc.get("views")
    if not isinstance(views, list) or not views:
        return errs + ["`views` must be a non-empty list"]
    seen = set()
    for n, v in enumerate(views):
        where = f"views[{n}]"
        if not isinstance(v, dict):
            errs.append(f"{where} must be an object")
            continue
        extra = sorted(set(v) - VIEW_KEYS)
        if extra:
            errs.append(f"{where} has unknown keys {extra}")
        if not isinstance(v.get("id"), str) or not VIEW_ID.match(v["id"]) or v["id"] in seen:
            errs.append(f"{where}.id must be a unique lowercase slug")
        seen.add(v.get("id"))
        if v.get("type") not in TYPES:
            errs.append(f"{where}.type must be one of {', '.join(TYPES)}")
        if not isinstance(v.get("head"), dict):
            errs.append(f"{where}.head must be an Archify document")
        if "base" in v and (v.get("type") != "architecture" or not isinstance(v["base"], dict)):
            errs.append(f"{where}.base is only for an architecture view, as an Archify document")
        if _carries_repository([v.get("base"), v.get("head")]):
            errs.append(f"{where} carries meta.repository, which would publish private paths; remove it")
    return errs


def digest(doc):
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:12]


def read_index(arch_dir):
    try:
        with open(os.path.join(arch_dir, "index.json")) as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) and isinstance(data.get("versions"), list) else {"versions": []}
    except (OSError, ValueError):
        return {"versions": []}


def _write_json(path, obj):
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh, indent=1, sort_keys=True)
    os.replace(tmp, path)


def load(slug, programs=None):
    """-> (doc|None, sha|None, [problem]). An absent file is not a problem; the page says how to add one."""
    src, _ = paths(slug, programs)
    if not os.path.isfile(src):
        return None, None, []
    try:
        with open(src) as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as exc:
        return None, None, [f"{os.path.basename(src)} is not valid JSON: {exc}"]
    errs = validate(doc)
    return (None, None, errs) if errs else (doc, digest(doc), [])


def archive(arch_dir, doc, sha):
    """Append-only: a version file is written once and never rewritten."""
    os.makedirs(arch_dir, exist_ok=True)
    path = os.path.join(arch_dir, f"{sha}.json")
    if not os.path.exists(path):
        _write_json(path, doc)
    return path


def _clean_env():
    env = dict(os.environ)
    env.pop("ARCHIFY_BRAND_ALLOW_PRIVATE", None)
    return env


def _summary(receipt_path):
    try:
        with open(receipt_path) as fh:
            comp = (json.load(fh).get("summary") or {}).get("components") or {}
        return {k: int(comp.get(k) or 0) for k in ("added", "changed", "removed")}
    except (OSError, ValueError, TypeError):
        return None


def render_view(view, out_dir, run=subprocess.run):
    """-> {id, title, type, note, file, summary, ok, error}. Inputs are written beside the output."""
    vid = view["id"]
    out = os.path.join(out_dir, f"{vid}.html")
    head = os.path.join(out_dir, f"{vid}.head.json")
    _write_json(head, view["head"])
    node = ["node", archify_bin()]
    if view["type"] == "architecture" and view.get("base"):
        base = os.path.join(out_dir, f"{vid}.base.json")
        receipt = os.path.join(out_dir, f"{vid}.receipt.json")
        _write_json(base, view["base"])
        cmd = node + ["compare", "architecture", base, head, out, "--receipt", receipt, "--json"]
    else:
        receipt = None
        cmd = node + ["deliver", view["type"], head, out, "--json"]
    row = {"id": vid, "title": view.get("title") or vid, "type": view["type"], "note": view.get("note"),
           "file": os.path.join(os.path.basename(out_dir), f"{vid}.html"), "compare": bool(receipt), "summary": None}
    try:
        r = run(cmd, capture_output=True, text=True, timeout=BUILD_TIMEOUT_S, env=_clean_env())
    except (OSError, subprocess.TimeoutExpired) as exc:
        return dict(row, ok=False, error=f"Archify did not finish: {exc}")
    if r.returncode != 0 or not os.path.isfile(out):
        return dict(row, ok=False, error=f"Archify exit {r.returncode}: {(r.stderr or r.stdout).strip()[-300:]}")
    return dict(row, ok=True, error=None, summary=_summary(receipt) if receipt else None)


def needs_build(index, sha, arch_dir):
    entry = next((v for v in index["versions"] if v.get("sha") == sha), None)
    if not entry or not entry.get("built"):
        return True
    return any(not os.path.isfile(os.path.join(arch_dir, v["file"])) for v in entry.get("views") or [])


def build(slug, programs=None, run=subprocess.run, now=None):
    """Validate, archive, render when needed, update index.json. -> (index, [problem])."""
    doc, sha, problems = load(slug, programs)
    _, arch_dir = paths(slug, programs)
    index = read_index(arch_dir)
    if not doc:
        return index, problems
    archive(arch_dir, doc, sha)
    if not needs_build(index, sha, arch_dir):
        return index, problems
    if not os.path.isfile(archify_bin()):
        problems.append(f"Archify is not installed at {archify_bin()}, so the diagram was not drawn")
        views, built = [], False
    else:
        out_dir = os.path.join(arch_dir, sha)
        os.makedirs(out_dir, exist_ok=True)
        views = [render_view(v, out_dir, run) for v in doc["views"]]
        built = all(v["ok"] for v in views)
        problems += [f"diagram {v['id']}: {v['error']}" for v in views if not v["ok"]]
    stamp = (now or dt.datetime.now(dt.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    keep = [v for v in index["versions"] if v.get("sha") != sha]
    prior = next((v for v in index["versions"] if v.get("sha") == sha), {})
    entry = {"sha": sha, "updated_at": doc.get("updated_at"), "archived_at": prior.get("archived_at") or stamp,
             "built": built, "views": views}
    index = {"schema": SCHEMA, "current": sha, "versions": keep + [entry]}
    _write_json(os.path.join(arch_dir, "index.json"), index)
    return index, problems


def page_section(slug, programs=None):
    """What the page shows, read without building. -> {current, archived, reason, problems}."""
    doc, sha, problems = load(slug, programs)
    _, arch_dir = paths(slug, programs)
    index = read_index(arch_dir)
    versions = index["versions"]
    archived = [v for v in versions if v.get("sha") != sha and v.get("built")]
    archived.sort(key=lambda v: v.get("archived_at") or "", reverse=True)
    rel = os.path.basename(arch_dir)
    fix = lambda v: dict(v, views=[dict(x, file=f"{rel}/{x['file']}") for x in v.get("views") or [] if x.get("ok")])
    if doc is None:
        reason = None if problems else "No system diagram yet"
        return {"current": None, "archived": [fix(v) for v in archived], "reason": reason,
                "pointer": AUTHORING, "problems": problems, "dir": arch_dir}
    entry = next((v for v in versions if v.get("sha") == sha), None)
    current = {"sha": sha, "updated_at": doc.get("updated_at"),
               "views": [{"id": v["id"], "title": v.get("title") or v["id"], "type": v["type"], "note": v.get("note")}
                         for v in doc["views"]], "built": False}
    if entry and entry.get("built") and not needs_build(index, sha, arch_dir):
        current = dict(fix(entry), built=True)
    return {"current": current, "archived": [fix(v) for v in archived], "reason": None, "pointer": AUTHORING,
            "problems": problems, "dir": arch_dir}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--program", required=True)
    a = ap.parse_args(argv)
    index, problems = build(a.program)
    print(json.dumps({"current": index.get("current"), "problems": problems}))
    return 0 if not problems else 2


if __name__ == "__main__":
    sys.exit(main())
