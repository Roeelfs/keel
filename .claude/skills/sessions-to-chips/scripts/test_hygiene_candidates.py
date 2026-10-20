#!/usr/bin/env python3
"""Tests for hygiene_candidates.classify. Run: python3 -I test_hygiene_candidates.py"""
import datetime, os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hygiene_candidates import classify, ticket_keys

NOW = datetime.datetime(2026, 10, 20, 12, 0, 0)


def row(sid, title, parent="M", branch="", pr=None, state=None, hours_ago=5.0, wt="", archived=False):
    ts = (NOW - datetime.timedelta(hours=hours_ago)).isoformat()
    return {"sessionId": sid, "title": title, "parentSessionId": parent, "branch": branch,
            "pr": pr, "prState": state, "archived": archived, "lastActivityAt": ts,
            "worktree": wt}


MANAGER = row("M", "[Manager] Apps", parent="", wt="/wt/manager")


def ids(items):
    return sorted(i["sessionId"] for i in items)


class Classify(unittest.TestCase):
    def test_merged_idle_child_is_archived(self):
        out = classify([MANAGER, row("a", "Build X", pr=1, state="MERGED")], "M", NOW)
        self.assertEqual(ids(out["archive"]), ["a"])

    def test_merged_but_recent_child_is_kept(self):
        out = classify([MANAGER, row("a", "Build X", pr=1, state="MERGED", hours_ago=0.2)], "M", NOW)
        self.assertEqual(out["archive"], [])
        self.assertEqual(ids(out["keep"]), ["a"])

    def test_open_pr_is_kept(self):
        out = classify([MANAGER, row("a", "Build X", pr=1, state="OPEN", hours_ago=48)], "M", NOW)
        self.assertEqual(ids(out["keep"]), ["a"])

    def test_merged_parent_with_live_child_is_not_archived(self):
        # Archiving a parent cascades to its finished children; never propose it while a
        # descendant is still live.
        rows = [MANAGER, row("a", "Build X", pr=1, state="MERGED"),
                row("b", "Bake X", parent="a", hours_ago=0.1)]
        out = classify(rows, "M", NOW)
        self.assertNotIn("a", ids(out["archive"]))

    def test_stale_no_pr_child_goes_to_review(self):
        out = classify([MANAGER, row("a", "Research Y", hours_ago=30)], "M", NOW)
        self.assertEqual(ids(out["review"]), ["a"])

    def test_shared_ticket_converges_and_open_pr_survives(self):
        rows = [MANAGER,
                row("a", "ABC-12 spec", hours_ago=2),
                row("b", "Build", branch="feat/abc-12-impl", pr=7, state="OPEN", hours_ago=3)]
        out = classify(rows, "M", NOW)
        self.assertEqual(len(out["converge"]), 1)
        self.assertEqual(out["converge"][0]["survivor"]["sessionId"], "b")
        self.assertEqual(ids(out["converge"][0]["fold"]), ["a"])
        self.assertIn("ticket:ABC-12", out["converge"][0]["keys"])

    def test_shared_worktree_converges_but_manager_worktree_does_not(self):
        rows = [MANAGER,
                row("a", "Bake one", wt="/wt/manager", hours_ago=2),
                row("b", "Bake two", wt="/wt/manager", hours_ago=2),
                row("c", "Fix A", wt="/wt/x", hours_ago=2),
                row("d", "Fix A again", wt="/wt/x", hours_ago=2)]
        out = classify(rows, "M", NOW)
        self.assertEqual(len(out["converge"]), 1)
        group = out["converge"][0]
        self.assertEqual(sorted([group["survivor"]["sessionId"]] + ids(group["fold"])), ["c", "d"])

    def test_foreign_and_archived_sessions_are_out_of_scope(self):
        rows = [MANAGER, row("x", "Other", parent="OTHER", pr=1, state="MERGED"),
                row("y", "Gone", pr=2, state="MERGED", archived=True)]
        out = classify(rows, "M", NOW)
        self.assertEqual(out["counts"]["family"], 0)

    def test_nested_manager_family_belongs_to_the_nested_manager(self):
        rows = [MANAGER, row("N", "[Manager] Sub", hours_ago=0.1),
                row("c", "Sub child", parent="N", pr=4, state="MERGED")]
        out = classify(rows, "M", NOW)
        self.assertEqual(out["counts"]["family"], 0)
        self.assertEqual(ids(classify(rows, "N", NOW)["archive"]), ["c"])

    def test_grandchildren_are_in_scope(self):
        rows = [MANAGER, row("a", "Lane", hours_ago=0.1), row("b", "Sub", parent="a", pr=3, state="MERGED")]
        out = classify(rows, "M", NOW)
        self.assertEqual(ids(out["archive"]), ["b"])

    def test_manager_resolves_by_cli_id(self):
        from hygiene_candidates import resolve_manager
        m = dict(MANAGER, cli="cli-M", account="a")
        self.assertEqual(resolve_manager([m], "cli-M")["sessionId"], "M")


class TicketKeys(unittest.TestCase):
    def test_ignores_hashes_and_ship_labels(self):
        self.assertEqual(ticket_keys({"title": "K-1 B4 ship 2", "branch": "claude/funny-darwin-2c9cf4"}), set())

    def test_reads_title_and_branch(self):
        self.assertEqual(ticket_keys({"title": "CYN-2898 H2: spec", "branch": "claude/cyn-2898-h2-51d9e0"}),
                         {"CYN-2898"})


if __name__ == "__main__":
    unittest.main()
