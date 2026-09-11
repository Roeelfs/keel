#!/usr/bin/env python3
"""Regressions for stale native history and misleading rollout liveness."""

import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "sessions.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("activity_sessions", SCRIPT)
SESSIONS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SESSIONS
SPEC.loader.exec_module(SESSIONS)

BASE = "2026-09-01T12:"
SID = "11111111-1111-7111-8111-111111111111"
ALIAS = "22222222-2222-7222-8222-222222222222"


def event(time, kind, **payload):
    return {"timestamp": BASE + time + "Z", "type": "event_msg",
            "payload": {"type": kind, **payload}}


def command(time="03:00", ident="cmd-1"):
    return event(time, "item_completed", item={
        "type": "CommandExecution", "id": ident, "status": "completed",
        "command": ["/bin/sh", "-c", "git status --short"], "exit_code": 0,
    })


def wait_event(cursor="frozen:1", changed=False):
    return event("04:00", "item_completed", item={
        "type": "McpToolCall", "id": "wait-" + cursor, "server": "codex_app",
        "tool": "wait_threads", "status": "completed",
        "arguments": {"targets": [{"threadId": "worker", "afterCursor": cursor}]},
        "result": {"content": [{"type": "text", "text": json.dumps({
            "timedOut": True, "polls": [{
                "cursor": cursor, "changed": changed,
                "thread": {"id": "worker"},
                "latestTurn": {"status": "inProgress"},
            }],
        })}]},
    })


class ActivityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.live = self.root / "sessions"
        self.live.mkdir()
        self.path = self.live / ("rollout-2026-09-01T12-00-00-" + SID + ".jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, *events, history_mode=None, history_base=None, alias=None):
        if alias:
            self.path = self.live / (
                "rollout-2026-09-01T12-00-00-" + SID + "_" + alias + ".jsonl"
            )
        header = {"timestamp": BASE + "00:00Z", "type": "session_meta",
                  "payload": {"id": SID, "thread_name": "Example task",
                              "timestamp": BASE + "00:00Z", "source": "vscode",
                              "history_mode": history_mode,
                              "history_base": history_base}}
        self.path.write_text("\n".join(json.dumps(x) for x in [header, *events]) + "\n")
        return SESSIONS.parse_transcript(self.path, SID).to_summary()

    def native_db(self, turn="old-turn", item=None, thread_id=SID):
        db = self.root / "thread_history_1.sqlite"
        with closing(sqlite3.connect(db)) as c, c:
            c.execute("CREATE TABLE IF NOT EXISTS thread_turns(thread_id TEXT, turn_id TEXT, rollout_ordinal INTEGER, status TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS thread_items(thread_id TEXT, item_id TEXT)")
            c.execute("INSERT INTO thread_turns VALUES(?,?,1,'inProgress')", (thread_id, turn))
            if item:
                c.execute("INSERT INTO thread_items VALUES(?,?)", (thread_id, item))
        return db

    def survey(self):
        with patch.object(SESSIONS, "SESSIONS_ROOT", self.live), patch.object(
            SESSIONS, "ARCHIVED_SESSIONS_ROOT", self.root / "archived_sessions"
        ):
            return SESSIONS.collect_session_by_sid(SID)[0].to_summary()

    def test_new_completion_wins_over_orphaned_old_turn_and_fresh_file(self):
        r = self.write(
            event("00:01", "task_started", turn_id="orphan"),
            event("01:00", "task_started", turn_id="current"),
            event("02:00", "task_complete", turn_id="current", last_agent_message="Done"),
        )
        self.assertEqual(r["status"], "complete")
        self.assertEqual(r["open_turns"], 0)

    def test_interruption_is_terminal_even_when_rollout_was_just_written(self):
        r = self.write(event("00:01", "task_started", turn_id="current"),
                       event("01:00", "turn_aborted", turn_id="current", reason="interrupted"))
        self.assertEqual(r["status"], "interrupted")
        self.assertEqual(r["open_turns"], 0)

    def test_late_old_completion_does_not_close_new_turn(self):
        r = self.write(event("00:01", "task_started", turn_id="old"),
                       event("01:00", "task_started", turn_id="current"),
                       event("02:00", "task_complete", turn_id="old"), command())
        self.assertEqual(r["status"], "active")
        self.assertEqual(r["latest_turn_id"], "current")

    def test_new_tool_completion_updates_activity_and_readable_timeline(self):
        r = self.write(event("00:01", "task_started", turn_id="current"), command())
        self.assertEqual(r["updated_at"], SESSIONS.ts_from_iso(BASE + "03:00Z"))
        self.assertEqual(r["last_tool_event"]["name"], "commandExecution")
        self.assertEqual(r["last_tool_event"]["exit_code"], 0)
        self.assertIn("git status", r["timeline_tail"][-1]["text"])

    def test_unchanged_wait_survives_intervening_diagnostic_command(self):
        r = self.write(event("00:01", "task_started", turn_id="current"),
                       wait_event(), command("04:01"), wait_event())
        self.assertEqual(r["last_wait"]["unchanged_count"], 2)
        self.assertEqual(r["last_wait"]["targets"], ["worker"])
        self.assertIn("not evidence of progress", r["last_wait"]["warning"])

    def test_changed_wait_resets_unchanged_counter(self):
        r = self.write(wait_event(), wait_event(), wait_event("fresh:2", changed=True))
        self.assertEqual(r["last_wait"]["unchanged_count"], 0)

    def test_native_history_behind_is_reported_without_writing_database(self):
        self.write(event("01:00", "task_started", turn_id="current"), command())
        db = self.native_db()
        before = db.read_bytes()
        r = self.survey()
        self.assertEqual(r["native_history"]["status"], "behind")
        self.assertEqual(r["native_history"]["rollout_turn_id"], "current")
        self.assertEqual(r["native_history"]["indexed_turn_id"], "old-turn")
        self.assertEqual(db.read_bytes(), before)

    def test_matching_turn_with_missing_item_is_still_behind(self):
        self.write(event("01:00", "task_started", turn_id="current"), command())
        self.native_db(turn="current")
        self.assertEqual(self.survey()["native_history"]["status"], "behind")

    def test_matching_projection_is_current(self):
        self.write(event("01:00", "task_started", turn_id="current"), command())
        self.native_db(turn="current", item="cmd-1")
        self.assertEqual(self.survey()["native_history"]["status"], "current")

    def test_paginated_alias_uses_current_rollout_projection_not_frozen_thread_history(self):
        self.write(event("01:00", "task_started", turn_id="current"), command(),
                   history_mode="paginated", history_base={"thread_id": SID}, alias=ALIAS)
        self.native_db(turn="old-turn", item="cmd-1")
        self.native_db(turn="current", item="cmd-1", thread_id=ALIAS)
        history = self.survey()["native_history"]
        self.assertEqual(history["status"], "current")
        self.assertEqual(history["indexed_rollout_id"], ALIAS)

    def test_paginated_single_uuid_filename_with_history_base_uses_logical_projection(self):
        self.write(event("01:00", "task_started", turn_id="current"),
                   history_mode="paginated", history_base={"thread_id": SID})
        self.native_db(turn="current")
        history = self.survey()["native_history"]
        self.assertEqual(history["status"], "current")
        self.assertEqual(history["indexed_rollout_id"], SID)

    def test_paginated_malformed_underscore_alias_is_unavailable(self):
        self.path = self.live / (
            "rollout-2026-09-01T12-00-00-" + SID + "_not-a-rollout-id.jsonl"
        )
        self.write(event("01:00", "task_started", turn_id="current"),
                   history_mode="paginated", history_base={"thread_id": SID})
        self.native_db(turn="current", thread_id=ALIAS)
        history = self.survey()["native_history"]
        self.assertEqual(history["status"], "unavailable")
        self.assertEqual(history["reason"], "Malformed paginated rollout identity")

    def test_partial_tail_and_missing_index_do_not_hide_completed_turn(self):
        self.write(event("01:00", "task_started", turn_id="current"),
                   event("02:00", "task_complete", turn_id="current"))
        with self.path.open("a") as f:
            f.write('{"timestamp":')
        r = self.survey()
        self.assertEqual(r["status"], "complete")
        self.assertEqual(r["native_history"]["status"], "unavailable")

    def test_late_old_tool_does_not_become_current_turn_progress(self):
        old_tool = command()
        old_tool["payload"]["turn_id"] = "old"
        r = self.write(event("00:01", "task_started", turn_id="old"),
                       event("01:00", "task_started", turn_id="current"), old_tool)
        self.assertEqual(r["latest_turn_id"], "current")
        self.assertIsNone(r["last_tool_event"])

    def test_new_turn_does_not_inherit_prior_tools_or_wait_count(self):
        r = self.write(event("00:01", "task_started", turn_id="old"),
                       command(), wait_event(), wait_event(),
                       event("05:00", "task_started", turn_id="current"))
        self.assertIsNone(r["last_tool_event"])
        self.assertIsNone(r["last_wait"])

    def test_malformed_wait_does_not_truncate_later_terminal_record(self):
        malformed = wait_event()
        malformed["payload"]["item"]["result"]["content"][0]["text"] = json.dumps({
            "polls": [{"thread": "invalid shape", "changed": False}], "timedOut": True,
        })
        r = self.write(event("00:01", "task_started", turn_id="current"),
                       malformed, event("05:00", "task_complete", turn_id="current"))
        self.assertEqual(r["status"], "complete")


if __name__ == "__main__":
    unittest.main()
