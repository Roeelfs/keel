#!/usr/bin/env python3
"""claude-sessions — survey live Claude Code sessions and extract recent state.

Reuses warp-snapshot's live-PID detection: ~/.claude/sessions/<PID>.json filtered
by alive PID + interactive kind. For each live session, walks the JSONL transcript
and extracts: last user message, last assistant text, latest TodoWrite payload.

Usage:
    python3 sessions.py                # list live sessions (table)
    python3 sessions.py --filter myproject # filter by cwd substring
    python3 sessions.py --survey       # full state dump for each session
    python3 sessions.py --survey --sid <uuid>  # one session only
    python3 sessions.py --survey --json        # machine-readable
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

HOME = Path.home()
SESSIONS_DIR = HOME / ".claude" / "sessions"
PROJECTS_DIR = HOME / ".claude" / "projects"
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _jsonl_age_seconds(path: Path | None) -> float | None:
    """Seconds since the JSONL was last written. None if path missing.

    This is a more reliable activity signal than last-message timestamp:
    a session running a long bash or waiting on an agent dispatch writes
    NOTHING to the JSONL until the tool returns. Last-message TS goes stale,
    but mtime tracks the file itself and updates on every line written
    (tool_use frames, tool_result frames, etc.)."""
    if path is None:
        return None
    try:
        import time
        return time.time() - path.stat().st_mtime
    except OSError:
        return None


def _child_proc_count(pid: int) -> int:
    """Count of live immediate child processes of `pid`. A non-zero count
    means the session is actively running a tool (bash, agent, MCP call,
    git, npm, etc.) right now — even if its JSONL hasn't been written to
    in minutes. Use this as the second activity signal alongside JSONL mtime."""
    if pid <= 0:
        return 0
    try:
        import subprocess
        r = subprocess.run(
            ["pgrep", "-P", str(pid)],
            capture_output=True, text=True, timeout=2,
        )
        if r.returncode != 0:
            return 0
        return sum(1 for line in r.stdout.splitlines() if line.strip().isdigit())
    except (OSError, subprocess.SubprocessError):
        return 0


def _activity_status(jsonl_age: float | None, child_procs: int) -> str:
    """Combine the two signals into a single label.

    - ACTIVE: writing to JSONL right now OR has child processes running
    - WARM:   JSONL touched in the last 30 min, no children → between turns
    - IDLE:   nothing for 30+ min, no children → likely waiting on user
    """
    if child_procs > 0:
        return "ACTIVE"
    if jsonl_age is None:
        return "?"
    if jsonl_age < 120:
        return "ACTIVE"
    if jsonl_age < 1800:
        return "WARM"
    return "IDLE"


def _fmt_age(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds / 60)}m"
    if seconds < 86400:
        return f"{seconds / 3600:.1f}h"
    return f"{int(seconds / 86400)}d"


def find_session_jsonl(sid: str) -> Path | None:
    if not PROJECTS_DIR.exists():
        return None
    for d in PROJECTS_DIR.iterdir():
        if not d.is_dir():
            continue
        candidate = d / f"{sid}.jsonl"
        if candidate.exists():
            return candidate
    return None


def get_live_sessions(filter_str: str | None = None) -> list[dict]:
    out: list[dict] = []
    if not SESSIONS_DIR.exists():
        return out
    for f in sorted(SESSIONS_DIR.glob("*.json")):
        try:
            d = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        pid = d.get("pid")
        if not isinstance(pid, int) or not pid_alive(pid):
            continue
        if d.get("kind") != "interactive":
            continue
        sid = d.get("sessionId") or ""
        cwd = d.get("cwd") or ""
        if not UUID_RE.match(sid) or not cwd.startswith("/"):
            continue
        if filter_str and filter_str.lower() not in cwd.lower():
            continue
        out.append({
            "pid": pid,
            "sid": sid,
            "cwd": cwd,
            "name": d.get("name") or "",
            "started_at": d.get("startedAt", 0),
        })
    seen: dict[str, dict] = {}
    for s in sorted(out, key=lambda x: x["started_at"]):
        seen.setdefault(s["sid"], s)
    return sorted(seen.values(), key=lambda x: (x["cwd"], x["started_at"]))


def _extract_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for c in content:
            if isinstance(c, dict) and c.get("type") == "text":
                return c.get("text", "")
    return ""


def _extract_tool_uses(content) -> list[tuple[str, dict]]:
    """Return ALL tool_use frames in this content (not just the first)."""
    out: list[tuple[str, dict]] = []
    if not isinstance(content, list):
        return out
    for c in content:
        if isinstance(c, dict) and c.get("type") == "tool_use":
            name = c.get("name") or "?"
            inp = c.get("input") if isinstance(c.get("input"), dict) else {}
            out.append((name, inp))
    return out


def _summarize_tool_use(name: str, inp: dict, max_len: int = 140) -> str:
    """One-line summary of a tool_use suitable for survey output."""
    if not isinstance(inp, dict):
        return f"{name}"
    if name == "Bash":
        cmd = inp.get("command") or ""
        cmd = " ".join(cmd.split())  # collapse newlines/whitespace
        return f"Bash: {cmd[:max_len]}"
    if name in ("Read", "Edit", "Write"):
        return f"{name}: {inp.get('file_path', '?')}"
    if name == "TodoWrite":
        todos = inp.get("todos") or []
        n_done = sum(1 for t in todos if isinstance(t, dict) and t.get("status") == "completed")
        return f"TodoWrite: {len(todos)} todos ({n_done} done)"
    if name == "TaskCreate":
        return f"TaskCreate: {inp.get('subject', '?')}"
    if name == "TaskUpdate":
        return f"TaskUpdate: id={inp.get('taskId', '?')} status={inp.get('status', '?')}"
    if name == "Skill":
        return f"Skill: {inp.get('skill', '?')}"
    if name == "Agent":
        return f"Agent[{inp.get('subagent_type', 'general')}]: {inp.get('description', '?')}"
    if name == "WebFetch":
        return f"WebFetch: {inp.get('url', '?')[:max_len]}"
    if name.startswith("mcp__"):
        return f"{name}"
    # Fallback: name + first key/value pair
    keys = list(inp.keys())
    if keys:
        v = str(inp[keys[0]])[:60]
        return f"{name}: {keys[0]}={v}"
    return name


def _git_commits_for_session(cwd: str, sid: str, days: int = 7) -> list[str]:
    """Return short-format commits authored in the last N days that include
    `Session-Id: <sid>` in the trailer. Empty list on any failure."""
    import subprocess
    if not cwd or not Path(cwd).is_dir() or not (Path(cwd) / ".git").exists():
        return []
    try:
        # --all so worktrees on feature branches are included
        result = subprocess.run(
            ["git", "log", "--all", f"--since={days}.days.ago",
             f"--grep=Session-Id: {sid}", "--oneline", "-30"],
            cwd=cwd, capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return []
        return [line for line in result.stdout.splitlines() if line.strip()]
    except (OSError, subprocess.SubprocessError):
        return []


_SID_RE = re.compile(r"^Session-Id:\s*([a-zA-Z0-9-]+)\s*$", re.MULTILINE)


def _first_user_text(path: Path, max_lines: int = 80) -> str:
    """Read the first non-system user message from a session JSONL, early-exit.
    For paste-spawned sessions the first user message defines the session's
    purpose (e.g. 'Goal: ship the sharing API ...') even when the NAME field
    is generic or wrong (auto-generated 'hose', 'add-deps-stage-4b', etc.)."""
    try:
        with path.open() as fh:
            for i, line in enumerate(fh):
                if i > max_lines:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("type") != "user":
                    continue
                msg = d.get("message") if isinstance(d.get("message"), dict) else None
                if not msg or msg.get("role") != "user":
                    continue
                txt = _extract_text(msg.get("content"))
                if not txt:
                    continue
                # Skip wrapped tool-result / system-reminder / caveat noise
                head = txt[:200]
                if txt.startswith("<") or txt.startswith("Caveat") or "<system-reminder>" in head:
                    continue
                return txt
    except OSError:
        pass
    return ""


_GOAL_RE = re.compile(r"\bGoal\s*:\s*([^\n.]{10,200})", re.IGNORECASE)
_SHIP_RE = re.compile(r"\b(ship|implement|fix|build)\s+([^.\n]{10,150})", re.IGNORECASE)


def _purpose_hint(text: str, max_len: int = 90) -> str:
    """Extract a short purpose hint from a session's first user message.
    Hierarchy: 'Goal: …' phrase → 'ship/implement/fix/build …' verb → first sentence.
    A typical worktree-handoff prompt ('You are continuing the work in a new
    worktree. Goal: ship feature X — …') puts the meaningful goal mid-line, so a
    line-start match isn't enough — search anywhere."""
    if not text:
        return ""
    m = _GOAL_RE.search(text)
    if m:
        hint = m.group(1).strip()
        return hint[:max_len]
    m = _SHIP_RE.search(text)
    if m:
        hint = (m.group(1) + " " + m.group(2)).strip()
        return hint[:max_len]
    first = text.strip().split(". ", 1)[0].strip()
    return first[:max_len]


def _recent_main_commits(cwd: str, days: int = 2, limit: int = 25) -> list[dict]:
    """Recent commits visible from main + origin/main with Session-Id attribution
    and push status. Cross-session view: shows what landed regardless of which
    live session authored it. Catches commits with mismatched/manually-pasted
    Session-Id trailers and orphan commits from dead sessions.

    Uses regex on the full commit body rather than git's %(trailers:...) format,
    because git only recognizes the LAST trailer block and rejects any trailer
    separated from later trailers by a blank line (e.g. Session-Id followed by
    a blank line then Co-Authored-By appears trailer-less to git)."""
    import subprocess
    if not cwd or not Path(cwd).is_dir() or not (Path(cwd) / ".git").exists():
        return []
    try:
        # Use \x1f (unit separator) as a NUL-safe delimiter between fields,
        # and \x1e (record separator) between commits.
        FIELD = "\x1f"
        RECORD = "\x1e"
        fmt = f"%H{FIELD}%h{FIELD}%s{FIELD}%B{RECORD}"
        result = subprocess.run(
            ["git", "log", "main", "origin/main",
             f"--since={days}.days.ago",
             f"--pretty=format:{fmt}",
             "--no-merges", f"-{limit}"],
            cwd=cwd, capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return []
        origin_main_sha = subprocess.run(
            ["git", "rev-parse", "origin/main"],
            cwd=cwd, capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        reachable = subprocess.run(
            ["git", "rev-list", origin_main_sha],
            cwd=cwd, capture_output=True, text=True, timeout=10,
        )
        origin_set = set(reachable.stdout.split()) if reachable.returncode == 0 else set()
        commits, seen = [], set()
        for record in result.stdout.split(RECORD):
            record = record.lstrip()  # git inserts \n between records
            if not record:
                continue
            parts = record.split(FIELD, 3)
            if len(parts) < 4:
                continue
            full_sha, short_sha, subject, body = parts
            if full_sha in seen:
                continue
            seen.add(full_sha)
            m = _SID_RE.search(body)
            sid = m.group(1) if m else None
            commits.append({
                "sha": short_sha,
                "subject": subject.strip(),
                "sid": sid,
                "pushed": full_sha in origin_set,
            })
        return commits
    except (OSError, subprocess.SubprocessError):
        return []


def survey_session(sid: str, max_assistant_tail_chars: int = 1200,
                   tool_use_tail: int = 10) -> dict:
    """Walk the JSONL once, capture the last user message, last assistant text,
    last K tool_use calls, and the most-recent TodoWrite payload. Also mine
    git for commits authored by this session (via Session-Id trailer)."""
    from collections import deque
    path = find_session_jsonl(sid)
    if path is None:
        return {"error": f"no jsonl for sid={sid}"}
    last_user_text: str | None = None
    last_user_ts: str | None = None
    last_assistant_text: str | None = None
    last_assistant_ts: str | None = None
    last_todos: list | None = None
    recent_tool_uses: deque[dict] = deque(maxlen=tool_use_tail)
    msg_count = 0
    try:
        with path.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                t = d.get("type")
                msg = d.get("message") if isinstance(d.get("message"), dict) else None
                if not msg:
                    continue
                msg_count += 1
                role = msg.get("role")
                content = msg.get("content")
                ts = d.get("timestamp")
                if role == "user" and t == "user":
                    txt = _extract_text(content)
                    if txt and not txt.startswith("<"):
                        if not txt.startswith("Caveat") and "<system-reminder>" not in txt[:200]:
                            last_user_text = txt
                            last_user_ts = ts
                elif role == "assistant":
                    txt = _extract_text(content)
                    if txt:
                        last_assistant_text = txt
                        last_assistant_ts = ts
                    for name, inp in _extract_tool_uses(content):
                        recent_tool_uses.append({
                            "ts": ts,
                            "name": name,
                            "summary": _summarize_tool_use(name, inp),
                        })
                        if name == "TodoWrite" and isinstance(inp, dict):
                            last_todos = inp.get("todos")
    except OSError as e:
        return {"error": str(e)}
    return {
        "sid": sid,
        "jsonl": str(path),
        "msg_count": msg_count,
        "last_user": (last_user_text or "")[-2000:],
        "last_user_ts": last_user_ts,
        "last_assistant_tail": (last_assistant_text or "")[-max_assistant_tail_chars:],
        "last_assistant_ts": last_assistant_ts,
        "recent_tool_uses": list(recent_tool_uses),
        "todos": last_todos,
    }


def cmd_list(args) -> int:
    sessions = get_live_sessions(args.filter)
    if not sessions:
        print("No live Claude sessions.")
        return 0
    # Best-effort enrich each session with a content-derived purpose hint —
    # the NAME field can be auto-generated nonsense ('hose', 'add-deps-stage-4b')
    # and tells you nothing about what the session is actually working on.
    for s in sessions:
        jsonl = find_session_jsonl(s["sid"])
        s["hint"] = _purpose_hint(_first_user_text(jsonl)) if jsonl else ""
        s["jsonl_age"] = _jsonl_age_seconds(jsonl)
        s["child_procs"] = _child_proc_count(s["pid"])
        s["status"] = _activity_status(s["jsonl_age"], s["child_procs"])
    print(f"{'PID':>6}  {'SID':10}  {'NAME':26}  {'STATUS':6}  {'AGE':>5}  {'CH':>2}  PURPOSE")
    for s in sessions:
        name = (s["name"] or "(unnamed)")[:24]
        hint = s.get("hint") or "?"
        age = _fmt_age(s.get("jsonl_age"))
        print(f"{s['pid']:>6}  {s['sid'][:8]:10}  {name:26}  {s['status']:6}  {age:>5}  {s['child_procs']:>2}  {hint}")
    return 0


def _scan_jsonl_for_sid(sid_prefix: str) -> dict | None:
    """Find a JSONL file (alive or not) matching sid_prefix; return a synthetic
    session record so survey can run on dead sessions too."""
    if not PROJECTS_DIR.exists():
        return None
    for d in PROJECTS_DIR.iterdir():
        if not d.is_dir():
            continue
        for f in d.glob(f"{sid_prefix}*.jsonl"):
            return {
                "sid": f.stem,
                "cwd": d.name.lstrip("-").replace("-", "/"),  # best-effort
                "name": "(dead)",
                "pid": -1,
                "started_at": 0,
            }
    return None


def cmd_survey(args) -> int:
    sessions = get_live_sessions(args.filter)
    if args.sid:
        sessions = [s for s in sessions if s["sid"].startswith(args.sid)]
        if not sessions:
            # Fallback: maybe the session exited. Look in projects/ JSONLs.
            scanned = _scan_jsonl_for_sid(args.sid)
            if scanned:
                sessions = [scanned]
                print(f"(note: sid {args.sid} not in live registry — surveying historical JSONL)",
                      file=sys.stderr)
    if not sessions:
        print("No matching sessions.", file=sys.stderr)
        return 1
    out = []
    for s in sessions:
        info = survey_session(s["sid"])
        info["name"] = s["name"]
        info["cwd"] = s["cwd"]
        info["pid"] = s["pid"]
        jsonl = find_session_jsonl(s["sid"])
        info["jsonl_age_seconds"] = _jsonl_age_seconds(jsonl)
        info["child_procs"] = _child_proc_count(s["pid"])
        info["status"] = _activity_status(info["jsonl_age_seconds"], info["child_procs"])
        info["purpose_hint"] = _purpose_hint(_first_user_text(jsonl)) if jsonl else ""
        if not args.no_git:
            info["session_commits"] = _git_commits_for_session(s["cwd"], s["sid"])
        out.append(info)
    if args.json:
        print(json.dumps(out, indent=2, default=str))
        return 0
    # Cross-session timeline: surface commits on main regardless of which live
    # session authored them. Catches mismatched/orphan Session-Id trailers
    # that the per-session view (filtered by exact SID match) silently drops.
    if not args.no_git:
        sid_to_name: dict[str, str] = {}
        for info in out:
            full_sid = info.get("sid") or ""
            if full_sid:
                sid_to_name[full_sid] = info.get("name") or "(unnamed)"
        seen_cwds: set[str] = set()
        for info in out:
            cwd = info.get("cwd")
            if not cwd or cwd in seen_cwds:
                continue
            seen_cwds.add(cwd)
            timeline = _recent_main_commits(cwd, days=2, limit=25)
            if not timeline:
                continue
            sep = "=" * 80
            print(f"\n{sep}")
            print(f"RECENT MAIN COMMITS (cwd={cwd}, last 2 days)")
            print(sep)
            for c in timeline:
                push_marker = "  " if c["pushed"] else "* "
                sid = c.get("sid") or ""
                if sid in sid_to_name:
                    attribution = sid_to_name[sid]
                elif sid:
                    attribution = f"<dead/orphan sid:{sid[:8]}>"
                else:
                    attribution = "(no Session-Id)"
                print(f"  {push_marker}{c['sha']}  {attribution:<38}  {c['subject']}")
            print("  (* = unpushed to origin/main)")
    for info in out:
        sep = "=" * 80
        print(f"\n{sep}")
        print(f"NAME: {info.get('name') or '(unnamed)'}  SID: {info.get('sid','?')[:8]}  PID: {info.get('pid','?')}")
        print(f"CWD:  {info.get('cwd')}")
        print(f"MSG_COUNT: {info.get('msg_count')}  LAST_USER_TS: {info.get('last_user_ts','?')}  LAST_ASSISTANT_TS: {info.get('last_assistant_ts','?')}")
        print(sep)
        if "error" in info:
            print(f"ERROR: {info['error']}")
            continue
        commits = info.get("session_commits") or []
        if commits:
            print(f"\n--- COMMITS BY THIS SESSION (Session-Id trailer) ---")
            for c in commits:
                print(f"  {c}")
        recent = info.get("recent_tool_uses") or []
        if recent:
            print(f"\n--- LAST {len(recent)} TOOL USES (newest last) ---")
            for tu in recent:
                ts = (tu.get("ts") or "")[:19].replace("T", " ")
                print(f"  [{ts}] {tu.get('summary','')}")
        print(f"\n--- LAST USER MSG ---\n{(info.get('last_user') or '(none)').strip()}")
        print(f"\n--- LAST ASSISTANT (tail) ---\n{(info.get('last_assistant_tail') or '(none)').strip()}")
        todos = info.get("todos")
        if todos:
            print("\n--- TODOS ---")
            for t in todos:
                if isinstance(t, dict):
                    status = t.get("status", "?")
                    content = t.get("content") or t.get("activeForm") or t.get("subject") or ""
                    print(f"  [{status}] {content}")
    return 0


def extract_decisions(sid: str, output_path: Path) -> Path:
    """Deep-walk one Claude session JSONL and emit a structured-decisions JSON.

    Schema is the cross-runtime contract consumed by spec-review's
    design-decisions-extractor agent. Codex-sessions emits the same shape.

    For each user turn, we accumulate the assistant's tool uses, file edits,
    and commits made BEFORE the next user turn — the "what did the user say
    AND what got done about it" window.
    """
    path = find_session_jsonl(sid)
    if path is None:
        # Try prefix match across all project dirs
        for d in PROJECTS_DIR.iterdir() if PROJECTS_DIR.exists() else []:
            if not d.is_dir():
                continue
            for f in d.glob(f"{sid}*.jsonl"):
                path = f
                break
            if path:
                break
    if path is None or not path.exists():
        raise SystemExit(f"no Claude JSONL found for sid prefix {sid!r}")

    user_turns: list[dict] = []
    assistant_summary: list[dict] = []
    files_touched: set[str] = set()
    tool_dist: dict[str, int] = {}
    session_meta: dict = {"cwd": None, "git_branch": None, "started_at": None}
    session_id_full = sid

    current: dict | None = None  # the open user turn we accumulate into

    def flush(t: dict | None) -> None:
        if t is not None:
            user_turns.append(t)

    with path.open("r", encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError:
                continue

            # Capture session meta from any record that carries it
            if not session_meta["cwd"] and rec.get("cwd"):
                session_meta["cwd"] = rec.get("cwd")
                session_meta["git_branch"] = rec.get("gitBranch")
                session_meta["started_at"] = rec.get("timestamp")
            if rec.get("sessionId") and len(session_id_full) < 36:
                session_id_full = rec["sessionId"]

            msg = rec.get("message")
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            content = msg.get("content")
            ts = rec.get("timestamp")

            if role == "user":
                # Skip tool-result-only "user" frames (input is a list of tool_result entries)
                text = _extract_text(content)
                if not text or text.startswith("<"):
                    # heuristic: a tool result wrapper looks like a tool_result list, _extract_text returns ""
                    if not text:
                        continue
                flush(current)
                current = {
                    "ts": ts,
                    "content": text[:4000],
                    "tools_after": [],
                    "files_edited_after": [],
                }

            elif role == "assistant":
                tool_uses = _extract_tool_uses(content)
                text = _extract_text(content)
                if text and len(text.strip()) >= 40 and current is not None:
                    assistant_summary.append({"ts": ts, "text": text[:1200]})
                for name, inp in tool_uses:
                    tool_dist[name] = tool_dist.get(name, 0) + 1
                    if current is not None:
                        current["tools_after"].append(_summarize_tool_use(name, inp))
                    if name in ("Edit", "Write", "MultiEdit"):
                        fp = inp.get("file_path") if isinstance(inp, dict) else None
                        if isinstance(fp, str):
                            files_touched.add(fp)
                            if current is not None:
                                current["files_edited_after"].append(fp)

    flush(current)

    # Mine git commits made by this session
    cwd = session_meta.get("cwd") or ""
    commits = _git_commits_for_session(cwd, session_id_full, days=14) if cwd else []

    payload = {
        "session_id": session_id_full,
        "runtime": "claude",
        "session_meta": session_meta,
        "user_turns": user_turns,
        "assistant_summary": assistant_summary[-30:],  # cap noise
        "commits_during_session": [{"line": c} for c in commits],
        "files_touched": sorted(files_touched),
        "tool_call_distribution": dict(sorted(tool_dist.items(), key=lambda kv: -kv[1])),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(user_turns)} user turns / {len(commits)} commits → {output_path}")
    return output_path


def cmd_extract_decisions(args) -> int:
    out = Path(args.output) if args.output else Path(f"/tmp/claude-decisions-{args.sid[:8]}.json")
    extract_decisions(args.sid, out)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="claude-sessions",
                                description="Survey live Claude Code sessions.")
    sub = p.add_subparsers(dest="cmd")
    pl = sub.add_parser("list", help="list live sessions")
    pl.add_argument("--filter", help="cwd substring filter")
    ps = sub.add_parser("survey", help="dump recent state per session")
    ps.add_argument("--filter", help="cwd substring filter")
    ps.add_argument("--sid", help="single sid prefix")
    ps.add_argument("--json", action="store_true", help="machine-readable JSON")
    ps.add_argument("--no-git", action="store_true", help="skip git Session-Id trailer mining")
    pe = sub.add_parser("extract-decisions",
                        help="Deep-walk one session for structured design-decision JSON (spec-review feed)")
    pe.add_argument("--sid", required=True, help="Session id (full or prefix)")
    pe.add_argument("--output", help="Output JSON path (default /tmp/claude-decisions-<sid>.json)")
    args = p.parse_args()
    if args.cmd == "list":
        return cmd_list(args)
    if args.cmd == "survey":
        return cmd_survey(args)
    if args.cmd == "extract-decisions":
        return cmd_extract_decisions(args)
    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
