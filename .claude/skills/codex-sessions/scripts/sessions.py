#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

INDEX_PATH = Path.home() / ".codex/session_index.jsonl"
SESSIONS_ROOT = Path.home() / ".codex/sessions"
STATE_DIR = Path("tools/codex-sessions/state")
STATE_DIR.mkdir(parents=True, exist_ok=True)


def ts_from_iso(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value).timestamp()
    except Exception:
        return None


def utcnow() -> float:
    return time.time()


def safe_get(obj: Any, *keys: str, default: Any = None) -> Any:
    cur = obj
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


@dataclass
class SessionRecord:
    sid: str
    title: str = ""
    path: Optional[Path] = None
    updated_at: Optional[float] = None
    mtime: Optional[float] = None
    status: str = "unknown"
    line_count: int = 0
    meta: Dict[str, Any] = field(default_factory=dict)
    turn_context: Dict[str, Any] = field(default_factory=dict)
    cwd: Optional[str] = None
    last_user: Optional[str] = None
    last_user_ts: Optional[float] = None
    last_assistant_tail: Optional[str] = None
    last_final_tail: Optional[str] = None
    last_task_started: Optional[float] = None
    last_task_complete: Optional[Dict[str, Any]] = None
    context_remaining_percent: Optional[float] = None
    context_used: Optional[int] = None
    context_total: Optional[int] = None
    recent_tool_calls: List[str] = field(default_factory=list)
    recent_execs: List[str] = field(default_factory=list)
    revision_events: List[str] = field(default_factory=list)
    timeline_tail: List[Dict[str, Any]] = field(default_factory=list)
    commits: List[Dict[str, str]] = field(default_factory=list)
    mention_files: List[str] = field(default_factory=list)
    open_turns: int = 0

    def to_summary(self, json_mode: bool = False) -> Dict[str, Any]:
        return {
            "sid": self.sid,
            "title": self.title,
            "status": self.status,
            "updated_at": self.updated_at,
            "mtime": self.mtime,
            "path": str(self.path) if self.path else None,
            "line_count": self.line_count,
            "open_turns": self.open_turns,
            "context_remaining_percent": self.context_remaining_percent,
            "context_used": self.context_used,
            "context_total": self.context_total,
            "cwd": self.cwd,
            "last_user": self.last_user,
            "last_user_ts": self.last_user_ts,
            "last_assistant_tail": self.last_assistant_tail,
            "last_final_tail": self.last_final_tail,
            "last_task_complete": self.last_task_complete,
            "recent_tool_calls": self.recent_tool_calls[-10:],
            "recent_execs": self.recent_execs[-10:],
            "revisions": self.revision_events[-10:],
            "commits": self.commits,
            "commits_count": len(self.commits),
            "path_exists": bool(self.path and self.path.exists()),
            "meta": self.meta if json_mode else {
                "originator": self.meta.get("originator"),
                "cli_version": self.meta.get("cli_version"),
                "source": self.meta.get("source"),
                "model_provider": self.meta.get("model_provider"),
            },
            "turn_context": self.turn_context if json_mode else {
                "approval_policy": self.turn_context.get("approval_policy"),
                "sandbox_policy": self.turn_context.get("sandbox_policy"),
                "permission_profile": self.turn_context.get("permission_profile"),
                "effort": self.turn_context.get("effort"),
            },
            "timeline_tail": self.timeline_tail[-15:],
        }


def load_index() -> List[Dict[str, Any]]:
    records = []
    if not INDEX_PATH.exists():
        return records
    with INDEX_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except Exception:
                continue
            records.append(payload)
    return records


def build_transcript_paths() -> List[Path]:
    if not SESSIONS_ROOT.exists():
        return []
    return list(SESSIONS_ROOT.rglob("*.jsonl"))


def extract_sid_from_path(path: Path) -> str:
    stem = path.stem
    if "-" not in stem:
        return stem
    parts = stem.split("-")
    if len(parts) >= 6:
        return "-".join(parts[-5:])
    return stem


def record_search_blob(record: SessionRecord) -> str:
    values: List[str] = [
        record.sid,
        record.title or "",
        record.cwd or "",
        str(record.path or ""),
        record.last_user or "",
        record.last_assistant_tail or "",
        record.last_final_tail or "",
        str(record.turn_context.get("cwd") or ""),
    ]
    values.extend(record.recent_execs[-10:])
    values.extend(record.revision_events[-20:])
    values.extend(record.mention_files[-20:])
    return " ".join(v for v in values if v).lower()


