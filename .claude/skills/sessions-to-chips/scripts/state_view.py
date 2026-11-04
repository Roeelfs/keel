#!/usr/bin/env python3
"""state_view.py - the authored half of the state page: the `## VIEW` block (schema state-view/2) and the
manager's other judgment inputs, read strictly. Every bad input becomes a Problems row with its reason;
nothing is dropped silently. Owners and rules: ../specs/2026-11-03-manager-state-viewer.md
"""
import datetime as dt
import json
import re

RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})$")
FUTURE_SLACK_S = 300

# key: (required field, allowed fields, {field: allowed values}, date fields)
LISTS = {
    "outcomes": ("outcome", {"outcome", "tickets"}, {}, ()),
    "needs_you": ("ask", {"ask", "recommended", "grill"}, {}, ()),
    "exposure": ("ref", {"ref", "state", "evidence"}, {"state": ("dark", "live", "n/a")}, ()),
    "proof_owed": ("claim", {"claim", "proof", "org", "runner", "verdict", "ticket"},
                   {"verdict": ("owed", "pass", "fail")}, ()),
    "done": ("what", {"date", "what", "why", "refs"}, {}, ("date",)),
    "architecture": ("what", {"date", "what", "refs"}, {}, ("date",)),
    "design": ("what", {"what", "meaning", "kind", "ref", "tier", "review", "stop", "date"},
               {"kind": ("spec", "adr", "module"), "tier": ("critical", "standard", "light", "none")}, ("date",)),
    "findings": ("found", {"date", "outcome", "found", "refs"}, {}, ("date",)),
    "decisions": ("decision", {"date", "decision", "why", "by", "supersedes"}, {}, ("date",)),
    "dead_ends": ("what", {"date", "what", "why"}, {}, ("date",)),
    "incidents": ("what", {"date", "what", "cause", "fix", "rca"}, {}, ("date",)),
    "skills_done": ("skill", {"skill", "ref", "date"}, {}, ("date",)),
    "adopted": ("note", {"refs", "note"}, {}, ()),
}
LIST_FIELDS = ("tickets", "refs")  # lists of ids; every other field is text
TEXT = ("updated_at", "destination")
# Retired keys stay visible under "not migrated" with their new home until the manager converts them.
V1_HOME = {"explanation": "destination", "next_steps": "outcomes", "upcoming": "outcomes",
           "proven": "the derived Production truth", "unproven": "proof_owed",
           "workstreams": "done (what was delivered) and findings (what was learned)"}


def problem(source, detail, fix=None):
    return {"source": source, "detail": str(detail), "fix": fix}


def check_time(value, where, now, problems):
    """RFC3339 with a time and a zone, not in the future. -> parsed datetime or None."""
    if not isinstance(value, str) or not RFC3339.match(value):
        problems.append(problem("VIEW", f"{where} must be an RFC3339 time like 2026-11-03T16:00:00Z, got {value!r}"))
        return None
    t = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if now and (t - now).total_seconds() > FUTURE_SLACK_S:
        problems.append(problem("VIEW", f"{where} is in the future ({value}); it was not trusted"))
        return None
    return t


def _row(key, n, row, now, problems):
    required, allowed, enums, dates = LISTS[key]
    where = f"{key}[{n}]"
    if not isinstance(row, dict) or not isinstance(row.get(required), str) or not row[required].strip():
        problems.append(problem("VIEW", f"{where} needs a text `{required}`; it was not shown"))
        return None
    extra = sorted(set(row) - allowed)
    if extra:
        problems.append(problem("VIEW", f"{where} has unknown keys {extra}; those keys were not shown"))
    out = {}
    for k in sorted(allowed & set(row)):
        v = row[k]
        if v is None:
            continue
        if k in LIST_FIELDS:
            if not isinstance(v, list) or not all(isinstance(t, str) for t in v):
                problems.append(problem("VIEW", f"{where}.{k} must be a list of ids like \"#5073\" or \"CYN-3256\""))
                continue
            out[k] = v
            continue
        if not isinstance(v, str):
            problems.append(problem("VIEW", f"{where}.{k} must be text, got {type(v).__name__}; it was not shown"))
            continue
        if k in enums and v not in enums[k]:
            problems.append(problem("VIEW", f"{where}.{k} must be one of {', '.join(enums[k])}, got {v!r}"))
            continue
        if k in dates and check_time(v, f"{where}.{k}", now, problems) is None:
            out[k + "_invalid"] = v
            continue
        out[k] = v
    return out


