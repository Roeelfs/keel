#!/usr/bin/env python3
"""Plan, gates and completeness receipt for mine_all.py (pure rendering, plus --gate checks).

The plan lists the agent steps mine_all.py cannot do deterministically, in the founder's order:
phase 1 handoff miners (one per moved program), phase 2 AFTER phase 1 the child-ledger
reconcilers (incl. the old-descendant and orphan-transcript classifiers), the decisions sweep and
the worktree sweep, phase 3 the relay: ONE message per manager, only once every gate is PASS.
"""
import glob
import json
import os
import time

PROMPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "prompts")


def iso(ts):
    return time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime(ts)) if ts else "-"


def short(sid):
    return sid[6:14] if sid.startswith("local_") else sid[:8]


def _ledgers(ledger_dir):
    out = []
    for f in sorted(glob.glob(os.path.join(ledger_dir, "children-*.json"))):
        try:
            d = json.load(open(f))
        except (OSError, ValueError):
            continue
        out.append({"file": f, "manager": d.get("manager"), "managerSessionId": d.get("managerSessionId"),
                    "kind": d.get("kind", "children"), "n": len(d.get("children", []))})
    return out


def _unseen_rows(ledger_file, p, text):
    """Rows the program's checkpoint manager has not seen: active after its checkpoint, or owned by
    another manager instance and named in no handoff, wrap-up or state file (the Test B rule)."""
    try:
        d = json.load(open(ledger_file))
    except (OSError, ValueError):
        return 1
    stamp = time.strftime("%Y-%m-%dT%H:%M", time.gmtime(p["checkpoint"]))
    other = d.get("managerSessionId") != p.get("checkpoint_sid")
    named = lambda c: c["sessionId"] in text or c["sessionId"][6:14] in text or c["title"][:28] in text  # noqa: E731
    return sum(1 for c in d.get("children", [])
               if (c.get("lastActivity") or "")[:16] > stamp or (other and not named(c)))


def _program_of(ctx, sid):
    for p in ctx["programs"]:
        if sid in [m["sid"] for m in p["managers"]]:
            return p
    return None


def _repo(p):
    for m in p["managers"]:
        if m.get("repo"):
            return m["repo"]
    return "(unknown: ask the manager)"


