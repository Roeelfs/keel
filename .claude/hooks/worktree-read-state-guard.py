#!/usr/bin/env python3
"""worktree-read-state-guard — PreToolUse (Edit|Write). Advisory only, never blocks.

Two arms, both about read-state that the harness cannot see:

ARM 1 — SHARED COORDINATION FILE (added 2026-08-03).
  MEMORY.md and orchestrator program state are written by MULTIPLE sessions. Per-session
  read-state is per-path and cannot detect that a *different* session rewrote the file
  since this one last read it. Measured: 9 of 22 "File has not been read yet" errors in a
  week landed on these paths; two long-running sessions made 81 and 18 edits to the same
  MEMORY.md over overlapping weeks.

ARM 2 — CROSS-WORKTREE SWITCH (2026-07-24).
  One session produced 6 read-state errors editing the same two logical files across 5
  worktree copies. Read-state is per-PATH, so a worktree switch silently invalidates it.

Non-blocking by design: cross-worktree comparison and shared-file editing are both
legitimate, so a deny would wedge real work. Silent for single-worktree sessions.

FAILS OPEN on any error. Every firing is logged to analytics/hook-precision.jsonl so the
next context-economy run can grade precision instead of assuming it.

Lives in a real .py rather than an embedded `python3 -c` block: a single apostrophe in a
comment inside such a block silently darkens the whole hook, and an unheard guard is the
failure mode this layer keeps re-earning.
"""
import datetime
import json
import os
import re
import sys

WT = re.compile(r"/\.claude/worktrees/([^/]+)/")
SHARED = re.compile(r"(/memory/MEMORY\.md|/orchestrator/programs/[^/]*\.(state\.md|json)|\.state\.md)$")
READ_ISH = ("Read", "Glob", "Grep", "TodoWrite")


def wt_of(p):
    m = WT.search(p or "")
    return m.group(1) if m else None


def log_fire(arm, path, tpath, session=""):
    """Precision ledger. Best-effort: a logging failure must never darken the guard.

    A replay is not traffic. replay-corpus.py sets session_id="replay"
    (scripts/replay-corpus.py:66), and grading a hook necessarily fires it hundreds of
    times. A precision ledger that counts its own grading runs measures nothing.
    """
    if session == "replay":
        return
    try:
        out = os.path.expanduser("~/.claude/analytics/hook-precision.jsonl")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        rec = {
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "hook": "worktree-read-state-guard",
            "arm": arm,
            "path": path,
            "session": os.path.basename(tpath),
        }
        with open(out, "a") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass


def emit(msg):
    """Two audiences, two fields — NOT a dual path.

    `systemMessage` surfaces to the HUMAN. `hookSpecificOutput.additionalContext` is the
    model-facing channel and must be nested (the binary carries the validation string
    "Did you mean hookSpecificOutput.additionalContext"). A guard meant to steer the agent
    that emits only `systemMessage` is invisible to the agent — verified first-hand
    2026-08-03: this guard fired on a real Write and the assistant received nothing.
    """
    print(json.dumps({
        "systemMessage": msg,
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": msg,
        },
    }))
    sys.exit(0)


def tool_uses(line):
    """Yield (name, file_path) for every tool_use block in a transcript line."""
    try:
        rec = json.loads(line)
    except Exception:
        return
    msg = rec.get("message") or rec
    content = msg.get("content") if isinstance(msg, dict) else None
    if not isinstance(content, list):
        return
    for b in content:
        if isinstance(b, dict) and b.get("type") == "tool_use":
            yield b.get("name"), ((b.get("input") or {}).get("file_path")) or ""


def main():
    try:
        d = json.load(sys.stdin) or {}
    except Exception:
        return

    path = (d.get("tool_input") or {}).get("file_path") or ""
    tpath = d.get("transcript_path") or ""
    session = d.get("session_id") or ""
    if not path or not tpath or not os.path.isfile(tpath):
        return

    target_wt = wt_of(path)
    is_shared = bool(SHARED.search(path))
    if not target_wt and not is_shared:
        return

    try:
        with open(tpath, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 1_500_000))
            tail = f.read().decode("utf-8", "replace")
    except Exception:
        return

    lines = tail.splitlines()[-600:]

    # ---- ARM 1: shared coordination file ----
    if is_shared:
        saw_read = False
        for ln in reversed(lines):
            stop = False
            for name, fp in tool_uses(ln):
                if name == "Read" and fp == path:
                    saw_read = True
                    stop = True
                    break
                if name not in READ_ISH:
                    stop = True
                    break
            if stop:
                break
        if not saw_read:
            log_fire("shared-coordination", path, tpath, session)
            emit(
                "SHARED COORDINATION FILE: `%s` is written by MULTIPLE sessions.\n"
                "No Read of this exact path since your last non-read tool call. Another session "
                "may have rewritten it since you last saw it, and per-session read-state cannot "
                "detect that.\n"
                "Re-Read it immediately before editing. Where a sibling `.events.jsonl` exists, "
                "prefer APPENDING an event over rewriting shared state."
                % os.path.basename(path)
            )

    # ---- ARM 2: cross-worktree switch ----
    if not target_wt:
        return

    last_wt = None
    for ln in lines:
        if "worktrees" not in ln:
            continue
        for name, fp in tool_uses(ln):
            if name in ("Edit", "Write"):
                w = wt_of(fp)
                if w:
                    last_wt = w

    if not last_wt or last_wt == target_wt:
        return

    log_fire("cross-worktree", path, tpath, session)
    emit(
        "CROSS-WORKTREE SWITCH: last edit was in `%s`, this one targets `%s`.\n"
        "Read-state does NOT carry across worktrees. Batch-Read the files in this worktree "
        "before editing, or you will hit \"File has not been read yet\" (measured: 6 such "
        "errors in one session across 5 worktree copies of the same two files).\n"
        "Standing rule: one session = one worktree = one ship."
        % (last_wt, target_wt)
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
