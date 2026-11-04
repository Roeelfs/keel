#!/usr/bin/env python3
"""state_story.py - the work, told as outcomes: what was done, what changed in the architecture and the design,
the decisions in force, what was learned. The manager writes one line per item in `## VIEW`; this module joins
each line to the derived proof of the PRs it names, so a line that asserts a live or proven state the proof does
not reach reads as the manager's claim. Merged work no line names is listed as not yet summarized.
Pure functions over the payload's own rows. Rules: ../specs/2026-11-03-manager-state-viewer.md
"""
import datetime as dt
import re

RECENT_DAYS = 7
NOW_MAX = 6
STEP_RANK = {"open": 0, "merged": 1, "deployed": 2, "exposed": 3, "baked": 4}
STEP_WORDS = {"open": "PR open", "merged": "merged", "deployed": "deployed", "exposed": "live", "baked": "bake passed"}
# Words a summary may use only when the derived proof reaches the step they assert.
CLAIMS = ((re.compile(r"\b(baked|proven|bake passed)\b", re.I), "baked"),
          (re.compile(r"\b(live|in production|in prod|rolled out|turned on)\b", re.I), "exposed"),
          (re.compile(r"\b(deployed|reached prod|shipped to prod)\b", re.I), "deployed"))
PR_REF = re.compile(r"^#?(\d+)$")


def _ts(iso):
    try:
        return dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00")) if iso else None
    except ValueError:
        return None


def _pr_number(ref):
    m = PR_REF.match(str(ref).strip())
    return int(m.group(1)) if m else None


def asserted_step(text):
    """The furthest ladder step a sentence asserts, or None."""
    for rx, step in CLAIMS:
        if rx.search(text or ""):
            return step
    return None


def proven_step(ladder):
    """The ladder step as the page may say it: an `n/a` exposure has nothing to be live, so it reads as deployed."""
    step = (ladder or {}).get("step")
    exposure = ((ladder or {}).get("steps") or {}).get("exposure") or {}
    return "deployed" if step == "exposed" and exposure.get("state") == "n/a" else step


def _ref_rows(refs, by_pr):
    out = []
    for ref in refs or []:
        n = _pr_number(ref)
        row = by_pr.get(n) if n is not None else None
        out.append({"ref": f"#{n}" if n is not None else ref, "pr": n, "repo": (row or {}).get("repo"),
                    "step": proven_step(row["ladder"]) if row else None})
    return out


def done_rows(view, change_rows):
    """VIEW `done` joined to derived proof, newest first. `claim` marks a line asserting more than its proof."""
    by_pr = {r["pr"]: r for r in change_rows if r.get("pr")}
    rows = []
    for d in view.get("done") or []:
        refs = _ref_rows(d.get("refs"), by_pr)
        steps = [r["step"] for r in refs if r["step"] in STEP_RANK]
        reached = max(steps, key=STEP_RANK.get) if steps else None
        wants = asserted_step(d["what"])
        claim = bool(wants) and (reached is None or STEP_RANK[reached] < STEP_RANK[wants])
        rows.append(dict(d, refs=refs, reached=reached, claim=claim, asserts=wants))
    return sorted(rows, key=lambda r: r.get("date") or "", reverse=True)


def unsummarized(view, change_rows, publications):
    """Merged PRs and direct pushes that no `done`, `architecture` or `design` line names, newest first: shown by
    title, marked as not yet summarized, and listed in the `author` line. An `adopted` ref came with a ticket this
    program took over, delivered by another program: it is never asked for, and never counts as this one's work."""
    refs = [str(r).strip() for k in ("done", "architecture", "adopted") for d in view.get(k) or [] for r in d.get("refs") or []]
    refs += [str(d["ref"]).strip() for d in view.get("design") or [] if d.get("ref")]  # a spec PR summarized as design
    named_prs = {n for n in map(_pr_number, refs) if n is not None}

    def named_sha(sha):
        return bool(sha) and any(len(r) >= 7 and str(sha).startswith(r) for r in refs)

    out = []
    for r in change_rows:
        if r.get("merged_at") and r.get("pr") and r["pr"] not in named_prs:
            out.append({"pr": r["pr"], "repo": r["repo"], "title": r.get("title"), "at": r["merged_at"],
                        "step": r["ladder"]["step"], "tickets": r.get("tickets") or []})
    on_ladder = {(r["repo"], r.get("pr")) for r in change_rows if r.get("pr")}
    for p in publications:
        if (p.get("repo"), p.get("pr")) in on_ladder or p.get("pr") in named_prs or named_sha(p.get("sha")):
            continue
        out.append({"pr": p.get("pr"), "sha": p.get("sha"), "repo": p.get("repo"), "title": p.get("artifact") or p.get("note"),
                    "at": p.get("at"), "step": None, "tickets": [p["ticket"]] if p.get("ticket") else []})
    return sorted(out, key=lambda r: r.get("at") or "", reverse=True)


def recent(rows, now, key="date"):
    """Rows for Now: the last RECENT_DAYS, at most NOW_MAX; with none that recent, the newest few."""
    cutoff = now - dt.timedelta(days=RECENT_DAYS)
    fresh = [r for r in rows if (_ts(r.get(key)) or cutoff) > cutoff]
    picked = (fresh or rows[:3])[:NOW_MAX]
    return picked, len(rows) - len(picked)


def story(view, change_rows, publications, decisions, now):
    """-> {now: {...}, history: {...}}: the sections that read as the work, in the founder's order."""
    done = done_rows(view, change_rows)
    pending = unsummarized(view, change_rows, publications)
    by_pr = {r["pr"]: r for r in change_rows if r.get("pr")}
    arch = sorted((dict(a, refs=_ref_rows(a.get("refs"), by_pr)) for a in view.get("architecture") or []),
                  key=lambda r: r.get("date") or "", reverse=True)
    design = view.get("design") or []
    adopted = [dict(a, refs=_ref_rows(a.get("refs"), by_pr)) for a in view.get("adopted") or []]
    decisions = sorted(decisions, key=lambda d: d.get("date") or "", reverse=True)
    findings = sorted((dict(f, refs=_ref_rows(f.get("refs"), by_pr)) for f in view.get("findings") or []),
                      key=lambda r: r.get("date") or "", reverse=True)
    now_done, done_more = recent(done, now)
    now_pending, pending_more = recent(pending, now, key="at")
    now_dec, dec_more = recent(decisions, now)
    now_found, found_more = recent(findings, now)
    return {
        "now": {"done": now_done, "done_more": done_more, "unsummarized": now_pending, "unsummarized_more": pending_more,
                "architecture": arch[:NOW_MAX], "design": design, "decisions": now_dec, "decisions_more": dec_more,
                "findings": now_found, "findings_more": found_more},
        "history": {"done": done, "unsummarized": pending, "architecture": arch, "design": design, "findings": findings,
                    "adopted": adopted},
    }


def step_words(step):
    return STEP_WORDS.get(step or "", "not read")