def build_plan(ctx):
    date, s2c = ctx["date"], ctx["s2c"]
    stamp = time.strftime("%Y-%m-%dT%H%MZ", time.gmtime(ctx["now"]))  # one name per run: never clobber an earlier handoff
    hand, relay = os.path.join(s2c, "handoff"), os.path.join(s2c, "relay")
    sweep = {}
    try:
        sweep = json.load(open(os.path.join(ctx["work"], "handoff-sweep.json")))
    except (OSError, ValueError):
        pass
    phase1, handoff_of = [], {}
    for p in ctx["programs"]:
        if not p["moved"]:
            continue
        titles = {m["title"] for m in p["managers"]}
        rows = [w for w in sweep.get("worktrees", []) if w.get("manager") in titles]
        rows_file = os.path.join(ctx["work"], f"sweep-{p['slug']}.json")
        with open(rows_file, "w") as fh:
            json.dump(rows, fh, indent=1)
        notes = sorted(glob.glob(os.path.join(s2c, "wrapup", f"*{p['slug']}*.md")), key=os.path.getmtime)
        out = os.path.join(hand, f"{stamp}-{p['slug']}.md")
        handoff_of[p["slug"]] = out
        segs = ctx["digests"].get(p["slug"], [])
        phase1.append({"id": f"handoff:{p['slug']}", "prompt": os.path.join(PROMPTS, "handoff-miner.md"), "model": "haiku",
                       "inputs": {"PROGRAM": p["slug"], "DIGEST": [s["digest"] for s in segs],
                                  "TRANSCRIPT": [s["transcript"] for s in segs], "CHECKPOINT": f"{iso(p['checkpoint'])} ({p['checkpoint_src']})",
                                  "CHECKPOINT_NOTE": notes[-1] if notes else "none", "STATE_FOLD": p["fold"],
                                  "SWEEP_ROWS": rows_file, "REPO": _repo(p)}, "out": out})
    phase2, skipped = [], []
    for lg in _ledgers(ctx["ledger_dir"]):
        p = _program_of(ctx, lg["managerSessionId"] or "")
        if p is not None and lg["kind"] == "children":
            unseen = _unseen_rows(lg["file"], p, ctx.get("named_text", ""))
            if not unseen:
                skipped.append(f"{os.path.basename(lg['file'])}: all {lg['n']} rows predate {p['slug']}'s checkpoint "
                               f"{iso(p['checkpoint'])} and are its own or already named in a handoff/state file")
                continue
        if lg["kind"] == "old-descendants":
            sid, handoff, mode = "old-descendants", "none: verdict DONE / AT-RISK / SUPERSEDED per row", "test-b"
        elif lg["kind"] == "orphan-transcripts":
            sid, handoff, mode = "orphan-transcripts", "none: add 'likeliest program' per row", "orphans"
        elif p is None:
            sid, handoff, mode = "unmanaged", "none: add 'likeliest program' per AT-RISK row", "unmanaged"
        else:
            sid = f"{p['slug']}-children-{short(lg['managerSessionId'])}"
            handoff = handoff_of.get(p["slug"]) or f"none (program quiet since checkpoint): judge against {p['fold']['state']}"
            mode = "children"
        phase2.append({"id": f"reconcile:{sid}", "prompt": os.path.join(PROMPTS, "child-ledger-reconciler.md"),
                       "model": "haiku", "mode": mode, "inputs": {"LEDGER": lg["file"], "HANDOFF": handoff},
                       "rows": lg["n"], "out": os.path.join(hand, f"{stamp}-{sid}.md"), "program": (p or {}).get("slug")})
    repos = sorted({_repo(p) for p in ctx["programs"]})
    decisions = os.path.join(relay, f"{stamp}-sweep-decisions.md")
    worktrees = os.path.join(relay, f"{stamp}-sweep-worktrees.md")
    phase2 += [{"id": "decisions-sweep", "prompt": os.path.join(PROMPTS, "decisions-sweep.md"), "model": "sonnet",
                "inputs": {"DATE": date, "CHECKPOINT": ctx["since_iso"], "REPO": repos}, "out": decisions},
               {"id": "worktree-sweep", "prompt": os.path.join(PROMPTS, "worktree-sweep.md"), "model": "sonnet",
                "inputs": {"CHECKPOINT": ctx["since_iso"], "REPOS": repos,
                           "KNOWN": os.path.join(ctx["work"], "handoff-sweep.json")}, "out": worktrees}]
    messages, kits = [], []
    for p in ctx["programs"]:
        children = [s["out"] for s in phase2 if s.get("program") == p["slug"]]
        if not (p["moved"] or children):
            continue
        base = {"program": p["slug"], "handoff": handoff_of.get(p["slug"]), "children": children,
                "decisions": decisions, "worktrees": worktrees, "state": p["fold"]["state"]}
        if not p["live"]:  # whole family archived: its rows ride the absorber's message, never a start
            absorber = next((q for q in ctx["programs"] if q["slug"] == p["absorbed_by"]), None)
            messages.append(dict(base, kind="closed-program-rows", target=(absorber or {}).get("relay_to")))
        elif p["absorbed_by"]:
            messages.append(dict(base, kind="fold-notice", target=p["relay_to"], absorber=p["absorbed_by"]))
        elif p["relay_to"]:
            messages.append(dict(base, kind="catchup", target=p["relay_to"]))
        else:
            messages.append(dict(base, kind="no-manager-here", target=None))
            kits.append(f"Program {p['slug']} has no manager on this account. Reply `start {p['slug']}` (recommended: "
                        f"its handoff shows live work) or `leave {p['slug']}`; the dispatcher starts nothing unasked.")
    kits.append("After the send round: type `go` in each manager whose next step needs a child session "
                "(a catch-up turn cannot start sessions).")
    kits.append("A send refused with 'Workspace requires trust approval': open that session, accept the trust "
                "prompt, reply `Done`; the dispatcher resends from relay/<date>-pending-sends.md.")
    return {"created": time.time(), "date": date, "since": ctx["since_iso"], "here": ctx["here"],
            "dry_run": ctx["dry_run"], "skipped": skipped, "phases": [
                {"phase": 1, "name": "handoff miners", "parallel": True, "steps": phase1},
                {"phase": 2, "name": "reconcilers + decisions sweep + worktree sweep", "after": 1, "parallel": True, "steps": phase2},
                {"phase": 3, "name": "relay: ONE message per manager", "after": 2,
                 "only_when": "mine_all.py --gate <plan> exits 0", "messages": messages, "founder_kits": kits}]}


