"""Derived handoffs from tracker relations and existing ticket ownership; never persisted."""


def _session(sid, ctx):
    row = ctx["sessions"].get(sid) or ctx["sessions"].get(ctx["cli"].get(sid, "")) or {}
    return f"{row['title']} ({sid})" if row.get("title") else sid


def _owners(ticket, ctx, *, managers=True):
    bindings = list(ctx["bindings"])
    programs = [p for p in ctx.get("programs") or [] if not p.get("absorbed_by")
                and str(p.get("status") or "").lower() not in ("done", "closed")]
    bindings += [b for p in programs for b in p.get("bindings") or []]
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


def derive(ctx, closed):
    """Both relation directions matter: an outside-map waiter appears only in `blocks`.

    Keep a closed edge visible while the consumer stays open. Without a delivery receipt we
    cannot claim it was just closed or already announced, so offer a message, never send it.
    """
    kids = {c["ticket"]: c for c in (ctx.get("tracker") or {}).get("children") or []}
    edges = {}
    for cid, child in kids.items():
        for b in child.get("blocked_by") or []:
            edges[(cid, b["ticket"])] = (child.get("state"), b.get("state"))
        for w in child.get("blocks") or []:
            edges[(w["ticket"], cid)] = (w.get("state"), child.get("state"))
    rows = []
    for (waiter, blocker), (wstate, bstate) in sorted(edges.items()):
        # A ticket's own row is stronger than a relation's copied state.
        wtype = ((kids.get(waiter) or {}).get("state") or wstate or {}).get("type")
        btype = ((kids.get(blocker) or {}).get("state") or bstate or {}).get("type")
        if wtype in closed:
            continue
        if btype not in closed and all((kids.get(t) or {}).get("kind") == "ship" for t in (waiter, blocker)):
            continue  # Ship stacks do not block dispatch in the engine.
        owner = _owners(blocker, ctx, managers=False)
        if btype not in closed and not owner:
            continue
        tell = (_owners(waiter, ctx) or f"the owner of {waiter}") if btype in closed else owner
        waiting_owner = _owners(waiter, ctx) or f"the owner of {waiter}"
        message = (f"{blocker} is {btype}; check what remains before continuing {waiter}."
                   if btype in closed else f"{waiter} waits on {blocker}; please tell {waiting_owner} when it can continue.")
        rows.append({"waiter": waiter, "blocker": blocker, "closed": btype in closed,
                     "tell": tell, "message": message})
    return rows
