#!/usr/bin/env python3
"""work_state.py — every piece of manager work is a bound map ticket with a derived state.

One engine owns the binding record (ticket -> carriers), derives each map ticket's state, and
emits flags: UNBOUND, READY_NOT_DISPATCHED, STALLED, BAKE_OWED, STALE_OPEN, DUPLICATE_TITLE, PROOF_FAILED
(only the first two block). It never merges, pushes,
deploys or bakes, and it writes no tracker state. Ticket ids are opaque strings; the tracker is
reached only through the manifest's `map.snapshot_cmd` (contract `work-state-tracker/<major>`).

Commands (all take --program <slug>):
  snapshot [--refresh] [--json]   remote tiers by TTL (tracker 300 s, gh 120 s), local probes
  guard                           no network, no git; state facts on stdin; exit 4 = blocking
  bind | carrier | retire         the only writers of manifest `bindings` (work_state_store.py)
  migrate [--all] [--dry-run]     lanes/claims -> bindings + events (work_state_migrate.py)
  bake-body <ship>                the bake ticket body, key set read from merge-and-retire.md
  bake-exempt                     R15 docs-only predicate over a PR's or a push's changed paths
  lane-row                        append one full lane row (spawn-lane.sh, codex-dispatch.sh)
Exit codes: 0 nothing blocking · 4 `blocking` non-empty · 1 error or schema mismatch.
Contract: ../references/manager-contract.md §Program state and §No stop without an armed wake.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import program_family as pf  # noqa: E402
import work_state_store as st  # noqa: E402
import work_state_sources as src  # noqa: E402

SCHEMA = "work-state-snapshot/1"
TRACKER_MAJORS = {1}
CLOSED = frozenset({"completed", "canceled", "duplicate"})
STARTED = "started"
LEASE = {"lane": 5400, "session": 14400, "pr_pending": 1500, "launch": 600, "card": 86400}
TRACKER_STALE_S = 7200
TRUNCATED_BLOCKER = "relations_truncated"
WAKE_GRACE_S = 600
FLAGS = ("UNBOUND", "READY_NOT_DISPATCHED", "STALLED", "BAKE_OWED", "STALE_OPEN", "DUPLICATE_TITLE", "PROOF_FAILED")
DUP_IGNORED = frozenset({"canceled", "duplicate"})
LANE_UNBOUND_AGE_S = 7 * 86400
MERGE_AND_RETIRE = os.path.join(HERE, "..", "references", "merge-and-retire.md")
# R15: bake-exempt only when every path is docs and none sits under a behavior-bearing segment.
# Conservative and project-neutral; a manifest adds its own globs under `map.bake_exempt_deny`.
DENY_SEGMENTS = frozenset({"skills", "agents", ".github", "tooling", "infra", "scripts", "src", "apps",
                           "packages", "lib", "hooks", "prompts", "orgs", "customers", "ci", ".claude"})


class SchemaMismatch(Exception):
    pass


# ---------- pure helpers ----------

def literal_prefix(glob):
    return re.split(r"[*?\[]", glob, maxsplit=1)[0]


def paths_intersect(a, b):
    """Literal-prefix test: two path sets collide when one literal prefix starts the other."""
    for x in a or []:
        for y in b or []:
            px, py = literal_prefix(x), literal_prefix(y)
            if px.startswith(py) or py.startswith(px):
                return True
    return False


def docs_only(paths, deny_globs=()):
    """R15, exactly the docs-only rule: every changed path is under docs/ or is a .md file, and none
    sits under code, infra, tooling, CI, customer-org, skill or agent paths."""
    if not paths:
        return False
    import fnmatch
    for p in paths:
        p = p.strip().lstrip("./")
        segs = p.split("/")
        if not (segs[0] == "docs" or p.endswith(".md")):
            return False
        if any(s in DENY_SEGMENTS for s in segs[:-1]):
            return False
        if any(fnmatch.fnmatch(p, g) for g in deny_globs):
            return False
    return True


def bake_keys(path=MERGE_AND_RETIRE):
    """The bake obligation key set, parsed from its one owner: merge-and-retire.md §Post-merge proof."""
    with open(path) as fh:
        text = fh.read()
    sec = text.split("## Post-merge proof", 1)[1].split("\n## ", 1)[0]
    m = re.search(r"`\{([^}]+)\}`", sec)
    return [k.strip() for k in m.group(1).split(",")]


def _h(*parts):
    return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _branch_of(written):
    return str(written).split("\u0000")[-1]


def check_tracker_schema(data):
    s = str((data or {}).get("schema") or "")
    m = re.match(r"^work-state-tracker/(\d+)", s)
    if not m or int(m.group(1)) not in TRACKER_MAJORS:
        raise SchemaMismatch(f"schema_mismatch: tracker snapshot schema {s!r}, engine reads majors {sorted(TRACKER_MAJORS)}")


# ---------- liveness (§2.1) ----------

def pr_facts(row):
    if not row:
        return None, False, None
    roll = row.get("statusCheckRollup") or []
    pending = any((c.get("status") and c.get("status") != "COMPLETED") or c.get("state") == "PENDING" for c in roll)
    concl = sorted(str(c.get("conclusion") or c.get("state") or c.get("status")) for c in roll)
    return row.get("state"), pending, _h(row.get("headRefOid"), concl, row.get("reviewDecision"))


MERGE_STATE_WHY = {"DIRTY": "merge conflict", "BEHIND": "behind its base", "BLOCKED": "branch protection (reason not named)",
                   "UNSTABLE": "a non-required check fails", "DRAFT": "draft"}


def pr_view(pub, prs):
    """An open PR's merge readiness, derived again from THIS tick's gh read. A draft never reads as ready, and
    a block reason never comes from an earlier tick: a row older than the gh TTL, or a field gh did not
    return, reads `unknown`. -> dict | None (no PR publication)."""
    if "pr" not in (pub or {}):
        return None
    row = prs.get(f"{pub.get('repo')}#{pub.get('pr')}")
    if not row:
        return {"pr": pub.get("pr"), "state": None, "draft": None, "readiness": "unknown", "why": "no gh row this tick"}
    age = row.get("_age_s")
    out = {"pr": pub.get("pr"), "state": row.get("state"), "draft": row.get("isDraft"),
           "age_s": int(age) if age is not None else None}
    if row.get("state") != "OPEN":
        return dict(out, readiness=str(row.get("state") or "unknown").lower(), why=None)
    if age is None or age >= src.TTL["gh"]:
        return dict(out, readiness="unknown", why=f"gh read is {'of unknown age' if age is None else f'{int(age)} s old'}; "
                                                "not derived this tick")
    if row.get("isDraft") is None:
        return dict(out, readiness="unknown", why="gh returned no isDraft")
    if row.get("isDraft"):
        return dict(out, readiness="draft", why="draft: mark it ready before any merge")
    roll = row.get("statusCheckRollup")
    fails = sorted({str(c.get("name") or c.get("context") or "?") for c in roll or []
                    if str(c.get("conclusion") or c.get("state") or "").upper() in ("FAILURE", "ERROR", "TIMED_OUT",
                                                                                   "CANCELLED", "ACTION_REQUIRED")})
    _, pending, _ = pr_facts(row)
    why = []
    if fails:
        why.append("checks failing: " + ", ".join(fails[:5]))
    elif pending:
        why.append("checks pending")
    rd = row.get("reviewDecision")
    if rd in ("CHANGES_REQUESTED", "REVIEW_REQUIRED"):
        why.append(rd.lower().replace("_", " "))
    ms = row.get("mergeStateStatus")
    if ms in MERGE_STATE_WHY and not (ms in ("BLOCKED", "UNSTABLE") and why):
        why.append(MERGE_STATE_WHY[ms])
    if why:
        return dict(out, readiness="blocked", why="; ".join(why))
    if ms in ("CLEAN", "HAS_HOOKS"):
        return dict(out, readiness="ready", why=None)
    return dict(out, readiness="unknown", why=f"mergeStateStatus {ms or 'not returned'}")


def wake_fire(cid, wakes):
    times = [t for w in wakes for t in w.get("times") or [] if cid in (w.get("line") or "")]
    return max((st.parse_iso(t) for t in times), default=None)


def carrier_state(c, ctx):
    """-> (live True|False|None, fingerprint or None, awaiting category or None)."""
    now, t = ctx["now"], c["type"]
    git = ctx.get("git")
    if t == "lane":
        row = ctx["lanes"].get(c["id"]) or {}
        pid, start = c.get("pid") or row.get("pid"), c.get("pid_start") or row.get("pid_start")
        live = bool(pid) and pid in ctx["pids"] and (not start or " ".join(start.split()) == ctx["pids"][pid])
        out = c.get("outfile") or row.get("outfile")
        wt = row.get("worktree")
        g = (git or {}).get(wt) if wt else {}
        fp = None if git is None else _h(g.get("head"), g.get("paths"), bool(out and ctx["outfiles"].get(out)))
        return live, fp, None
    if t == "session":
        row = ctx["sessions"].get(c["id"]) or ctx["sessions"].get(ctx["cli"].get(c["id"], ""))
        if not row:
            return False, None, None
        cat = pf.fresh_category(row)
        if pf.awaiting_manager(row):
            return False, None, cat
        live = pf.session_live(row, now, LEASE["session"])
        wt = row.get("worktreePath") or row.get("cwd")
        head = ((git or {}).get(wt) or {}).get("head") if git is not None else None
        fp = None if git is None else _h(cat, _h(row.get("lastTurnReport")), row.get("prs"),
                                          row.get("writtenBranches"), head)
        return live, fp, None
    if t in ("agent", "workflow", "bg"):
        live = None if ctx["live_bg"] is None else c["id"] in ctx["live_bg"]
        out = c.get("outfile")
        return live, _h(bool(out and ctx["outfiles"].get(out))), None
    if t == "card":
        return now - st.parse_iso(c["bound_at"]) < LEASE["card"], None, None
    if t == "wake":
        fire = wake_fire(c["id"], ctx["state"].get("wakes") or [])
        return bool(fire and now < fire + WAKE_GRACE_S), None, None
    if t == "founder":
        return True, None, None
    return False, None, None


# ---------- derive (pure) ----------

def _child_map(tracker):
    return {c["ticket"]: c for c in (tracker or {}).get("children") or []}


def _blocking_blockers(child, kids):
    out = []
    for b in child.get("blocked_by") or []:
        # Relation {ticket, state|null}: a null state is unreadable and counts open unless the blocker is
        # in the map, whose own row then decides. Relations carry no kind: an outside-map blocker is never
        # a ship -> ship stack.
        rid = b["ticket"]
        stype = ((b.get("state") or {}).get("type")) or ((kids.get(rid) or {}).get("state") or {}).get("type")
        if stype in CLOSED:
            continue
        if (kids.get(rid) or {}).get("kind") == "ship" and child.get("kind") == "ship":
            continue  # R6: ship -> ship stacks; merge order stays at the merge gate
        out.append(rid)
    if "relations_truncated" in (child.get("errors") or []):
        out.append(TRUNCATED_BLOCKER)  # the blocker list is incomplete: never ready (fail closed)
    return out


def _bake_child(ship_id, kids):
    hits = [c for c in kids.values() if c.get("kind") == "bake"
            and any(b["ticket"] == ship_id for b in c.get("blocked_by") or [])]
    hits.sort(key=lambda c: ((c.get("state") or {}).get("type") in CLOSED, c.get("order", 0)))
    return hits[0] if hits else None


def _verdict(bake):
    """R17: the bake ticket's state is the verdict (Done = pass, canceled/duplicate = fail)."""
    if not bake:
        return None
    stype = (bake.get("state") or {}).get("type")
    return {"completed": "pass", "canceled": "fail", "duplicate": "fail"}.get(stype, "pending")


