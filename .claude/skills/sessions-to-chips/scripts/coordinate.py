#!/usr/bin/env python3
"""coordinate.py - managers see each other's ownership and settle overlaps between them.

Owner of: the cross-manager peer view (`peers_block`, printed at every role load by role_brief.py), the
coordination ledger `<programs>/coordination.jsonl` (its row schema and its only writer), derived thread state,
the `owns` writers (own / release / settle-as-cede) and the takeover writer that applies the contract's
abandonment rule. It reuses every other owner: manifests and binding moves through work_state_store, carrier
liveness through work_state.carrier_state, sidecars through state_index.other_sidecars, path overlap through
state_sources, fold families through program_family.
Lock order, for every writer here: folds.lock, then coordination.jsonl.lock, then manifest locks in sorted slug order.
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
SIDECAR_STALE_S = 3 * 3600
CAP_PEERS, CAP_OVERLAPS, CAP_TAKEOVER = 12, 10, 8
ACTIVE = ("open", "answered", "proposed", "contested", "escalate", "expired", "taken-unbound")
CLOSED = ("ruled", "taken", "taken-unbound")


def _programs(programs=None):
    return programs or os.environ.get("WORK_STATE_PROGRAMS") or st.PROGRAMS


def ledger_path(programs=None):
    return os.path.join(_programs(programs), LEDGER)


# ---------- the ledger ----------

class _CoordLock:
    """Exclusive flock on coordination.jsonl.lock; re-entrant within a process (a writer holds it across its
    read-check-write, and append_row takes it again)."""
    _held = {}

    def __init__(self, programs=None):
        self.path = ledger_path(programs) + ".lock"

    def __enter__(self):
        fh, n = self._held.get(self.path, (None, 0))
        if n:
            self._held[self.path] = (fh, n + 1)
            return self
        fh = open(self.path, "a")
        fcntl.flock(fh, fcntl.LOCK_EX)
        self._held[self.path] = (fh, 1)
        return self

    def __exit__(self, *exc):
        fh, n = self._held[self.path]
        if n > 1:
            self._held[self.path] = (fh, n - 1)
            return
        del self._held[self.path]
        fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()


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
    """Validate and append one row under the coordination lock. -> the row."""
    validate_row(row)
    with _CoordLock(programs):
        with open(ledger_path(programs), "a") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
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


# ---------- liveness: the engine's carrier_state, failing closed ----------

def _pid_table(pids):
    """{pid: lstart} from the engine's one `ps`; a pid `ps` did not return is re-probed with kill(0), and one that
    cannot be proven gone keeps a sentinel start, so an unprovable carrier reads live (a wrong 'dead' hands away
    live work)."""
    import work_state_sources as wss
    table = wss.ps_pids(pids)
    for p in {int(x) for x in pids if x} - set(table):
        try:
            os.kill(p, 0)
            table[p] = None
        except ProcessLookupError:
            continue
        except OSError:
            table[p] = None
    return table


class World:
    """One fresh read of every store the view needs: manifests, the session index, the ledger, the sidecars."""

    def __init__(self, now, programs=None, rows=None, manifests=None, ledger=None):
        self.now = now
        self.programs = _programs(programs)
        self.manifests = st.read_all(self.programs) if manifests is None else manifests
        self.index = pf.session_index(write=False) if rows is None else rows
        self.ledger, self.bad = read_rows(self.programs) if ledger is None else (ledger, 0)
        self._ctx = None
        self._sidecars = None

    def refresh(self):
        """A fresh read of manifests and the ledger (writers call it under their locks)."""
        return World(self.now, self.programs, self.index)

    # -- carriers --
    def ctx(self):
        if self._ctx is None:
            pids = [c.get("pid") for m in self.manifests.values() for b in m.get("bindings") or []
                    for c in b.get("carriers") or [] if c.get("pid")]
            self._ctx = {"now": self.now.timestamp(), "lanes": {}, "pids": _pid_table(pids), "sessions": self.index,
                         "cli": {r.get("cliSessionId"): sid for sid, r in self.index.items() if r.get("cliSessionId")},
                         "live_bg": None, "outfiles": {}, "state": {}, "git": None}
        return self._ctx

    def carrier_live(self, c):
        """True unless the engine proves the carrier dead. Unknown (None) is live; a wake carrier, whose facts this
        reader does not load, is live; a pid `ps` could not settle is live (see _pid_table)."""
        import work_state as ws
        if c.get("type") == "wake":
            return True
        ctx = self.ctx()
        if c.get("type") == "lane" and c.get("pid") and ctx["pids"].get(int(c["pid"]), "") is None:
            return True
        live = ws.carrier_state(c, ctx)[0]
        return live is not False

    # -- programs --
    def owner(self, slug):
        return pf.terminal_owner(slug, self.manifests)

    def members(self, slug):
        """The programs whose terminal owner is `slug` (itself included): an absorbed member's claims are its owner's."""
        return sorted(s for s in self.manifests if self.owner(s) == slug)

    def manager_present(self, slug):
        import role_brief as rb
        m = self.manifests.get(slug) or {}
        return rb.holder_live(m.get("manager_session") or "", (), self.now, self.index)

    def stale(self, slug):
        """A parseable updated_at more than 24 h old. Missing or unparseable is NOT stale (fail closed)."""
        try:
            t = st.parse_iso((self.manifests.get(slug) or {}).get("updated_at"))
        except (ValueError, TypeError):
            return False
        return self.now.timestamp() - t > STALE_S

    def abandoned(self, slug):
        """The contract's rule, on the terminal owner: its manifest >24 h stale, no present manager, and no live
        carrier on ANY binding of any member program."""
        o = self.owner(slug)
        if not o or o != slug or not self.stale(o) or self.manager_present(o):
            return False
        return not any(self.carrier_live(c) for s in self.members(o)
                       for b in (self.manifests.get(s) or {}).get("bindings") or [] for c in b.get("carriers") or [])

    def peers(self, me):
        import state_index as si
        mine = self.owner(me) or me
        return sorted(s for s, m in self.manifests.items()
                      if s != mine and self.owner(s) == s and si.live_program(m)
                      and (self.manager_present(s) or any((self.manifests[x].get("bindings") or [])
                                                          for x in self.members(s))))

    # -- contact identity (who a message goes to), separate from the display name --
    def contact(self, slug):
        """-> (full sessionId | None, why). A message goes only to one resolved, present manager session."""
        value = (self.manifests.get(slug) or {}).get("manager_session") or ""
        if not value.strip():
            return None, "no manager_session"
        if not self.manager_present(slug):
            return None, "manager not present"
        hit = LOCAL_RX.search(value)
        tok = re.match(r"\s*([0-9a-f]{8}-[0-9a-f-]{27,})", value)
        if hit:
            rows = [sid for sid in self.index if sid.startswith(hit.group(0))]
        elif tok:
            rows = [sid for sid, r in self.index.items() if r.get("cliSessionId") == tok.group(1)]
        else:
            return None, "manager_session is not a local_ or cli id (Codex or other runtime)"
        if len(rows) != 1:
            return None, f"{'ambiguous' if rows else 'unresolved'} manager id"
        return rows[0], ""

    # -- sidecars: state_index's reader, with coverage --
    def sidecars(self):
        import state_index as si
        if self._sidecars is None:
            self._sidecars = {d.get("program"): d for d in si.other_sidecars("", self.now, self.programs)}
        return self._sidecars

    def coverage(self, slug):
        """-> '' when slug's sidecar is fresh and whole, else why path overlap for it is incomplete."""
        d = self.sidecars().get(slug)
        if d is None:
            return "no sidecar"
        why = []
        try:
            age = self.now.timestamp() - st.parse_iso(d.get("generated_at"))
            if age > SIDECAR_STALE_S:
                why.append(f"sidecar {int(age // 3600)} h old")
        except (ValueError, TypeError):
            why.append("sidecar of unknown age")
        if any((h or {}).get("collapsed") for h in (d.get("holdings") or {}).values()):
            why.append("files collapsed to dirs")
        if d.get("holdings_dropped"):
            why.append("PR files dropped")
        return ", ".join(why)


