#!/usr/bin/env python3
"""Focused discovery tests for live and archived Codex rollouts."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "sessions.py"
SPEC = importlib.util.spec_from_file_location("codex_sessions", SCRIPT)
assert SPEC and SPEC.loader
SESSIONS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SESSIONS
SPEC.loader.exec_module(SESSIONS)


def write_rollout(root: Path, sid: str, title: str, source: object = "vscode") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"rollout-2026-08-23T00-00-00-{sid}.jsonl"
    payload = {
        "timestamp": "2026-08-23T00:00:00Z",
        "type": "session_meta",
        "payload": {
            "id": sid,
            "timestamp": "2026-08-23T00:00:00Z",
            "cwd": "/tmp/project",
            "thread_name": title,
            "originator": "Codex Desktop",
            "source": source,
        },
    }
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    return path


class ArchivedSessionDiscoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.live = root / "sessions"
        self.archived = root / "archived_sessions"
        self.index = root / "session_index.jsonl"
        self.index.write_text("", encoding="utf-8")

        self.original_live = SESSIONS.SESSIONS_ROOT
        self.original_index = SESSIONS.INDEX_PATH
        self.had_archived = hasattr(SESSIONS, "ARCHIVED_SESSIONS_ROOT")
        self.original_archived = getattr(SESSIONS, "ARCHIVED_SESSIONS_ROOT", None)
        SESSIONS.SESSIONS_ROOT = self.live
        SESSIONS.ARCHIVED_SESSIONS_ROOT = self.archived
        SESSIONS.INDEX_PATH = self.index

    def tearDown(self) -> None:
        SESSIONS.SESSIONS_ROOT = self.original_live
        SESSIONS.INDEX_PATH = self.original_index
        if self.had_archived:
            SESSIONS.ARCHIVED_SESSIONS_ROOT = self.original_archived
        else:
            delattr(SESSIONS, "ARCHIVED_SESSIONS_ROOT")
        self.temp.cleanup()

    def test_transcript_roots_are_ordered_live_then_archived(self) -> None:
        live_path = write_rollout(self.live, "live-session-id", "Live")
        archived_path = write_rollout(self.archived, "archived-session-id", "Archived")

        self.assertEqual(SESSIONS.build_transcript_paths(), [live_path, archived_path])

    def test_sid_resolution_finds_archives_but_prefers_live_duplicate(self) -> None:
        archived_only = write_rollout(self.archived, "archive-only-id", "Archived only")
        self.assertEqual(
            SESSIONS.find_transcript_for_session("archive-only-id", {}, {}),
            archived_only,
        )

        live = write_rollout(self.live, "duplicate-session-id", "Live duplicate")
        write_rollout(self.archived, "duplicate-session-id", "Archived duplicate")
        self.assertEqual(
            SESSIONS.find_transcript_for_session("duplicate-session-id", {}, {}),
            live,
        )

    def test_default_list_includes_archive_only_record_with_archived_label(self) -> None:
        write_rollout(self.archived, "archive-list-id", "Archived task")

        records = SESSIONS.collect_sessions(None, None)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].sid, "archive-list-id")
        self.assertEqual(records[0].title, "Archived task")
        self.assertTrue(records[0].archived)
        self.assertEqual(records[0].status, "archived")

    def test_default_list_excludes_archived_subagent_rollouts(self) -> None:
        write_rollout(self.archived, "archive-root-id", "Archived root")
        write_rollout(
            self.archived,
            "archive-child-id",
            "Archived child",
            source={"subagent": {"thread_spawn": {"parent_thread_id": "archive-root-id"}}},
        )

        records = SESSIONS.collect_sessions(None, None)

        self.assertEqual([record.sid for record in records], ["archive-root-id"])

    def test_survey_sid_resolves_archive_before_applying_limit(self) -> None:
        self.index.write_text(
            json.dumps(
                {
                    "id": "newer-unrelated-id",
                    "thread_name": "Newer unrelated task",
                    "updated_at": "2026-08-24T00:00:00Z",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        archived = write_rollout(
            self.archived,
            "archive-survey-id",
            "Archived survey task",
        )
        output = io.StringIO()

        with patch.object(
            sys,
            "argv",
            [str(SCRIPT), "survey", "--sid", "archive-survey", "--limit", "1"],
        ), redirect_stdout(output):
            SESSIONS.main()

        rendered = output.getvalue()
        self.assertIn("archive-survey-id", rendered)
        self.assertIn(str(archived), rendered)
        self.assertNotIn("not found", rendered)

    def test_survey_sid_bypasses_global_session_collection(self) -> None:
        write_rollout(self.archived, "archive-direct-id", "Archived direct task")
        output = io.StringIO()

        with patch.object(
            sys,
            "argv",
            [str(SCRIPT), "survey", "--sid", "archive-direct"],
        ), patch.object(
            SESSIONS,
            "collect_sessions",
            side_effect=AssertionError("explicit SID must not scan every session"),
        ), redirect_stdout(output):
            SESSIONS.main()

        self.assertIn("archive-direct-id", output.getvalue())


if __name__ == "__main__":
    unittest.main()