def read_block(text, problems):
    """The last fenced JSON block under the last `## VIEW` heading. -> dict or None."""
    heads = list(re.finditer(r"^##\s+VIEW\b.*$", text, re.M))
    if not heads:
        problems.append(problem("VIEW", "the state file has no ## VIEW block, so the narrative is empty",
                                "add one: references/manager-contract.md, State page"))
        return None
    body = re.split(r"^##\s", text[heads[-1].end():], maxsplit=1, flags=re.M)[0]
    fences = list(re.finditer(r"^```(?:json)?[ \t]*\n(.*?)^```", body, re.M | re.S))
    if not fences:
        problems.append(problem("VIEW", "the ## VIEW block has no fenced JSON"))
        return None
    try:
        raw = json.loads(fences[-1].group(1))
    except ValueError as exc:
        problems.append(problem("VIEW", f"the ## VIEW block is not valid JSON: {exc}"))
        return None
    if not isinstance(raw, dict):
        problems.append(problem("VIEW", f"the ## VIEW block must be an object, got {type(raw).__name__}"))
        return None
    return raw


def read_view(text, now, problems):
    """-> {view, legacy}. `legacy` keeps v1 text visible under "not migrated" until it is converted."""
    raw = read_block(text, problems)
    if raw is None:
        return {"view": {}, "legacy": []}
    view, legacy = {}, []
    for key in sorted(raw):
        if key in V1_HOME:
            legacy.append({"key": key, "home": V1_HOME[key], "text": _legacy_text(raw[key])})
            problems.append(problem("VIEW", f"`{key}` is a retired key; move it to {V1_HOME[key]}",
                                    "edit the ## VIEW block in place"))
        elif key not in LISTS and key not in TEXT:
            problems.append(problem("VIEW", f"unknown key `{key}` was not shown"))
    for key in TEXT:
        if key in raw:
            if isinstance(raw[key], str):
                view[key] = raw[key]
            else:
                problems.append(problem("VIEW", f"`{key}` must be text; it was not shown"))
    if "updated_at" in view and check_time(view["updated_at"], "updated_at", now, problems) is None:
        view["updated_at_invalid"] = view.pop("updated_at")
    for key in LISTS:
        if key not in raw:
            continue
        if not isinstance(raw[key], list):
            problems.append(problem("VIEW", f"`{key}` must be a list; it was not shown"))
            continue
        view[key] = [r for r in (_row(key, n, row, now, problems) for n, row in enumerate(raw[key])) if r]
    for n, r in enumerate(view.get("adopted") or []):
        if not r.get("refs"):
            problems.append(problem("VIEW", f"adopted[{n}] needs `refs`, the PRs it names; it was not shown"))
    if "adopted" in view:
        view["adopted"] = [r for r in view["adopted"] if r.get("refs")]
    return {"view": view, "legacy": legacy}


def _legacy_text(value):
    """v1 rows as plain lines, so unconverted narrative stays readable and is never lost."""
    if isinstance(value, str):
        return [value]
    lines = []
    for row in value if isinstance(value, list) else [value]:
        if isinstance(row, dict):
            lines.append(" · ".join(str(v) for v in row.values() if isinstance(v, (str, int, float)) and str(v).strip()))
        elif row is not None:
            lines.append(str(row))
    return [x for x in lines if x]