# ---------- threads ----------

def threads(rows):
    out = {}
    for r in rows:
        out.setdefault(r["thread"], []).append(r)
    return out


def _holds(owner, item, world):
    return item in claims(owner, world) or (item.startswith("seam:") and any(
        o["seam"] == item[5:] for s in world.members(owner) for o in (world.manifests.get(s) or {}).get("owns") or []))


def thread_state(trows, world):
    """Derived, never stored. -> (state, owner | None).
    Precedence: taken > ruled > expired > escalate > contested > settled > proposed > answered > open."""
    ask = trows[0]
    a, b = ask["from"], ask["to"]
    took = [r for r in trows if r["verb"] == "takeover"]
    if took:
        owner = took[-1]["owner"]
        return ("taken" if _holds(owner, ask["item"], world) else "taken-unbound"), owner
    rulings = [r for r in trows if r["verb"] == "ruling"]
    if rulings:
        return "ruled", rulings[-1]["owner"]
    if world.abandoned(b) or world.abandoned(a):
        return "expired", None
    live_both = world.manager_present(a) and world.manager_present(b)
    decisive = [r for r in trows if r["verb"] in ("settle", "contest")]
    age = world.now.timestamp() - st.parse_iso(trows[-1]["ts"])
    if decisive and decisive[-1]["verb"] == "contest":
        return ("escalate" if live_both else "contested"), None
    settles = [r for r in decisive if r["verb"] == "settle"]
    if settles:
        owner = settles[-1]["owner"]
        agreed = {r["from"] for r in settles if r["owner"] == owner}
        if owner != settles[-1]["from"] or agreed >= {a, b}:
            return "settled", owner
        return ("escalate" if live_both and age > STALE_S else "proposed"), owner
    if ask["item"].startswith("question:") and any(r["verb"] == "reply" and r["from"] == b for r in trows):
        return "answered", None
    return ("escalate" if live_both and age > STALE_S else "open"), None


