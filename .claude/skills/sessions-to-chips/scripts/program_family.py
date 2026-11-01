#!/usr/bin/env python3
"""One row per PROGRAM across ALL accounts: every manager instance it ever had. Read-only.

Why: programs hop between accounts and carry one manager id per hop (measured 2026-11-01: Release
had 3, Cynap 4), and a child's spawnedFrom parent often sits on the other account.

Identity, strongest first:
  1. A program manifest (~/.claude/orchestrator/programs/<slug>.json) whose `manager_session` or
     `orchestrator_session` names the row's session id, its CLI id, or any transcript of its chain
     (manifests often name an OLD transcript: Apps names edae2f58, which no store row carries).
  2. The title key: "[Manager] User Journey: map ..." and "[Manager] CRM (fork)" key as
     "user journey" and "crm".
A title group that matches a manifest takes the manifest's slug; `absorbed_by` is carried.

Usage: program_family.py [--since ISO] [--grep TITLE-SUBSTR] [--json]
"""
import argparse
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import transcript_chain as tc  # noqa: E402

STORE = os.environ.get("S2C_STORE") or os.path.expanduser("~/Library/Application Support/Claude/claude-code-sessions")
HOME = os.environ.get("S2C_CLAUDE_HOME") or os.path.expanduser("~/.claude")
ID_RX = re.compile(r"(?:local_|(?<![0-9a-z]))([0-9a-f]{6,8})")


def is_manager(row):
    return (row.get("title") or "").startswith("[Manager]")


def program_key(title):
    t = re.sub(r"^\[Manager\]\s*[-:]?\s*", "", title or "")
    t = re.sub(r"\((fork|copy)\)", "", t, flags=re.I).split(":")[0]
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()[:40]


def load_store(store=None):
    """-> (rows {sessionId: row+_acct/_org/_file}, unreadable [(file, reason)], accounts summary)."""
    store = store or STORE
    rows, bad, accounts = {}, [], {}
    for acct in sorted(os.listdir(store)) if os.path.isdir(store) else []:
        adir = os.path.join(store, acct)
        if not os.path.isdir(adir):
            continue
        a = accounts.setdefault(acct, {"orgs": {}, "sessions": 0, "managers": 0, "unreadable": 0})
        for org in sorted(os.listdir(adir)):
            files = glob.glob(os.path.join(adir, org, "local_*.json"))
            a["orgs"][org] = len(files)
            for f in files:
                try:
                    with open(f) as fh:
                        d = json.load(fh)
                except (OSError, ValueError) as e:
                    bad.append((f, f"{type(e).__name__}: {e}"[:120]))
                    a["unreadable"] += 1
                    continue
                d["_acct"], d["_org"], d["_file"] = acct, org, f
                d.setdefault("sessionId", os.path.basename(f)[:-5])
                rows[d["sessionId"]] = d
                a["sessions"] += 1
                a["managers"] += is_manager(d)
    return rows, bad, accounts


def load_manifests(programs_dir=None):
    out = []
    for f in glob.glob(os.path.join(programs_dir or os.path.join(HOME, "orchestrator/programs"), "*.json")):
        try:
            d = json.load(open(f))
        except (OSError, ValueError):
            continue
        if not isinstance(d, dict) or not d.get("program"):
            continue
        ids = set()
        for k in ("manager_session", "orchestrator_session"):
            ids |= {m.group(1) for m in ID_RX.finditer(str(d.get(k) or "")) if any(c.isdigit() for c in m.group(1))}
        out.append({"slug": d["program"], "ids": ids, "absorbed_by": d.get("absorbed_by"),
                    "absorbs": d.get("absorbs"), "map": d.get("map"), "updated_at": d.get("updated_at"),
                    "manifest": f, "mtime": os.path.getmtime(f)})
    return out


def root_manager(sid, rows):
    cur, seen = sid, set()
    while cur in rows and cur not in seen:
        seen.add(cur)
        if is_manager(rows[cur]):
            return cur
        cur = (rows[cur].get("spawnedFrom") or {}).get("sessionId")
    return None


def instance_ids(row, chain_stems=()):
    return {row["sessionId"].replace("local_", ""), row.get("cliSessionId") or ""} | set(chain_stems)


