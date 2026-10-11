"""Focused, synthetic tests for the read-only Codex completion shadow audit."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("codex_completion_audit.py")


def record(kind, payload, timestamp="2026-10-11T12:00:00Z", **extra):
    return {"timestamp": timestamp, "type": kind, "payload": payload, **extra}


def turn(turn_id, answer=None, *, terminal="task_complete", phase="final_answer", duplicate=False):
    lines = [record("event_msg", {"type": "task_started", "turn_id": turn_id}),
             record("turn_context", {"turn_id": turn_id})]
    if answer is not None:
        if duplicate:
            lines.append(record("event_msg", {"type": "agent_message", "message": answer}))
        lines.append(record("response_item", {"type": "message", "role": "assistant",
                                              "phase": phase, "content": [{"type": "output_text", "text": answer}]},
                            metadata={"turn_id": turn_id}))
    if terminal:
        lines.append(record("event_msg", {"type": terminal, "turn_id": turn_id},
                            timestamp="2026-10-11T12:00:01Z"))
    return lines


class CompletionAuditTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name, lines, *, source="vscode", session_id=None):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        session_id = session_id or name.removesuffix(".jsonl")
        all_lines = [record("session_meta", {"id": session_id, "source": source})] + lines
        path.write_text("\n".join(json.dumps(line) for line in all_lines) + "\n")
        return path

    def run_audit(self, *args):
        proc = subprocess.run([sys.executable, str(SCRIPT), "--sessions-root", str(self.root), *args],
                              text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_completed_root_turn_observes_explicit_next_steps_without_leaking_text(self):
        path = self.write("root.jsonl", turn("t1", "Done.\nNext steps: none — requested scope is complete."))
        report = self.run_audit()
        self.assertEqual(report["selected_count"], 1)
        item = report["turns"][0]
        self.assertEqual((item["source_path"], item["session_id"], item["turn_id"]),
                         (str(path), "root", "t1"))
        self.assertEqual(item["line"], 4)
        self.assertTrue(item["next_steps_present"])
        self.assertTrue(item["none_marker"])
        self.assertFalse(item["missing_candidate"])
        self.assertEqual(item["completion_status"], "needs_human_review")
        self.assertNotIn("text", item)
        self.assertIn("Next steps:", self.run_audit("--include-text")["turns"][0]["text"])

    def test_child_active_aborted_missing_and_unmarked_final_are_skipped(self):
        self.write("child.jsonl", turn("c", "Done"), source={"subagent": {"thread_spawn": {"depth": 1}}})
        self.write("root.jsonl", turn("good", "Done")
                   + turn("aborted", "Done", terminal="task_aborted")
                   + turn("missing", terminal="task_complete")
                   + turn("unmarked", "Done", phase="commentary"))
        self.write("active.jsonl", turn("active", "Next steps: none", terminal=None))
        report = self.run_audit()
        self.assertEqual([x["turn_id"] for x in report["turns"]], ["good"])
        reasons = {x["reason"] for x in report["skipped"]}
        self.assertTrue({"subagent_session", "active_session", "aborted_turn", "missing_final"} <= reasons)

    def test_duplicate_transport_is_one_turn_and_response_final_wins(self):
        self.write("root.jsonl", turn("t1", "Next steps: owner does thing", duplicate=True))
        report = self.run_audit()
        self.assertEqual(report["selected_count"], 1)
        self.assertEqual(report["turns"][0]["line"], 5)

    def test_malformed_file_is_skipped_conservatively(self):
        path = self.write("bad.jsonl", turn("t1", "Done"))
        with path.open("a") as handle:
            handle.write('{"type":')
        report = self.run_audit()
        self.assertEqual(report["selected_count"], 0)
        self.assertEqual(report["malformed_lines"], 1)
        self.assertIn("malformed_jsonl", {x["reason"] for x in report["skipped"]})

    def test_quoted_and_fenced_next_steps_are_not_counted(self):
        self.write("root.jsonl", turn("t1", "> Next steps: none\n```\nNext steps: none\n```\nDone"))
        item = self.run_audit()["turns"][0]
        self.assertFalse(item["next_steps_present"])
        self.assertTrue(item["missing_candidate"])

    def test_markdown_and_singular_headings_are_explicit_markers(self):
        for heading in ("# Next steps", "**Next steps:**", "**Next steps**", "Next step:"):
            with self.subTest(heading=heading):
                path = self.write("root.jsonl", turn("t1", f"Done\n{heading}\nOwner: check it"))
                self.assertTrue(self.run_audit()["turns"][0]["next_steps_present"])
                path.unlink()

    def test_active_latest_turn_excludes_earlier_completed_turns_in_session(self):
        self.write("root.jsonl", turn("done", "Next steps: none")
                   + turn("ongoing", "Working", terminal=None))
        report = self.run_audit()
        self.assertEqual(report["selected_count"], 0)
        self.assertIn("active_session", {item["reason"] for item in report["skipped"]})

    def test_unknown_source_is_not_certified_root(self):
        self.write("root.jsonl", turn("t1", "Done"), source={"other": "unknown"})
        report = self.run_audit()
        self.assertEqual(report["selected_count"], 0)
        self.assertIn("unknown_session_source", {item["reason"] for item in report["skipped"]})

    def test_restart_of_same_turn_clears_old_terminal_and_final(self):
        self.write("root.jsonl", turn("t1", "Next steps: none")
                   + [record("event_msg", {"type": "task_started", "turn_id": "t1"})])
        report = self.run_audit()
        self.assertEqual(report["selected_count"], 0)
        self.assertIn("active_session", {item["reason"] for item in report["skipped"]})

    def test_final_after_terminal_boundary_is_not_a_completed_reply(self):
        lines = turn("t1", terminal="task_complete")
        lines.append(record("response_item", {"type": "message", "role": "assistant",
                                              "phase": "final_answer",
                                              "content": [{"type": "output_text", "text": "Next steps: none"}]},
                            metadata={"turn_id": "t1"}))
        self.write("root.jsonl", lines)
        report = self.run_audit()
        self.assertEqual(report["selected_count"], 0)
        self.assertIn("missing_final", {item["reason"] for item in report["skipped"]})

    def test_non_english_without_marker_is_unknown(self):
        self.write("root.jsonl", turn("t1", "העבודה הושלמה. אין צעדים נוספים."))
        item = self.run_audit()["turns"][0]
        self.assertIsNone(item["missing_candidate"])
        self.assertEqual(item["lexical_observation"], "unknown_language")

    def test_headless_exec_excluded_by_default_and_opted_in_explicitly(self):
        self.write("exec.jsonl", turn("t1", "Done\nNEXT_ACTION: owner resumes"), source="exec")
        default = self.run_audit()
        self.assertEqual(default["selected_count"], 0)
        self.assertIn("headless_exec_session", {item["reason"] for item in default["skipped"]})
        included = self.run_audit("--include-exec")
        self.assertEqual(included["selected_count"], 1)
        item = included["turns"][0]
        self.assertEqual(item["source"], "exec")
        self.assertTrue(item["next_action_present"])
        self.assertFalse(item["next_steps_present"])
        self.assertFalse(item["missing_candidate"])

    def test_quoted_next_action_is_not_a_visible_handoff(self):
        self.write("root.jsonl", turn("t1", "> next_action: owner\n```\nNEXT_ACTION: owner\n```"))
        item = self.run_audit()["turns"][0]
        self.assertFalse(item["next_action_present"])
        self.assertTrue(item["missing_candidate"])

    def test_limit_and_exclude_session_select_recent_completed_turns(self):
        self.write("a.jsonl", turn("a1", "Done"), session_id="a")
        self.write("b.jsonl", turn("b1", "Done"), session_id="b")
        report = self.run_audit("--limit", "1", "--exclude-session", "b")
        self.assertEqual([x["session_id"] for x in report["turns"]], ["a"])
        self.assertIn("excluded_session", {x["reason"] for x in report["skipped"]})

    def test_explicit_channel_final_and_nullable_content(self):
        lines = turn("t1", "Next steps: owner follows up", phase="commentary")
        lines[2]["payload"].pop("phase")
        lines[2]["payload"]["channel"] = "final"
        lines += turn("t2", "placeholder")
        lines[-2]["payload"]["content"] = [{"type": "output_text", "text": None}]
        self.write("root.jsonl", lines)
        report = self.run_audit()
        self.assertEqual([item["turn_id"] for item in report["turns"]], ["t1"])
        self.assertIn("missing_final", {item["reason"] for item in report["skipped"]})

    def test_file_cap_reports_uninspected_scope_and_limit_accounting(self):
        self.write("a.jsonl", turn("a1", "Done") + turn("a2", "Done"))
        self.write("b.jsonl", turn("b1", "Done"))
        report = self.run_audit("--max-files", "1", "--limit", "1")
        self.assertEqual((report["discovered_files"], report["inspected_files"],
                          report["not_inspected_files"]), (2, 1, 1))
        self.assertEqual(report["eligible_completed_count"], 2 if report["turns"][0]["session_id"] == "a" else 1)
        self.assertEqual(report["not_selected_due_limit"],
                         report["eligible_completed_count"] - report["selected_count"])

    def test_accented_name_does_not_hide_missing_marker(self):
        self.write("root.jsonl", turn("t1", "Done for José.\nPlease check the release."))
        self.assertTrue(self.run_audit()["turns"][0]["missing_candidate"])

    def test_indented_code_is_not_a_visible_marker(self):
        self.write("root.jsonl", turn("t1", "    Next steps: none\nThe code block above is an example."))
        item = self.run_audit()["turns"][0]
        self.assertFalse(item["next_steps_present"])

    def test_structured_json_handoff_has_a_next_action(self):
        for value in ("Owner: run check", ["Owner: run check"]):
            self.write("root.jsonl", turn("t1", json.dumps({"status": "partial", "next_action": value})))
            item = self.run_audit()["turns"][0]
            self.assertTrue(item["next_action_present"])
            self.assertFalse(item["missing_candidate"])
        for value in (None, "", [], {"quoted": "not an action"}):
            self.write("root.jsonl", turn("t1", json.dumps({"next_action": value})))
            self.assertFalse(self.run_audit()["turns"][0]["next_action_present"])

    def test_limit_must_be_positive(self):
        proc = subprocess.run([sys.executable, str(SCRIPT), "--sessions-root", str(self.root),
                               "--limit", "0"], text=True, capture_output=True)
        self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
