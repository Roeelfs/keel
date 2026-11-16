#!/usr/bin/env python3
"""state_view.py - the authored half of the state page: the file head (the one parser, `read_head`, and the
one writer, `--write-head`), the `## VIEW` block (schema state-view/2) and the manager's other judgment
inputs, read strictly. Every bad input becomes a Problems row with its reason; nothing is dropped silently.
Owners and rules: ../specs/2026-11-03-manager-state-viewer.md, ../specs/2026-11-16-account-switch-gaps.md
(row 10). Top-level imports stay stdlib-only: the Stop guard imports this module under its time budget.

Usage:
  python3 state_view.py --write-head <slug> --since "<what changed since the previous head>"
"""
import argparse
import datetime as dt
import json
import os
import re
import sys

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
TEXT = ("destination",)
DATE_REQUIRED = ("done", "decisions")
# Retired keys stay visible under "not migrated" with their new home until the manager converts them.
V1_HOME = {"explanation": "destination", "next_steps": "outcomes", "upcoming": "outcomes",
           "proven": "the derived Production truth", "unproven": "proof_owed",
           "workstreams": "done (what was delivered) and findings (what was learned)",
           "updated_at": "the file head (moved there: run `state_view.py --write-head`)"}

# ---------- the file head: the first three lines, before the `# ` title ----------
HEAD_KEYS = ("updated_at", "writer", "since-last-session")
HEAD_FORM = {"updated_at": "updated_at: 2026-11-16T13:37:51Z (RFC3339 UTC to the second, with Z)",
             "writer": "writer: local_<uuid> (account <account id>)",
             "since-last-session": "since-last-session: <one line: what changed since the previous head>"}
HEAD_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
HEAD_WRITER = re.compile(r"^(local_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}) \(account ([^()\s]+)\)$")
HEAD_LINE = re.compile(r"^([A-Za-z][A-Za-z_-]*):[ \t]?(.*)$")
WRITE_HEAD = 'python3 state_view.py --write-head <slug> --since "<what changed>"'


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


def read_head(text, now, problems):
    """-> (head, reason). head = {updated_at, writer, account, since} or None. reason: ok | missing (line 1
    is not head-shaped, e.g. the `# ` title) | unparsed (a head is there but malformed). Every non-ok
    reason adds exactly one Problems row naming the line and the expected form."""
    lines = (text or "").split("\n")[:3]
    if not HEAD_LINE.match(lines[0] if lines else ""):
        problems.append(problem("State file", f"no file head: line 1 is {(lines[0] if lines else '')[:60]!r}; "
                                f"the first three lines must be `{HEAD_FORM['updated_at']}`, "
                                f"`{HEAD_FORM['writer']}`, `{HEAD_FORM['since-last-session']}`", f"run `{WRITE_HEAD}`"))
        return None, "missing"
    vals = {}
    for n, key in enumerate(HEAD_KEYS):
        m = HEAD_LINE.match(lines[n]) if n < len(lines) else None
        bad = None
        if not m or m.group(1) != key:
            bad = f"is {(lines[n] if n < len(lines) else '')[:60]!r}"
        else:
            v = m.group(2).strip()
            if key == "updated_at":
                t = dt.datetime.fromisoformat(v.replace("Z", "+00:00")) if HEAD_TIME.match(v) else None
                if t is None:
                    bad = f"has updated_at {v!r}"
                elif now and (t - now).total_seconds() > FUTURE_SLACK_S:
                    bad = f"has updated_at {v} in the future"
            elif key == "writer":
                w = HEAD_WRITER.match(v)
                if not w:
                    bad = f"has writer {v!r} (a full local_<uuid> session id is required)"
                else:
                    vals["account"] = w.group(2)
                    v = w.group(1)
            elif not v:
                bad = "has an empty since-last-session"
            vals[key] = v
        if bad:
            problems.append(problem("State file", f"file head line {n + 1} {bad}; expected `{HEAD_FORM[key]}`",
                                    f"run `{WRITE_HEAD}`"))
            return None, "unparsed"
    return {"updated_at": vals["updated_at"], "writer": vals["writer"], "account": vals["account"],
            "since": vals["since-last-session"]}, "ok"


