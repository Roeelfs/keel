#!/usr/bin/env python3
"""SubagentStart/Stop acceptance telemetry. SHADOW ONLY: never emits a block.

Start records HEADs keyed by parent session + agent id. Stop accepts explicit
Role: implementation / Class: implementation in the lane's first user message,
or agent_type=implementation. Research/unclassified lanes are observational.
Unknown event/transcript shapes are logged as unproven, never inferred as success.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
# lane_commit_guard lives beside the machine's scripts or in keel's bin/ (this file's clone).
for _d in (_HERE.parent / "scripts", _HERE.parent.parent / "bin", Path.home() / ".claude" / "scripts"):
    if (_d / "lane_commit_guard.py").exists():
        sys.path.insert(0, str(_d))
        break
from lane_commit_guard import evidence, snapshot

IMPLEMENTATION = re.compile(r"^\s*(?:Role|Class):\s*implementation\b", re.I | re.M)


def transcript(path):
    records = []
    if not path:
        return records
    with open(path) as stream:
        for line in stream:
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict):
                records.append(value)
    return records


def user_text(record):
    message = record.get("message") or {}
    content = message.get("content", "") if isinstance(message, dict) else ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(block.get("text", "") for block in content
                         if isinstance(block, dict) and block.get("type") == "text")
    return ""


def evaluate(event, before, records):
    first_user = next((r for r in records if r.get("type") == "user"), {})
    implementation = (event.get("agent_type") == "implementation"
                      or bool(IMPLEMENTATION.search(user_text(first_user))))
    final = next((r for r in reversed(records) if r.get("type") == "result"), {})
    reasons = ["is_error"] if final.get("is_error") is True else []
    result = {}
    if implementation:
        if before is None:
            return {"would_block": reasons, "unproven": "missing_start", "class": "implementation"}
        actual = next((r["cwd"] for r in reversed(records) if isinstance(r.get("cwd"), str)), None)
        result = evidence(before, event["cwd"], actual)
        if not result["committed"]:
            reasons.append("zero_commit")
    return {**result, "class": "implementation" if implementation else "other",
            "would_block": reasons}


def main():
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict) or event.get("hook_event_name") not in ("SubagentStart", "SubagentStop"):
            return 0
        if not event.get("agent_id") or not event.get("session_id"):
            return 0
        base = Path(os.environ.get("LANE_ACCEPTANCE_HOME", Path.home() / ".claude"))
        state = base / "state" / "lane-acceptance"
        state.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256((event["session_id"] + ":" + event["agent_id"]).encode()).hexdigest()
        path = state / (key + ".json")
        if event["hook_event_name"] == "SubagentStart":
            path.write_text(json.dumps(snapshot(event["cwd"])))
            return 0
        before = json.loads(path.read_text()) if path.exists() else None
        result = evaluate(event, before, transcript(event.get("agent_transcript_path")))
        row = {"ts": datetime.now(timezone.utc).isoformat(), "mode": "shadow",
               "session_id": event["session_id"], "agent_id": event["agent_id"], **result}
        log = base / "analytics" / "lane-acceptance.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a") as stream:
            stream.write(json.dumps(row) + "\n")
        path.unlink(missing_ok=True)
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        print("lane-acceptance-shadow: unproven: %s" % exc, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