def validate_hold(h, ctx, kids, by_ticket, live_of):
    t, reason, args = h.get("ticket"), str(h.get("reason") or ""), h.get("args") or []
    if t not in kids:
        return "not_a_map_ticket"
    base, _, target = reason.partition(":")
    base = base.lower()
    if base == "file-collision":
        other = by_ticket.get(target)
        mine = [p for a in args[:1] for p in a.split(",") if p]
        if not other or not any(live_of(c) for c in other["carriers"]):
            return f"file-collision: {target} has no live binding"
        if not mine:
            return "file-collision: name the held ticket's paths (Hold: <t> file-collision:<other> <glob,glob>)"
        return None if paths_intersect(mine, other.get("paths")) else f"file-collision: paths do not intersect {target}"
    if base == "completion-mode":
        if str(ctx["state"].get("mode") or "").lower() != "completion":
            return "completion-mode: the last AT-WAKE carries no `Mode: completion`"
        return None if t not in by_ticket else "completion-mode: the held ticket is bound (inside the build group)"
    if base == "founder-gated":
        g = kids.get(target)
        if not g or (g.get("state") or {}).get("type") in CLOSED:
            return f"founder-gated: grill {target} is not an open map ticket"
        b = by_ticket.get(target)
        return None if b and any(c["type"] == "founder" for c in b["carriers"]) else \
            f"founder-gated: grill {target} has no founder carrier"
    return f"unknown hold reason {reason!r}"


