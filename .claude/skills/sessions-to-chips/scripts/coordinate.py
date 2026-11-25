#!/usr/bin/env python3
"""coordinate.py - managers see each other's ownership and settle overlaps between them.

Owner of: the cross-manager peer view (`peers_block`, printed at every role load by role_brief.py), the
coordination ledger `<programs>/coordination.jsonl` (its row schema and its only writer), derived thread state,
the `owns` writers (own / release / settle-as-cede / takeover), and the takeover writer that applies the
contract's abandonment rule. It reuses every other owner: manifests and binding retirement through
work_state_store, path overlap through state_sources, liveness through program_family and role_brief.holder_live.
Rules: ../specs/2026-11-25-managers-coordinate.md
"""
import argparse
import datetime as dt
import fcntl
import json
import os
import re
import secrets
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import program_family as pf  # noqa: E402
import work_state_store as st  # noqa: E402

LEDGER = "coordination.jsonl"
VERBS = ("ask", "reply", "settle", "contest", "ruling", "takeover")
OWNER_VERBS = ("settle", "ruling", "takeover")
ITEM_KINDS = ("ticket", "branch", "worktree", "pr", "path", "seam", "question")
ROW_KEYS = {"ts": (str, True), "thread": (str, True), "verb": (str, True), "from": (str, True), "to": (str, True),
            "item": (str, True), "text": (str, True), "owner": (str, False), "session": (str, True)}
THREAD_RX = re.compile(r"^c-\d{8}-[0-9a-f]{6}$")
LOCAL_RX = re.compile(r"local_[0-9a-f-]{6,}")
STALE_S = 24 * 3600
RECENT_S = 24 * 3600
CAP_PEERS, CAP_OVERLAPS, CAP_THREADS = 12, 10, 8
DEAD_CARRIERS = ("wake", "card", "founder", "bake")
PID_CARRIERS = ("lane", "bg", "agent", "workflow")
ACTIVE = ("open", "answered", "contested", "escalate", "expired")


def _programs(programs=None):
    return programs or os.environ.get("WORK_STATE_PROGRAMS") or st.PROGRAMS


def ledger_path(programs=None):
    return os.path.join(_programs(programs), LEDGER)


# ---------- the ledger ----------

def validate_row(r):
    st._check_keys(r, ROW_KEYS, "coordination row")
    if r["verb"] not in VERBS:
        raise st.SchemaError(f"verb: one of {VERBS}")
    if not THREAD_RX.match(r["thread"]):
        raise st.SchemaError("thread: c-<YYYYMMDD>-<6 hex>")
    kind = r["item"].split(":", 1)[0]
    if kind not in ITEM_KINDS or ":" not in r["item"] or not r["item"].split(":", 1)[1].strip():
        raise st.SchemaError(f"item: <kind>:<value>, kind one of {ITEM_KINDS}")
    if r["verb"] in OWNER_VERBS and not r.get("owner"):
        raise st.SchemaError(f"{r['verb']} needs owner")
    if r["verb"] not in OWNER_VERBS and "owner" in r:
        raise st.SchemaError(f"{r['verb']} takes no owner")
    if not r["from"] or not r["to"] or r["from"] == r["to"]:
        raise st.SchemaError("from and to: two different programs")


