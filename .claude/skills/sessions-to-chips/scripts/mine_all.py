#!/usr/bin/env python3
"""Resume / mine, ONE pass: every deterministic step of the faithful flow, then a plan of the
agent steps and a COMPLETENESS RECEIPT. The dispatcher runs this first and only this.

  1. Accounts from every session-store dir (never --account alone).
  2. The account this session runs on (CLAUDE_SESSION_ID -> its store dir; --here overrides).
  3. Transcript chains for every session active in the window (transcript_chain.py).
  4. Programs and their manager instances across accounts (program_family.py).
  5. Checkpoint per program = the last TURN of its newest manager on this account (transcript
     row, cross-checked against the store's lastAssistantUuid); never a typed time.
  6. child_ledger.py, handoff_sweep.py and the coverage audit over --account all.
  7. Hole widening until holes = 0 or each hole is named unreadable with its reason.
  8. State-file fold by the newest of state, events, manifest and lineage activity.
  9. Digests of every chain segment active since the checkpoint (mine_session.py).
 10. The plan (handoff miners, then reconcilers + decisions + worktree sweeps, then relay) and
     the receipt at ~/.claude/sessions-to-chips/relay/<date>-completeness-receipt.md.

Exit: 0 every gate PASS · 2 a deterministic gate FAILED (do not message anyone) · 3 deterministic
gates PASS, agent gates OWED (run the plan, then `mine_all.py --gate <plan>`).

Usage: python3 -I mine_all.py [--dry-run] [--here ACCT] [--window-days 14] [--date YYYY-MM-DD]
       python3 -I mine_all.py --gate <plan.json>
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import tempfile
import time

HERE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE_DIR)
import child_ledger  # noqa: E402
import coverage_audit as ca  # noqa: E402
import list_sessions  # noqa: E402
import mine_report  # noqa: E402
import program_family as pf  # noqa: E402
import transcript_chain as tc  # noqa: E402

DEFAULT_STORE = os.path.expanduser("~/Library/Application Support/Claude/claude-code-sessions")
DEFAULT_HOME = os.path.expanduser("~/.claude")


def ts_of(row, key="lastActivityAt"):
    return tc.parse_ts(row.get(key))


def naive_iso(ts):
    """The form list_sessions.py emits, so coverage_audit compares like with like."""
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def detect_here(rows, here_arg, cli_env):
    if here_arg:
        accts = {r["_acct"] for r in rows.values() if r["_acct"].startswith(here_arg)}
        return (accts.pop(), f"--here {here_arg}") if len(accts) == 1 else (None, f"--here {here_arg} matched {len(accts)} account dirs")
    for r in rows.values():
        if cli_env and r.get("cliSessionId") == cli_env:
            return r["_acct"], f"CLAUDE_SESSION_ID {cli_env[:8]} is store row {r['sessionId'][6:14]}"
    return None, "CLAUDE_SESSION_ID matches no store row; pass --here <account-prefix>"


def manager_facts(row, chain):
    own = tc.files_named(row.get("cliSessionId"), chain["projects"])
    verdict, last = pf.turn_verdict(row, own)
    return {"sid": row["sessionId"], "acct": row["_acct"], "title": row.get("title", ""),
            "archived": bool(row.get("isArchived")), "cli": row.get("cliSessionId") or "",
            "last_turn": last, "store_last": ts_of(row), "turn_edge": ts_of(row, "lastTurnEdgeAt"),
            "verdict": verdict, "own": own, "chain": chain["members"], "pre_window": chain["pre_window"],
            "last_assistant_uuid": row.get("lastAssistantUuid"), "repo": row.get("originCwd") or row.get("cwd")}


def checkpoint_for(mgrs, here, floor):
    mine = [m for m in mgrs if m["acct"] == here and m["last_turn"]]
    if mine:
        m = max(mine, key=lambda m: m["last_turn"])
        src = (f"{m['acct'][:8]}:{m['sid'][6:14]} last turn {tc.iso(m['last_turn'])} (transcript "
               f"{m['cli'][:8]}, {m['verdict']}; store lastTurnEdgeAt {tc.iso(m['turn_edge'])}, "
               f"lastActivityAt {tc.iso(m['store_last'])})")
        return m["last_turn"], src, m["sid"]
    return floor, f"no manager on this account: window floor {tc.iso(floor)}", None


def state_fold(slug, programs_dir, lineage_last, manifest):
    p = lambda ext: os.path.join(programs_dir, f"{slug}.{ext}")  # noqa: E731
    mt = lambda f: os.path.getmtime(f) if os.path.exists(f) else 0.0  # noqa: E731
    last_event = 0.0
    try:
        with open(p("events.jsonl"), errors="ignore") as fh:
            lines = [ln for ln in fh.read().splitlines() if ln.strip()]
        ev = json.loads(lines[-1]) if lines else {}
        last_event = max(tc.parse_ts(ev.get(k)) for k in ("ts", "at", "time", "timestamp", "updated_at")) if ev else 0.0
    except (OSError, ValueError, TypeError):
        pass
    state, events = mt(p("state.md")), mt(p("events.jsonl"))
    newest = max(state, events, last_event, lineage_last, tc.parse_ts((manifest or {}).get("updated_at")))
    verdict = "MISSING" if not state else ("CURRENT" if state >= newest - 1800 else
                                           f"STALE by {(newest - state) / 3600:.1f} h")
    return {"state": p("state.md"), "state_mtime": state, "events_mtime": events, "last_event": last_event,
            "manifest_updated": tc.parse_ts((manifest or {}).get("updated_at")), "lineage_last": lineage_last,
            "map": (manifest or {}).get("map"), "map_comment": "UNREAD here (Linear): the handoff miner reads it",
            "newest": newest, "verdict": verdict}


def run_script(name, argv, env):
    r = subprocess.run([sys.executable, "-I", os.path.join(HERE_DIR, name), *argv],
                       capture_output=True, text=True, env=env)
    return r.returncode, r.stdout, r.stderr[-400:]


def widen(rows, ls_rows, since_iso, ledger_dir, text, chains, graph, owned, projects, max_rounds):
    """Hole-widening loop. Each round re-runs the coverage audit; each hole class has one widening
    action that ledgers the missing rows, so the next round sees them. Stops when a round widens
    nothing. Returns (history, residual)."""
    history, orphan_done = [], False
    member_set = {m for c in chains.values() for m in c["members"]}
    for n in range(1, max_rounds + 1):
        res = ca.audit(ls_rows, "all", since_iso, ledger_dir, text)
        orphans = [] if orphan_done else [f for f, h in graph["heads"].items() if h.get("entrypoint") == "claude-desktop"
                                         and tc.stem(f) not in owned and f not in member_set
                                         and os.path.getmtime(f) >= tc.parse_ts(since_iso)]
        attached = attach_orphans(orphans, rows, chains, since_iso)
        orphans = [f for f in orphans if f not in attached]
        history.append({"round": n, "test_a": len(res["holes"]), "test_b": len(res["unnamed"]),
                        "orphans": len(orphans), "attached": len(attached)})
        if not (res["holes"] or res["unnamed"] or orphans):
            return history, res
        if res["holes"]:
            write_ledger(ledger_dir, f"children-widened-r{n}.json", "(widened: Test A holes)",
                         [child_ledger.ledger_row(r["sessionId"], rows[r["sessionId"]], projects)
                          for r in res["holes"] if r["sessionId"] in rows])
        if res["unnamed"]:
            write_ledger(ledger_dir, f"children-old-descendants-r{n}.json", "(old descendants: Test B)",
                         [dict(child_ledger.ledger_row(k["sessionId"], rows[k["sessionId"]], projects), manager=t)
                          for t, k in res["unnamed"] if k["sessionId"] in rows], kind="old-descendants")
        if orphans:
            write_ledger(ledger_dir, f"children-orphan-transcripts-r{n}.json", "(orphan transcripts)",
                         [orphan_row(f, graph) for f in orphans], kind="orphan-transcripts")
            orphan_done = True
    return history, ca.audit(ls_rows, "all", since_iso, ledger_dir, text)


def attach_orphans(orphans, rows, chains, since_iso):
    """Weaker heuristic for a desktop transcript with no store row and no parentUuid link: same
    project dir AND same custom title as a session in the window. Returns attached paths."""
    by_key = {}
    for sid, c in chains.items():
        r = rows.get(sid) or {}
        for m in c["members"]:
            by_key.setdefault((os.path.dirname(m), r.get("title")), sid)
    out = []
    for f in orphans:
        title = tc.head_facts(f).get("title")
        sid = by_key.get((os.path.dirname(f), title)) if title else None
        if sid:
            chains[sid]["members"].append(f)
            chains[sid].setdefault("heuristic", []).append(f)
            out.append(f)
    return out


def orphan_row(path, graph):
    h = graph["heads"].get(path) or tc.head_facts(path)
    t = tc.tail_facts(path)
    return {"title": h.get("title") or "(untitled)", "sessionId": "transcript:" + tc.stem(path),
            "lastActivity": tc.iso(t["last_turn_ts"]), "status": None, "lastReport": None,
            "prs": [], "branches": [], "worktree": os.path.basename(os.path.dirname(path)), "transcript": path}


def write_ledger(ledger_dir, name, manager, children, kind="children"):
    with open(os.path.join(ledger_dir, name), "w") as fh:
        json.dump({"manager": manager, "managerSessionId": None, "kind": kind, "children": children}, fh, indent=1)


def prove_chains(mgr_facts, all_files):
    """A manager whose store lastAssistantUuid is in none of its chain files: widen to every
    transcript on disk. Returns {sid: reason} for those still unproven (named unreadable)."""
    unproven = {}
    missing = {m["last_assistant_uuid"]: m for m in mgr_facts if m["verdict"] == "MISSING-TURNS"}
    held = tc.files_holding(set(missing), all_files) if missing else {}
    for u, m in missing.items():
        if held.get(u):
            m["chain"] += [f for f in held[u] if f not in m["chain"]]
            m["verdict"] = "ok (widened to all transcripts)"
        else:
            unproven[m["sid"]] = f"store lastAssistantUuid {u[:8]} is in no transcript on disk"
    for m in mgr_facts:
        if m["verdict"] == "NO-TRANSCRIPT":
            unproven[m["sid"]] = f"no transcript named {m['cli'][:8]} on disk (purged); store row is the only record"
    return unproven


def mine(a):
    now = tc.parse_ts(a.now) if a.now else time.time()
    date = a.date or datetime.datetime.fromtimestamp(now, datetime.timezone.utc).strftime("%Y-%m-%d")
    store, home = a.store or DEFAULT_STORE, a.claude_home or DEFAULT_HOME
    projects, s2c = os.path.join(home, "projects"), os.path.join(home, "sessions-to-chips")
    programs_dir = os.path.join(home, "orchestrator", "programs")
    env = dict(os.environ, S2C_STORE=store, S2C_CLAUDE_HOME=home)
    work = a.work_dir or (tempfile.mkdtemp(prefix="mine-all-") if a.dry_run else os.path.join(s2c, "handoff", f"{date}-mine"))
    ledger_dir, digest_dir = os.path.join(work, "ledger"), os.path.join(work, "digests")
    os.makedirs(ledger_dir, exist_ok=True)

    rows, unreadable, accounts = pf.load_store(store)
    here, here_why = detect_here(rows, a.here, os.environ.get("CLAUDE_SESSION_ID"))
    floor = now - a.window_days * 86400
    active = {s: r for s, r in rows.items() if ts_of(r) >= floor}
    owned = {r.get("cliSessionId") for r in rows.values() if r.get("cliSessionId")}
    pool = tc.candidates(floor, projects)
    chains, graph = tc.resolve({s: tc.files_named(r.get("cliSessionId"), projects) for s, r in active.items()},
                               floor, projects, pool, owned)
    for c in chains.values():
        c["projects"] = projects
    fams = pf.families(rows, pf.load_manifests(programs_dir),
                       {s: [tc.stem(m) for m in c["members"]] for s, c in chains.items()})

    programs = []
    for slug, f in sorted(fams.items()):
        lineage_last = max([ts_of(rows[s]) for s in f["managers"] + f["lineage"]] or [0])
        if lineage_last < floor:
            continue
        mgrs = [manager_facts(rows[s], chains.get(s) or {"members": tc.files_named(rows[s].get("cliSessionId"), projects),
                                                         "pre_window": [], "projects": projects}) for s in f["managers"]]
        cp, cp_src, cp_sid = checkpoint_for(mgrs, here, floor)
        # Live = some unarchived session of the program was active in the window. A program whose
        # whole family is archived is closed: listed, never mined.
        family = [rows[s] for s in f["managers"] + f["lineage"]]
        live = any(not r.get("isArchived") and ts_of(r) >= floor for r in family)
        # Moved = anything the checkpoint manager has not seen: another instance's turn or any
        # lineage session's activity after the checkpoint.
        other = [m["last_turn"] for m in mgrs if m["last_turn"] != cp] + [ts_of(rows[s]) for s in f["lineage"]]
        moved = live and max(other or [0]) > cp + 60
        live_here = sorted((m for m in mgrs if m["acct"] == here and not m["archived"]), key=lambda m: -m["store_last"])
        man = f["manifest"] or {}
        programs.append({"slug": slug, "key": f["key"], "managers": mgrs, "lineage": f["lineage"], "live": live,
                         "checkpoint": cp, "checkpoint_sid": cp_sid, "checkpoint_src": cp_src, "moved": moved, "absorbed_by": man.get("absorbed_by"),
                         "conflict": f["conflict"], "relay_to": live_here[0]["sid"] if live_here else None,
                         "fold": state_fold(slug, programs_dir, lineage_last, man)})

    # One sweep window for every program: from the earliest checkpoint among live programs (a
    # moved one first). Per-program reconcile steps then drop rows their manager already saw.
    cps = ([p["checkpoint"] for p in programs if p["moved"]] or [p["checkpoint"] for p in programs if p["live"]]
           or [now])
    since = max(floor, min(cps))
    since_iso = naive_iso(since)
    sweeps = {}
    for name, argv in (("child_ledger.py", ["--account", "all", "--since", since_iso, "--out", ledger_dir]),
                       ("handoff_sweep.py", ["--account", "all", "--since", since_iso,
                                             "--handoff-dir", os.path.join(s2c, "handoff")])):
        rc, out, err = run_script(name, argv, env)
        sweeps[name] = {"rc": rc, "err": err}
        if name == "handoff_sweep.py" and rc == 0:
            with open(os.path.join(work, "handoff-sweep.json"), "w") as fh:
                fh.write(out)

    all_mgrs = [m for p in programs for m in p["managers"] if m["store_last"] >= since]
    unproven = prove_chains(all_mgrs, sorted(set(pool) | set(tc.candidates(0, projects))) if any(
        m["verdict"] == "MISSING-TURNS" for m in all_mgrs) else pool)
    ls_rows = list_sessions.load_all(store)
    history, residual = widen(rows, ls_rows, since_iso, ledger_dir, ca.named_text(home), chains, graph,
                              owned, projects, a.max_rounds)

    digests = make_digests(programs, since, digest_dir, a.dry_run)
    ctx = {"date": date, "now": now, "here": here, "here_why": here_why, "store": store, "home": home,
           "accounts": accounts, "unreadable": unreadable, "rows": rows, "programs": programs,
           "since": since, "since_iso": since_iso, "floor": floor, "window_days": a.window_days,
           "chains": chains, "pool": pool, "owned": owned, "graph": graph, "sweeps": sweeps,
           "unproven": unproven, "history": history, "residual": residual, "digests": digests,
           "work": work, "ledger_dir": ledger_dir, "s2c": s2c, "dry_run": a.dry_run,
           "named_text": ca.named_text(home)}
    plan = mine_report.build_plan(ctx)
    gates = mine_report.gates(ctx, plan)
    receipt = mine_report.render_receipt(ctx, plan, gates)
    out_dir = work if a.dry_run else os.path.join(s2c, "relay")
    os.makedirs(out_dir, exist_ok=True)
    plan_path = os.path.join(out_dir, f"{date}-mine-plan.json")
    receipt_path = os.path.join(out_dir, f"{date}-completeness-receipt.md")
    plan["receipt"], plan["plan"] = receipt_path, plan_path
    with open(plan_path, "w") as fh:
        json.dump(plan, fh, indent=1)
    with open(receipt_path, "w") as fh:
        fh.write(receipt)
    print(receipt)
    print(f"\nreceipt: {receipt_path}\nplan:    {plan_path}")
    return mine_report.exit_code(gates)


def make_digests(programs, since, digest_dir, dry_run):
    """One mine_session.py digest per chain segment of a moved program's managers with rows after
    the checkpoint (a segment older than `since` has none, by mtime)."""
    out = {}
    for p in programs:
        if not p["moved"]:
            continue
        segs = []
        for m in p["managers"]:
            for f in m["chain"]:
                if os.path.exists(f) and os.path.getmtime(f) >= since and f not in [s["transcript"] for s in segs]:
                    segs.append({"transcript": f, "bytes": os.path.getsize(f), "manager": m["sid"]})
        for s in segs:
            s["digest"] = os.path.join(digest_dir, f"{p['slug']}-{tc.stem(s['transcript'])[:8]}.txt")
            if not dry_run:
                os.makedirs(digest_dir, exist_ok=True)
                with open(s["digest"], "w") as fh:
                    r = subprocess.run([sys.executable, "-I", os.path.join(HERE_DIR, "mine_session.py"), s["transcript"]],
                                       stdout=fh, stderr=subprocess.PIPE, text=True)
                s["rc"] = r.returncode
        out[p["slug"]] = segs
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="write only under a temp work dir; no digests")
    ap.add_argument("--here", help="account dir prefix this session runs on (default: from CLAUDE_SESSION_ID)")
    ap.add_argument("--window-days", type=float, default=14)
    ap.add_argument("--max-rounds", type=int, default=4)
    ap.add_argument("--date")
    ap.add_argument("--now", help=argparse.SUPPRESS)
    ap.add_argument("--store")
    ap.add_argument("--claude-home")
    ap.add_argument("--work-dir")
    ap.add_argument("--gate", metavar="PLAN", help="check the agent steps' artifacts and re-render the receipt")
    a = ap.parse_args()
    sys.exit(mine_report.check_gate(a.gate) if a.gate else mine(a))


if __name__ == "__main__":
    main()