def active_thread(world, x, y, item):
    """The newest thread on `item` between x and y that is not finished -> thread id | None (one thread per item)."""
    best = None
    for tid, trows in threads(world.ledger).items():
        if trows[0]["item"] == item and {trows[0]["from"], trows[0]["to"]} == {x, y}:
            if thread_state(trows, world)[0] in ACTIVE and (best is None or trows[-1]["ts"] > best[1]):
                best = (tid, trows[-1]["ts"])
    return best and best[0]


# ---------- claims and overlap ----------

def _repo(b):
    return (b.get("publication") or {}).get("repo") or ""


def binding_items(b):
    """The non-path items one binding claims."""
    out = [f"ticket:{b['ticket']}"]
    if b.get("branch"):
        out.append(f"branch:{_repo(b)}:{b['branch']}")
    if b.get("worktree"):
        out.append(f"worktree:{os.path.realpath(b['worktree'])}")
    if (b.get("publication") or {}).get("pr"):
        out.append(f"pr:{_repo(b)}#{b['publication']['pr']}")
    return out


def claims(slug, world):
    """-> {item: since} for the non-path kinds, from the open bindings of slug and every member folded into it."""
    out = {}
    for s in world.members(slug) or [slug]:
        for b in (world.manifests.get(s) or {}).get("bindings") or []:
            for item in binding_items(b):
                out[item] = b.get("bound_at") or ""
    return out


def holdings(slug, world):
    """{repo: {"prs": {n: files}, "paths": [globs]}}: the sidecar's PR files and bound paths, plus seams."""
    out = {}
    side = (world.sidecars().get(slug) or {}).get("holdings") or {}
    for repo, h in side.items():
        out[repo] = {"prs": dict(h.get("prs") or {}), "paths": list(h.get("paths") or [])}
    for s in world.members(slug) or [slug]:
        m = world.manifests.get(s) or {}
        for b in m.get("bindings") or []:
            if b.get("paths") and _repo(b):
                ent = out.setdefault(_repo(b), {"prs": {}, "paths": []})
                ent["paths"] += [p for p in b["paths"] if p not in ent["paths"]]
        for o in m.get("owns") or []:
            ent = out.setdefault(o["repo"], {"prs": {}, "paths": []})
            ent["paths"] += [p for p in o["paths"] if p not in ent["paths"]]
    return out


def _first(mine, theirs, me, peer):
    """Earlier `since` wins; a tie goes to the lower slug, so the two sides never both read 'yours'."""
    return (theirs or "~", peer) < (mine or "~", me)


def _branch(item):
    _, repo, name = item.split(":", 2)
    return repo, name


