#!/usr/bin/env python3
"""state_brief.py - the track's state as a short plain-text brief, from the page's own payload (one payload, two
renderings). The manager reads it at every wake and session start in place of re-deriving the program, works the
map from it, updates `## VIEW` and re-renders. Bounded to MAX_LINES; every list says how many it left out.
Rules: ../specs/2026-11-03-manager-state-viewer.md
`wake_lines` adds what changed in the manager's instructions since its last AT-WAKE stamp: the rulings ledger
lines, the instruction-file commits, and whether this session runs on config older than disk. Fails soft and
visibly, never silently.
"""
import datetime as dt
import os
import re
import subprocess

import state_story as story

HERE = os.path.dirname(os.path.realpath(__file__))
LEDGER = os.path.join(os.path.dirname(HERE), "references", "rulings-ledger.md")
CONTRACT = os.path.join(os.path.dirname(HERE), "references", "manager-contract.md")
GLOBAL_RULES = os.path.join(os.path.expanduser("~"), ".claude", "CLAUDE.md")
LEDGER_CAP, LOG_CAP = 14, 6
RULING = re.compile(r"^-\s+(\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?Z)?)\s*\|\s*(.+)$")
MAX_LINES = 60
KIND = {"spec": "Spec", "adr": "ADR", "module": "Module"}
FLAG = {"UNBOUND": "not started", "READY_NOT_DISPATCHED": "ready, not started",
        "STALLED": "stopped moving", "BAKE_OWED": "bake owed", "STALE_OPEN": "landed, still open",
        "DUPLICATE_TITLE": "duplicate title", "PROOF_FAILED": "three or more failed proofs"}


def _clause(text):
    """A sentence used as a clause: no trailing full stop, so joins never read ".;"."""
    return str(text or "").strip().rstrip(".")


def _problem(x):
    """One Problems item in plain words: an engine note's code reads as words, never as an id."""
    m = re.match(r"^engine note: ([a-z_]+)(?::(.*))?$", x.get("detail") or "")
    detail = (m.group(1).replace("_", " ") + (f" ({m.group(2)})" if m.group(2) else "")) if m else x.get("detail") or ""
    return f"{x['source']}: {detail[:80]}"


def _day(iso):
    return str(iso or "")[:10] or "undated"


def _refs(refs):
    return " ".join(r["ref"] if isinstance(r, dict) else str(r) for r in refs or [])


def _section(title, items, more=0, cap=6):
    if not items and not more:
        return []
    lines = [title + ":"] + ["- " + x for x in items[:cap]]
    left = more + max(0, len(items) - cap)
    if left:
        lines.append(f"- +{left} more on the page")
    return lines


def held_text(h):
    k = h.get("kind")
    if k == "waiter":
        return f"{h['waiter']} waits on {h['blocker']}; tell {h['tell']}: {h['message']}"
    if k == "flag":
        return f"{h.get('id')}: {FLAG.get(h.get('flag'), str(h.get('flag')).lower())}"
    if k == "hold":
        return f"{h.get('id')} held ({h.get('reason')}{': ' + h['text'] if h.get('text') else ''})" + \
            ("" if h.get("valid") is not False else f"; the hold is not valid: {h.get('why')}")
    if k == "blocked":
        return f"{h.get('id')} waits on {', '.join(x for x in h.get('by') or [] if x) or 'an unnamed blocker'}"
    if k == "main":
        return f"main health of {h.get('repo')}: {h.get('state')}" + (f" ({h['why']})" if h.get("why") else "")
    if k == "overlap":
        return f"same files as {h.get('name') or h.get('program')} in {h.get('repo')} (advisory)"
    if k == "design":
        return f"design stop on {h.get('what')}: {h.get('stop')}"
    return str(h.get("id") or k)


def open_pr_text(r):
    """`#5113 title: draft` / `: blocked (checks pending)` / `: ready` / `: merge state unknown (why)`."""
    rd = r["readiness"]
    word = {"ready": "ready to merge", "draft": "DRAFT, not ready", "blocked": "blocked"}.get(rd["state"], "merge state unknown")
    return f"#{r.get('pr')} {(r.get('title') or '')[:60]}".rstrip() + f": {word}" + \
        (f" ({_clause(rd['why'])})" if rd.get("why") and rd["state"] != "draft" else "")


def _ticket_states(o):
    return ", ".join(f"{t['id']} {t.get('state') or 'unknown'}" for t in o.get("tickets") or [])


def parse_when(s):
    """`2026-11-04`, `2026-11-04T16:22Z` or `2026-11-04T16:22:00Z` -> aware datetime, else None."""
    m = re.match(r"^(\d{4}-\d{2}-\d{2})(?:T(\d{2}):(\d{2})(?::(\d{2}))?Z)?$", str(s or "").strip())
    if not m:
        return None
    d = dt.datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
    return d.replace(hour=int(m.group(2)), minute=int(m.group(3)), second=int(m.group(4) or 0)) if m.group(2) else d


