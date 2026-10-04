#!/usr/bin/env python3
"""Post-hoc per-lane spend: sum token usage per `ROLE: <label>` over a Workflow run's agent transcripts.

Usage:  python3 lane_spend.py <workflow run dir>   ->  writes <dir>/lane-spend.json and prints it

Every spec-review lane prompt starts with a fixed `ROLE: <label>` line. This reads each
`agent-*.jsonl` in the run dir (JSON parsing, never grep), takes the ROLE from the first user
message, and sums input + cache_read + cache_creation + output tokens (a message id seen on several
streamed lines counts once, at its largest usage). Zero saving by itself: it exists so the costliest
Claude lanes can be moved to Codex with evidence.
"""
import json
import re
import sys
from pathlib import Path

USAGE_KEYS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens")
ROLE_RE = re.compile(r"^\s*ROLE:\s*(\S+)", re.M)


def first_user_text(records):
    for rec in records:
        msg = rec.get("message") if isinstance(rec.get("message"), dict) else rec
        if rec.get("type") != "user" and msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def agent_usage(records):
    best = {}
    for i, rec in enumerate(records):
        msg = rec.get("message")
        if not isinstance(msg, dict) or not isinstance(msg.get("usage"), dict):
            continue
        key = msg.get("id") or f"line-{i}"
        total = {k: int(msg["usage"].get(k) or 0) for k in USAGE_KEYS}
        if key not in best or sum(total.values()) >= sum(best[key].values()):
            best[key] = total
    return {k: sum(u[k] for u in best.values()) for k in USAGE_KEYS}


def load(path):
    out = []
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def lane_spend(run_dir):
    roles = {}
    for path in sorted(Path(run_dir).glob("agent-*.jsonl")):
        records = load(path)
        m = ROLE_RE.search(first_user_text(records))
        role = m.group(1) if m else "UNLABELED"
        usage = agent_usage(records)
        row = roles.setdefault(role, {"agents": 0, **{k: 0 for k in USAGE_KEYS}, "total": 0})
        row["agents"] += 1
        for k in USAGE_KEYS:
            row[k] += usage[k]
        row["total"] += sum(usage.values())
    return dict(sorted(roles.items(), key=lambda kv: -kv[1]["total"]))


def main(argv):
    if len(argv) != 2 or not Path(argv[1]).is_dir():
        print("usage: lane_spend.py <workflow run dir>", file=sys.stderr)
        return 1
    result = lane_spend(argv[1])
    Path(argv[1], "lane-spend.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