def derive(ctx):
    """Pure. ctx -> (snapshot dict, new cache parts {fp, ready_since})."""
    now, slug, map_id = ctx["now"], ctx["slug"], ctx.get("map_id")
    tracker, bindings = ctx.get("tracker"), ctx["bindings"]
    kids = _child_map(tracker)
    order = [c["ticket"] for c in (tracker or {}).get("children") or []]
    by_ticket = {b["ticket"]: b for b in bindings}
    notes, awaiting, flags = list(ctx.get("notes") or []), [], {k: [] for k in FLAGS}
    cstate = {}
    for ticket, count in (ctx.get("proof_failures") or {}).items():
        if count >= 3 and ticket in (set(kids) | set(by_ticket)):
            flags["PROOF_FAILED"].append({"item": ticket, "why": f"{count} failed proofs since last pass",
                                           "fix": "inspect proof receipts and salvage before re-dispatch"})

    def live_of(c):
        k = (c["type"], c["id"])
        if k not in cstate:
            cstate[k] = carrier_state(c, ctx)
        return cstate[k][0] is not False  # None (unknown) counts live: never a false STALLED

    # Holds (R23)
    holds, valid_hold = [], {}
    for h in ctx["state"].get("holds") or []:
        why = validate_hold(h, ctx, kids, by_ticket, live_of)
        holds.append(dict(h, valid=why is None, why=why))
        if why is None:
            valid_hold[h["ticket"]] = h
        else:
            notes.append(f"hold_invalid:{h.get('ticket')}:{why}")

    # Per-binding liveness, awaiting, STALLED, BAKE_OWED
    fp_cache, new_fp, bake_keys_seen = ctx.get("fp_cache") or {}, {}, set()
    for b in bindings:
        t = b["ticket"]
        kid = kids.get(t)
        closed = bool(kid and (kid.get("state") or {}).get("type") in CLOSED)
        live_any, fps, unknown_fp = False, [], False
        for c in b["carriers"]:
            lv = live_of(c)
            _, fp, cat = cstate[(c["type"], c["id"])]
            if cat:
                awaiting.append({"ticket": t, "carrier": c["id"], "category": cat})
            if lv:
                live_any = True
                if c["type"] in ("card", "founder", "wake"):
                    continue
                fps.append(fp)
                unknown_fp |= fp is None
        pub = b.get("publication") or {}
        prow = ctx["prs"].get(f"{pub.get('repo')}#{pub.get('pr')}") if "pr" in pub else None
        pstate, pending, pfp = pr_facts(prow)
        merged = bool(prow and prow.get("mergedAt")) or pub.get("via") == "push"
        if pstate == "OPEN":
            live_any = True
            fps.append(pfp)
        elif pstate == "CLOSED" and not merged:
            awaiting.append({"ticket": t, "pr": pub.get("pr"), "category": "pr_closed"})
        if merged and kid and not closed:
            key = st.publication_key(pub)
            flags["STALE_OPEN"].append({"item": t, "publication": key,
                                        "why": f"bound artifact {key} landed while the ticket is "
                                               f"{(kid.get('state') or {}).get('name')}",
                                        "fix": f"resolve {t} this turn, citing {key}"})
        if t == map_id:
            dead = [c["id"] for c in b["carriers"] if c["type"] not in ("founder",) and not live_of(c)]
            if dead:
                notes.append(f"retire_carriers:{t}:{','.join(dead)}")
            continue
        # BAKE_OWED (R12)
        kind = (kid or {}).get("kind")
        if kind == "ship" and merged and not b["bake"].startswith("none:"):
            key = st.publication_key(pub)
            bake = _bake_child(t, kids)
            if (not bake or (bake.get("state") or {}).get("type") in CLOSED) and key not in bake_keys_seen \
                    and not (bake and _verdict(bake) == "pass"):
                bake_keys_seen.add(key)
                flags["BAKE_OWED"].append({"item": t, "publication": key,
                                           "fix": f"R12: adopt or ticket-add --kind bake --blocked-by {t}; "
                                                  f"resolve {t}; bind the bake with a wake carrier; retire {t}"})
        if closed:
            notes.append(f"retire_due:{t}")
            continue
        if kid is None and tracker is not None:
            notes.append(f"binding_not_in_map:{t}")
        has_artifact = bool(pub) or any(ctx["outfiles"].get(c.get("outfile") or "") for c in b["carriers"])
        mine_await = any(a["ticket"] == t for a in awaiting)
        stalled = None
        if not b["carriers"] and now - st.parse_iso(b["bound_at"]) > LEASE["launch"]:
            stalled = "c: bound with no carrier for more than 600 s (launch died)"
        elif b["carriers"] and not live_any and not mine_await and not has_artifact:
            stalled = "a: no live carrier, nothing awaiting the manager, no artifact (salvage git status first)"
        elif live_any and fps and not unknown_fp:
            fp = _h(sorted(fps))
            prev = fp_cache.get(t) or {}
            since = prev.get("since") if prev.get("fingerprint") == fp else (now if prev else st.parse_iso(b["bound_at"]))
            new_fp[t] = {"fingerprint": fp, "since": since}
            lease = b.get("lease_s") or (LEASE["pr_pending"] if pstate == "OPEN" and pending else
                                         LEASE["session"] if any(c["type"] == "session" for c in b["carriers"])
                                         else LEASE["lane"])
            if now - since > lease:
                stalled = f"b: fingerprint unchanged {int(now - since)} s > lease {lease} s with a live carrier"
        elif live_any and fp_cache.get(t):
            new_fp[t] = fp_cache[t]
        if stalled:
            flags["STALLED"].append({"item": t, "why": stalled,
                                     "fix": "no live carrier: salvage, retire the dead carrier, continue in the same "
                                            "worktree (--cwd); live carrier: inspect or message it, never a second writer"})

    # DUPLICATE_TITLE: two children of one map share a normalized title and one is still open
    by_title = {}
    for cid in order:
        c = kids[cid]
        if ((c.get("state") or {}).get("type")) in DUP_IGNORED or not c.get("title"):
            continue
        by_title.setdefault(" ".join(re.findall(r"[a-z0-9]+", c["title"].lower())), []).append(cid)
    for tickets in by_title.values():
        if not any((kids[x].get("state") or {}).get("type") not in CLOSED for x in tickets):
            continue  # every copy is already closed: nothing left to resolve
        for cid in tickets[1:]:
            flags["DUPLICATE_TITLE"].append({"item": cid, "duplicate_of": tickets[0],
                                             "why": f"same title as {tickets[0]} under map {map_id}",
                                             "fix": f"mark {cid} Duplicate of {tickets[0]}, or retitle one"})

    # Items, READY, UNBOUND(started)
    items, ready_since = [], dict(ctx.get("ready_since") or {})
    counts = {"done": 0, "open": 0, "blocked": 0}
    new_ready = {}
    for cid in order:
        c = kids[cid]
        stype = (c.get("state") or {}).get("type")
        b = by_ticket.get(cid)
        blockers = _blocking_blockers(c, kids)
        state = ("closed" if stype in CLOSED else "active" if b else "blocked" if blockers else "ready")
        f = []
        if state == "closed":
            counts["done"] += 1
        else:
            counts["open"] += 1
            counts["blocked"] += state == "blocked"
        errs = c.get("errors") or []
        if state != "closed":
            if c.get("kind") is None:
                notes.append(f"kind_conflict:{cid}" if "kind_conflict" in errs else f"kind_missing:{cid}")
            notes += [f"{e}:{cid}" for e in errs if e.endswith("_truncated")]
        if state == "ready" and not b:
            if stype == STARTED:
                f.append("UNBOUND")
                flags["UNBOUND"].append({"item": cid, "why": "tracker state started with no binding (R8b)",
                                         "fix": f"work_state.py bind --program {slug} --ticket {cid}, then carrier"})
            elif "kind_conflict" not in errs and not ctx.get("absorbed") and cid not in valid_hold:
                f.append("READY_NOT_DISPATCHED")
                new_ready[cid] = ready_since.get(cid, now)
                flags["READY_NOT_DISPATCHED"].append({
                    "item": cid, "kind": c.get("kind"),
                    "fix": f"dispatch {cid}: work_state.py bind, a tracked launch, carrier; or a valid Hold: {cid} <reason>"})
            elif cid in valid_hold:
                new_ready[cid] = ready_since.get(cid, now)
        for fl in ("STALLED", "BAKE_OWED", "STALE_OPEN", "DUPLICATE_TITLE", "PROOF_FAILED"):
            if any(x["item"] == cid for x in flags[fl]):
                f.append(fl)
        bake = _bake_child(cid, kids) if c.get("kind") == "ship" else None
        # R18: tracker contract /1 carries no verdict-comment link, so each predecessor names its bake
        # ticket, whose verdict comment the manager reads at the merge gate.
        preds = [{"ticket": x["ticket"], "bake_verdict": _verdict(_bake_child(x["ticket"], kids)),
                  "bake_ticket": (_bake_child(x["ticket"], kids) or {}).get("ticket")}
                 for x in c.get("blocked_by") or [] if (kids.get(x["ticket"]) or {}).get("kind") == "ship"] \
            if c.get("kind") == "ship" and b and b.get("carve_out") else []
        fpe = new_fp.get(cid)
        items.append({"ticket": cid, "kind": c.get("kind"), "kind_inferred": bool(c.get("kind_inferred")),
                      "state": state, "title": c.get("title"),
                      "carriers": [{"type": x["type"], "id": x["id"], "live": cstate.get((x["type"], x["id"]), (None,))[0]}
                                   for x in (b or {}).get("carriers") or []],
                      "publication": (b or {}).get("publication"),
                      "pr": pr_view((b or {}).get("publication"), ctx["prs"]), "blocked_by": blockers,
                      "ready_since": st.now_iso(new_ready[cid]) if cid in new_ready else None,
                      "fingerprint_age_s": int(now - fpe["since"]) if fpe else None,
                      "bake_verdict": _verdict(bake), "predecessor_verdicts": preds, "flags": f,
                      "ended": stype if state == "closed" else None,
                      "bake_ended": ((bake or {}).get("state") or {}).get("type") if bake else None})
    for t, b in by_ticket.items():
        if t not in kids and t != map_id:
            items.append({"ticket": t, "kind": None, "kind_inferred": False, "state": "active", "title": None,
                          "carriers": [{"type": x["type"], "id": x["id"], "live": cstate.get((x["type"], x["id"]), (None,))[0]}
                                       for x in b["carriers"]], "publication": b.get("publication"),
                          "pr": pr_view(b.get("publication"), ctx["prs"]), "blocked_by": [],
                          "ready_since": None, "fingerprint_age_s": None, "bake_verdict": None,
                          "predecessor_verdicts": [], "flags": [fl for fl in ("STALLED", "PROOF_FAILED") if
                                                                 any(x["item"] == t for x in flags[fl])]})

    # UNBOUND carriers (R22)
    if not map_id:
        flags["UNBOUND"].append({"item": "map", "why": "the program has no map", "fix": "create the map"})
    bound_ids = {c["id"] for b in bindings for c in b["carriers"]}
    floor = ctx.get("floor") or 0
    sessions, cli = ctx["sessions"], ctx["cli"]
    for sid in sorted(ctx["family_sessions"]):
        row = sessions.get(sid)
        if not row or pf.is_manager(row) or ctx.get("absorbed"):
            continue
        if sid in bound_ids or (row.get("cliSessionId") in bound_ids):
            continue
        if not pf.session_live(row, now, LEASE["session"]) or pf.parse_last(row) < floor:
            continue
        flags["UNBOUND"].append({"item": sid, "why": f"live child session {row.get('title')!r} in no binding",
                                 "fix": f"work_state.py bind --program {slug} --ticket <its ticket> (ticket-add first "
                                        f"if none), then carrier --type session --id {sid}"})
    for lane, row in sorted(ctx["lanes"].items()):
        if row.get("parent") not in ctx["manager_ids"] or lane in bound_ids:
            continue
        ts = st.parse_iso(row.get("ts"))
        if ts < floor:
            continue
        pid, start = row.get("pid"), row.get("pid_start")
        live = pid in ctx["pids"] and (not start or " ".join(start.split()) == ctx["pids"][pid])
        if live or (row.get("outfile") and now - ts < LANE_UNBOUND_AGE_S):
            flags["UNBOUND"].append({"item": lane, "why": f"lane row ({'live pid' if live else 'outfile, < 7 d'}) in no binding",
                                     "fix": f"work_state.py bind --program {slug} --ticket <its ticket>, then carrier "
                                            f"--type lane --id {lane}"})
    bound_branches = {b.get("branch") for b in bindings if b.get("branch")}
    bound_prs = {st.publication_key(b["publication"]) for b in bindings if b.get("publication")}
    carrier_sessions = [sessions.get(c["id"]) or sessions.get(cli.get(c["id"], "")) for b in bindings
                        for c in b["carriers"] if c["type"] == "session"]
    carrier_sessions += [sessions.get(s) for s in ctx["family_sessions"]]
    branches = {_branch_of(w) for r in carrier_sessions if r for w in r.get("writtenBranches") or []}
    for key, row in sorted(ctx["prs"].items()):
        if row.get("state") == "OPEN" and row.get("headRefName") in branches and key not in bound_prs \
                and row.get("headRefName") not in bound_branches:
            flags["UNBOUND"].append({"item": key, "why": f"open PR on a carrier's branch {row.get('headRefName')}",
                                     "fix": f"work_state.py bind --continue --program {slug} --ticket <its ship> "
                                            f"--repo {key.split('#')[0]} --pr {key.split('#')[1]}"})

    # Exemptions and blocking (R29): the engine alone decides
    status = str(ctx["state"].get("status") or "").upper()
    blocking = [dict(x, flag="UNBOUND") for x in flags["UNBOUND"]]
    ready_block = [dict(x, flag="READY_NOT_DISPATCHED") for x in flags["READY_NOT_DISPATCHED"]]
    if tracker is None:
        notes.append("no_tracker" if not ctx.get("has_tracker_cmd") else "tracker_unavailable")
    elif (ctx.get("tracker_age_s") or 0) > TRACKER_STALE_S:
        notes.append(f"ready_dropped:tracker_age_{int(ctx['tracker_age_s'])}s")
        ready_block = []
    blocking += ready_block
    if status == "DONE":
        if tracker is not None and counts["open"] == 0:
            blocking = []
            notes.append("exempt:status_done_zero_open")
        else:
            notes.append("status_done_with_open_children:no_exemption")
    if status == "GRILLING":
        notes.append("grilling:only_founder_items_exempt")
    frontier = [i["ticket"] for i in items if i["state"] == "ready"]
    map_line = (f"Map {map_id}: done {counts['done']} / open {counts['open']} / blocked {counts['blocked']}; "
                f"frontier now: {', '.join(frontier) or 'none'}")
    snap = {"schema": SCHEMA, "program": slug, "map": map_id, "taken_at": st.now_iso(now),
            "remote_age_s": {"tracker": None if ctx.get("tracker_age_s") is None else int(ctx["tracker_age_s"]),
                             "gh": None if ctx.get("gh_age_s") is None else int(ctx["gh_age_s"])},
            "children_count": (tracker or {}).get("children_count", len(order)) if tracker else None,
            "items": items, "flags": flags, "blocking": [{"item": x["item"], "flag": x["flag"], "fix": x["fix"]}
                                                         for x in blocking],
            "awaiting_manager": awaiting, "holds": holds, "frontier": frontier,
            "pending_events": list(ctx.get("pending_events") or []), "map_line": map_line, "notes": notes}
    return snap, {"fp": new_fp, "ready_since": new_ready}


