#!/usr/bin/env python3
"""state_brief.py - the track's state as a short plain-text brief, from the page's own payload (one payload, two
renderings). The manager reads it at every wake and session start in place of re-deriving the program, works the
map from it, updates `## VIEW` and re-renders. Bounded to MAX_LINES; every list says how many it left out.
Rules: ../specs/2026-11-03-manager-state-viewer.md
"""
import re

import state_story as story

MAX_LINES = 60
KIND = {"spec": "Spec", "adr": "ADR", "module": "Module"}
FLAG = {"UNBOUND": "not started", "READY_NOT_DISPATCHED": "ready, not started",
        "STALLED": "stopped moving", "BAKE_OWED": "bake owed", "STALE_OPEN": "landed, still open",
        "DUPLICATE_TITLE": "duplicate title"}


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


def brief(p):
    """-> text. Sections in the founder's order: destination, done, architecture, design, decisions, next, holds,
    proof owed, then the keys to update."""
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
    return "\n".join(_bound(out, footer))


def _bound(body, footer):
    """The footer (the keys to update) always survives; the body is cut to fit."""
    body = [x for i, x in enumerate(body) if x or (i and body[i - 1])]  # no double blank lines
    room = MAX_LINES - len(footer)
    if len(body) > room:
        body = body[:room - 1] + [f"(brief cut at {MAX_LINES} lines; the page has the rest)"]
    return body + footer