def gates(ctx, plan):
    acc = ctx["accounts"]
    res, hist = ctx["residual"], ctx["history"]
    last_orphans = hist[-1]["orphans"] if hist else 0
    no_mgr = sum(1 for p in ctx["programs"] if p["live"] and not any(m["acct"] == ctx["here"] for m in p["managers"]))
    g = [
        ("accounts", sum(a["sessions"] for a in acc.values()) > 0,
         f"{len(acc)} account dirs, {sum(a['sessions'] for a in acc.values())} sessions, {len(ctx['unreadable'])} unreadable (named)"),
        ("this-account", bool(ctx["here"]), ctx["here_why"]),
        ("checkpoints", bool(ctx["here"]) and all(p["checkpoint"] for p in ctx["programs"]),
         f"{len(ctx['programs'])} programs, {no_mgr} live with no manager instance here (checkpoint = window floor)"),
        ("chains", True, f"{sum(1 for p in ctx['programs'] for m in p['managers'] if m['store_last'] >= ctx['since']) - len(ctx['unproven'])} "
                         f"manager chains proven by lastAssistantUuid, {len(ctx['unproven'])} named unreadable"),
        ("sweeps-ran", all(s["rc"] == 0 for s in ctx["sweeps"].values()),
         ", ".join(f"{k} rc {v['rc']}" + (f" ({v['err'].strip()[:80]})" if v["rc"] else "") for k, v in ctx["sweeps"].items())),
        ("coverage-test-a", not res["holes"], f"{len(res['holes'])} sessions active since {ctx['since_iso']} outside every ledger"),
        ("old-descendants-test-b", not res["unnamed"], f"{len(res['unnamed'])} older unmerged descendants neither named nor ledgered"),
        ("orphan-transcripts", last_orphans == 0, f"{last_orphans} desktop transcripts with no store row left unledgered"),
    ]
    out = [{"id": i, "kind": "deterministic", "status": "PASS" if ok else "FAIL", "evidence": ev} for i, ok, ev in g]
    for ph in plan["phases"][:2]:
        for s in ph["steps"]:
            out.append({"id": s["id"], "kind": "agent", "status": "OWED", "evidence": s["out"]})
    return out


def exit_code(gs):
    if any(g["status"] == "FAIL" for g in gs):
        return 2
    return 3 if any(g["status"] == "OWED" for g in gs) else 0


def _gate_table(gs):
    det = [g for g in gs if g["kind"] == "deterministic"]
    agent = [g for g in gs if g["kind"] == "agent"]
    lines = ["## Gates", "", "| gate | status | evidence |", "|---|---|---|"]
    lines += [f"| {g['id']} | **{g['status']}** | {g['evidence']} |" for g in det]
    counts = {s: sum(1 for g in agent if g["status"] == s) for s in ("PASS", "OWED", "FAIL")}
    lines += ["", f"Agent gates: {len(agent)} (PASS {counts['PASS']}, OWED {counts['OWED']}, FAIL {counts['FAIL']}).", ""]
    lines += [f"- {g['status']} `{g['id']}` -> {g['evidence']}" for g in agent if g["status"] != "PASS"]
    verdict = {0: "ALL GATES PASS: relay may start (phase 3).", 2: "A DETERMINISTIC GATE FAILED: message no manager.",
               3: "Agent gates OWED: run phases 1-2, then `mine_all.py --gate <plan>`. Message no manager yet."}[exit_code(gs)]
    return "\n".join(lines + ["", f"**{verdict}**", ""])