# ---------- commands ----------

def _emit(obj, as_json=True):
    print(json.dumps(obj, indent=2, default=str) if as_json else obj)


def run_snapshot(slug, *, mode="snapshot", refresh=False, stdin_facts=None, programs=None, runner=subprocess.run,
                 now=None):
    """-> (snapshot, exit code). The guard path (mode 'guard') writes no cache."""
    ctx, cache, _ = src.build_ctx(slug, mode=mode, refresh=refresh, stdin_facts=stdin_facts, programs=programs,
                                  runner=runner, now=now, check=check_tracker_schema)
    snap, parts = derive(ctx)
    if mode != "guard":
        cache["fp"] = dict(cache.get("fp") or {}, **parts["fp"])
        cache["fp"] = {k: v for k, v in cache["fp"].items() if any(b["ticket"] == k for b in ctx["bindings"])}
        cache["ready_since"] = parts["ready_since"]
        day = st.now_iso(ctx["now"])[:10]
        if cache.get("outcome_day") != day and ctx["tracker"] is not None:
            verdicts = [i["bake_verdict"] for i in snap["items"] if i["kind"] == "ship"]
            src.telemetry({"program": slug, "kind": "outcome", "day": day,
                           "closed": sum(i["state"] == "closed" for i in snap["items"]),
                           "bake_pass": verdicts.count("pass"), "bake_fail": verdicts.count("fail")})
            cache["outcome_day"] = day
        src.write_cache(slug, cache)
    return snap, (4 if snap["blocking"] else 0)