def _newer(stamp, since):
    """A date-only ruling shows to every wake stamped that day; a timed one is exact."""
    if since is None:
        return True
    when = parse_when(stamp)
    return when > since if "T" in stamp else when.date() >= since.date()


def ruling_lines(since, path=LEDGER):
    """The ledger lines newer than `since` (a datetime, or None for all), capped, with a visible failure line."""
    try:
        with open(path, encoding="utf-8") as fh:
            rows = [m.groups() for m in map(RULING.match, fh.read().splitlines()) if m]
    except OSError as exc:
        return [f"Rulings ledger unreadable: {path} ({exc.strerror or exc}); read it by hand before acting"]
    if not rows:
        return [f"Rulings ledger unreadable: {path} has no dated `- <date> | <rule> | <source>` lines"]
    new = [f"- {d} {rule}" for d, rule in rows if _newer(d, since)]
    if since is None:
        head = f"Rulings in force ({len(rows)}; no AT-WAKE stamp, so all; stamp `## AT-WAKE (<UTC ISO>)` to see only new ones):"
    elif not new:
        return [f"Rulings: none new since {since:%Y-%m-%dT%H:%MZ} ({len(rows)} in force: {path})"]
    else:
        head = f"Rulings new since your last wake {since:%Y-%m-%dT%H:%MZ} ({len(new)} of {len(rows)}):"
    return [head] + new[:LEDGER_CAP] + ([f"- +{len(new) - LEDGER_CAP} more in {path}"] if len(new) > LEDGER_CAP else [])


def instruction_changes(since, files=None, run=subprocess.run):
    """One line per commit to each instruction file since `since` (the last LOG_CAP when None), deduplicated."""
    files = files or (("global", GLOBAL_RULES), ("contract", CONTRACT), ("ledger", LEDGER))
    window = [f"--since={since:%Y-%m-%dT%H:%M:%SZ}"] if since else [f"-n{LOG_CAP}"]
    lines, seen, errors = [], set(), []
    for label, path in files:
        real = os.path.realpath(path)
        try:
            res = run(["git", "-C", os.path.dirname(real), "log", "--oneline", *window, "--", real],
                      capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError) as exc:
            errors.append(f"{label} ({exc})")
            continue
        if res.returncode != 0:
            errors.append(f"{label} ({(res.stderr or '').strip()[:80] or 'git log failed'})")
            continue
        for row in res.stdout.splitlines():
            if row and row.split(" ", 1)[0] not in seen:
                seen.add(row.split(" ", 1)[0])
                lines.append(f"- {label}: {row[:110]}")
    scope = f"since {since:%Y-%m-%dT%H:%MZ}" if since else f"last {LOG_CAP} per file, no AT-WAKE stamp"
    out = [f"Instruction changes ({scope}): " + ("none" if not lines else f"{len(lines)}" + ("; Read the changed files" if since else ""))]
    out += lines[:LOG_CAP] + ([f"- +{len(lines) - LOG_CAP} more"] if len(lines) > LOG_CAP else [])
    return out + ([f"Instruction log unreadable: {'; '.join(errors)}"] if errors else [])


def _session_start(run=subprocess.run):
    """Start time (epoch) of the nearest ancestor Claude CLI process, else None."""
    pid = os.getppid()
    for _ in range(8):
        res = run(["ps", "-o", "ppid=,lstart=,command=", "-p", str(pid)], capture_output=True, text=True, timeout=5)
        m = re.match(r"\s*(\d+)\s+(\w{3} \w{3}\s+\d+ [\d:]+ \d{4})\s+(.*)$", res.stdout or "")
        if not m:
            return None
        if "disclaimer" not in m.group(3) and re.search(r"(^|/)claude(\s|$)", m.group(3)):
            return dt.datetime.strptime(" ".join(m.group(2).split()), "%a %b %d %H:%M:%S %Y").timestamp()
        pid = int(m.group(1))
        if pid <= 1:
            return None
    return None


def freshness_line():
    """config_freshness.py's verdict for THIS session: instruction/settings commits after its CLI started."""
    try:
        import config_freshness as cf
        start = _session_start()
        if start is None:
            return "Config freshness: unknown (no ancestor Claude CLI process; a Codex host or a test run)"
        reread = cf.git_changes(cf.CLAUDE, start, ["CLAUDE.md", "output-styles"])
        reread += cf.git_changes(os.path.dirname(os.path.dirname(cf.KEEL_SKILLS)), start, [".claude/skills"])
        restart = cf.settings_restart_changes(start)
    except (OSError, ImportError, ValueError, subprocess.SubprocessError) as exc:
        return f"Config freshness: unreadable ({exc})"
    since = dt.datetime.fromtimestamp(start).strftime("%Y-%m-%d %H:%M")
    if restart:
        return f"Config freshness: STALE-RESTART since session start {since} ({len(restart)} settings change(s)); end the CLI when idle"
    if reread:
        return f"Config freshness: STALE-REREAD since session start {since} ({len(reread)} commit(s)); Read the changed files"
    return f"Config freshness: FRESH since session start {since}"