def find_transcript_for_session(sid: str, cached: Dict[str, Path], index_entry: Dict[str, Any]) -> Optional[Path]:
    if sid in cached:
        return cached[sid]

    # Direct or explicit path from session index
    for key in ("path", "transcript", "transcript_path", "session_path"):
        value = index_entry.get(key)
        if isinstance(value, str):
            p = Path(os.path.expanduser(value))
            if p.exists():
                cached[sid] = p
                return p

    root = SESSIONS_ROOT
    if not root.exists():
        return None

    matches = list(root.rglob(f"*{sid}*.jsonl"))
    if matches:
        cached[sid] = max(matches, key=lambda p: p.stat().st_mtime)
        return cached[sid]

    # Fallback: scan by session_meta.id
    for path in build_transcript_paths():
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    if obj.get("type") == "session_meta":
                        sid_value = safe_get(obj, "payload", "id")
                        if sid_value == sid:
                            cached[sid] = path
                            return path
        except Exception:
            continue
    return None


def match_filter(text: str, terms: List[str]) -> bool:
    lower = text.lower()
    return all(t in lower for t in terms)


def entry_timestamp(entry: Dict[str, Any]) -> Optional[float]:
    return ts_from_iso(entry.get("updated_at") or entry.get("timestamp"))


def parse_since_date(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            continue
    return ts_from_iso(value)


def shallow_record(entry: Dict[str, Any]) -> SessionRecord:
    sid = str(entry.get("id") or "").strip()
    title = entry.get("thread_name") or entry.get("title") or ""
    updated = entry_timestamp(entry)
    rec = SessionRecord(sid=sid, title=title, updated_at=updated, mtime=updated)
    rec.meta = {
        "id": sid,
        "cwd": entry.get("cwd"),
        "source": entry.get("source"),
        "originator": entry.get("originator"),
        "cli_version": entry.get("cli_version"),
        "base_instructions": None,
    }
    if updated:
        age = utcnow() - updated
        if age < 120:
            rec.status = "active"
        elif age < 1800:
            rec.status = "warm"
        else:
            rec.status = "indexed"
    else:
        rec.status = "indexed"
    return rec


def parse_transcript(path: Path, sid: str) -> SessionRecord:
    record = SessionRecord(sid=sid)
    line_count = 0
    now = utcnow()
    timer_stack = []
    try:
        stat = path.stat()
        record.mtime = stat.st_mtime
    except Exception:
        pass

    try:
        with path.open("r", encoding="utf-8") as f:
            for raw in f:
                line_count += 1
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except Exception:
                    continue

                etype = obj.get("type")
                payload = obj.get("payload", {})
                when = ts_from_iso(str(obj.get("timestamp") or payload.get("timestamp") or ""))

                if etype == "session_meta":
                    sid_value = safe_get(payload, "id")
                    if sid_value:
                        record.sid = str(sid_value)
                    if not record.title:
                        record.title = safe_get(payload, "thread_name") or safe_get(payload, "title", default="") or record.title
                    record.cwd = safe_get(payload, "cwd")
                    record.meta = {
                        "id": safe_get(payload, "id"),
                        "originator": safe_get(payload, "originator"),
                        "cli_version": safe_get(payload, "cli_version"),
                        "source": safe_get(payload, "source"),
                        "model_provider": safe_get(payload, "model_provider"),
                        "base_instructions": safe_get(payload, "base_instructions", "text"),
                    }

                elif etype == "turn_context":
                    record.turn_context = {
                        "cwd": safe_get(payload, "cwd"),
                        "current_date": safe_get(payload, "current_date"),
                        "timezone": safe_get(payload, "timezone"),
                        "approval_policy": safe_get(payload, "approval_policy"),
                        "sandbox_policy": safe_get(payload, "sandbox_policy"),
                        "permission_profile": safe_get(payload, "permission_profile"),
                        "model": safe_get(payload, "model"),
                        "effort": safe_get(payload, "effort"),
                    }

                elif etype == "event_msg":
                    msg_type = safe_get(payload, "type")
                    if msg_type == "token_count":
                        record.context_remaining_percent = safe_get(payload, "context_remaining_percent")
                        record.context_used = safe_get(payload, "used")
                        record.context_total = safe_get(payload, "total")
                    elif msg_type == "task_started":
                        when_val = when or now
                        timer_stack.append(when_val)
                        record.last_task_started = when_val
                    elif msg_type == "task_complete":
                        when_val = when or now
                        record.last_task_complete = {
                            "ts": when_val,
                            "model": safe_get(payload, "model"),
                            "last_agent_message": safe_get(payload, "last_agent_message"),
                            "duration_ms": safe_get(payload, "duration_ms"),
                        }
                        if timer_stack:
                            timer_stack.pop()
                    elif msg_type == "user_message":
                        text = safe_get(payload, "text") or safe_get(payload, "content")
                        if isinstance(text, str):
                            record.last_user = text[:400]
                            record.last_user_ts = when
                    elif msg_type == "assistant_message":
                        text = safe_get(payload, "text") or safe_get(payload, "content")
                        if isinstance(text, str):
                            record.last_assistant_tail = text[:600]
                            tag = safe_get(payload, "tags", default=[]) or []
                            if "final" in tag:
                                record.last_final_tail = text[:600]
                            elif "result" in tag and not record.last_final_tail:
                                record.last_final_tail = text[:600]
                        action = safe_get(payload, "subtype")
                        if action:
                            record.revision_events.append(f"assistant_subtype:{action}")
                    elif msg_type in {"agent_message", "final_answer"}:
                        text = safe_get(payload, "message") or safe_get(payload, "text") or safe_get(payload, "content")
                        if isinstance(text, str):
                            record.last_assistant_tail = text[:600]
                            record.last_final_tail = text[:600]
                    elif msg_type in {"task_revision", "revision", "session_revision"}:
                        action = safe_get(payload, "data") or safe_get(payload, "text")
                        if action:
                            s = str(action)
                            if len(s) > 250:
                                s = s[:247] + "..."
                            record.revision_events.append(s)

                elif etype == "response_item":
                    rtype = safe_get(payload, "type")
                    if rtype == "function_call":
                        name = safe_get(payload, "name", default="")
                        if name:
                            record.recent_tool_calls.append(name)
                        arguments = safe_get(payload, "arguments")
                        if isinstance(arguments, str) and arguments:
                            if len(arguments) > 180:
                                arguments = arguments[:177] + "..."
                            record.revision_events.append(f"tool_args::{name}::{arguments}")
                    elif rtype == "function_call_output":
                        call = safe_get(payload, "name")
                        if call:
                            record.recent_tool_calls.append(f"{call}:output")
                    elif rtype == "message":
                        role = safe_get(payload, "role", default="")
                        content = safe_get(payload, "content", default=[])
                        text_parts = []
                        if isinstance(content, list):
                            for part in content:
                                if not isinstance(part, dict):
                                    continue
                                if part.get("type") in {"output_text", "input_text"}:
                                    text_parts.append(str(part.get("text") or ""))
                        text = "\n".join([p for p in text_parts if p]).strip()
                        phase = safe_get(payload, "phase")
                        if text:
                            if role == "user":
                                record.last_user = text[:400]
                                record.last_user_ts = when
                            else:
                                record.last_assistant_tail = text[:600]
                                if phase in {"final", "final_answer"}:
                                    record.last_final_tail = text[:600]

                elif etype == "function_call":
                    name = safe_get(payload, "name")
                    if name:
                        record.recent_tool_calls.append(name)

                elif etype == "exec_command_end":
                    cmd = safe_get(payload, "cmd") or safe_get(payload, "command") or ""
                    cmd_short = str(cmd).strip().replace("\n", " ")
                    if len(cmd_short) > 220:
                        cmd_short = cmd_short[:217] + "..."
                    status = safe_get(payload, "status", default="ok")
                    code = safe_get(payload, "exit_code")
                    record.recent_execs.append(f"{status}:{code}:{cmd_short}")

                # timeline for latest decisions
                if etype in {"event_msg", "response_item", "session_meta", "turn_context"}:
                    timeline_payload = {
                        "ts": when or now,
                        "type": etype,
                        "kind": safe_get(payload, "type", default=""),
                        "text": safe_get(payload, "text", default="") or safe_get(payload, "name", default=""),
                    }
                    record.timeline_tail.append(timeline_payload)

                if etype == "session_meta" and safe_get(payload, "thread_name"):
                    record.title = safe_get(payload, "thread_name", default=record.title) or record.title
                    record.updated_at = ts_from_iso(safe_get(payload, "timestamp"))

    except Exception:
        pass

    record.line_count = line_count

    if record.updated_at is None:
        record.updated_at = record.last_user_ts or record.mtime

    if timer_stack:
        record.open_turns = len(timer_stack)
    if record.last_task_complete:
        started = record.last_task_started or 0
        if record.last_task_complete.get("ts", 0) >= started:
            record.open_turns = 0

    # infer status
    age = now - (record.mtime or 0)
    if record.open_turns > 0:
        record.status = "active"
    elif age < 120:
        record.status = "active"
    elif age < 1800:
        record.status = "warm"
    elif record.last_task_complete:
        record.status = "complete"
    else:
        record.status = "idle"

    return record


def collect_sessions(
    filter_text: Optional[str],
    limit: Optional[int],
    *,
    deep: bool = False,
    since: Optional[str] = None,
    days: Optional[int] = None,
) -> List[SessionRecord]:
    raw = load_index()
    terms = []
    if filter_text:
        terms = [x.strip().lower() for x in filter_text.split(" ") if x.strip()]

    min_ts = parse_since_date(since)
    if days is not None:
        min_ts = max(min_ts or 0, utcnow() - (days * 86400))

    raw_sorted = sorted(
        raw,
        key=lambda item: entry_timestamp(item)
        if entry_timestamp(item) is not None
        else 0.0,
        reverse=True,
    )

    path_cache: Dict[str, Path] = {}
    sessions: List[SessionRecord] = []
    for entry in raw_sorted:
        sid = str(entry.get("id") or "").strip()
        if not sid:
            continue

        updated = entry_timestamp(entry)
        if min_ts and (not updated or updated < min_ts):
            continue

        rec = shallow_record(entry)
        shallow_blob = " ".join(filter(None, [sid, rec.title or ""])).lower()
        shallow_match = not terms or match_filter(shallow_blob, terms)

        path: Optional[Path] = None
        if terms or deep:
            path = find_transcript_for_session(sid, path_cache, entry)

        if not deep and not (terms and path and not shallow_match):
            if not shallow_match:
                continue
            sessions.append(rec)
            if limit and len(sessions) >= limit:
                break
            continue

        if path:
            rec.path = path
            parsed = parse_transcript(path, sid)
            rec = parsed
            rec.sid = sid
            rec.title = rec.title or entry.get("thread_name", "")
            if rec.path is None:
                rec.path = path
        else:
            rec.title = entry.get("thread_name", "") or entry.get("title", "")
            rec.updated_at = ts_from_iso(entry.get("updated_at"))
            rec.mtime = rec.updated_at
        rec.path = rec.path or path
        rec.meta = rec.meta or {
            "id": sid,
            "cwd": entry.get("cwd"),
            "source": entry.get("source"),
            "originator": entry.get("originator"),
            "cli_version": entry.get("cli_version"),
            "base_instructions": None,
        }
        rec.line_count = rec.line_count or 0

        search_blob = record_search_blob(rec)
        if terms and not match_filter(search_blob, terms):
            continue

        sessions.append(rec)
        if limit and len(sessions) >= limit:
            break

    if (terms or deep) and (not limit or len(sessions) < limit):
        seen_paths = {s.path.resolve() for s in sessions if s.path}
        seen_sids = {s.sid for s in sessions if s.sid}
        transcript_paths = sorted(
            build_transcript_paths(),
            key=lambda p: p.stat().st_mtime if p.exists() else 0.0,
            reverse=True,
        )
        for path in transcript_paths:
            try:
                mtime = path.stat().st_mtime
            except Exception:
                continue
            if min_ts and mtime < min_ts:
                continue
            try:
                resolved = path.resolve()
            except Exception:
                resolved = path
            if resolved in seen_paths:
                continue

            rec = parse_transcript(path, extract_sid_from_path(path))
            rec.path = path
            if rec.sid in seen_sids:
                continue
            if terms and not match_filter(record_search_blob(rec), terms):
                continue

            sessions.append(rec)
            seen_paths.add(resolved)
            seen_sids.add(rec.sid)
            if limit and len(sessions) >= limit:
                break

    sessions.sort(
        key=lambda record: record.updated_at or record.mtime or 0.0,
        reverse=True,
    )
    return sessions


def list_sessions(sessions: List[SessionRecord]) -> None:
    for s in sessions:
        updated = (
            datetime.fromtimestamp(s.updated_at, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            if s.updated_at
            else "n/a"
        )
        print(f"{s.status:8} | {s.sid[:8]} | {s.title[:40]:40} | {updated} | {s.path}")


def survey_json(sessions: List[SessionRecord]) -> None:
    print(json.dumps([s.to_summary(json_mode=True) for s in sessions], indent=2))


def survey_text(sid: Optional[str], sessions: List[SessionRecord]) -> None:
    if sid:
        sessions = [s for s in sessions if s.sid.startswith(sid)]
        if not sessions:
            print(json.dumps({"error": f"session {sid} not found"}, indent=2))
            return
    for s in sessions[:1] if sid else sessions:
        print(f"SID: {s.sid}")
        print(f"TITLE: {s.title}")
        print(f"STATUS: {s.status}")
        print(f"PATH: {s.path}")
        print(f"UPDATED: {s.updated_at}")
        if s.last_user:
            print(f"LAST USER: {s.last_user}")
        if s.last_assistant_tail:
            print(f"LAST ASSISTANT: {s.last_assistant_tail[:200]}")
        if s.last_final_tail:
            print(f"LAST FINAL: {s.last_final_tail[:200]}")
        if s.last_task_complete:
            print(f"LAST COMPLETE: {s.last_task_complete}")
        if s.timeline_tail:
            print("TIMELINE TAIL:")
            for item in s.timeline_tail[-8:]:
                ts = item.get("ts")
                label = item.get("kind") or item.get("type")
                print(f"- {ts}: {label}: {(item.get('text') or '')[:120]}")


def collect_git_commits(sid: str) -> List[Dict[str, str]]:
    repo = Path.cwd()
    try:
        out = subprocess.check_output(
            [
                "git",
                "-C",
                str(repo),
                "log",
                "--format=%H%x01%s%x01%ad",
                "--date=iso-strict",
                "--max-count=15",
                f"--grep=Session-Id: {sid}",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return []
    entries: List[Dict[str, str]] = []
    for line in out.splitlines():
        parts = line.split("\x01")
        if len(parts) < 3:
            continue
        sha, subject, date = parts[0], parts[1], parts[2]
        entries.append({"sha": sha, "subject": subject, "date": date})
    return entries


def get_prs_and_issues(sid: str, no_gh: bool) -> Dict[str, Any]:
    if no_gh:
        return {"prs": "disabled", "issues": "disabled"}
    try:
        prs = subprocess.check_output(
            ["gh", "pr", "list", "--search", sid, "--json", "number,title,state,updatedAt,url"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        issues = subprocess.check_output(
            ["gh", "issue", "list", "--search", sid, "--json", "number,title,state,updatedAt,url"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return {
            "prs": json.loads(prs or "[]"),
            "issues": json.loads(issues or "[]"),
            "source": "github-cli",
        }
    except Exception as err:
        return {"prs": f"unavailable: {err}", "issues": f"unavailable: {err}", "source": "github-cli"}


def write_state_miners(sessions: List[SessionRecord], filter_text: Optional[str], no_gh: bool) -> Dict[str, Any]:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    latest_sid = sessions[0].sid if sessions else ""
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "filter": filter_text,
        "sessions": [s.to_summary(json_mode=True) for s in sessions],
        "top_session": sessions[0].sid if sessions else None,
        "top_session_title": sessions[0].title if sessions else None,
    }
    payload["next_actions"] = []
    payload["open_questions"] = []

    for s in sessions[:5]:
        if s.last_task_complete:
            payload["next_actions"].append(
                f"{s.sid}: review final outcome if action remains open"
            )
        if s.open_turns > 0:
            payload["open_questions"].append(
                f"{s.sid}: unresolved in-flight task started without completion"
            )

    cache_file = STATE_DIR / f"state-miner-{ts}.json"
    survey_file = STATE_DIR / f"survey-{ts}.json"
    state_file = STATE_DIR / "last-state.json"
    cache_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    survey_file.write_text(json.dumps(payload["sessions"], indent=2), encoding="utf-8")

    # fill in git metadata for top session
    if latest_sid:
        payload["latest_commits"] = collect_git_commits(latest_sid)
        payload["latest_gh"] = get_prs_and_issues(latest_sid, no_gh=no_gh)

    state_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    prompt = [
        "# Codex Session State Miner",
        "",
        "Run this summary through an orchestration pass.",
        "",
        "## Active Lanes",
        "",
    ]
    active = [s for s in sessions if s.status == "active"]
    if active:
        for s in active:
            line = f"- {s.sid} | {s.title} | {s.status} | {s.last_user[:120] if s.last_user else 'no user tail'}"
            prompt.append(line)
    else:
        prompt.append("- No active lanes detected.")
    prompt += [
        "",
        "## Cross-Lane State",
        "",
        f"- sessions_scanned: {len(sessions)}",
        f"- filter: {filter_text or 'none'}",
        "- look for sequencing conflicts across sessions before changing shared files.",
        "",
        "## Latest Revisions",
        "",
    ]
    for s in sessions[:8]:
        summary = (
            f"- {s.sid} | {s.title} | {s.status} | "
            f"final='{(s.last_final_tail or '').strip()[:140]}'"
        )
        prompt.append(summary)

    prompt += [
        "",
        "## Next Moves",
        "",
        "1. Confirm one active session owner before claiming any shared-file changes.",
        "2. Surface unresolved session constraints and verify that latest revisions are reflected in branch state.",
        "3. Re-run mine before starting handoff so the state cache is current.",
        "",
        "## Cache JSON",
        "",
        "```json",
    ]
    prompt.append(json.dumps(payload, indent=2))
    prompt.append("```")
    prompt_file = STATE_DIR / f"state-miner-{ts}.md"
    prompt_file.write_text("\n".join(prompt) + "\n", encoding="utf-8")

    return {
        "cache_file": str(cache_file),
        "survey_file": str(survey_file),
        "state_file": str(state_file),
        "prompt_file": str(prompt_file),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mine local Codex sessions")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--filter", help="Filter text across sid/thread title; add --deep to include cwd/path", default=None)
        p.add_argument("--limit", type=int, default=None, help="Maximum sessions to return; use 0 for no cap")
        p.add_argument("--since", help="Only include sessions updated since YYYY-MM-DD or ISO timestamp", default=None)
        p.add_argument("--days", type=int, help="Only include sessions updated in the last N days", default=None)
        p.add_argument("--deep", action="store_true", help="Parse matching transcripts for cwd/path/final output details")

    list_parser = subparsers.add_parser("list", help="List codex sessions")
    add_common(list_parser)

    survey_parser = subparsers.add_parser("survey", help="Survey sessions in JSON")
    add_common(survey_parser)
    survey_parser.add_argument("--sid", help="Survey single session id prefix", default=None)
    survey_parser.add_argument("--json", action="store_true", help="Output JSON")

    mine_parser = subparsers.add_parser("mine", help="Mine sessions and write orchestrator artifacts")
    add_common(mine_parser)
    mine_parser.add_argument("--no-gh", action="store_true")

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    days = args.days
    if args.command == "mine" and args.since is None and days is None:
        days = 2
    limit = args.limit
    if args.command == "survey" and args.filter and limit is None:
        limit = 25
    if limit == 0:
        limit = None
    sessions = collect_sessions(
        args.filter,
        limit,
        deep=args.deep or args.command == "mine",
        since=args.since,
        days=days,
    )

    if args.command == "list":
        list_sessions(sessions)
        return

    if args.command == "survey":
        if args.json:
            if args.sid:
                sessions = [s for s in sessions if s.sid.startswith(args.sid)]
            survey_json(sessions)
        else:
            survey_text(args.sid, sessions)
        return

    if args.command == "mine":
        for s in sessions:
            if not s.path:
                continue
            s.commits = collect_git_commits(s.sid)
        outputs = write_state_miners(sessions, args.filter, args.no_gh)
        print("wrote:")
        for _, path in outputs.items():
            print(f"- {path}")


if __name__ == "__main__":
    main()
