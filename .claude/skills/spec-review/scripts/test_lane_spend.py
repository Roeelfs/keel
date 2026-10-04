#!/usr/bin/env python3
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lane_spend  # noqa: E402


def write_agent(d, name, prompt, usages):
    recs = [{"type": "user", "message": {"role": "user", "content": prompt}}]
    for mid, u in usages:
        recs.append({"type": "assistant", "message": {"id": mid, "role": "assistant", "usage": u}})
    (Path(d) / f"agent-{name}.jsonl").write_text("\n".join(json.dumps(r) for r in recs))


class LaneSpendTests(unittest.TestCase):
    def test_sums_per_role_and_dedupes_streamed_messages(self):
        with tempfile.TemporaryDirectory() as d:
            u = lambda i, cr, cc, o: {"input_tokens": i, "cache_read_input_tokens": cr, "cache_creation_input_tokens": cc, "output_tokens": o}
            write_agent(d, "a", "ROLE: edge-case-miner\nbrief", [("m1", u(1, 100, 10, 5)), ("m1", u(1, 100, 10, 50)), ("m2", u(2, 200, 0, 7))])
            write_agent(d, "b", "ROLE: edge-case-miner\nbrief", [("m1", u(1, 1, 1, 1))])
            write_agent(d, "c", [{"type": "text", "text": "no label here"}], [("m1", u(3, 0, 0, 0))])
            (Path(d) / "agent-d.jsonl").write_text("not json\n")
            out = lane_spend.lane_spend(d)
            self.assertEqual(out["edge-case-miner"]["agents"], 2)
            self.assertEqual(out["edge-case-miner"]["total"], (1 + 100 + 10 + 50) + (2 + 200 + 7) + 4)
            self.assertEqual(out["UNLABELED"]["total"], 3)
            self.assertIn("UNLABELED", out)

    def test_main_writes_file(self):
        with tempfile.TemporaryDirectory() as d:
            write_agent(d, "a", "ROLE: codex-envelope-extractor\n", [("m", {"input_tokens": 4, "output_tokens": 1})])
            self.assertEqual(lane_spend.main(["x", d]), 0)
            self.assertEqual(json.loads((Path(d) / "lane-spend.json").read_text())["codex-envelope-extractor"]["total"], 5)


if __name__ == "__main__":
    unittest.main()
