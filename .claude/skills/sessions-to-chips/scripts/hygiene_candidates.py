#!/usr/bin/env python3
"""Session hygiene: propose which of a manager's sessions to archive or converge.

A manager accumulates child sessions. Each finished child is one more row the human has to
read, and two children on the same topic split one context in two. This script reads the
desktop session store and PROPOSES; the manager verifies each proposal and acts with the
session tools (see ../HYGIENE.md). It sends, archives and changes nothing.

Scope is the manager's own family: every non-archived descendant (children, grandchildren).

  archive    PR merged or closed, idle >= --idle-hours, and no live descendant of its own
             (archiving a parent archives its finished children with it).
  review     no PR and idle >= --stale-hours: probably finished or parked. Read its last
             turn before deciding.
  converge   two or more live, non-archive sessions that share a topic key: the same
             tracker id (e.g. ABC-123, in title or branch), the same PR, or the same
             worktree. One survives; the others hand it their state and are archived.
  keep       everything else (open PR, recent activity).

Usage:
  hygiene_candidates.py --manager <sessionId | title substring> [--idle-hours 1]
                        [--stale-hours 24] [--now ISO]
  hygiene_candidates.py --all-managers [--prefix "[Manager]"]
Output: JSON {manager, archive:[...], review:[...], converge:[{key, survivor, fold:[...]}],
              keep:[...], counts:{...}}
"""
import argparse, datetime, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

TICKET_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9]{1,9})-(\d{1,6})\b")
DONE_PR_STATES = {"MERGED", "CLOSED"}
# Branch/title words that look like an id but are not a tracker key.
NOT_TICKETS = {"SHIP", "PR", "P", "S", "H", "K", "A", "B", "V", "UTF", "SHA", "ISO", "RFC", "ADR"}


def parse_ts(s):
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(str(s).replace("Z", "")[:19])
    except ValueError:
        return None


def ticket_keys(row):
    keys = set()
    for text in (row.get("title") or "", row.get("branch") or ""):
        for prefix, num in TICKET_RE.findall(text):
            p = prefix.upper()
            if p in NOT_TICKETS or p.isdigit() or len(p) < 2:
                continue
            keys.add(f"{p}-{num}")
    return keys


def descendants(rows, root_id, prefix):
    """The root's family, stopping at a nested manager: it owns its own family."""
    kids = {}
    for r in rows:
        kids.setdefault(r["parentSessionId"], []).append(r)
    out, stack = [], list(kids.get(root_id, []))
    while stack:
        r = stack.pop()
        if r["title"].startswith(prefix):
            continue
        out.append(r)
        stack.extend(kids.get(r["sessionId"], []))
    return out, kids


def idle_hours(row, now):
    ts = parse_ts(row.get("lastActivityAt"))
    return None if ts is None else (now - ts).total_seconds() / 3600


def brief(row, now):
    h = idle_hours(row, now)
    return {
        "sessionId": row["sessionId"],
        "title": row["title"],
        "pr": row.get("pr"),
        "prState": row.get("prState"),
        "branch": row.get("branch") or "",
        "worktree": row.get("worktree") or "",
        "idleHours": None if h is None else round(h, 1),
    }


