#!/usr/bin/env python3
"""role_brief.py - load a manager's role from disk: the one thing every wake runs first.

Usage:
  role_brief.py --program <slug> [--session <id>]   print the role brief, then record the load
  role_brief.py --version                            {"version", "sources"} of the role on disk
  role_brief.py --status --program <slug> [--session <id>]   {"status", "version", "ack", "delta"}; writes nothing
  role_brief.py --check-staged                       pre-commit: refuse a staged role.md change with no `## Changes` line

The brief (about 90 lines plus the context brief): a header with the role version and the version this
manager last loaded, health lines (keel checkout behind origin, overlay ledger missing, state page older than
its state file), the changes since that load as rule text, the role card, the rulings in force, the wake steps
with a ready-to-paste wake prompt, then the `render_state.py --context` brief built from the same payload.

The ROLE VERSION is the first 8 hex of sha256 over the declared role sources (role.md, the public rulings ledger,
the overlay rulings ledger, the overlay role notes). It is computed, never bumped. This script is the one owner
of it: the Stop guard and the prompt hooks import `role_version` and `ack_status` from here.

The LOAD RECORD `<programs>/<slug>.role.json` = {version, sources, loaded_at, session_id, degraded} is written
only here, after the brief prints, even when part of the brief failed (`degraded: true`), so a broken source
never leaves a manager in an impossible block. Never hand-edit it. Rules: ../references/role.md.
Module-level imports stay stdlib-only: the Stop guard imports this file under a 2 s budget.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
SKILL = os.path.dirname(HERE)
ROLE = os.path.join(SKILL, "references", "role.md")
PUBLIC_LEDGER = os.path.join(SKILL, "references", "rulings-ledger.md")
CHANGE = re.compile(r"^-\s+(\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?Z)?)\s*\|\s*(.+)$")
FIRST_LOAD_CHANGES = 10
DELTA_CAP = 12
ROLE_LABELS = ("role", "overlay")  # sources whose `## Changes` lines are role changes; the ledgers carry rulings


def overlay_dir():
    return os.environ.get("MANAGER_ROLE_OVERLAY") or os.path.join(
        os.path.expanduser("~"), ".claude", "skills-overlay", "sessions-to-chips")


def programs_dir():
    return os.environ.get("WORK_STATE_PROGRAMS") or os.path.join(os.path.expanduser("~"), ".claude", "orchestrator",
                                                                 "programs")


def role_sources():
    """[(label, path)] in hash order. The overlay entries may be absent; an absent file hashes as `absent`."""
    ov = overlay_dir()
    return [("role", ROLE), ("ledger", PUBLIC_LEDGER),
            ("rulings", os.path.join(ov, "rulings-ledger.md")), ("overlay", os.path.join(ov, "role-overlay.md"))]


def _read(path):
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def role_version(sources=None):
    """-> (version, {label: sha12 | "absent"}). Pure over the files' bytes."""
    total, shas = hashlib.sha256(), {}
    for label, path in sources or role_sources():
        data = _read(path)
        shas[label] = hashlib.sha256(data).hexdigest()[:12] if data is not None else "absent"
        total.update(f"{label}\0{shas[label]}\n".encode())
    return total.hexdigest()[:8], shas


# ---------- the load record ----------

def ack_path(slug, programs=None):
    return os.path.join(programs or programs_dir(), f"{slug}.role.json")


def read_ack(slug, programs=None):
    try:
        with open(ack_path(slug, programs), encoding="utf-8") as fh:
            ack = json.load(fh)
        return ack if isinstance(ack, dict) else None
    except (OSError, ValueError):
        return None


def write_ack(slug, version, shas, session, degraded, now, programs=None):
    path = ack_path(slug, programs)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"version": version, "sources": shas, "loaded_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                   "session_id": session or None, "degraded": bool(degraded)}, fh)
    os.replace(tmp, path)
    return path


def parse_when(s):
    """`2026-11-04`, `2026-11-04T16:22Z` or `2026-11-04T16:22:00Z` / `...:00.123Z` -> aware datetime, else None."""
    s = str(s or "").strip()
    m = re.match(r"^(\d{4}-\d{2}-\d{2})(?:T(\d{2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?(?:Z|\+00:00))?$", s)
    if not m:
        return None
    d = dt.datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
    return d.replace(hour=int(m.group(2)), minute=int(m.group(3)), second=int(m.group(4) or 0)) if m.group(2) else d


def ack_status(ack, version, session=None, compacted_at=None):
    """-> current | missing | changed | new_session | compacted. Pure.
    `session`: the asking session's id; an ack written by another session is not this session's load (a fresh
    start or an account switch). An ack with no session id (a Codex host) is not held to one.
    `compacted_at`: the newest compaction boundary of this session; a load before it is lost context."""
    if not ack:
        return "missing"
    if ack.get("version") != version:
        return "changed"
    if session and ack.get("session_id") and ack["session_id"] != session:
        return "new_session"
    loaded = parse_when(ack.get("loaded_at"))
    if compacted_at and (loaded is None or loaded < compacted_at):
        return "compacted"
    return "current"


