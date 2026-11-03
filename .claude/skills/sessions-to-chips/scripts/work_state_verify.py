#!/usr/bin/env python3
"""Verification tooling for the work-state engine (V0, V1, V2). Each check states its failure.

  v0 --program <slug> [--runs 20]   time `work_state.py guard` on the real store, warm index, one
                                    changed session file per run (simulated by dropping that file's
                                    index entry, so the store itself is never touched).
                                    FAIL if p95 >= 1 s or any run >= 2 s.
  v1 --program <slug> --out <dir>   save one `snapshot --json` and a hand-classification sheet: every
                                    open child and every carrier the state file names since --since.
                                    FAIL is a human verdict: any row left unexplained.
  v2 [--program <slug>] [--live]    read work-state.jsonl: a cold tracker fetch costs ceil(children/50)
                                    requests and <= 5,000 x-complexity per page; --live also runs a cold
                                    then a warm snapshot and FAILs on any request the warm one makes.
Exit 0 PASS, 1 FAIL, 2 cannot run.
"""
import argparse
import json
import math
import os
import re
import statistics
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import program_family as pf  # noqa: E402
import work_state_sources as src  # noqa: E402
import work_state_store as st  # noqa: E402

ENGINE = os.path.join(HERE, "work_state.py")


def v0(slug, runs=20, facts=None):
    facts = facts or {"state_facts": {"status": "WORKING"}, "live_bg": []}
    pf.session_index()  # warm
    try:
        with open(pf.INDEX) as fh:
            files = sorted(json.load(fh)["files"])
    except (OSError, ValueError, KeyError):
        return {"verdict": "CANNOT-RUN", "why": "no session index"}, 2
    times, rcs = [], []
    for i in range(runs):
        with open(pf.INDEX) as fh:
            idx = json.load(fh)
        idx["files"].pop(files[i % len(files)], None)
        with open(pf.INDEX, "w") as fh:
            json.dump(idx, fh)
        t0 = time.monotonic()
        p = subprocess.run([sys.executable, "-I", ENGINE, "guard", "--program", slug], input=json.dumps(facts),
                           capture_output=True, text=True, timeout=10)
        times.append(time.monotonic() - t0)
        rcs.append(p.returncode)
    times.sort()
    p95 = times[max(0, math.ceil(0.95 * len(times)) - 1)]
    res = {"runs": runs, "p50_s": round(statistics.median(times), 3), "p95_s": round(p95, 3),
           "max_s": round(times[-1], 3), "exit_codes": sorted(set(rcs))}
    fail = p95 >= 1.0 or times[-1] >= 2.0 or any(rc not in (0, 4) for rc in rcs)
    res["verdict"] = "FAIL" if fail else "PASS"
    return res, int(fail)


def v1(slug, out, since="2026-11-01"):
    os.makedirs(out, exist_ok=True)
    p = subprocess.run([sys.executable, "-I", ENGINE, "snapshot", "--program", slug, "--json"], capture_output=True,
                       text=True, timeout=120)
    with open(os.path.join(out, "snapshot.json"), "w") as fh:
        fh.write(p.stdout)
    try:
        snap = json.loads(p.stdout)
    except ValueError:
        return {"verdict": "CANNOT-RUN", "why": p.stdout[:300]}, 2
    if snap.get("error"):
        return {"verdict": "CANNOT-RUN", "why": snap}, 2
    rows = [("child", i["ticket"], i["state"], ",".join(i["flags"]), "") for i in snap["items"] if i["state"] != "closed"]
    try:
        text = open(st.manifest_path(slug)[:-5] + ".state.md").read()
    except OSError:
        text = ""
    carriers = set()
    for blk in re.split(r"^## ", text, flags=re.M):
        dates = re.findall(r"\d{4}-\d{2}-\d{2}", blk[:200])
        if dates and max(dates) < since:
            continue
        carriers |= {c for c in re.findall(r"\b(?:bg|agent|workflow|session|task|lane)(?:\s+task)?[:\s]+([A-Za-z0-9_-]{6,})",
                                            blk) if re.search(r"\d", c)}
        carriers |= set(re.findall(r"\blocal_[0-9a-f]{8}\b", blk))
    rows += [("carrier", c, "", "", "") for c in sorted(carriers)]
    with open(os.path.join(out, "classification.tsv"), "w") as fh:
        fh.write("kind\tid\tstate\tflags\thand verdict (bound|held|real flag|explained: why)\n")
        for r in rows:
            fh.write("\t".join(r) + "\n")
    return {"verdict": "NEEDS-HAND-CLASSIFICATION", "rows": len(rows), "out": out}, 0


def v2(slug=None, live=False):
    def rows():
        try:
            with open(src.ANALYTICS) as fh:
                return [json.loads(x) for x in fh if x.strip()]
        except OSError:
            return []
    fails = []
    if live:
        if not slug:
            return {"verdict": "CANNOT-RUN", "why": "--live needs --program"}, 2
        n0 = len(rows())
        subprocess.run([sys.executable, "-I", ENGINE, "snapshot", "--program", slug, "--refresh", "--json"],
                       capture_output=True, text=True, timeout=180)
        n1 = len(rows())
        subprocess.run([sys.executable, "-I", ENGINE, "snapshot", "--program", slug, "--json"], capture_output=True,
                       text=True, timeout=180)
        warm = [r for r in rows()[n1:] if r.get("source") in ("tracker", "gh") and r.get("program") == slug]
        if warm:
            fails.append(f"warm snapshot made {len(warm)} remote request rows")
        if n1 == n0:
            fails.append("cold snapshot logged no remote request (no tracker configured?)")
    tr = [r for r in rows() if r.get("source") == "tracker" and r.get("requests") is not None
          and (not slug or r.get("program") == slug)]
    for r in tr:
        want = math.ceil((r.get("children_count") or 0) / 50) or 1
        if r["requests"] > want:
            fails.append(f"{r['ts']} {r['program']}: {r['requests']} tracker requests > ceil(children/50) = {want}")
        over = [x for x in r.get("x_complexity") or [] if x and x > 5000]
        if over:
            fails.append(f"{r['ts']} {r['program']}: x-complexity {over} > 5,000 per page")
    res = {"tracker_rows": len(tr), "fails": fails}
    if not tr:
        return dict(res, verdict="CANNOT-RUN", why="no tracker request rows recorded"), 2
    res["verdict"] = "FAIL" if fails else "PASS"
    return res, int(bool(fails))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a0 = sub.add_parser("v0")
    a0.add_argument("--program", required=True)
    a0.add_argument("--runs", type=int, default=20)
    a1 = sub.add_parser("v1")
    a1.add_argument("--program", required=True)
    a1.add_argument("--out", required=True)
    a1.add_argument("--since", default="2026-11-01")
    a2 = sub.add_parser("v2")
    a2.add_argument("--program")
    a2.add_argument("--live", action="store_true")
    a = ap.parse_args()
    if a.cmd == "v0":
        res, rc = v0(a.program, a.runs)
    elif a.cmd == "v1":
        res, rc = v1(a.program, a.out, a.since)
    else:
        res, rc = v2(a.program, a.live)
    print(json.dumps(res, indent=2))
    return rc


if __name__ == "__main__":
    sys.exit(main())