def overlaps(me, peer, world):
    """-> [{item, kind, theirs_first, since_me, since_peer, detail, uncertain}] between my claims and one peer's."""
    import state_sources as ss
    mine, theirs = claims(me, world), claims(peer, world)
    out = []
    for item in sorted(set(mine) & set(theirs)):
        unsure = item.startswith("branch::")
        out.append({"item": item, "kind": item.split(":", 1)[0], "since_me": mine[item], "since_peer": theirs[item],
                    "theirs_first": _first(mine[item], theirs[item], me, peer), "uncertain": unsure})
    mb = {i: _branch(i) for i in mine if i.startswith("branch:")}
    tb = {i: _branch(i) for i in theirs if i.startswith("branch:")}
    for i, (r1, n1) in sorted(mb.items()):
        for j, (r2, n2) in sorted(tb.items()):
            if i != j and n1 == n2 and (not r1 or not r2):
                out.append({"item": i if r1 else j, "kind": "branch", "since_me": mine[i], "since_peer": theirs[j],
                            "theirs_first": _first(mine[i], theirs[j], me, peer), "uncertain": True})
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
    bs = [b for s in world.members(slug) or [slug] for b in (world.manifests.get(s) or {}).get("bindings") or []]
    seams = ", ".join(f'"{o["seam"]}"' for s in world.members(slug) or [slug]
                      for o in (world.manifests.get(s) or {}).get("owns") or [])
    prs = sum(1 for b in bs if (b.get("publication") or {}).get("pr"))
    wts = sum(1 for b in bs if b.get("worktree"))
    return (f"owns seam(s) {seams}; " if seams else "") + f"{len(bs)} ticket(s), {prs} PR(s), {wts} worktree(s)"


def _cut(lines, cap, me):
    if cap is None or len(lines) <= cap:
        return lines
    return lines[:cap] + [f"- +{len(lines) - cap} more: coordinate.py peers --program {me} --all"]


