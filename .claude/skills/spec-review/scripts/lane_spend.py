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


def first_user_text(records, limit=3):
    """Text of the first few user messages: the Workflow harness may prepend a framing
    message before the lane prompt, so ROLE is not always in the first one."""
    texts = []
    for rec in records:
        msg = rec.get("message") if isinstance(rec.get("message"), dict) else rec
        if rec.get("type") != "user" and msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            texts.append("\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"))
        if len(texts) >= limit:
            break
    return "\n".join(texts)


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


def roles_from_files(paths, marker=None):
    """Per-ROLE token totals over agent transcripts. With `marker`, only agents whose first user
    messages mention it (the run dir, which every lane prompt names) are counted."""
    roles = {}
    for path in sorted(paths):
        records = load(path)
        head = first_user_text(records)
        if marker and marker not in head:
            continue
        m = ROLE_RE.search(head)
        role = m.group(1) if m else "UNLABELED"
        usage = agent_usage(records)
        row = roles.setdefault(role, {"agents": 0, **{k: 0 for k in USAGE_KEYS}, "total": 0})
        row["agents"] += 1
        for k in USAGE_KEYS:
            row[k] += usage[k]
        row["total"] += sum(usage.values())
    return dict(sorted(roles.items(), key=lambda kv: -kv[1]["total"]))


def lane_spend(run_dir):
    return roles_from_files(Path(run_dir).glob("agent-*.jsonl"))


def workflow_dirs(sid, projects_root=None):
    """Every Workflow run dir of this session (~/.claude/projects/<project>/<sid>/subagents/workflows/wf_*)."""
    root = Path(projects_root or Path.home() / ".claude" / "projects")
    return sorted(root.glob(f"*/{sid}/subagents/workflows/wf_*")) if sid else []


QUOTA_RE = re.compile(r"you.?ve hit your (?:\w+ )?limit|hit your (?:weekly|session|usage) limit", re.I)


def quota_hits(paths, marker=None):
    """Session/weekly-limit messages in agent transcripts. The harness writes them as a synthetic assistant
    message (model `<synthetic>`, error `rate_limit`); an agent quoting the phrase in prose never matches."""
    hits = []
    for path in sorted(paths):
        records = load(path)
        head = first_user_text(records)
        if marker and marker not in head:
            continue
        m = ROLE_RE.search(head)
        for rec in records:
            msg = rec.get("message") if isinstance(rec.get("message"), dict) else {}
            if rec.get("type") != "assistant" or not (msg.get("model") == "<synthetic>" or rec.get("error") == "rate_limit"):
                continue
            text = "\n".join(b.get("text", "") for b in msg.get("content") or [] if isinstance(b, dict))
            if QUOTA_RE.search(text):
                hits.append({"role": m.group(1) if m else "UNLABELED", "text": text.strip()[:160], "ts": rec.get("timestamp", "")})
    return hits


TOKENS_RE = re.compile(r"tokens used\s*:?\s*\n?\s*([\d,]+)", re.I)


def codex_tokens(run):
    """Tokens each Codex dispatch of the run reported (`tokens used` in its .log), keyed by out-file stem."""
    out = {}
    for log in sorted((Path(run) / "codex").glob("*.log")):
        if log.name.endswith(".dispatch.log"):
            continue
        hits = TOKENS_RE.findall(log.read_text(encoding="utf-8", errors="replace"))
        if hits:
            out[log.name.replace(".out.md.log", "").replace(".log", "")] = int(hits[-1].replace(",", ""))
    return out


def run_spend(run, sid, ceiling, wf_dirs=None, projects_root=None):
    """Spend of ONE spec-review run: its Claude lanes (agents whose prompt names the run dir) plus its
    Codex dispatches, against the tier's tokenCeiling. warn at 1.0x, stop at 1.5x."""
    dirs = [Path(d) for d in wf_dirs] if wf_dirs else workflow_dirs(sid, projects_root)
    files = [f for d in dirs for f in d.glob("agent-*.jsonl")]
    roles = roles_from_files(files, marker=str(run))
    claude = sum(r["total"] for r in roles.values())
    codex = codex_tokens(run)
    total = claude + sum(codex.values())
    ratio = round(total / ceiling, 3) if ceiling else 0
    return {"claudeTotal": claude, "codexTotal": sum(codex.values()), "total": total, "tokenCeiling": ceiling,
            "ratio": ratio, "warn": bool(ceiling) and ratio >= 1.0, "stop": bool(ceiling) and ratio >= STOP_RATIO,
            "roles": roles, "codex": codex, "workflowDirs": [str(d) for d in dirs]}


STOP_RATIO = 1.5


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