def wake_lines(at_wake_at):
    """The block every wake starts with: rulings, instruction commits, config freshness."""
    since = parse_when(at_wake_at)
    return ruling_lines(since) + instruction_changes(since) + [freshness_line()]


def brief(p, wake=None):
    """-> text. Sections in the founder's order: destination, done, architecture, design, decisions, next, holds,
    proof owed, then the keys to update. `wake` (from wake_lines) follows the head lines, outside the MAX_LINES bound."""
    now, st = p.get("now") or {}, p.get("story", {}).get("now") or {}
    stale = p.get("stale") or {}
    head = f"{p.get('name') or p.get('program')} (map {(p.get('map') or {}).get('issue') or 'none'}), state at {p.get('generated_at')}"
    narrative = f"Narrative updated {p.get('updated_at') or 'never'}" + \
        (f"; stale: {', '.join(f'{n} {k}' for k, n in (stale.get('counts') or {}).items()) or 'changes'} since then" if stale.get("stale") else "")
    out = [head, narrative, "", "Destination: " + (p.get("destination") or p.get("goal") or "not written"), ""]
    done = [f"{_day(d.get('date'))} {d['what']}" + (f" ({_refs(d['refs'])})" if d.get("refs") else "") +
            (f" [your claim; proof reaches {story.step_words(d.get('reached'))}]" if d.get("claim") else "")
            for d in st.get("done") or []]
    done += [f"not yet summarized: #{u['pr']} {u.get('title') or ''}".rstrip() if u.get("pr")
             else f"not yet summarized: push {str(u.get('sha') or '')[:10]}" for u in st.get("unsummarized") or []]
    out += _section("Done recently", done, st.get("done_more", 0) + st.get("unsummarized_more", 0), cap=8)
    sysv = now.get("system") or {}
    arch = [a["what"] + (f" ({_refs(a.get('refs'))})" if a.get("refs") else "") for a in st.get("architecture") or []]
    if not (sysv.get("current") or {}).get("views"):
        arch.append(f"no system diagram yet: author {p.get('program')}.arch.json")
    out += _section("Architecture changes", arch, cap=5)
    out += _section("Design changes", [f"{KIND.get(d.get('kind'), 'Change')}: {_clause(d['what'])}" + (f": {_clause(d['meaning'])}" if d.get("meaning") else "") +
                                       (f" ({d['ref']})" if d.get("ref") else "") for d in st.get("design") or []], cap=5)
    out += _section("Decisions in force", [_clause(d["decision"]) + (f"; why: {_clause(d['why'])}" if d.get("why") else "") +
                                           (f"; by {d['by']}" if d.get("by") else "") +
                                           (f"; replaces {d['supersedes']}" if d.get("supersedes") else "")
                                           for d in st.get("decisions") or []], st.get("decisions_more", 0), cap=5)
    out += _section("Learned", [_clause(f["found"]) + (f" ({f['outcome']})" if f.get("outcome") else "") for f in st.get("findings") or []],
                    st.get("findings_more", 0), cap=4)
    out += _section("Next outcomes on the map", [f"{o['outcome']} [{_ticket_states(o) or 'no tickets'}]" for o in now.get("outcomes") or []], cap=6)
    out += _section("Needs the founder", [_clause(q["ask"]) + (f"; recommended: {_clause(q['recommended'])}" if q.get("recommended") else "")
                                          for q in now.get("needs_you") or []], cap=4)
    out += _section("Held by", [held_text(h) for h in now.get("held_by") or []], cap=6)
    out += _section("Proof owed", [f"{r['claim']} ({r.get('ticket') or 'no ticket'}, {r.get('verdict')})" for r in now.get("proof_owed") or []], cap=4)
    out += _section("Open PRs", [open_pr_text(r) for r in (now.get("production") or {}).get("rows") or []
                                 if r.get("readiness")], cap=6)
    c = (now.get("production") or {}).get("counts") or {}
    out += ["Production: " + ", ".join(f"{c.get(k, 0)} {w}" for k, w in (("open", "PR open"), ("merged", "merged"), ("deployed", "deployed"),
                                                                          ("exposed", "live"), ("baked", "baked"))), ""]
    probs = p.get("problems") or []
    out += [f"Problems: {len(probs)}" + (": " + "; ".join(_problem(x) for x in probs[:2]) if probs else ""), ""]
    keys = p.get("author") or []
    footer = ["Update in ## VIEW before ending the turn:"] + (["- " + k for k in keys] if keys else ["- nothing owed"])
    footer += ["Then re-render: render_state.py --program " + str(p.get("program"))]
    lines = _bound(out, footer)
    return "\n".join(lines[:2] + ([""] + list(wake) if wake else []) + lines[2:])


def _bound(body, footer):
    """The footer (the keys to update) always survives; the body is cut to fit."""
    body = [x for i, x in enumerate(body) if x or (i and body[i - 1])]  # no double blank lines
    room = MAX_LINES - len(footer)
    if len(body) > room:
        body = body[:room - 1] + [f"(brief cut at {MAX_LINES} lines; the page has the rest)"]
    return body + footer