def render_receipt(ctx, plan, gs):
    L = [f"# Completeness receipt {ctx['date']} (mine_all.py{' --dry-run' if ctx['dry_run'] else ''})", "",
         f"- Generated {iso(ctx['now'])}. This account: `{ctx['here']}` ({ctx['here_why']}).",
         f"- Window floor {iso(ctx['floor'])} ({ctx['window_days']:g} d). Sweep since {ctx['since_iso']}Z "
         f"(earliest checkpoint among {'moved' if any(p['moved'] for p in ctx['programs']) else 'live'} programs). "
         f"Programs: {len(ctx['programs'])}, live {sum(p['live'] for p in ctx['programs'])}, "
         f"moved {sum(p['moved'] for p in ctx['programs'])}.", "", "## Accounts scanned", "",
         "| account | orgs (sessions) | sessions | managers | unreadable |", "|---|---|---|---|---|"]
    for a, v in sorted(ctx["accounts"].items()):
        orgs = ", ".join(f"{o[:8]} ({n})" for o, n in v["orgs"].items())
        L.append(f"| {a[:8]}{' (here)' if a == ctx['here'] else ''} | {orgs} | {v['sessions']} | {v['managers']} | {v['unreadable']} |")
    L += ["", "## Programs", "", "| program | manager instances (acct:session cli verdict) | checkpoint | moved | relay to | state fold |",
          "|---|---|---|---|---|---|"]
    for p in ctx["programs"]:
        inst = "<br>".join(f"{m['acct'][:8]}:{short(m['sid'])} {m['cli'][:8]}{' arch' if m['archived'] else ''} {m['verdict']}"
                           for m in sorted(p["managers"], key=lambda m: -m["store_last"]))
        f = p["fold"]
        fold = (f"{f['verdict']}: state {iso(f['state_mtime'])}, events {iso(f['events_mtime'])} (last {iso(f['last_event'])}), "
                f"lineage {iso(f['lineage_last'])}, map comment {f['map_comment'].split(':')[0]}")
        tag = f" (absorbed by {p['absorbed_by']})" if p["absorbed_by"] else ""
        L.append(f"| {p['slug']}{tag} | {inst} | {iso(p['checkpoint'])}: {p['checkpoint_src']} | "
                 f"{'yes' if p['moved'] else ('no' if p['live'] else 'closed')} | {short(p['relay_to']) if p['relay_to'] else 'none here'} | {fold} |")
    chains = ctx["chains"]
    segs = {m for c in chains.values() for m in c["members"]}
    nbytes = sum(os.path.getsize(m) for m in segs if os.path.exists(m))
    multi = [(s, c) for s, c in chains.items() if len(c["members"]) > 1]
    heur = sum(len(c.get("heuristic", [])) for c in chains.values())
    lanes = sum(1 for h in ctx["graph"]["heads"].values() if h.get("entrypoint") == "sdk-cli")
    dg = [s for v in ctx["digests"].values() for s in v]
    L += ["", "## Transcript chains", "",
          f"- {len(chains)} sessions active in the window resolved to {len(segs)} transcript files, {nbytes / 1e6:.1f} MB.",
          f"- {len(multi)} chains span more than one file (resume/move/fork mints a new transcript id); "
          f"{sum(len(c['pre_window']) for c in chains.values())} links end before the window (provably no post-window rows).",
          f"- {heur} orphan transcripts attached by the weaker heuristic (same project dir + same custom title).",
          f"- {lanes} headless-lane transcripts (`sdk-cli`) in the window: lanes, not sessions; graded by artifact, not mined.",
          f"- Digests: {len(dg)} segments, {sum(s['bytes'] for s in dg) / 1e6:.1f} MB"
          f"{' (dry run: not written)' if ctx['dry_run'] else ''}."]
    for s, c in multi:
        r = ctx["rows"].get(s, {})
        if (r.get("title") or "").startswith("[Manager]"):
            L.append(f"  - {r['title'][:50]} {short(s)}: " + ", ".join(os.path.basename(m)[:8] for m in c["members"]))
    lg = _ledgers(ctx["ledger_dir"])
    L += ["", "## Children ledgered", "", f"- {sum(x['n'] for x in lg)} rows in {len(lg)} ledger files under `{ctx['ledger_dir']}`."]
    L += [f"  - {os.path.basename(x['file'])}: {x['n']}" for x in lg]
    L += [f"- Not reconciled: {s}" for s in plan.get("skipped", [])]
    L += ["", "## Holes", "", "| round | Test A holes | Test B unnamed | orphan transcripts | attached |", "|---|---|---|---|---|"]
    L += [f"| {h['round']} | {h['test_a']} | {h['test_b']} | {h['orphans']} | {h['attached']} |" for h in ctx["history"]]
    res = ctx["residual"]
    residual = len(res["holes"]) + len(res["unnamed"]) + (ctx["history"][-1]["orphans"] if ctx["history"] else 0)
    L += ["", f"**holes = {residual}** after widening; named unreadable = {len(ctx['unreadable']) + len(ctx['unproven'])}."]
    L += [f"- UNREADABLE store row `{f}`: {why}" for f, why in ctx["unreadable"]]
    L += [f"- UNREADABLE chain {short(s)}: {why}" for s, why in ctx["unproven"].items()]
    body = "\n".join(L) + "\n\n"
    plan["receipt_body"], plan["gates"] = body, gs
    return body + _gate_table(gs)


def check_gate(plan_path, echo=True):
    """Grade each agent step by its ARTIFACT: the out file exists, is non-empty and is newer than
    the plan. Re-renders the receipt. Exit 0 all PASS, 3 OWED, 2 a deterministic gate FAILED."""
    plan = json.load(open(plan_path))
    outs = {s["id"]: s["out"] for ph in plan["phases"][:2] for s in ph["steps"]}
    for g in plan["gates"]:
        if g["kind"] != "agent":
            continue
        f = outs.get(g["id"], "")
        ok = os.path.exists(f) and os.path.getsize(f) > 0 and os.path.getmtime(f) >= plan["created"]
        g["status"] = "PASS" if ok else "OWED"
    with open(plan["receipt"], "w") as fh:
        fh.write(plan["receipt_body"] + _gate_table(plan["gates"]))
    with open(plan_path, "w") as fh:
        json.dump(plan, fh, indent=1)
    if echo:
        print(open(plan["receipt"]).read())
    return exit_code(plan["gates"])
