#!/usr/bin/env python3
"""One row per PROGRAM across ALL accounts: every manager id it ever had, the newest activity of
its whole lineage, and whether its manager transcripts can be trusted. Read-only.

Why: Mode 4 sweeps used to key on one "other account" and one manager id. Measured 2026-11-01:
programs hop between accounts and carry several manager ids (Release had 3, Cynap 4); a
single-account sweep orphaned children whose spawnedFrom parent sat on the other account.
A manager's transcript can also end days before the store's lastActivityAt (Release: last
user/assistant row 2026-10-28T12:38Z, store 2026-10-31T11:27Z), so "mined the transcript" never
means "mined the program".

Usage: program_family.py [--since ISO] [--grep TITLE-SUBSTR] [--json]
Columns: program | manager ids (account:cli8) | newest lineage activity | per-manager transcript
verdict. GAP = store activity is >30 min newer than the transcript's last user/assistant row:
work after that row is NOT minable; read the manager's state/map and its children instead.
RESUMED = transcript rows carry two accountUuids (the session ran on both accounts).
"""
import argparse, collections, datetime, glob, json, os, re

STORE = os.path.expanduser("~/Library/Application Support/Claude/claude-code-sessions")
PROJECTS = os.path.expanduser("~/.claude/projects")


def iso(ms):
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ") if ms else "-"


def program_key(title):
    t = re.sub(r"^\[Manager\]\s*[-:]?\s*", "", title).lower()
    return re.sub(r"[^a-z0-9]+", " ", t).split(":")[0].strip()[:40]


def transcript_facts(cli):
    hits = glob.glob(f"{PROJECTS}/*/{cli}.jsonl") if cli else []
    if not hits:
        return None
    path = max(hits, key=os.path.getmtime)
    last, accts = None, set()
    with open(path, errors="ignore") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("accountUuid"):
                accts.add(r["accountUuid"][:8])
            if r.get("type") in ("user", "assistant") and r.get("timestamp"):
                last = r["timestamp"]
    return {"path": path, "last_msg": last, "accounts": sorted(accts)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-01-01T00:00")
    ap.add_argument("--grep", default="")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    since = int(datetime.datetime.fromisoformat(a.since).replace(tzinfo=datetime.timezone.utc).timestamp() * 1000)

    rows = {}
    for f in glob.glob(f"{STORE}/*/*/local_*.json"):
        try:
            d = json.load(open(f))
        except ValueError:
            continue
        d["_acct"] = f[len(STORE) + 1:].split(os.sep)[0][:8]
        rows[d["sessionId"]] = d

    def root_manager(sid):
        cur, seen = sid, set()
        while cur in rows and cur not in seen:
            seen.add(cur)
            if rows[cur].get("title", "").startswith("[Manager]"):
                return cur
            cur = (rows[cur].get("spawnedFrom") or {}).get("sessionId")
        return None

    programs = collections.defaultdict(lambda: {"managers": [], "lineage_last": 0, "children": 0})
    for sid, d in rows.items():
        if d.get("title", "").startswith("[Manager]") and a.grep.lower() in d["title"].lower():
            p = programs[program_key(d["title"])]
            p["managers"].append(d)
    for sid, d in rows.items():
        m = root_manager(sid)
        if m and not d.get("title", "").startswith("[Manager]"):
            k = program_key(rows[m]["title"])
            if k in programs:
                programs[k]["children"] += 1
                programs[k]["lineage_last"] = max(programs[k]["lineage_last"], d.get("lastActivityAt", 0))

    out = []
    for k, p in programs.items():
        mgrs = sorted(p["managers"], key=lambda d: -d.get("lastActivityAt", 0))
        newest = max([m.get("lastActivityAt", 0) for m in mgrs] + [p["lineage_last"]])
        if newest < since:
            continue
        per = []
        for m in mgrs:
            tf = transcript_facts(m.get("cliSessionId"))
            store = m.get("lastActivityAt", 0)
            verdict = "NO-TRANSCRIPT"
            if tf:
                last = tf["last_msg"]
                lm = int(datetime.datetime.fromisoformat(last.replace("Z", "+00:00")).timestamp() * 1000) if last else 0
                verdict = "GAP" if store - lm > 30 * 60 * 1000 else "ok"
                if len(tf["accounts"]) > 1:
                    verdict += "+RESUMED"
            per.append({"acct": m["_acct"], "cli": (m.get("cliSessionId") or "")[:8], "archived": bool(m.get("isArchived")),
                        "store_last": iso(store), "transcript_last_msg": (tf or {}).get("last_msg"), "verdict": verdict})
        out.append({"program": k, "managers": per, "lineage_last": iso(newest), "children": p["children"]})
    out.sort(key=lambda r: r["lineage_last"], reverse=True)
    if a.json:
        print(json.dumps(out, indent=2))
        return
    for r in out:
        print(f"\n{r['program']}  lineage-last {r['lineage_last']}  children {r['children']}")
        for m in r["managers"]:
            print(f"   {m['acct']}:{m['cli']}{' arch' if m['archived'] else ''}  store {m['store_last']}  "
                  f"transcript {m['transcript_last_msg']}  {m['verdict']}")


if __name__ == "__main__":
    main()