def classify(rows, manager_id, now, idle_h=1.0, stale_h=24.0, prefix="[Manager]"):
    live = [r for r in rows if not r["archived"]]
    family, kids = descendants(live, manager_id, prefix)
    has_live_kids = {r["sessionId"] for r in family if kids.get(r["sessionId"])}
    manager_wt = next((r.get("worktree") for r in live if r["sessionId"] == manager_id), "")

    archive, review, rest = [], [], []
    for r in family:
        h = idle_hours(r, now)
        idle_enough = h is not None and h >= idle_h
        if (r.get("prState") or "").upper() in DONE_PR_STATES and idle_enough \
                and r["sessionId"] not in has_live_kids:
            archive.append(r)
        elif not r.get("pr") and h is not None and h >= stale_h \
                and r["sessionId"] not in has_live_kids:
            review.append(r)
        else:
            rest.append(r)

    # Union-find over shared topic keys among the sessions that stay.
    parent = {r["sessionId"]: r["sessionId"] for r in rest}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    by_key = {}
    for r in rest:
        keys = {f"ticket:{k}" for k in ticket_keys(r)}
        if r.get("pr"):
            keys.add(f"pr:{r['pr']}")
        wt = r.get("worktree") or ""
        if wt and wt != manager_wt:
            keys.add(f"worktree:{wt}")
        for k in keys:
            by_key.setdefault(k, []).append(r["sessionId"])
    for ids in by_key.values():
        for other in ids[1:]:
            parent[find(other)] = find(ids[0])

    groups = {}
    for r in rest:
        groups.setdefault(find(r["sessionId"]), []).append(r)
    converge, keep = [], []
    for members in groups.values():
        if len(members) < 2:
            keep.extend(members)
            continue
        member_ids = {m["sessionId"] for m in members}
        shared = sorted(k for k, ids in by_key.items() if len(member_ids.intersection(ids)) >= 2)
        # Survivor: an open PR beats none, then the most recent activity.
        survivor = max(members, key=lambda m: (
            (m.get("prState") or "").upper() == "OPEN", m.get("lastActivityAt") or ""))
        converge.append({
            "keys": shared,
            "survivor": brief(survivor, now),
            "fold": [brief(m, now) for m in members if m is not survivor],
        })

    return {
        "manager": manager_id,
        "archive": [brief(r, now) for r in archive],
        "review": [brief(r, now) for r in review],
        "converge": converge,
        "keep": [brief(r, now) for r in keep],
        "counts": {
            "family": len(family), "archive": len(archive), "review": len(review),
            "converge_groups": len(converge),
            "after_if_all_applied": len(family) - len(archive) - sum(len(g["fold"]) for g in converge),
        },
    }


def resolve_manager(rows, ref):
    live = [r for r in rows if not r["archived"]]
    # A session knows its own CLI id ($CLAUDE_SESSION_ID), not its desktop local_ id.
    exact = [r for r in live if ref in (r["sessionId"], r["cli"])]
    if exact:
        return exact[0]
    hits = sorted((r for r in live if ref.lower() in r["title"].lower()),
                  key=lambda r: r["lastActivityAt"], reverse=True)
    return hits[0] if hits else None


def main():
    from list_sessions import load_all
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--manager", help="local_ id, CLI id or title; default: this session ($CLAUDE_SESSION_ID)")
    g.add_argument("--all-managers", action="store_true")
    ap.add_argument("--prefix", default="[Manager]")
    ap.add_argument("--idle-hours", type=float, default=1.0)
    ap.add_argument("--stale-hours", type=float, default=24.0)
    ap.add_argument("--now")
    ap.add_argument("--account", help="account-uuid prefix; default: the most recently active account")
    a = ap.parse_args()
    now = parse_ts(a.now) if a.now else \
        datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    rows = load_all()
    # Sessions of another signed-in account are not reachable from this app session.
    account = a.account or max(rows, key=lambda r: r["lastActivityAt"])["account"] if rows else ""
    rows = [r for r in rows if r["account"].startswith(account)]
    if not a.all_managers:
        ref = a.manager or os.environ.get("CLAUDE_SESSION_ID", "")
        m = resolve_manager(rows, ref) if ref else None
        if not m:
            print(json.dumps({"error": f"no live session matches {ref!r}"}))
            return 2
        out = classify(rows, m["sessionId"], now, a.idle_hours, a.stale_hours, a.prefix)
        out["managerTitle"] = m["title"]
        print(json.dumps(out, indent=2))
        return 0
    managers = [r for r in rows if not r["archived"] and r["title"].startswith(a.prefix)]
    report = []
    for m in sorted(managers, key=lambda r: r["title"]):
        out = classify(rows, m["sessionId"], now, a.idle_hours, a.stale_hours, a.prefix)
        out["managerTitle"] = m["title"]
        report.append(out)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
