#!/usr/bin/env python3
"""Read-only lexical shadow audit of completed root Codex replies.

This does not decide whether work was complete or whether any next action was right.
It never executes transcript content or writes to the sessions directory.
"""

import argparse
import heapq
import json
import re
import sys
import unicodedata
from pathlib import Path


NEXT_STEPS = re.compile(r"^Next steps?(?:\s*:\s*(.*))?$", re.IGNORECASE)
NEXT_ACTION = re.compile(r"^Next[_ ]action\s*:", re.IGNORECASE)
NONE_MARKER = re.compile(r"^none\b", re.IGNORECASE)
SKIPPED_DETAIL_LIMIT = 100


def positive_int(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def explicit_final(payload):
    return (payload.get("type") == "message" and payload.get("role") == "assistant"
            and (payload.get("channel") == "final" or payload.get("phase") == "final_answer"))


def response_text(payload):
    content = payload.get("content")
    if not isinstance(content, list):
        return None
    chunks = [item.get("text") for item in content
              if isinstance(item, dict) and item.get("type") in ("output_text", "text")
              and isinstance(item.get("text"), str)]
    return "\n".join(chunks) if chunks else None


def structured_next_action(answer):
    """Recognize a whole JSON handoff, never JSON quoted inside narrative/code."""
    try:
        value = json.loads(answer)
    except (ValueError, TypeError):
        return False
    action = value.get("next_action") if isinstance(value, dict) else None
    if isinstance(action, str):
        return bool(action.strip())
    return (isinstance(action, list) and bool(action)
            and all(isinstance(item, str) and item.strip() for item in action))


def observe_next_steps(answer):
    """Find a visible English heading, excluding Markdown quotes and code fences."""
    fenced = False
    next_steps_present = False
    none_marker = False
    next_action_present = structured_next_action(answer)
    for raw in answer.splitlines():
        if raw.startswith(("    ", "\t")):
            continue
        stripped = raw.lstrip()
        if stripped.startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if fenced or stripped.startswith(">"):
            continue
        candidate = re.sub(r"^(?:[-*]\s+)?(?:#{1,6}\s+)?", "", stripped)
        if candidate.startswith("**") and candidate.endswith("**") and len(candidate) > 4:
            candidate = candidate[2:-2]
        elif candidate.startswith("**"):
            candidate = re.sub(r"^\*\*(Next steps?)\*\*", r"\1", candidate,
                               flags=re.IGNORECASE)
        match = NEXT_STEPS.fullmatch(candidate.strip())
        if match:
            next_steps_present = True
            none_marker = bool(NONE_MARKER.match((match.group(1) or "").strip()))
        if NEXT_ACTION.match(candidate.strip()):
            next_action_present = True
    if next_steps_present or next_action_present:
        return {"next_steps_present": next_steps_present, "none_marker": none_marker,
                "next_action_present": next_action_present, "missing_candidate": False,
                "lexical_observation": "heading_present" if next_steps_present else "next_action_present"}
    letters = [ch for ch in answer if ch.isalpha()]
    non_latin = sum("LATIN" not in unicodedata.name(ch, "") for ch in letters)
    non_english = bool(letters) and non_latin > len(letters) / 2
    return {"next_steps_present": False, "none_marker": False, "next_action_present": False,
            "missing_candidate": None if non_english else True,
            "lexical_observation": "unknown_language" if non_english else "heading_absent_candidate"}


def is_subagent(meta):
    source = meta.get("source")
    return bool(meta.get("subagent") or (isinstance(source, dict) and source.get("subagent")))


def is_known_root(meta):
    return meta.get("source") in ("cli", "vscode", "desktop", "exec")


def inspect_file(path, include_text, include_exec):
    """Hold only one file's compact turn state; reject its candidates on any corruption."""
    turns = {}
    session_meta = None
    current_turn = None
    latest_started = None
    malformed = 0
    truncated = False
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, raw in enumerate(handle, 1):
                if not raw.endswith("\n"):
                    truncated = True
                try:
                    record = json.loads(raw)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    malformed += 1
                    continue
                if not isinstance(record, dict) or not isinstance(record.get("payload"), dict):
                    malformed += 1
                    continue
                kind, payload = record.get("type"), record["payload"]
                if kind == "session_meta":
                    session_meta = payload
                    continue
                if kind == "turn_context" and isinstance(payload.get("turn_id"), str):
                    current_turn = payload["turn_id"]
                    turns.setdefault(current_turn, {"final": None, "terminal": None})
                    continue
                if kind == "event_msg" and payload.get("type") in (
                        "task_started", "task_complete", "task_aborted"):
                    turn_id = payload.get("turn_id")
                    if not isinstance(turn_id, str):
                        malformed += 1
                        continue
                    current_turn = turn_id
                    turn = turns.setdefault(turn_id, {"final": None, "terminal": None})
                    if payload["type"] == "task_started":
                        latest_started = turn_id
                        turn["final"] = None
                        turn["terminal"] = None
                    else:
                        turn["terminal"] = (payload["type"], record.get("timestamp"),
                                            line_number)
                    continue
                if kind == "response_item" and explicit_final(payload):
                    metadata = record.get("metadata") or {}
                    turn_id = metadata.get("turn_id") if isinstance(metadata, dict) else None
                    turn_id = turn_id if isinstance(turn_id, str) else current_turn
                    if not turn_id:
                        malformed += 1
                        continue
                    text = response_text(payload)
                    turns.setdefault(turn_id, {"final": None, "terminal": None})["final"] = (
                        text, line_number, record.get("timestamp"))
    except (OSError, UnicodeDecodeError) as error:
        return [], [{"source_path": str(path), "source": None,
                     "reason": "unreadable_file",
                     "error_type": type(error).__name__}], malformed

    if malformed or truncated:
        return [], [{"source_path": str(path),
                     "source": session_meta.get("source") if session_meta else None,
                     "reason": "malformed_jsonl" if malformed else "truncated_jsonl"}], malformed
    if not session_meta or not isinstance(session_meta.get("id"), str):
        return [], [{"source_path": str(path), "source": None,
                     "reason": "missing_session_meta"}], malformed
    session_id = session_meta["id"]
    source = session_meta.get("source")
    if is_subagent(session_meta):
        return [], [{"source_path": str(path), "session_id": session_id,
                     "source": source, "reason": "subagent_session"}], malformed
    if not is_known_root(session_meta):
        return [], [{"source_path": str(path), "session_id": session_id,
                     "source": source, "reason": "unknown_session_source"}], malformed
    if source == "exec" and not include_exec:
        return [], [{"source_path": str(path), "session_id": session_id,
                     "source": source, "reason": "headless_exec_session"}], malformed
    if latest_started and turns[latest_started]["terminal"] is None:
        return [], [{"source_path": str(path), "session_id": session_id,
                     "source": source, "turn_id": latest_started,
                     "reason": "active_session"}], malformed

    selected, skipped = [], []
    for turn_id, turn in turns.items():
        base = {"source_path": str(path), "session_id": session_id,
                "source": source, "turn_id": turn_id}
        terminal = turn["terminal"]
        if terminal is None:
            skipped.append({**base, "reason": "active_turn"})
        elif terminal[0] == "task_aborted":
            skipped.append({**base, "reason": "aborted_turn"})
        elif (turn["final"] is None or not turn["final"][0]
              or turn["final"][1] > terminal[2]):
            skipped.append({**base, "reason": "missing_final"})
        else:
            answer, line, timestamp = turn["final"]
            item = {**base, "line": line, "timestamp": timestamp,
                    "completion_status": "needs_human_review", **observe_next_steps(answer)}
            if include_text:
                item["text"] = answer
            selected.append((terminal[1] or timestamp or "", item))
    return selected, skipped, malformed


def audit(root, limit, excluded, include_text, include_exec, max_files):
    report = {"audit_type": "offline_codex_completion_shadow",
              "boundary": "Lexical observations only; completed work and correctness require human review.",
              "discovered_files": 0, "inspected_files": 0, "not_inspected_files": 0,
              "eligible_completed_count": 0, "not_selected_due_limit": 0,
              "skipped_count": 0, "skipped": [],
              "skipped_details_truncated": False, "malformed_lines": 0,
              "selected_count": 0, "turns": []}
    recent = []
    paths = sorted(root.rglob("*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)
    report["discovered_files"] = len(paths)
    report["not_inspected_files"] = max(0, len(paths) - max_files)
    paths = paths[:max_files]
    for path in paths:
        report["inspected_files"] += 1
        candidates, skipped, malformed = inspect_file(path, include_text, include_exec)
        report["malformed_lines"] += malformed
        for item in skipped:
            report["skipped_count"] += 1
            if len(report["skipped"]) < SKIPPED_DETAIL_LIMIT:
                report["skipped"].append(item)
            else:
                report["skipped_details_truncated"] = True
        for timestamp, item in candidates:
            if item["session_id"] in excluded:
                report["skipped_count"] += 1
                if len(report["skipped"]) < SKIPPED_DETAIL_LIMIT:
                    report["skipped"].append({"source_path": item["source_path"],
                                               "session_id": item["session_id"],
                                               "source": item["source"],
                                               "turn_id": item["turn_id"],
                                               "reason": "excluded_session"})
                else:
                    report["skipped_details_truncated"] = True
                continue
            report["eligible_completed_count"] += 1
            key = (timestamp, item["source_path"], item["line"])
            if len(recent) < limit:
                heapq.heappush(recent, (key, item))
            elif key > recent[0][0]:
                heapq.heapreplace(recent, (key, item))
    report["turns"] = [item for _, item in sorted(recent, reverse=True)]
    report["selected_count"] = len(report["turns"])
    report["not_selected_due_limit"] = report["eligible_completed_count"] - report["selected_count"]
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions-root", type=Path, required=True,
                        help="Explicit local Codex sessions directory")
    parser.add_argument("--limit", type=positive_int, default=10,
                        help="Maximum recent completed root turns (default: 10)")
    parser.add_argument("--max-files", type=positive_int, default=100,
                        help="Maximum newest files inspected (default: 100)")
    parser.add_argument("--exclude-session", action="append", default=[],
                        help="Session ID to exclude; may be repeated")
    parser.add_argument("--include-text", action="store_true",
                        help="Include final reply text in JSON (off by default)")
    parser.add_argument("--include-exec", action="store_true",
                        help="Include headless source=exec sessions (off by default)")
    args = parser.parse_args()
    if not args.sessions_root.is_dir():
        parser.error("--sessions-root must be an existing directory")
    json.dump(audit(args.sessions_root, args.limit, set(args.exclude_session),
                    args.include_text, args.include_exec, args.max_files),
              sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
