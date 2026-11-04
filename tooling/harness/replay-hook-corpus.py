#!/usr/bin/env python3
"""Replay real Bash transcript calls through one hook, sequentially."""
import glob
import json
import os
import subprocess
import sys
from pathlib import Path


def extract_calls(projects: str, pattern: str, maximum: int):
    paths = sorted(
        glob.glob(os.path.join(projects, pattern, "*.jsonl")),
        key=os.path.getmtime,
        reverse=True,
    )
    calls = []
    for path in paths:
        if len(calls) >= maximum:
            break
        try:
            handle = open(path, errors="ignore")
        except OSError:
            continue
        with handle:
            for line in handle:
                if '"Bash"' not in line:
                    continue
                try:
                    record = json.loads(line)
                except Exception:
                    continue
                content = (record.get("message") or {}).get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if block.get("type") != "tool_use" or block.get("name") != "Bash":
                        continue
                    command = (block.get("input") or {}).get("command")
                    if command:
                        calls.append((command, record.get("cwd") or ""))
                # Deliberately after the whole record: this preserves the shell
                # contract when one transcript line contains more than `maximum` calls.
                if len(calls) >= maximum:
                    break
    return paths, calls


def run_hook(hook: str, command: str, cwd: str) -> tuple[int, str]:
    envelope = {
        "session_id": "replay",
        "transcript_path": "/dev/null",
        "cwd": cwd,
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command, "description": "replay"},
    }
    result = subprocess.run(
        ["bash", hook],
        input=(json.dumps(envelope) + "\n").encode(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    # Shell command substitution removes trailing newlines before the `tr | cut`.
    output = result.stdout.decode(errors="surrogateescape").rstrip("\n")
    # The legacy corpus summary only used exit/fire counts, but still normalized
    # and truncated the merged hook output before intentionally discarding it.
    return result.returncode, output.replace("\n", " ")[:160]


def main(argv: list[str]) -> int:
    if len(argv) != 6:
        raise SystemExit("usage: replay-hook-corpus.py <projects> <hooks> <hook> <glob> <max>")
    projects, hooks, hook_name, pattern, maximum = argv[1:]
    hook = Path(hooks) / hook_name
    if not hook.is_file():
        print(f"no such hook: {hook_name}", file=sys.stderr)
        return 1
    paths, calls = extract_calls(projects, pattern, int(maximum))
    print(f"extracted {len(calls)} real Bash calls from {len(paths)} transcripts", file=sys.stderr)

    fired = []
    multi = fired_multi = 0
    for command, cwd in calls:
        is_multiline = "\n" in command
        multi += is_multiline
        exit_code, _output = run_hook(str(hook), command, cwd)
        if exit_code:
            fired_multi += is_multiline
            fired.append(f"{exit_code}\t{command.replace(chr(10), '⏎')[:110]}")

    total = len(calls)
    print(f"\n=== {hook_name} over {total} real calls ({multi} multi-line, {multi * 100 // max(total, 1)}%) ===")
    print(f"fired: {len(fired)}  (of which multi-line: {fired_multi})")
    if fired:
        print("\n--- sample ---")
        # Keep the shell contract's locale-aware `sort -u | head -25` ordering.
        sample = subprocess.run(
            ["sort", "-u"],
            input="\n".join(fired) + "\n",
            stdout=subprocess.PIPE,
            text=True,
            check=True,
        ).stdout.splitlines()
        for line in sample[:25]:
            print(line)
    print("\nREVIEW EVERY LINE ABOVE: a fire on a legitimate command is a wedge.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
