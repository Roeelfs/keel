#!/usr/bin/env python3
"""Group a target set of desktop sessions into manager-led categories.

Structure the sidebar already has: a TOP-LEVEL session with chips nested under it
(`spawnedFrom.sessionId` in each chip's local_*.json). One category = one manager +
its sub-sessions. This script computes that, deterministically, from the store.

Usage:
  group_sessions.py --grep "Spec "                       # target set by title substring
  group_sessions.py --cli <cli1> <cli2> ...              # target set by cliSessionId
  group_sessions.py --root "Built-in apps concept"       # a root session + its whole subtree
  options: --categories cats.json   {"Apps": ["title substr", ...], ...}  explicit overrides
           --include-archived       default skips archived rows
Output (stdout, JSON): {"groups":[{category, manager, members[], source}], "unplaced":[...]}
  manager  = the topmost ancestor present in the set (or the root named by --root)
  source   = "lineage" | "categories-file" | "singletons"
Sessions with no lineage and no --categories hit land in `unplaced`: the caller (a mining
agent or the human) must assign a category — never guess one from a single title.
"""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from list_sessions import load_all

def subtree(rows, root_id):
    kids = {}
    for r in rows:
        kids.setdefault(r["parentSessionId"], []).append(r)
    out, stack = [], [root_id]
    while stack:
        for c in kids.get(stack.pop(), []):
            out.append(c)
            stack.append(c["sessionId"])
    return out

def slim(r):
    return {k: r[k] for k in ("title", "cli", "sessionId", "parentSessionId", "branch",
                              "worktree", "worktreeName", "pr", "prState", "archived",
                              "lastActivityAt")}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grep")
    ap.add_argument("--cli", nargs="*")
    ap.add_argument("--root")
    ap.add_argument("--categories")
    ap.add_argument("--include-archived", action="store_true")
    a = ap.parse_args()
    rows = load_all()
    if not a.include_archived:
        rows = [r for r in rows if not r["archived"]]
    by_id = {r["sessionId"]: r for r in rows}

    if a.root:
        roots = [r for r in rows if a.root.lower() in r["title"].lower()]
        if len(roots) != 1:
            sys.exit(f"--root matched {len(roots)} sessions; narrow it: " + "; ".join(r["title"] for r in roots))
        target = [roots[0]] + subtree(rows, roots[0]["sessionId"])
    elif a.cli:
        target = [r for r in rows if r["cli"] in set(a.cli)]
    elif a.grep:
        target = [r for r in rows if a.grep.lower() in r["title"].lower()]
    else:
        sys.exit("give --root, --cli or --grep")
    in_set = {r["sessionId"]: r for r in target}

    def top(r):
        seen = set()
        while r["parentSessionId"] in in_set and r["sessionId"] not in seen:
            seen.add(r["sessionId"])
            r = in_set[r["parentSessionId"]]
        return r

    groups, placed = {}, set()
    if a.categories:
        for cat, needles in json.load(open(a.categories)).items():
            ms = [r for r in target if any(n.lower() in r["title"].lower() for n in needles)]
            if ms:
                groups[cat] = {"category": cat, "manager": None, "members": ms, "source": "categories-file"}
                placed.update(r["sessionId"] for r in ms)
    for r in target:
        if r["sessionId"] in placed:
            continue
        t = top(r)
        if t["sessionId"] == r["sessionId"] and not any(c["parentSessionId"] == r["sessionId"] for c in target):
            continue  # a childless root: handled below
        g = groups.setdefault(t["sessionId"], {"category": t["title"], "manager": t, "members": [], "source": "lineage"})
        if r["sessionId"] != t["sessionId"]:
            g["members"].append(r)
        placed.add(r["sessionId"])
    unplaced = [r for r in target if r["sessionId"] not in placed]
    out = {"groups": [], "unplaced": [slim(r) for r in unplaced]}
    for g in groups.values():
        out["groups"].append({"category": g["category"], "source": g["source"],
                              "manager": slim(g["manager"]) if g["manager"] else None,
                              "members": [slim(m) for m in sorted(g["members"], key=lambda x: x["lastActivityAt"])]})
    out["groups"].sort(key=lambda g: g["category"].lower())
    print(json.dumps(out, indent=2))

if __name__ == "__main__":
    main()