def view(me, world, all_=False):
    """-> dict of the block's sections (lists of strings), JSON-safe. Escalations and threads are never cut;
    the rest is cut in this order of keeping: release, takeover, exact overlaps, path overlaps, peers."""
    cmd = f"python3 {HERE}/coordinate.py"
    me = world.owner(me) or me
    cap = (lambda n: None) if all_ else (lambda n: n)
    peers = world.peers(me)
    live = [p for p in peers if world.manager_present(p)]
    gone = [p for p in peers if p not in live and world.abandoned(p)]
    peer_lines, exact, paths, release, take, cover = [], [], [], [], [], []
    for p in peers:
        m = world.manifests[p]
        sid, why = world.contact(p)
        who = ("manager present" if p in live else
               "ABANDONED (manifest >24 h stale, no present manager, no live carrier)" if p in gone
               else "no present manager")
        contact = f"contact {sid}" if sid else f"ledger-only ({why})"
        peer_lines.append(f"- {m.get('name') or p} [{p}]: {who}; {contact}; {_held(p, world)}")
        gap = world.coverage(p)
        if gap:
            cover.append(f"{p} ({gap})")
        for o in overlaps(me, p, world):
            d = decided(o["item"], me, p, world)
            if d:
                if d[1] == me:
                    continue  # the loser's block carries the release line
                release.append(f"- {o['item']}: {d[0]} to {p} on {d[2][:10]}, but you still hold it → {cmd} release "
                               f"--program {me} --item '{o['item']}'")
                continue
            if p in gone and o["kind"] != "path":
                continue  # offered as a takeover below
            tid = active_thread(world, me, p, o["item"])
            first = ("" if o["theirs_first"] is None else
                     f" (first claim: {'theirs' if o['theirs_first'] else 'yours'}, "
                     f"{(o['since_peer'] if o['theirs_first'] else o['since_me'])[:10]})")
            note = " (repo unknown on one side: confirm it is the same repo)" if o.get("uncertain") else ""
            extra = f" [{o['detail']}] (advisory)" if o.get("detail") else ""
            act = (f"thread {tid} is open: {cmd} show --program {me} --thread {tid}" if tid else
                   f"{cmd} ask --program {me} --to {p} --item '{o['item']}' --text \"<question>\"")
            line = f"- {o['item']} is claimed by you and by {p}{first}{note}{extra} → {act}"
            (paths if o["kind"] == "path" else exact).append(line)
        if p in gone:
            for s in world.members(p):
                for b in (world.manifests.get(s) or {}).get("bindings") or []:
                    take.append(f"- {p} claim ticket:{b['ticket']} is abandoned → {cmd} takeover --program {me} "
                                f"--from {p} --item 'ticket:{b['ticket']}'")
                for o in (world.manifests.get(s) or {}).get("owns") or []:
                    take.append(f"- {p} seam \"{o['seam']}\" is abandoned → {cmd} takeover --program {me} "
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
            if me == a:
                esc_lines.append(line + f" → you asked, so you escalate: AskUserQuestion naming both goals, then "
                                        f"{cmd} ruling --program {me} --thread {tid} --owner <program> "
                                        "--text \"<founder's answer>\"")
            else:
                esc_lines.append(line + f" → {a} asked and escalates to the founder; nothing for you to send")
        elif state == "expired":
            thread_lines.append(line + " → the takeover line replaces it")
        elif state == "taken-unbound":
            thread_lines.append(line + f" → {owner} recorded a takeover it does not hold: {owner} re-runs takeover")
        elif state in ("open", "contested", "proposed") and last["from"] != me:
            thread_lines.append(line + f" → answer now: {cmd} reply|settle|contest --program {me} --thread {tid} "
                                       "--text \"…\" [--owner <program> for settle]")
        elif state in ("open", "contested", "proposed"):
            thread_lines.append(line + " → waiting on them")
        else:
            thread_lines.append(line)
    return {"peers": _cut(peer_lines, cap(CAP_PEERS), me), "live": len(live), "abandoned": len(gone),
            "escalate": esc_lines, "threads": thread_lines, "release": _cut(release, cap(CAP_OVERLAPS), me),
            "takeover": _cut(take, cap(CAP_TAKEOVER), me), "overlaps": _cut(exact, cap(CAP_OVERLAPS), me),
            "path_overlaps": _cut(paths, cap(CAP_OVERLAPS), me), "coverage": cover, "skipped_rows": world.bad}


def render(me, v):
    out = [f"Escalate to founder ({len(v['escalate'])}):"] + v["escalate"]
    out += [f"Threads for you ({len(v['threads'])}):"] + v["threads"]
    if v["release"]:
        out += [f"Release ({len(v['release'])}):"] + v["release"]
    out += [f"Takeover available ({len(v['takeover'])}):"] + v["takeover"]
    n = len(v["overlaps"]) + len(v["path_overlaps"])
    gap = f"; path coverage incomplete for {', '.join(v['coverage'])}" if v["coverage"] else ""
    out += [f"Overlaps ({n}{gap}):"] + v["overlaps"] + v["path_overlaps"]
    if not n and v["coverage"]:
        out.append("- none found in what could be read; this is not a no-overlap verdict")
    out += [f"Other managers ({v['live']} live, {v['abandoned']} abandoned):"] + (v["peers"] or ["- none"])
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
    """Record a seam. Refuses one whose paths overlap a non-abandoned peer's seam or bound paths. The check and the
    write run under the coordination lock, so two managers cannot both win. A retry keeps the original `since`."""
    import state_sources as ss
    with _CoordLock(world.programs):
        w = world.refresh()
        for p in w.peers(me):
            if w.abandoned(p):
                continue
            h = holdings(p, w).get(repo) or {}
            for g in paths:
                hit = next((x for x in h.get("paths") or [] if ss.paths_overlap(g, x)), None)
                if hit:
                    return False, (f"refused: {g} overlaps {p}'s claim {hit}. First claim wins; ask instead: "
                                   f"python3 {HERE}/coordinate.py ask --program {me} --to {p} --item 'seam:{seam}' "
                                   f"--text \"<why you need it>\"")

        def fn(m):
            prev = next((o for o in m.get("owns") or [] if o["seam"] == seam), None)
            since = prev["since"] if prev and prev["repo"] == repo and prev["paths"] == list(paths) else \
                st.now_iso(w.now.timestamp())
            entry = {"seam": seam, "repo": repo, "paths": list(paths), "since": since}
            return dict(m, owns=[o for o in m.get("owns") or [] if o["seam"] != seam] + [entry])
        _edit(me, w.programs, fn)
    return True, f"{me} owns seam {seam!r} ({repo}: {', '.join(paths)})"


def release(world, me, item):
    """Give up a claim. seam:<name> leaves `owns`; any other item retires the binding that holds it, with the
    reason `ceded to <owner>` when a decided thread names one. -> (ok, message)."""
    if item.startswith("seam:"):
        _edit(me, world.programs, lambda m: dict(m, owns=[o for o in m.get("owns") or [] if o["seam"] != item[5:]]))
        return True, f"{me} released {item}"
    for s in world.members(me) or [me]:
        for b in (world.manifests.get(s) or {}).get("bindings") or []:
            if item not in binding_items(b):
                continue
            to = [p for p in world.manifests if p != me and (d := decided(item, me, p, world)) and d[1] == p]
            reason = f"ceded to {to[0]}" if to else "released"
            st.retire(s, b["ticket"], reason=reason, verdict="ceded" if to else None, programs=world.programs)
            return True, f"{s} retired binding {b['ticket']} holding {item} ({reason})"
    return False, f"refused: {me} holds no {item}"


def _thread(world, tid):
    trows = threads(world.ledger).get(tid)
    if not trows:
        raise st.SchemaError(f"no thread {tid}")
    return trows


def ask(world, me, to, item, text, session=""):
    """Open (or re-surface) the one thread on `item` with `to`. -> (ok, message ending in the SendMessage payload,
    or a ledger-only note)."""
    if to not in world.manifests:
        raise st.SchemaError(f"no program {to}")
    owner = world.owner(to)
    if owner != to:
        raise st.SchemaError(f"{to} is folded into {owner or '(no owner)'}; ask {owner} instead")
    if world.owner(me) == to:
        raise st.SchemaError(f"{to} is your own fold family")
    with _CoordLock(world.programs):
        w = world.refresh()
        tid = active_thread(w, me, to, item)
        reused = bool(tid)
        if not tid:
            tid = _row(w, "ask", me, to, item, text, session)["thread"]
    target, why = w.contact(to)
    msg = (f"[coordination {tid}] {me} asks {to} about {item}: {text} — answer with: python3 {HERE}/"
           f"coordinate.py reply|settle|contest --program {to} --thread {tid} --text \"…\"")
    head = f"thread {tid} already open on {item}; no new row. " if reused else ""
    if not target:
        return True, f"{head}ledger-only: {to} {why}; the row reaches its manager at its next role load"
    payload = {"to": target, "message": msg, "notify_when_idle": True}
    return True, (f"{head}SendMessage this payload now, from a non-final message (the row is already written, so a "
                  f"lost message still reaches them at their next role load):\n{json.dumps(payload)}")


def answer(world, me, verb, tid, text, owner=None, session=""):
    with _CoordLock(world.programs):
        w = world.refresh()
        trows = _thread(w, tid)
        a, b = trows[0]["from"], trows[0]["to"]
        if me not in (a, b):
            raise st.SchemaError(f"{me} is not a party to {tid}")
        state, _ = thread_state(trows, w)
        if state in CLOSED:
            raise st.SchemaError(f"{tid} is {state}; it takes no more rows")
        if verb == "ruling" and me != a:
            raise st.SchemaError(f"only the asker ({a}) records the founder's ruling")
        if verb in ("settle", "ruling") and owner not in (a, b):
            raise st.SchemaError(f"owner must be {a} or {b}")
        other = b if me == a else a
        _row(w, verb, me, other, trows[0]["item"], text, session, thread=tid, owner=owner)
        ceded = verb == "settle" and owner != me
        if ceded:
            _cede(w, me, owner, trows[0]["item"])
    tail = ""
    if ceded and not trows[0]["item"].startswith(("seam:", "question:")):
        tail = (f"; now release what you hold: python3 {HERE}/coordinate.py release --program {me} "
                f"--item '{trows[0]['item']}'")
    return True, f"{verb} written on {tid}" + (f"; {me} ceded {trows[0]['item']} to {owner}" if ceded else "") + tail


def _cede(world, me, owner, item):
    seam = item[len("seam:"):] if item.startswith("seam:") else None

    def fn(m):
        ceded = [c for c in m.get("ceded") or [] if c.get("item") != item] + [{"item": item, "to": owner}]
        m = dict(m, ceded=ceded)
        if seam is not None and "owns" in m:
            m["owns"] = [o for o in m["owns"] if o["seam"] != seam]
        return m
    _edit(me, world.programs, fn)


def show(world, tid):
    trows = _thread(world, tid)
    state, owner = thread_state(trows, world)
    out = [f"{tid} {trows[0]['item']} {trows[0]['from']} → {trows[0]['to']}: {state}" + (f" (owner {owner})" if owner else "")]
    out += [f"- {r['ts']} {r['verb']} by {r['from']}" + (f" owner={r['owner']}" if r.get("owner") else "") +
            f": {r['text']}" for r in trows]
    return True, "\n".join(out)


def _children(slug, programs):
    import work_state as ws
    return ws._children(slug, programs)


def takeover(world, me, peer, item, text="", session="", children=None):
    """Take an abandoned claim. Under folds.lock then the coordination lock, re-read everything and re-apply the
    abandonment rule; a ticket moves by st.transfer (bind here first, retire there second, one locked operation,
    refused outside my map); the ledger row comes last. -> (ok, message)."""
    kind, value = item.split(":", 1)
    if kind not in ("ticket", "seam"):
        raise st.SchemaError("takeover moves a ticket: or seam: claim")
    owner = world.owner(peer)
    if owner != peer:
        raise st.SchemaError(f"{peer} is folded into {owner or '(no owner)'}; take over from {owner}")
    with st._GraphLock(world.programs), _CoordLock(world.programs):
        w = world.refresh()
        if not w.abandoned(peer):
            raise st.SchemaError(f"{peer} is not abandoned (fresh or unreadable manifest, present manager, or a live "
                                 "or unprovable carrier)")
        if kind == "ticket":
            src = next((s for s in w.members(peer) for b in (w.manifests.get(s) or {}).get("bindings") or []
                       if b["ticket"] == value), None)
            if not src:
                raise st.SchemaError(f"{peer} holds no binding for {value}")
            if children is None:
                _, _, children, _ = _children(me, w.programs)
            map_id = ((w.manifests.get(me) or {}).get("map") or {}).get("issue")

            def allow(b):
                fresh = w.refresh()
                return fresh.abandoned(peer), f"{peer} stopped being abandoned"
            st.transfer(src, me, value, children=children, map_id=map_id, allow=allow,
                        reason=f"takeover by {me}", programs=w.programs)
            nxt = f"{me} now holds {value} (branch, worktree, publication and paths kept; launch a carrier for it)"
        else:
            moved = {}

            def fn(m):
                hit = [o for o in m.get("owns") or [] if o["seam"] == value]
                if not hit:
                    raise st.SchemaError(f"{peer} owns no seam {value!r}")
                moved["seam"] = hit[0]
                return dict(m, owns=[o for o in m["owns"] if o["seam"] != value])
            src = next((s for s in w.members(peer) if any(o["seam"] == value for o in
                                                          (w.manifests.get(s) or {}).get("owns") or [])), peer)

            def give(m):
                seam = dict(moved["seam"], since=st.now_iso(w.now.timestamp()))
                return dict(m, owns=[o for o in m.get("owns") or [] if o["seam"] != value] + [seam])
            _edit(src, w.programs, fn)  # remove there first: a crash between leaves it unowned, never doubly owned
            _edit(me, w.programs, give)
            nxt = f"{me} now owns seam {value!r}"
        r = _row(w, "takeover", me, peer, item, text or f"{peer} claim abandoned", session, owner=me)
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
    cmd("peers", json={"action": "store_true"}, all={"action": "store_true", "dest": "all_"})
    cmd("own", seam={"required": True}, repo={"required": True}, paths={"required": True, "nargs": "+"})
    cmd("release", item={"required": True})
    cmd("ask", to={"required": True}, item={"required": True}, text={"required": True})
    cmd("show", thread={"required": True})
    for v in ("reply", "settle", "contest", "ruling"):
        cmd(v, thread={"required": True}, text={"required": True}, owner={"default": None})
    cmd("takeover", **{"from": {"required": True, "dest": "peer"}, "item": {"required": True},
                       "text": {"default": ""}})
    a = ap.parse_args(argv)
    world = World(dt.datetime.now(dt.timezone.utc))
    try:
        if a.cmd == "peers":
            v = view(a.program, world, a.all_)
            print(json.dumps(v, indent=2) if a.json else render(a.program, v))
            return 0
        if a.cmd == "own":
            ok, msg = own(world, a.program, a.seam, a.repo, a.paths, a.session)
        elif a.cmd == "release":
            ok, msg = release(world, a.program, a.item)
        elif a.cmd == "ask":
            ok, msg = ask(world, a.program, a.to, a.item, a.text, a.session)
        elif a.cmd == "show":
            ok, msg = show(world, a.thread)
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
