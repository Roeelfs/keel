"""Derived handoffs from tracker relations and existing ticket ownership; the told record is the store's."""


def _session(sid, ctx):
    row = ctx["sessions"].get(sid) or ctx["sessions"].get(ctx["cli"].get(sid, "")) or {}
    return f"{row['title']} ({sid})" if row.get("title") else sid


def _programs(ctx):
    return [p for p in ctx.get("programs") or [] if not p.get("absorbed_by")
            and str(p.get("status") or "").lower() not in ("done", "closed")]


def _owners(ticket, ctx, *, managers=True):
    programs = _programs(ctx)
    bindings = list(ctx["bindings"]) + [b for p in programs for b in p.get("bindings") or []]
    sessions = sorted({c["id"] for b in bindings if b["ticket"] == ticket
                       for c in b.get("carriers") or [] if c["type"] == "session"})
    if sessions:
        return ", ".join(_session(s, ctx) for s in sessions)
    if not managers:
        return ""
    managers = {p.get("manager_session") or p.get("orchestrator_session") for p in programs
                if ticket == (p.get("map") or {}).get("issue")
                or any(b["ticket"] == ticket for b in p.get("bindings") or [])}
    if ticket in {c["ticket"] for c in (ctx.get("tracker") or {}).get("children") or []}:
        managers.add(ctx.get("manager_session"))
    return ", ".join(_session(s, ctx) for s in sorted(s for s in managers if s))


def _landed(ticket, ctx):
    """A blocker's bound publication that already landed or ended, read from this tick's gh rows: the PR
    merges hours before its ticket is closed, and the waiter is owed the news at the merge."""
    bindings = list(ctx["bindings"]) + [b for p in _programs(ctx) for b in p.get("bindings") or []]
    for b in bindings:
        pub = b.get("publication") or {}
        if b["ticket"] != ticket or not pub:
            continue
        if pub.get("via") == "push":
            return f"{pub.get('repo')}@{str(pub.get('sha'))[:12]} pushed"
        row = (ctx.get("prs") or {}).get(f"{pub.get('repo')}#{pub.get('pr')}") or {}
        if row.get("mergedAt") or row.get("state") == "MERGED":
            return f"{pub.get('repo')}#{pub.get('pr')} merged"
        if row.get("state") == "CLOSED":
            return f"{pub.get('repo')}#{pub.get('pr')} closed unmerged"
    return None


def _kids(ctx):
    return {c["ticket"]: c for c in (ctx.get("tracker") or {}).get("children") or []}


def _edges(ctx):
    """(waiter, blocker) -> (waiter state type, blocker state type); a ticket's own row is stronger than a
    relation's copied state."""
    kids, raw = _kids(ctx), {}
    for cid, child in kids.items():
        for b in child.get("blocked_by") or []:
            raw[(cid, b["ticket"])] = (child.get("state"), b.get("state"))
        for w in child.get("blocks") or []:
            raw[(w["ticket"], cid)] = (w.get("state"), child.get("state"))
    return {(w, b): (((kids.get(w) or {}).get("state") or ws or {}).get("type"),
                     ((kids.get(b) or {}).get("state") or bs or {}).get("type"))
            for (w, b), (ws, bs) in raw.items()}


def derive(ctx, closed):
    """Both relation directions matter: an outside-map waiter appears only in `blocks`.

    Keep a closed edge visible while the consumer stays open. A row is `closed` when its blocker's ticket
    is closed or its bound PR merged or closed; `notify` stays False here: only the snapshot's claim
    against the store's told record (`claim_notices`) sets it, once per blocker closure.
    """
    kids = _kids(ctx)
    rows = []
    for (waiter, blocker), (wtype, btype) in sorted(_edges(ctx).items()):
        if wtype in closed:
            continue
        landed = None if btype in closed else _landed(blocker, ctx)
        done = btype in closed or landed is not None
        if not done and all((kids.get(t) or {}).get("kind") == "ship" for t in (waiter, blocker)):
            continue  # Ship stacks do not block dispatch in the engine.
        owner = _owners(blocker, ctx, managers=False)
        if not done and not owner:
            continue
        waiting_owner = _owners(waiter, ctx) or f"the owner of {waiter}"
        tell = waiting_owner if done else owner
        if btype in closed:
            ended, message = btype, f"{blocker} is {btype}; check what remains before continuing {waiter}."
        elif landed:
            ended, message = landed, f"{blocker}'s {landed}; check what remains before continuing {waiter}."
        else:
            ended, message = None, f"{waiter} waits on {blocker}; please tell {waiting_owner} when it can continue."
        rows.append({"waiter": waiter, "blocker": blocker, "closed": done, "ended": ended,
                     "tell": tell, "message": message, "notify": False})
    return rows


def notice_keys(rows):
    """The store's claim input: 'waiter|blocker' -> how the blocker ended, for every closed edge."""
    return {f"{r['waiter']}|{r['blocker']}": r["ended"] for r in rows if r["closed"]}


def still_told(ctx, closed):
    """-> keep(key, ended) for the store's told record. A told edge is forgotten only when the waiter closed,
    the relation is gone, or the blocker's ticket reopened after a ticket closure; a merged PR never
    un-merges, so a gh read that misses its row this tick never re-arms the notice."""
    edges = _edges(ctx)

    def keep(key, ended):
        waiter, blocker = key.split("|", 1)
        if (waiter, blocker) not in edges:
            return False
        wtype, btype = edges[(waiter, blocker)]
        return wtype not in closed and not (ended in closed and btype not in closed)
    return keep
