"""Read-only activity facts from durable Codex events; never controls a session."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ToolEvent:
    id: str | None
    name: str
    ts: float | None
    status: str | None
    exit_code: int | None = None
    command: str = ""


@dataclass(frozen=True)
class WaitEvent:
    targets: tuple[str, ...]
    fingerprint: tuple[tuple[str, str], ...]
    unchanged_count: int

    def summary(self) -> dict[str, Any]:
        return {
            "targets": list(self.targets),
            "unchanged_count": self.unchanged_count,
            "warning": ("Repeated unchanged waits are not evidence of progress. "
                        "Check the dependency's durable turn and artifacts before waiting again.")
                       if self.unchanged_count >= 2 else None,
        }


@dataclass(frozen=True)
class Activity:
    updated_at: float | None = None
    turn_id: str | None = None
    turn_status: str | None = None
    last_tool: ToolEvent | None = None
    last_wait: WaitEvent | None = None


def wait_fact(item: dict[str, Any], previous: WaitEvent | None) -> WaitEvent | None:
    result = item.get("result") or {}
    if not isinstance(result, dict):
        return None
    texts = result.get("content") or []
    decoded = None
    for part in texts:
        if not isinstance(part, dict) or part.get("type") != "text":
            continue
        try:
            decoded = json.loads(part.get("text", ""))
        except (ValueError, TypeError):
            continue
        if isinstance(decoded, dict):
            break
    if not isinstance(decoded, dict):
        return None
    polls = decoded.get("polls")
    if not isinstance(polls, list) or not polls or not all(isinstance(p, dict) for p in polls):
        return None
    if any(not isinstance(p.get("thread"), dict) for p in polls):
        return None
    fingerprint = tuple(sorted(
        (str((p.get("thread") or {}).get("id", "")), str(p.get("cursor", ""))) for p in polls
    ))
    unchanged = decoded.get("timedOut") is True and all(p.get("changed") is False for p in polls)
    count = (previous.unchanged_count + 1 if previous and previous.fingerprint == fingerprint else 1)
    return WaitEvent(tuple(tid for tid, _ in fingerprint), fingerprint, count if unchanged else 0)


def tool_fact(item: dict[str, Any], when: float | None) -> ToolEvent | None:
    kind = item.get("type")
    command = item.get("command") or ""
    if isinstance(command, list):
        command = " ".join(str(part) for part in command)
    if kind == "CommandExecution":
        return ToolEvent(item.get("id"), "commandExecution", when, item.get("status"),
                         item.get("exit_code"), str(command)[:220])
    if kind == "McpToolCall":
        return ToolEvent(item.get("id"), str(item.get("tool", "mcp")), when, item.get("status"))
    if kind == "FileChange":
        return ToolEvent(item.get("id"), "fileChange", when, item.get("status"))
    return None


def observe(activity: Activity, obj: dict[str, Any], when: float | None) -> Activity:
    updated = max(activity.updated_at or 0, when or 0) or None
    activity = replace(activity, updated_at=updated)
    payload = obj.get("payload")
    if obj.get("type") != "event_msg" or not isinstance(payload, dict):
        return activity
    kind, turn_id = payload.get("type"), payload.get("turn_id")
    if kind == "task_started":
        return replace(activity, turn_id=turn_id, turn_status="active",
                       last_tool=None, last_wait=None)
    if kind in {"task_complete", "turn_aborted"}:
        if turn_id and activity.turn_id and turn_id != activity.turn_id:
            return activity
        return replace(activity, turn_status="complete" if kind == "task_complete" else "interrupted")
    item = payload.get("item")
    if kind != "item_completed" or not isinstance(item, dict):
        return activity
    if turn_id and activity.turn_id and turn_id != activity.turn_id:
        return activity
    tool = tool_fact(item, when)
    if not tool:
        return activity
    wait = (wait_fact(item, activity.last_wait) if tool.name == "wait_threads"
            else activity.last_wait)
    return replace(activity, last_tool=tool, last_wait=wait)


def activity_fields(activity: Activity) -> dict[str, Any]:
    return {
        "latest_turn_id": activity.turn_id,
        "last_tool_event": asdict(activity.last_tool) if activity.last_tool else None,
        "last_wait": activity.last_wait.summary() if activity.last_wait else None,
    }


def native_history(root: Path, sid: str, turn_id: str | None,
                   last_tool: dict[str, Any] | None, status: str) -> dict[str, Any]:
    """Compare a scoped snapshot only. 'behind' may include normal indexing lag."""
    db = root / "thread_history_1.sqlite"
    if not db.exists() or not turn_id:
        return {"status": "unavailable", "reason": "No comparable native history snapshot"}
    try:
        with closing(sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.1)) as conn:
            turn = conn.execute(
                "SELECT turn_id,status FROM thread_turns WHERE thread_id=? "
                "ORDER BY rollout_ordinal DESC LIMIT 1", (sid,),
            ).fetchone()
            item_id = (last_tool or {}).get("id")
            item_present = not item_id or bool(conn.execute(
                "SELECT 1 FROM thread_items WHERE thread_id=? AND item_id=? LIMIT 1",
                (sid, item_id),
            ).fetchone())
    except sqlite3.Error as exc:
        return {"status": "unavailable", "reason": type(exc).__name__}
    expected = {"active": "inProgress", "complete": "completed", "interrupted": "interrupted"}.get(status)
    matches = bool(turn and turn[0] == turn_id and item_present and
                   (expected is None or turn[1] == expected))
    return {
        "status": "current" if matches else "behind",
        "rollout_turn_id": turn_id,
        "indexed_turn_id": turn[0] if turn else None,
        "latest_tool_indexed": item_present,
        "warning": None if matches else (
            "Native history is behind this rollout snapshot. Do not use its stale cursor "
            "or active flag as a completion signal. Preserve the session and verify durable evidence."
        ),
    }