def append_row(row, programs=None):
    """Validate and append one row under `coordination.jsonl.lock`. -> the row."""
    validate_row(row)
    path = ledger_path(programs)
    with open(path + ".lock", "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            with open(path, "a") as fh:
                fh.write(json.dumps(row, sort_keys=True) + "\n")
        finally:
            fcntl.flock(lk, fcntl.LOCK_UN)
    return row


def read_rows(programs=None):
    """-> (valid rows in file order, count of skipped lines). A bad line is skipped, never fatal."""
    rows, bad = [], 0
    try:
        with open(ledger_path(programs)) as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    r = json.loads(line)
                    validate_row(r)
                    rows.append(r)
                except (ValueError, st.SchemaError):
                    bad += 1
    except OSError:
        pass
    return rows, bad


def new_thread(now):
    return f"c-{now:%Y%m%d}-{secrets.token_hex(3)}"


# ---------- liveness ----------

class World:
    """One fresh read of every store the view needs: manifests, the session index, the ledger."""

    def __init__(self, now, programs=None, rows=None, manifests=None, ledger=None):
        self.now = now
        self.programs = _programs(programs)
        self.manifests = st.read_all(self.programs) if manifests is None else manifests
        self.index = pf.session_index(write=False) if rows is None else rows
        self.ledger, self.bad = read_rows(self.programs) if ledger is None else (ledger, 0)

    def manager_present(self, slug):
        import role_brief as rb
        m = self.manifests.get(slug) or {}
        return rb.holder_live(m.get("manager_session") or "", (), self.now, self.index)

    def stale(self, slug):
        m = self.manifests.get(slug) or {}
        try:
            t = st.parse_iso(m.get("updated_at"))
        except ValueError:
            t = 0.0
        return self.now.timestamp() - t > STALE_S

    def carrier_live(self, c):
        """A session carrier with a present index row, or a pid carrier whose pid still has its start time. A pid
        carrier with no pid is unknown and counts as live: a wrong 'dead' hands away live work."""
        t = c.get("type")
        if t in DEAD_CARRIERS:
            return False
        if t == "session":
            import role_brief as rb
            cid = c.get("id") or ""
            row = next((r for r in self.index.values() if cid and ((r.get("sessionId") or "").startswith(cid)
                                                                  or r.get("cliSessionId") == cid)), None)
            return bool(row) and pf.session_present(row, self.now.timestamp(), rb.HOLDER_WINDOW_S)
        if t in PID_CARRIERS:
            if not c.get("pid"):
                return True
            now_start = st.pid_start(c["pid"])
            return bool(now_start) and (not c.get("pid_start") or now_start == " ".join(c["pid_start"].split()))
        return True

    def abandoned(self, slug, binding=None):
        """The contract's rule: manifest >24 h stale, no present manager, and (for a binding) no live carrier."""
        if not self.stale(slug) or self.manager_present(slug):
            return False
        return binding is None or not any(self.carrier_live(c) for c in binding.get("carriers") or [])

    def family(self, slug):
        owner = pf.terminal_owner(slug, self.manifests)
        return {s for s in self.manifests if owner and pf.terminal_owner(s, self.manifests) == owner}

    def peers(self, me):
        import state_index as si
        fam = self.family(me) | {me}
        return sorted(s for s, m in self.manifests.items()
                      if s not in fam and si.live_program(m)
                      and (self.manager_present(s) or (m.get("bindings") or [])))

    def local_id(self, slug):
        """The peer manager's `local_` id: from manager_session, else the index row for its cli uuid."""
        value = (self.manifests.get(slug) or {}).get("manager_session") or ""
        hit = LOCAL_RX.search(value)
        if hit:
            return hit.group(0)
        tok = re.match(r"\s*([0-9a-f]{8}-[0-9a-f-]{27,})", value)
        row = next((r for r in self.index.values() if tok and r.get("cliSessionId") == tok.group(1)), None)
        return (row or {}).get("sessionId")


# ---------- threads ----------

def threads(rows):
    out = {}
    for r in rows:
        out.setdefault(r["thread"], []).append(r)
    return out


def thread_state(trows, world):
    """Derived, never stored. -> (state, owner | None)."""
    ask = trows[0]
    a, b = ask["from"], ask["to"]
    if any(r["verb"] == "takeover" for r in trows):
        return "taken", [r for r in trows if r["verb"] == "takeover"][-1]["owner"]
    rulings = [r for r in trows if r["verb"] == "ruling"]
    if rulings:
        return "ruled", rulings[-1]["owner"]
    live_both = world.manager_present(a) and world.manager_present(b)
    settles = [i for i, r in enumerate(trows) if r["verb"] == "settle"]
    contests = {r["from"] for r in trows if r["verb"] == "contest"}
    owner = trows[settles[-1]]["owner"] if settles else None
    contested = (settles and any(r["verb"] == "contest" for r in trows[settles[-1] + 1:])) or contests >= {a, b}
    if contested:
        return ("escalate" if live_both else "contested"), owner
    if settles:
        return "settled", owner
    if world.abandoned(b):
        return "expired", None
    if ask["item"].startswith("question:") and any(r["verb"] == "reply" and r["from"] == b for r in trows):
        return "answered", None
    age = world.now.timestamp() - st.parse_iso(ask["ts"])
    return ("escalate" if live_both and age > STALE_S else "open"), None


# ---------- claims and overlap ----------

def _repo(b):
    return (b.get("publication") or {}).get("repo") or ""


def claims(slug, world):
    """-> {item: since} for the non-path kinds, from the program's open bindings."""
    out = {}
    for b in (world.manifests.get(slug) or {}).get("bindings") or []:
        since = b.get("bound_at") or ""
        out[f"ticket:{b['ticket']}"] = since
        if b.get("branch"):
            out[f"branch:{_repo(b)}:{b['branch']}"] = since
        if b.get("worktree"):
            out[f"worktree:{os.path.realpath(b['worktree'])}"] = since
        if (b.get("publication") or {}).get("pr"):
            out[f"pr:{_repo(b)}#{b['publication']['pr']}"] = since
    return out


def holdings(slug, world):
    """{repo: {"prs": {n: files}, "paths": [globs]}}: the rendered sidecar's PR files and bound paths, plus seams."""
    out = {}
    try:
        with open(os.path.join(world.programs, f"{slug}.state.json")) as fh:
            side = json.load(fh).get("holdings") or {}
    except (OSError, ValueError):
        side = {}
    for repo, h in side.items():
        out[repo] = {"prs": dict(h.get("prs") or {}), "paths": list(h.get("paths") or [])}
    m = world.manifests.get(slug) or {}
    for b in m.get("bindings") or []:
        if b.get("paths") and _repo(b):
            ent = out.setdefault(_repo(b), {"prs": {}, "paths": []})
            ent["paths"] += [p for p in b["paths"] if p not in ent["paths"]]
    for o in m.get("owns") or []:
        ent = out.setdefault(o["repo"], {"prs": {}, "paths": []})
        ent["paths"] += [p for p in o["paths"] if p not in ent["paths"]]
    return out


def overlaps(me, peer, world):
    """-> [{item, kind, theirs_first, since_me, since_peer, detail}] between my claims and one peer's."""
    import state_sources as ss
    mine, theirs = claims(me, world), claims(peer, world)
    out = []
    for item in sorted(set(mine) & set(theirs)):
        out.append({"item": item, "kind": item.split(":", 1)[0], "since_me": mine[item], "since_peer": theirs[item],
                    "theirs_first": (theirs[item] or "~") < (mine[item] or "~")})
    for row in ss.overlap(holdings(me, world), [{"program": peer, "holdings": holdings(peer, world)}]):
        out.append({"item": f"path:{row['repo']}:{row['paths'][0]}", "kind": "path", "theirs_first": None,
                    "detail": f"{row['path_count']} path(s); yours {', '.join(map(str, row['ours']))} vs theirs "
                              f"{', '.join(row['theirs'])}"})
    return out


def decided(item, a, b, world):
    """The newest settled/ruled/taken thread on `item` between programs a and b -> (state, owner, ts) | None."""
    best = None
    for trows in threads(world.ledger).values():
        if trows[0]["item"] != item or {trows[0]["from"], trows[0]["to"]} != {a, b}:
            continue
        state, owner = thread_state(trows, world)
        if state in ("settled", "ruled", "taken") and owner and (best is None or trows[-1]["ts"] > best[2]):
            best = (state, owner, trows[-1]["ts"])
    return best


# ---------- the block ----------

def _held(slug, world):
    m = world.manifests.get(slug) or {}
    bs = m.get("bindings") or []
    seams = ", ".join(f'"{o["seam"]}"' for o in m.get("owns") or [])
    prs = sum(1 for b in bs if (b.get("publication") or {}).get("pr"))
    wts = sum(1 for b in bs if b.get("worktree"))
    return (f"owns seam(s) {seams}; " if seams else "") + f"{len(bs)} ticket(s), {prs} PR(s), {wts} worktree(s)"


def _cut(lines, cap, me):
    return lines[:cap] + ([f"- +{len(lines) - cap} more: coordinate.py peers --program {me}"] if len(lines) > cap else [])


def view(me, world):
    """-> dict of the block's sections (lists of strings), JSON-safe."""
    cmd = f"python3 {HERE}/coordinate.py"
    peers = world.peers(me)
    live = [p for p in peers if world.manager_present(p)]
    gone = [p for p in peers if p not in live and world.abandoned(p)]
    peer_lines, over_lines, take_lines = [], [], []
    for p in peers:
        m = world.manifests[p]
        who = (f"manager {world.local_id(p) or m.get('manager_session') or '?'} present" if p in live
               else "ABANDONED (manifest >24 h stale, no present manager)" if p in gone else "no present manager")
        peer_lines.append(f"- {m.get('name') or p} [{p}] {who}; {_held(p, world)}")
        for o in overlaps(me, p, world):
            d = decided(o["item"], me, p, world)
            if d:
                if d[1] == me:
                    continue  # the loser's block carries the release line
                over_lines.append(f"- {o['item']}: {d[0]} to {p} on {d[2][:10]}, but you still hold it: release it")
                continue
            if p in gone and o["kind"] != "path":
                continue  # offered as a takeover below
            first = ("" if o["theirs_first"] is None else
                     f" (first claim: {'theirs' if o['theirs_first'] else 'yours'}, "
                     f"{(o['since_peer'] if o['theirs_first'] else o['since_me'])[:10]})")
            extra = f" [{o['detail']}] (advisory)" if o.get("detail") else ""
            over_lines.append(f"- {o['item']} is claimed by you and by {p}{first}{extra} → {cmd} ask --program {me} "
                              f"--to {p} --item '{o['item']}' --text \"<question>\"")
        if p in gone:
            for b in m.get("bindings") or []:
                if world.abandoned(p, b):
                    take_lines.append(f"- {p} claim ticket:{b['ticket']} is abandoned → {cmd} takeover --program "
                                      f"{me} --from {p} --item 'ticket:{b['ticket']}'")
            for o in m.get("owns") or []:
                take_lines.append(f"- {p} seam \"{o['seam']}\" is abandoned → {cmd} takeover --program {me} "
                                  f"--from {p} --item 'seam:{o['seam']}'")
    thread_lines, esc_lines = [], []
    for tid, trows in threads(world.ledger).items():
        a, b = trows[0]["from"], trows[0]["to"]
        if me not in (a, b):
            continue
        state, owner = thread_state(trows, world)
        other = b if a == me else a
        last = trows[-1]
        recent = world.now.timestamp() - st.parse_iso(last["ts"]) <= RECENT_S
        if state not in ACTIVE and not recent:
            continue
        line = (f"- {tid} {trows[0]['item']} with {other}: {state}"
                + (f" (owner {owner})" if owner else "") + f"; last: {last['verb']} by {last['from']}")
        if state == "escalate":
            esc_lines.append(line + f" → AskUserQuestion naming both goals, then {cmd} ruling --program {me} "
                                    f"--thread {tid} --owner <program> --text \"<founder's answer>\"")
        elif state == "expired":
            thread_lines.append(line + " → the takeover line below replaces it")
        elif state in ("open", "contested") and last["from"] != me:
            thread_lines.append(line + f" → answer now: {cmd} reply|settle|contest --program {me} --thread {tid} "
                                       "--text \"…\" [--owner <program> for settle]")
        elif state in ("open", "contested"):
            thread_lines.append(line + " → waiting on them; the doorbell is SendMessage to their local_ id")
        else:
            thread_lines.append(line)
    return {"peers": _cut(peer_lines, CAP_PEERS, me), "live": len(live), "abandoned": len(gone),
            "overlaps": _cut(over_lines, CAP_OVERLAPS, me), "threads": _cut(thread_lines, CAP_THREADS, me),
            "escalate": esc_lines, "takeover": _cut(take_lines, CAP_THREADS, me), "skipped_rows": world.bad}


def render(me, v):
    out = [f"Other managers ({v['live']} live, {v['abandoned']} abandoned):"] + (v["peers"] or ["- none"])
    out += [f"Overlaps ({len(v['overlaps'])}):"] + v["overlaps"]
    out += [f"Threads for you ({len(v['threads'])}):"] + v["threads"]
    out += [f"Escalate to founder ({len(v['escalate'])}):"] + v["escalate"]
    out += [f"Takeover available ({len(v['takeover'])}):"] + v["takeover"]
    if v["skipped_rows"]:
        out.append(f"Note: {v['skipped_rows']} unreadable coordination.jsonl line(s) skipped.")
    return "\n".join(out)


def peers_block(me, session, now, programs=None, rows=None):
    """The block role_brief embeds. Raises on a broken store; role_brief degrades the load."""
    return render(me, view(me, World(now, programs, rows)))


# ---------- writers ----------

def _row(world, verb, frm, to, item, text, session, thread=None, owner=None):
    r = {"ts": st.now_iso(world.now.timestamp()), "thread": thread or new_thread(world.now), "verb": verb,
         "from": frm, "to": to, "item": item, "text": text, "session": session or ""}
    if owner:
        r["owner"] = owner
    return append_row(r, world.programs)


def _edit(slug, programs, fn):
    with st._Locked(slug, programs) as lk:
        lk.write(fn(dict(lk.manifest)))


def own(world, me, seam, repo, paths, session=""):
    """Record a seam. Refuses one whose paths overlap a live peer's seam or bound paths. -> (ok, message)."""
    import state_sources as ss
    for p in world.peers(me):
        if world.abandoned(p):
            continue
        h = holdings(p, world).get(repo) or {}
        for g in paths:
            hit = next((x for x in h.get("paths") or [] if ss.paths_overlap(g, x)), None)
            if hit:
                return False, (f"refused: {g} overlaps {p}'s claim {hit}. First claim wins; ask instead: "
                               f"python3 {HERE}/coordinate.py ask --program {me} --to {p} --item 'seam:{seam}' "
                               f"--text \"<why you need it>\"")
    entry = {"seam": seam, "repo": repo, "paths": list(paths), "since": st.now_iso(world.now.timestamp())}
    _edit(me, world.programs, lambda m: dict(m, owns=[o for o in m.get("owns") or [] if o["seam"] != seam] + [entry]))
    return True, f"{me} owns seam {seam!r} ({repo}: {', '.join(paths)})"


def release(world, me, seam):
    _edit(me, world.programs, lambda m: dict(m, owns=[o for o in m.get("owns") or [] if o["seam"] != seam]))
    return True, f"{me} released seam {seam!r}"


def _thread(world, tid):
    trows = threads(world.ledger).get(tid)
    if not trows:
        raise st.SchemaError(f"no thread {tid}")
    return trows


def ask(world, me, to, item, text, session=""):
    if to not in world.manifests:
        raise st.SchemaError(f"no program {to}")
    r = _row(world, "ask", me, to, item, text, session)
    target = world.local_id(to)
    msg = (f"[coordination {r['thread']}] {me} asks {to} about {item}: {text} — answer with: python3 {HERE}/"
           f"coordinate.py reply|settle|contest --program {to} --thread {r['thread']} --text \"…\"")
    payload = {"to": target, "message": msg, "notify_when_idle": True}
    note = ("SendMessage this payload now (the ledger row is written, so a lost message still reaches them at "
            "their next role load):" if target else f"{to} has no reachable manager id; the row waits for its next load:")
    return True, f"{note}\n{json.dumps(payload)}"


def answer(world, me, verb, tid, text, owner=None, session=""):
    trows = _thread(world, tid)
    a, b = trows[0]["from"], trows[0]["to"]
    if me not in (a, b) and verb != "ruling":
        raise st.SchemaError(f"{me} is not a party to {tid}")
    if verb in ("settle", "ruling") and owner not in (a, b):
        raise st.SchemaError(f"owner must be {a} or {b}")
    other = b if me == a else a
    _row(world, verb, me, other, trows[0]["item"], text, session, thread=tid, owner=owner)
    if verb == "settle" and owner != me:
        _cede(world, me, owner, trows[0]["item"])
    return True, f"{verb} written on {tid}" + (f"; {me} ceded {trows[0]['item']} to {owner}" if
                                                verb == "settle" and owner != me else "")


def _cede(world, me, owner, item):
    seam = item[len("seam:"):] if item.startswith("seam:") else None

    def fn(m):
        ceded = [c for c in m.get("ceded") or [] if c.get("item") != item] + [{"item": item, "to": owner}]
        m = dict(m, ceded=ceded)
        if seam is not None and "owns" in m:
            m["owns"] = [o for o in m["owns"] if o["seam"] != seam]
        return m
    _edit(me, world.programs, fn)


def takeover(world, me, peer, item, text="", session=""):
    """Re-check the abandonment rule under the peer's lock, then move the claim. -> (ok, message)."""
    kind, value = item.split(":", 1)
    if kind == "ticket":
        def allow(b):
            fresh = World(world.now, world.programs, world.index, ledger=world.ledger)
            return (fresh.abandoned(peer, b), f"{peer} claim {item} is not abandoned (fresh manifest, present "
                                              "manager, or a live carrier)")
        st.retire(peer, value, reason=f"takeover by {me}", allow=allow, programs=world.programs)
        nxt = f"now bind it: python3 {HERE}/work_state.py bind --program {me} --ticket {value} --continue"
    elif kind == "seam":
        moved = {}

        def fn(m):
            fresh = World(world.now, world.programs, world.index, manifests=dict(world.manifests, **{peer: m}),
                          ledger=world.ledger)
            if not fresh.abandoned(peer):
                raise st.SchemaError(f"{peer} seam {value!r} is not abandoned")
            hit = [o for o in m.get("owns") or [] if o["seam"] == value]
            if not hit:
                raise st.SchemaError(f"{peer} owns no seam {value!r}")
            moved["seam"] = hit[0]
            return dict(m, owns=[o for o in m["owns"] if o["seam"] != value])
        _edit(peer, world.programs, fn)
        seam = dict(moved["seam"], since=st.now_iso(world.now.timestamp()))
        _edit(me, world.programs, lambda m: dict(m, owns=[o for o in m.get("owns") or [] if o["seam"] != value] + [seam]))
        nxt = f"{me} now owns seam {value!r}"
    else:
        raise st.SchemaError("takeover moves a ticket: or seam: claim")
    r = _row(world, "takeover", me, peer, item, text or f"{peer} claim abandoned", session, owner=me)
    for slug in (peer, me):
        st.append_event(slug, {"event": "takeover", "item": item, "from": peer, "to": me, "thread": r["thread"]},
                        world.programs)
    return True, f"took over {item} from {peer} ({r['thread']}); {nxt}"


# ---------- CLI ----------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def cmd(name, **extra):
        p = sub.add_parser(name)
        p.add_argument("--program", required=True)
        p.add_argument("--session", default=os.environ.get("CLAUDE_SESSION_ID", ""))
        for k, kw in extra.items():
            p.add_argument(f"--{k}", **kw)
        return p
    cmd("peers", json={"action": "store_true"})
    cmd("own", seam={"required": True}, repo={"required": True}, paths={"required": True, "nargs": "+"})
    cmd("release", seam={"required": True})
    cmd("ask", to={"required": True}, item={"required": True}, text={"required": True})
    for v in ("reply", "settle", "contest", "ruling"):
        cmd(v, thread={"required": True}, text={"required": True}, owner={"default": None})
    cmd("takeover", **{"from": {"required": True, "dest": "peer"}, "item": {"required": True},
                       "text": {"default": ""}})
    a = ap.parse_args(argv)
    world = World(dt.datetime.now(dt.timezone.utc))
    try:
        if a.cmd == "peers":
            v = view(a.program, world)
            print(json.dumps(v, indent=2) if a.json else render(a.program, v))
            return 0
        if a.cmd == "own":
            ok, msg = own(world, a.program, a.seam, a.repo, a.paths, a.session)
        elif a.cmd == "release":
            ok, msg = release(world, a.program, a.seam)
        elif a.cmd == "ask":
            ok, msg = ask(world, a.program, a.to, a.item, a.text, a.session)
        elif a.cmd == "takeover":
            ok, msg = takeover(world, a.program, a.peer, a.item, a.text, a.session)
        else:
            ok, msg = answer(world, a.program, a.cmd, a.thread, a.text, a.owner, a.session)
    except (st.SchemaError, OSError, ValueError) as exc:
        ok, msg = False, f"refused: {exc}"
    print(msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
