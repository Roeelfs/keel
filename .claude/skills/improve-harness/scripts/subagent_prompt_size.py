#!/usr/bin/env python3
"""Subagent prompt size by agent type and model.

Why it exists: some models price a request by prompt length (a turn whose prompt
crosses the tier line costs several times more), so "which tier did the lane's
turns land in" is the number that grades a cheap-tier delegation — dispatch share
is not. Prompt = input + cache-read + cache-creation tokens of one assistant turn.

Usage: subagent_prompt_size.py [--days 7] [--tier 100000] [--label-prefix py:]
Reads <home>/.claude/projects/**/subagents/**/*.jsonl and each file's .meta.json.
Prints one row per (agentType, model) with >= 5 agents, widest first.
"""
import argparse, collections, json, pathlib, statistics, time


def turns(path):
    seen, out = set(), []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            msg = rec.get("message") or {}
            usage = msg.get("usage")
            if rec.get("type") != "assistant" or not usage:
                continue
            key = (msg.get("id"), rec.get("requestId"))
            if key in seen:
                continue
            seen.add(key)
            prompt = sum(usage.get(k) or 0 for k in (
                "input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
            out.append((msg.get("model") or "?", prompt))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=float, default=7)
    ap.add_argument("--tier", type=int, default=100_000)
    ap.add_argument("--label-prefix", default="")
    args = ap.parse_args()
    cutoff = time.time() - args.days * 86400
    groups = collections.defaultdict(lambda: {"first": [], "all": []})
    scanned = 0
    for f in (pathlib.Path.home() / ".claude" / "projects").rglob("*.jsonl"):
        if "subagents" not in f.parts or f.stat().st_mtime < cutoff:
            continue
        try:
            meta = json.loads(f.with_suffix(".meta.json").read_text())
        except (OSError, ValueError):
            meta = {}
        if not (meta.get("description") or "").startswith(args.label_prefix):
            continue
        t = [x for x in turns(f) if x[0] != "<synthetic>"]
        if not t:
            continue
        scanned += 1
        g = groups[(meta.get("agentType") or "?", t[0][0])]
        g["first"].append(t[0][1])
        g["all"] += [p for _, p in t]
    print(f"scanned {scanned} subagent transcripts, last {args.days:g}d, tier line {args.tier}")
    print("agentType | model | agents | first-turn prompt min/med/max | turns | turns over tier")
    for (kind, model), g in sorted(groups.items(), key=lambda kv: -len(kv[1]["first"])):
        if len(g["first"]) < 5:
            continue
        over = sum(1 for p in g["all"] if p > args.tier)
        first = g["first"]
        print(f"{kind} | {model} | {len(first)} | {min(first)}/{int(statistics.median(first))}/{max(first)}"
              f" | {len(g['all'])} | {over} ({100 * over / len(g['all']):.0f}%)")


if __name__ == "__main__":
    main()