def _children(slug, programs=None, refresh=False):
    """Map child ids from the tracker tier (TTL-fetched), or None when the tracker is unavailable."""
    manifest = st.read_manifest(slug, programs)
    cache = src.read_cache(slug)
    data, _, _, _ = src.load_tracker(slug, manifest, cache, time.time(), refresh=refresh, check=check_tracker_schema)
    if data is not None:
        src.write_cache(slug, cache)
    return manifest, cache, ({c["ticket"] for c in data.get("children") or []} if data else None), data


def changed_paths(repo=None, pr=None, repo_dir=None, sha=None, runner=subprocess.run):
    if pr:
        r = runner(["gh", "pr", "diff", str(pr), "--repo", repo, "--name-only"], capture_output=True, text=True,
                   timeout=30)
    else:
        r = runner(["git", "-C", repo_dir or ".", "diff", "--name-only", f"{sha}^", sha], capture_output=True,
                   text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"changed paths unavailable (rc={r.returncode})")
    return [ln for ln in r.stdout.splitlines() if ln.strip()]


def bake_for(paths, deny=()):
    return "none:docs-only" if docs_only(paths, deny) else "required"


def bake_body(slug, ship, programs=None):
    manifest, cache, _, data = _children(slug, programs)
    kid = _child_map(data).get(ship) or {}
    b = next((x for x in manifest.get("bindings") or [] if x["ticket"] == ship), {})
    pub = b.get("publication") or {}
    values = {"obligation": f"Bake: {kid.get('title') or ship} (changed runtime seam of {ship})",
              "deploy SHA": pub.get("sha") or "<the merge SHA, confirmed present in the environment at the wake>",
              "environment": "<target environment the deploy seam confirmed>",
              "command/journey": "<the smallest project-authorized proof against the changed seam>",
              "test identity": "<the safe test identity or org the proof runs as>",
              "human-step kit": "<exact copy-ready steps for any human-gated step, or none>",
              "terminal assertion": "<the one observable that makes the verdict PASS or FAIL>"}
    keys = bake_keys()
    lines = [f"Bake of {ship} ({st.publication_key(pub) if pub else 'publication unknown'}).", ""]
    lines += [f"- **{k}**: {values.get(k, '<fill>')}" for k in keys]
    lines += ["", "Verdict: a comment citing the deploy SHA, the terminal assertion and its evidence. PASS: resolve "
                  "Done. FAIL: file a fix ship; cancel this ticket naming the new one."]
    return "\n".join(lines), keys