# ---------- changes and rulings ----------

def _section(text, name):
    """The body of `## <name>` up to the next `## ` heading."""
    m = re.search(rf"^##\s+{re.escape(name)}\s*$(.*?)(?=^##\s|\Z)", text, re.M | re.S)
    return m.group(1).strip("\n") if m else ""


def _text(path):
    data = _read(path)
    return data.decode("utf-8", "replace") if data is not None else None


def _newer(stamp, since):
    """A date-only line shows to every load stamped that day; a timed one is exact (the rulings-ledger rule)."""
    if since is None:
        return True
    when = parse_when(stamp)
    if when is None:
        return False
    return when > since if "T" in stamp else when.date() >= since.date()


def change_rows(sources=None):
    """[(stamp, kind, text)] from the role files' `## Changes` sections and the ledgers' `## Rulings` lines."""
    rows = []
    for label, path in sources or role_sources():
        text = _text(path)
        if text is None:
            continue
        body = _section(text, "Changes") if label in ROLE_LABELS else _section(text, "Rulings")
        kind = "role" if label in ROLE_LABELS else "ruling"
        rows += [(m.group(1), kind, m.group(2).strip()) for m in map(CHANGE.match, body.splitlines()) if m]
    return rows


def delta_lines(since, sources=None, cap=DELTA_CAP, kinds=("role", "ruling")):
    """The changes newer than `since` (None: the newest FIRST_LOAD_CHANGES), newest first, as `- <date> [kind] text`."""
    rows = [r for r in change_rows(sources) if r[1] in kinds]
    keyed = sorted(rows, key=lambda r: (parse_when(r[0]) or dt.datetime.min.replace(tzinfo=dt.timezone.utc)),
                   reverse=True)
    new = [r for r in keyed if _newer(r[0], since)] if since else keyed[:FIRST_LOAD_CHANGES]
    out = [f"- {d} [{k}] {t}" for d, k, t in new[:cap]]
    return out + ([f"- +{len(new) - cap} more: read {ROLE} and the overlay"] if len(new) > cap else [])


# ---------- health ----------