def manifest_for(ids, manifests):
    hits = [m for m in manifests if any(i and any(i.startswith(p) for p in m["ids"]) for i in ids)]
    return max(hits, key=lambda m: m["mtime"]) if hits else None


def families(rows, manifests, chains=None):
    """-> {slug: {"key", "managers": [sid], "lineage": [sid], "manifest": m|None, "conflict": [...]}}.
    chains: {sessionId: [transcript stems]} widens manifest matching to every chain segment."""
    chains = chains or {}
    groups = {}
    for sid, d in rows.items():
        if is_manager(d):
            groups.setdefault(program_key(d["title"]), []).append(sid)
    out = {}
    for key, sids in groups.items():
        found = [m for m in (manifest_for(instance_ids(rows[s], chains.get(s, ())), manifests) for s in sids) if m]
        man = max(found, key=lambda m: m["mtime"]) if found else None
        slug = man["slug"] if man else key.replace(" ", "-")
        fam = out.setdefault(slug, {"key": key, "managers": [], "lineage": [], "manifest": man, "conflict": []})
        fam["managers"] += sids
        fam["conflict"] = sorted(set(fam["conflict"]) | ({m["slug"] for m in found} - {slug}))
    by_mgr = {s: slug for slug, f in out.items() for s in f["managers"]}
    for sid in rows:
        m = root_manager(sid, rows)
        if m and m != sid and m in by_mgr:
            out[by_mgr[m]]["lineage"].append(sid)
    return out


def turn_verdict(row, files):
    """-> (verdict, last turn ts). ok | NON-TURN-ACTIVITY (store moved on focus or artifact rows
    only; lastAssistantUuid is in the transcript) | MISSING-TURNS | NO-TRANSCRIPT."""
    if not files:
        return "NO-TRANSCRIPT", 0.0
    last = max(tc.tail_facts(f)["last_turn_ts"] for f in files)
    want = row.get("lastAssistantUuid")
    if want and not any(tc.contains(f, want) for f in files):
        return "MISSING-TURNS", last
    gap = tc.parse_ts(row.get("lastActivityAt")) - last
    return ("NON-TURN-ACTIVITY" if gap > 1800 else "ok"), last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-01-01T00:00")
    ap.add_argument("--grep", default="")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    since = tc.parse_ts(a.since)
    rows, _, _ = load_store()
    out = []
    for slug, f in families(rows, load_manifests()).items():
        mgrs = sorted((rows[s] for s in f["managers"]), key=lambda d: -d.get("lastActivityAt", 0))
        if a.grep.lower() not in " ".join(m["title"].lower() for m in mgrs):
            continue
        newest = max(tc.parse_ts(rows[s].get("lastActivityAt")) for s in f["managers"] + f["lineage"])
        if newest < since:
            continue
        per = []
        for m in mgrs:
            verdict, last = turn_verdict(m, tc.files_named(m.get("cliSessionId")))
            per.append({"acct": m["_acct"][:8], "session": m["sessionId"][6:14], "cli": (m.get("cliSessionId") or "")[:8],
                        "archived": bool(m.get("isArchived")), "store_last": tc.iso(tc.parse_ts(m.get("lastActivityAt"))),
                        "last_turn": tc.iso(last), "verdict": verdict})
        out.append({"program": slug, "absorbed_by": (f["manifest"] or {}).get("absorbed_by"),
                    "managers": per, "lineage_last": tc.iso(newest), "children": len(f["lineage"])})
    out.sort(key=lambda r: r["lineage_last"], reverse=True)
    if a.json:
        print(json.dumps(out, indent=2))
        return
    for r in out:
        ab = f"  absorbed_by {r['absorbed_by']}" if r["absorbed_by"] else ""
        print(f"\n{r['program']}{ab}  lineage-last {r['lineage_last']}  children {r['children']}")
        for m in r["managers"]:
            print(f"   {m['acct'][:8]}:{m['session']} cli {m['cli']}{' arch' if m['archived'] else ''}  "
                  f"store {m['store_last']}  last turn {m['last_turn']}  {m['verdict']}")


if __name__ == "__main__":
    main()