def _retire_allow(slug, programs=None):
    _, _, _, data = _children(slug, programs)
    kids = _child_map(data)
    bound = {b["ticket"] for b in st.read_manifest(slug, programs).get("bindings") or []}

    def allow(b):
        if data is None:
            return False, "tracker unavailable: closure cannot be proven"
        kid = kids.get(b["ticket"])
        if not kid or (kid.get("state") or {}).get("type") not in CLOSED:
            return False, f"{b['ticket']} is not closed in the tracker"
        if kid.get("kind") == "ship" and b.get("publication") and b["bake"] == "required":
            bake = _bake_child(b["ticket"], kids)
            if not bake or (bake["ticket"] not in bound and (bake.get("state") or {}).get("type") not in CLOSED):
                return False, f"merged ship {b['ticket']} retires only once its bake ticket's binding exists (R5)"
        return True, ""
    return allow


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("snapshot", "guard", "bind", "carrier", "retire", "bake-body", "bake-exempt"):
        p = sub.add_parser(name)
        p.add_argument("--program", required=name not in ("bake-exempt",))
    sp = sub.choices
    sp["snapshot"].add_argument("--refresh", action="store_true")
    sp["snapshot"].add_argument("--json", action="store_true")
    b = sp["bind"]
    for k in ("--ticket", "--branch", "--worktree", "--artifact", "--repo", "--sha", "--paths"):
        b.add_argument(k, required=k == "--ticket")
    b.add_argument("--pr", type=int)
    b.add_argument("--bake", default="required", help="required | none:<reason> | auto (R15 docs-only)")
    b.add_argument("--carve-out", action="store_true")
    b.add_argument("--lease-s", type=int)
    b.add_argument("--continue", dest="cont", action="store_true")
    b.add_argument("--refresh", action="store_true")
    c = sp["carrier"]
    for k in ("--ticket", "--type", "--id", "--runtime", "--model", "--wave", "--pid-start", "--outfile"):
        c.add_argument(k, required=k in ("--ticket", "--type", "--id"))
    c.add_argument("--pid", type=int)
    r = sp["retire"]
    for k in ("--ticket", "--carrier", "--merge-sha", "--verdict", "--reason"):
        r.add_argument(k, required=k == "--ticket", default="" if k == "--reason" else None)
    sp["bake-body"].add_argument("ship")
    e = sp["bake-exempt"]
    for k in ("--repo", "--repo-dir", "--sha"):
        e.add_argument(k)
    e.add_argument("--pr", type=int)
    lr = sub.add_parser("lane-row")
    for k in ("--lane", "--parent", "--runtime", "--model", "--outfile", "--worktree"):
        lr.add_argument(k, default="")
    lr.add_argument("--pid", type=int, required=True)
    mg = sub.add_parser("migrate")
    mg.add_argument("--program")
    mg.add_argument("--all", action="store_true")
    mg.add_argument("--dry-run", action="store_true")
    mg.add_argument("--ticket-for", action="append", default=[], help="'<lane name>=<ticket>' after ticket-add")
    mg.add_argument("--resolved", action="append", default=[], help="a todo key the manager completed")
    a = ap.parse_args(argv)
    try:
        if a.cmd in ("snapshot", "guard"):
            facts = json.loads(sys.stdin.read() or "{}") if a.cmd == "guard" else None
            snap, rc = run_snapshot(a.program, mode=a.cmd, refresh=getattr(a, "refresh", False), stdin_facts=facts)
            if a.cmd == "guard" or a.json:
                _emit(snap)
            else:
                print(snap["map_line"])
                for x in snap["blocking"]:
                    print(f"BLOCKING {x['flag']} {x['item']}: {x['fix']}")
                for fl in ("STALLED", "BAKE_OWED", "STALE_OPEN", "DUPLICATE_TITLE", "PROOF_FAILED"):
                    for x in snap["flags"][fl]:
                        print(f"{fl} {x['item']}: {x.get('why') or x.get('publication')}")
                for n in snap["notes"]:
                    print(f"note {n}")
            return rc
        if a.cmd == "bind":
            manifest, cache, children, _ = _children(a.program, refresh=a.refresh)
            pub = None
            if a.repo and a.pr:
                pub = {"repo": a.repo, "pr": a.pr}
            elif a.repo and a.sha:
                pub = {"repo": a.repo, "sha": a.sha, "via": "push"}
            bake = a.bake
            if bake == "auto":
                bake = bake_for(changed_paths(a.repo, a.pr, a.worktree, a.sha),
                                (manifest.get("map") or {}).get("bake_exempt_deny") or ())
            binding, notes = st.bind(a.program, a.ticket, children=children, map_id=(manifest.get("map") or {}).get("issue"),
                                     bake=bake, branch=a.branch, worktree=a.worktree, artifact=a.artifact, publication=pub,
                                     carve_out=a.carve_out, paths=[p for p in (a.paths or "").split(",") if p] or None,
                                     lease_s=a.lease_s, cont=a.cont)
            rs = (cache.get("ready_since") or {}).pop(a.ticket, None)
            if rs:
                src.telemetry({"program": a.program, "kind": "bind_latency", "ticket": a.ticket,
                               "latency_s": int(time.time() - rs)})
                src.write_cache(a.program, cache)
            _emit({"binding": binding, "notes": notes})
            return 0
        if a.cmd == "carrier":
            extra = {"runtime": a.runtime, "model": a.model, "wave": a.wave, "pid": a.pid, "pid_start": a.pid_start,
                     "outfile": a.outfile}
            if a.type == "lane" and a.pid is None:
                row = st.read_lane_rows().get(a.id) or {}
                extra.update({k: extra[k] or row.get(k) for k in ("runtime", "model", "pid", "pid_start", "outfile")})
                extra["outfile"] = extra["outfile"] or None
            binding, notes = st.carrier(a.program, a.ticket, a.type, a.id, **extra)
            _emit({"binding": binding, "notes": notes})
            return 0
        if a.cmd == "retire":
            ids = [x for x in (a.carrier or "").split(",") if x]
            out = st.retire(a.program, a.ticket, carrier_ids=ids or None, merge_sha=a.merge_sha, verdict=a.verdict,
                            reason=a.reason, allow=None if ids else _retire_allow(a.program))
            _emit({"retired": out})
            return 0
        if a.cmd == "bake-body":
            print(bake_body(a.program, a.ship)[0])
            return 0
        if a.cmd == "bake-exempt":
            deny = ()
            if a.program:
                deny = (st.read_manifest(a.program).get("map") or {}).get("bake_exempt_deny") or ()
            print(bake_for(changed_paths(a.repo, a.pr, a.repo_dir, a.sha), deny))
            return 0
        if a.cmd == "lane-row":
            _emit(st.append_lane_row(a.lane, a.parent, a.runtime, a.model, a.pid, a.outfile, a.worktree))
            return 0
        if a.cmd == "migrate":
            import work_state_migrate as wm
            if a.all:
                res = wm.migrate_all(dry_run=a.dry_run)
            else:
                res = wm.migrate_program(a.program, dry_run=a.dry_run, ticket_for=dict(x.split("=", 1) for x in a.ticket_for),
                                         resolved=set(a.resolved))
            _emit(res)
            return 0 if a.dry_run or not (res.get("todo") if isinstance(res, dict) else None) else 1
    except SchemaMismatch as e:
        _emit({"error": "schema_mismatch", "detail": str(e)})
        return 1
    except (st.SchemaError, OSError, ValueError, RuntimeError) as e:
        _emit({"error": type(e).__name__, "detail": str(e)})
        return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