def keel_behind(run=subprocess.run, path=SKILL):
    """-> (n commits behind the upstream as last fetched, or None, detail). No network."""
    try:
        top = run(["git", "-C", path, "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=5)
        if top.returncode != 0:
            return None, "not a git checkout"
        res = run(["git", "-C", top.stdout.strip(), "rev-list", "--count", "HEAD..@{u}"],
                  capture_output=True, text=True, timeout=5)
        if res.returncode != 0:
            return None, (res.stderr or "no upstream").strip()[:80]
        return int(res.stdout.strip() or 0), top.stdout.strip()
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return None, str(exc)[:80]


def health_lines(slug, programs=None, run=subprocess.run):
    out = []
    n, detail = keel_behind(run)
    if n:
        out.append(f"!!! KEEL CHECKOUT BEHIND ORIGIN BY {n} COMMIT(S) ({detail}): the role on disk is not the pushed "
                   f"one. The Harness manager runs `git -C {detail} pull --ff-only`; everyone else reports it once.")
    elif n is None:
        out.append(f"Keel freshness unknown ({detail}).")
    rulings = dict(role_sources())["rulings"]
    if not os.path.isfile(rulings):
        out.append(f"!!! Overlay rulings ledger missing: {rulings}. No private ruling reaches you; tell the Harness manager.")
    base = os.path.join(programs or programs_dir(), slug)
    try:
        md, html = os.path.getmtime(base + ".state.md"), os.path.getmtime(base + ".state.html")
        if html < md:
            out.append(f"State page stale: {slug}.state.md is newer than {slug}.state.html; re-render this turn "
                       f"(render_state.py --program {slug}).")
    except OSError:
        if os.path.isfile(base + ".state.md"):
            out.append(f"State page never rendered: run render_state.py --program {slug} this turn.")
    return out


# ---------- the brief ----------

def context_brief(slug, since, now, run=subprocess.run):
    """The render_state --context brief from the same payload; its wake block carries instruction commits and
    config freshness only, because this brief prints the rulings itself. -> (text, degraded)."""
    try:
        sys.path.insert(0, HERE)
        import render_state
        import state_brief
        payload, _ = render_state.build_payload(slug, now, run)
        wake = state_brief.instruction_changes(since) + [state_brief.freshness_line()]
        return state_brief.brief(payload, wake=wake), False
    except Exception as exc:  # a broken brief degrades the load; it never blocks it
        return (f"Context brief unavailable ({type(exc).__name__}: {str(exc)[:120]}); run "
                f"`render_state.py --program {slug} --context` by hand."), True


def rulings_block(since):
    try:
        sys.path.insert(0, HERE)
        import state_brief
        return state_brief.ruling_lines(since), False
    except Exception as exc:
        return [f"Rulings unreadable ({type(exc).__name__}); read {PUBLIC_LEDGER} and the overlay ledger."], True


def overlay_card():
    text = _text(dict(role_sources())["overlay"])
    return _section(text, "Role card") if text else ""


def brief(slug, session, now, programs=None, run=subprocess.run):
    """-> (text, version, shas, degraded). Writes nothing."""
    version, shas = role_version()
    ack = read_ack(slug, programs)
    since = parse_when((ack or {}).get("loaded_at")) if ack and ack.get("session_id") in (None, session) else None
    role_text = _text(ROLE)
    degraded = role_text is None
    last = (f"you last loaded v{ack.get('version')} at {ack.get('loaded_at')}" if ack and since
            else "first load in this session")
    out = [f"Manager role v{version} for {slug}, loaded {now:%Y-%m-%dT%H:%M:%SZ} ({last}).",
           "Read top to bottom and do the wake steps in order."]
    out += health_lines(slug, programs, run)
    changes = delta_lines(since, kinds=("role",))  # rulings print in their own block below
    out += ["", f"Changes since your last load ({'all recent' if since is None else len(changes)}):"] + (changes or ["- none"])
    card = _section(role_text, "Role card") if role_text else f"ROLE CARD UNREADABLE: {ROLE}"
    ov = overlay_card()
    out += ["", "Role card:", card] + (["", "This machine's role notes:", ov] if ov else [])
    rulings, bad = rulings_block(since)
    out += [""] + rulings
    steps = _section(role_text, "Wake steps") if role_text else ""
    out += ["", "Wake steps:", steps or f"WAKE STEPS UNREADABLE: {ROLE}",
            "", f"Wake prompt (paste as is): /manager-role {slug} -- on fire: <the one action>",
            f"AT-WAKE line: Role: v{version}"]
    ctx, bad_ctx = context_brief(slug, since, now, run)
    out += ["", "----- context brief -----", ctx]
    return "\n".join(out), version, shas, degraded or bad or bad_ctx


# ---------- pre-commit ----------

def staged_role_change_ok(diff_text):
    """A staged diff of role.md passes when it adds a dated `## Changes` line (or touches nothing)."""
    added = [ln[1:] for ln in diff_text.splitlines() if ln.startswith("+") and not ln.startswith("+++")]
    removed = [ln for ln in diff_text.splitlines() if ln.startswith("-") and not ln.startswith("---")]
    if not added and not removed:
        return True
    return any(CHANGE.match(ln.strip()) for ln in added)


def check_staged(run=subprocess.run):
    top = run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if top.returncode != 0:
        return 0
    rel = ".claude/skills/sessions-to-chips/references/role.md"
    diff = run(["git", "-C", top.stdout.strip(), "diff", "--cached", "-U0", "--", rel], capture_output=True, text=True)
    if staged_role_change_ok(diff.stdout or ""):
        return 0
    print(f"role-check: {rel} changed with no new `## Changes` line. Append "
          "`- <YYYY-MM-DD> | <the rule as it now reads>` under `## Changes` so every manager is told.", file=sys.stderr)
    return 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--program")
    ap.add_argument("--session", default=os.environ.get("CLAUDE_SESSION_ID") or "")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--version", action="store_true")
    mode.add_argument("--status", action="store_true")
    mode.add_argument("--check-staged", action="store_true")
    args = ap.parse_args(argv)
    if args.version:
        version, shas = role_version()
        print(json.dumps({"version": version, "sources": shas}))
        return 0
    if args.check_staged:
        return check_staged()
    if not args.program:
        ap.error("--program <slug> is required")
    now = dt.datetime.now(dt.timezone.utc)
    if args.status:
        version, _ = role_version()
        ack = read_ack(args.program)
        st = ack_status(ack, version, args.session or None)
        since = parse_when((ack or {}).get("loaded_at")) if st not in ("missing", "new_session") else None
        print(json.dumps({"status": st, "version": version, "ack": ack,
                          "delta": [] if st == "current" else delta_lines(since)}))
        return 0
    text, version, shas, degraded = brief(args.program, args.session, now)
    print(text)
    try:
        path = write_ack(args.program, version, shas, args.session, degraded, now)
        print(f"\nRole v{version} recorded in {path}" + (" (degraded: part of the brief failed)" if degraded else ""))
    except OSError as exc:
        print(f"\nRole load NOT recorded ({exc}); the Stop guard will ask again.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