def head_time(head):
    """-> aware datetime of a parsed head, or None."""
    return dt.datetime.fromisoformat(head["updated_at"].replace("Z", "+00:00")) if head else None


def _row(key, n, row, now, problems):
    required, allowed, enums, dates = LISTS[key]
    where = f"{key}[{n}]"
    if isinstance(row, str):  # a bare line is the row's required field, e.g. "decisions": ["Use one template"]
        row = {required: row}
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
                problems.append(problem("VIEW", f"{where}.{k} must be a list of ids like \"#5073\" or \"TKT-3256\""))
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
    if key in DATE_REQUIRED and "date" not in out and "date_invalid" not in out:
        out["date_missing"] = True
        problems.append(problem("VIEW", f"{where} needs a `date`; it is shown tagged date_missing"))
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


# ---------- the one head writer ----------

def head_lines(writer, account, since, now):
    return [f"updated_at: {now.strftime('%Y-%m-%dT%H:%M:%SZ')}", f"writer: {writer} (account {account})",
            f"since-last-session: {since}"]


def replace_head(text, lines):
    """Rewrite the head in place: drop the leading `key: value` lines (a canonical or ad hoc head), put the
    three head lines there, leave every later byte unchanged. A file opening with its title gets them above it."""
    rows = text.split("\n")
    i = 0
    while i < len(rows) - 1 and HEAD_LINE.match(rows[i]):
        i += 1
    return "\n".join(lines + rows[i:])


def resolve_writer(cli_id, store_rows):
    """-> (local id, account dir) for the one store row whose cliSessionId is cli_id. Raises ValueError."""
    if not cli_id:
        raise ValueError("no CLAUDE_SESSION_ID in the environment")
    hits = [r for r in store_rows.values() if r.get("cliSessionId") == cli_id]
    if len(hits) != 1:
        raise ValueError(f"CLAUDE_SESSION_ID {cli_id[:8]} matches {'no' if not hits else len(hits)} store "
                         f"row{'s' if len(hits) > 1 else ''}")
    return hits[0]["sessionId"], hits[0]["_acct"]


def write_head(path, since, cli_id, store_rows, now):
    """Write the head of `path`. -> the head as read back. Raises ValueError (nothing written) on refusal."""
    if not (since or "").strip() or "\n" in since:
        raise ValueError("--since must be one non-empty line")
    writer, account = resolve_writer(cli_id, store_rows)
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    new = replace_head(text, head_lines(writer, account, since.strip(), now))
    tmp = f"{path}.head.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(new)
    os.replace(tmp, path)
    with open(path, encoding="utf-8") as fh:
        problems = []
        head, reason = read_head(fh.read(), now, problems)
    if reason != "ok":
        raise RuntimeError(f"the written head reads back as {reason}: {problems[0]['detail'] if problems else ''}")
    return head


def main(argv=None):
    ap = argparse.ArgumentParser(description="Write a program state file's head (row 10).")
    ap.add_argument("--write-head", required=True, metavar="SLUG")
    ap.add_argument("--since", required=True)
    a = ap.parse_args(argv)
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    import program_family as pf  # lazy: the guard imports this module and needs only read_head
    import work_state_store as st
    path = os.path.join(st.PROGRAMS, f"{a.write_head}.state.md")
    try:
        if not os.path.isfile(path):
            raise ValueError(f"{path} does not exist")
        if not a.since.strip():
            raise ValueError("--since is empty")
        rows = pf.load_store(pf.STORE)[0]
        head = write_head(path, a.since, os.environ.get("CLAUDE_SESSION_ID"), rows,
                          dt.datetime.now(dt.timezone.utc).replace(microsecond=0))
    except (ValueError, OSError) as exc:
        print(f"write-head refused: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"write-head failed: {exc}", file=sys.stderr)
        return 3
    print(f"head written: {head['updated_at']} by {head['writer']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
