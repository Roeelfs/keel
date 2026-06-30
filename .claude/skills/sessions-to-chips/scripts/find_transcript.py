#!/usr/bin/env python3
"""Locate transcript JSONL(s) by cliSessionId.

GOTCHA this exists to prevent: transcripts are NOT in the main project dir keyed by
cliSessionId. Each worktree gets its OWN project-slug dir under ~/.claude/projects/,
and the JSONL lives there named <cliSessionId>.jsonl. So search ALL project dirs.

Usage: find_transcript.py <cliSessionId> [<cliSessionId> ...]
Output (tab-separated): <cli>  <sizeKB>  <abs path>   (or "<cli>  MISSING")
"""
import sys, glob, os

ROOT = os.path.expanduser("~/.claude/projects")

def main():
    if len(sys.argv) < 2:
        print("usage: find_transcript.py <cliSessionId> ...", file=sys.stderr)
        sys.exit(2)
    for cli in sys.argv[1:]:
        hits = glob.glob(os.path.join(ROOT, "*", cli + ".jsonl"))
        if hits:
            for h in hits:
                print(f"{cli}\t{os.path.getsize(h)//1024}K\t{h}")
        else:
            print(f"{cli}\tMISSING")

if __name__ == "__main__":
    main()
