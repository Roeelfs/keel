#!/usr/bin/env python3
"""Wrap-up mode: build one checkpoint message per live manager chip.

Reads the desktop session store, finds live (non-archived) manager chips and their live
children, and fills WRAPUP_MESSAGE.md for each. Prints JSON; the caller sends each
`message` to its `sessionId` with the session-messaging tool. Nothing is sent here.

Three buckets, so a wrap-up never wakes a session twice or misses one:
  managers    newest live manager per category slug: these get the message.
  superseded  older live managers whose category already has a newer one: NOT messaged.
              Their children are listed so the surviving manager (or the human) can
              fold them in; archive only after confirming no child has live work.
  unmanaged   live sessions with recent activity that no manager parents (peer sessions,
              one-offs). The dispatcher messages these directly with their `message`.

Usage:
  wrapup_roster.py [--prefix "[Manager]"] [--date YYYY-MM-DD] [--only <title substr>]
                   [--recent-hours 72] [--include-superseded]
Output: {managers:[...], superseded:[...], unmanaged:[...], counts:{...}}
"""
import argparse, datetime, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from list_sessions import load_all


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:48] or "category"


def child_line(c):
    pr = f" PR#{c['pr']}/{c['prState']}" if c.get("pr") and c["pr"] != "-" else ""
    wt = f" worktree {c['worktreeName']}" if c.get("worktreeName") else ""
    return f"- {c['title']} [{c['sessionId']}]{pr}" + (f" branch {c['branch']}" if c.get("branch") else "") + wt


def parse_ts(s):
    try:
        return datetime.datetime.fromisoformat(s)
    except Exception:
        return datetime.datetime.min


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", default="[Manager]")
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    ap.add_argument("--only")
    ap.add_argument("--recent-hours", type=int, default=72)
    ap.add_argument("--include-superseded", action="store_true")
    a = ap.parse_args()

    manager_tpl = open(os.path.join(HERE, "..", "WRAPUP_MESSAGE.md")).read()
    unmanaged_tpl = open(os.path.join(HERE, "..", "WRAPUP_UNMANAGED_MESSAGE.md")).read()
    rows = [r for r in load_all() if not r["archived"]]
    by_id = {r["sessionId"]: r for r in rows}
    kids = {}
    for r in rows:
        kids.setdefault(r["parentSessionId"], []).append(r)

    def is_manager(r):
        return r["title"].startswith(a.prefix)

    mgrs = [r for r in rows if is_manager(r) and (not a.only or a.only.lower() in r["title"].lower())]
    # Group by category slug; the most recently active one survives.
    groups = {}
    for r in mgrs:
        groups.setdefault(slugify(r["title"][len(a.prefix):].strip()), []).append(r)

    managers, superseded = [], []
    for slug, members in groups.items():
        members.sort(key=lambda r: parse_ts(r["lastActivityAt"]))
        newest = members[-1]
        for r in members:
            live = sorted(kids.get(r["sessionId"], []), key=lambda c: c["lastActivityAt"])
            category = r["title"][len(a.prefix):].strip()
            children = "\n".join(child_line(c) for c in live) or "- (none live; close out your own story and write the note)"
            message = (manager_tpl.replace("{{DATE}}", a.date).replace("{{CATEGORY_SLUG}}", slug)
                       .replace("{{CHILDREN}}", children))
            entry = {"title": r["title"], "sessionId": r["sessionId"], "cli": r["cli"], "category": category,
                     "slug": slug, "liveChildren": len(live), "lastActivityAt": r["lastActivityAt"],
                     "children": [c["sessionId"] for c in live]}
            if r is newest:
                entry["message"] = message
                managers.append(entry)
            else:
                entry["supersededBy"] = newest["sessionId"]
                if a.include_superseded:
                    entry["message"] = message
                superseded.append(entry)

    # Unmanaged: recent, non-manager sessions whose ancestor chain contains no manager.
    cutoff = datetime.datetime.now() - datetime.timedelta(hours=a.recent_hours)

    def has_manager_ancestor(r):
        seen, cur = set(), r
        while cur and cur["parentSessionId"] and cur["parentSessionId"] not in seen:
            seen.add(cur["parentSessionId"])
            cur = by_id.get(cur["parentSessionId"])
            if cur and is_manager(cur):
                return True
        return False

    unmanaged = []
    if not a.only:
        for r in rows:
            if is_manager(r) or has_manager_ancestor(r) or parse_ts(r["lastActivityAt"]) < cutoff:
                continue
            unmanaged.append({
                "title": r["title"], "sessionId": r["sessionId"], "cli": r["cli"],
                "branch": r.get("branch") or "", "worktreeName": r.get("worktreeName") or "",
                "pr": r.get("pr"), "lastActivityAt": r["lastActivityAt"],
                "message": unmanaged_tpl.replace("{{DATE}}", a.date).replace("{{TITLE}}", r["title"]),
            })
        unmanaged.sort(key=lambda r: r["lastActivityAt"], reverse=True)

    print(json.dumps({"managers": managers, "superseded": superseded, "unmanaged": unmanaged,
                      "counts": {"managers": len(managers), "superseded": len(superseded),
                                 "unmanaged": len(unmanaged)}}, indent=2))


if __name__ == "__main__":
    main()
