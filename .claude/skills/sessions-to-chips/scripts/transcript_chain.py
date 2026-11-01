#!/usr/bin/env python3
"""Resolve a desktop session's transcript CHAIN: every JSONL file that holds its conversation.

What the data shows (measured 2026-11-01 over 1,688 store rows and 2,631 transcripts):
- A store row's `cliSessionId` names only its NEWEST transcript. When the app resumes, moves or
  forks a session it mints a new transcript id and the old file stays behind with no store row
  (29 such desktop files in 8 days, five of them `[Manager]` chains).
- The link is the head of the new file: its first row whose `parentUuid` (or
  `logicalParentUuid`) is not a row of the same file names a `uuid` in the predecessor file. A
  fork copies its parent's rows instead, so those rows carry the parent's `sessionId`.
- Links form a tree, not a line: two files can start from one parent row (Apps: 691fbad2 and
  e5804b07 both continue edae2f58 from row 5c472a2d), and the predecessor can keep growing after
  the fork. Every file that holds a link row is a member.
- The same transcript name can sit in two project dirs when the session's cwd moved (4 rows).
- The store's `lastAssistantUuid` was found in the store transcript for 630 of 630 rows, so it is
  the proof that a transcript holds every turn. `lastActivityAt` is not: it also moves on focus
  and artifact-ledger rows (Release 3db904d9: last turn 2026-10-28T12:38Z, store 2026-10-31T11:27Z,
  lastAssistantUuid present, the later rows are `artifact-autoreact-ledger` with no timestamp).
- `accountUuid` sits only on artifact-ledger rows, so two of them do NOT mean the session ran on
  two accounts. Account attribution comes from the store directory alone.

A link not found in any transcript modified since the window start cannot hide post-window rows
(a file with such rows has a newer mtime), so it is reported as `pre_window`, not as a hole.

Usage: transcript_chain.py <cli-id> [...] [--since ISO] [--projects DIR] [--json]
"""
import argparse
import datetime
import glob
import json
import mmap
import os
import re

PROJECTS = os.path.join((os.environ.get("S2C_CLAUDE_HOME") or os.path.expanduser("~/.claude")), "projects")
HEAD_BYTES = 512_000
TAIL_BYTES = 4_000_000
TURN_TYPES = ("user", "assistant")


def parse_ts(value):
    """ISO string or epoch-ms int -> epoch seconds (float); 0 when absent."""
    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float)) or str(value).isdigit():
        return int(value) / 1000.0
    s = str(value).replace("Z", "+00:00")
    dt = datetime.datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.timestamp()


def iso(ts):
    if not ts:
        return "-"
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def stem(path):
    return os.path.basename(path)[:-len(".jsonl")]


def files_named(cli, projects=None):
    return sorted(glob.glob(os.path.join(projects or PROJECTS, "*", f"{cli}.jsonl"))) if cli else []


def candidates(since_ts, projects=None):
    """Transcripts modified at or after since_ts: the only files that can hold post-window rows."""
    out = []
    for f in glob.glob(os.path.join(projects or PROJECTS, "*", "*.jsonl")):
        try:
            if os.path.getmtime(f) >= since_ts:
                out.append(f)
        except OSError:
            continue
    return sorted(out)


def _rows(buf, skip_first=False):
    lines = buf.split(b"\n")
    if skip_first:
        lines = lines[1:]
    for line in lines:
        if not line.strip():
            continue
        try:
            yield json.loads(line)
        except ValueError:
            continue


def head_facts(path):
    """The head link, any foreign sessionIds (fork copies), entrypoint and custom title."""
    own, link, foreign, entry, title = set(), None, set(), None, None
    name = stem(path)
    with open(path, "rb") as fh:
        buf = fh.read(HEAD_BYTES)
    for r in _rows(buf):
        entry = entry or r.get("entrypoint")
        if r.get("type") == "custom-title":
            title = r.get("customTitle") or r.get("title") or title
        sid = r.get("sessionId")
        if sid and sid != name:
            foreign.add(sid)
        parent = r.get("parentUuid") or r.get("logicalParentUuid")
        if link is None and parent and parent not in own:
            link = parent
        if r.get("uuid"):
            own.add(r["uuid"])
    return {"link": link, "foreign": sorted(foreign), "entrypoint": entry, "title": title}


def tail_facts(path):
    """Last user/assistant row (timestamp, uuid) and last assistant uuid, read from the tail."""
    size = os.path.getsize(path)
    for start in ([max(0, size - TAIL_BYTES), 0] if size > TAIL_BYTES else [0]):
        with open(path, "rb") as fh:
            fh.seek(start)
            rows = list(_rows(fh.read(), skip_first=start > 0))
        last_turn = next((r for r in reversed(rows) if r.get("type") in TURN_TYPES and r.get("timestamp")), None)
        last_asst = next((r for r in reversed(rows) if r.get("type") == "assistant" and r.get("uuid")), None)
        if last_turn:
            return {"last_turn_ts": parse_ts(last_turn["timestamp"]), "last_turn_uuid": last_turn.get("uuid"),
                    "last_assistant_uuid": (last_asst or {}).get("uuid"), "bytes": size}
    return {"last_turn_ts": 0.0, "last_turn_uuid": None, "last_assistant_uuid": None, "bytes": size}


def contains(path, needle):
    """True when the raw file contains the needle string (C-speed, any size)."""
    if not needle or not os.path.getsize(path):
        return False
    with open(path, "rb") as fh, mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        return mm.find(needle.encode()) != -1


UUID_ROW = re.compile(rb'"uuid":\s*"([0-9a-f-]{36})"')


def files_holding(uuids, files):
    """{uuid: [files whose rows define it]}: one mmap regex scan per file (BSD grep -F with many
    patterns ran CPU-bound for minutes over the same set)."""
    found = {u: [] for u in uuids}
    if not uuids:
        return found
    want = {u.encode() for u in uuids}
    for f in files:
        try:
            if not os.path.getsize(f):
                continue
            with open(f, "rb") as fh, mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                hits = {m.group(1) for m in UUID_ROW.finditer(mm)} & want
        except (OSError, ValueError):
            continue
        for u in hits:
            found[u.decode()].append(f)
    return found


def build_graph(pool):
    """One pass over the window: head facts of every file and the files that hold each head link.

    Returns {"heads": {path: head_facts}, "parents": {path: [paths it continues]}}.
    """
    heads = {f: head_facts(f) for f in pool}
    links = {h["link"] for h in heads.values() if h["link"]}
    held = files_holding(links, pool)
    parents = {}
    for f, h in heads.items():
        ps = [p for p in held.get(h["link"], []) if p != f] if h["link"] else []
        for sid in h["foreign"]:  # a fork copy: its parent transcript is a parent
            ps += [g for g in files_named_in(sid, pool) if g != f]
        parents[f] = list(dict.fromkeys(ps))
    return {"heads": heads, "parents": parents, "held": held}


def files_named_in(cli, pool):
    return [f for f in pool if stem(f) == cli]


def closure(seeds, graph, owned=frozenset()):
    """Chain of one session: its seed files, every ancestor, and every UNOWNED file that continues a
    member (an orphaned fork of the same session). `owned` = transcript stems some store row names.

    chain = {"members": [...], "pre_window": [link uuids found in no window file]}.
    """
    members, pre = list(dict.fromkeys(seeds)), []
    children = {}
    for f, ps in graph["parents"].items():
        for p in ps:
            children.setdefault(p, []).append(f)
    i = 0
    while i < len(members):
        f = members[i]
        i += 1
        h = graph["heads"].get(f) or head_facts(f)
        if h["link"] and not graph["held"].get(h["link"]) and h["link"] not in pre:
            pre.append(h["link"])
        nxt = graph["parents"].get(f, []) + [c for c in children.get(f, []) if stem(c) not in owned]
        for g in nxt:
            if g not in members:
                members.append(g)
    return {"members": members, "pre_window": pre}


def resolve(seeds, since_ts, projects=None, pool=None, owned=frozenset()):
    """seeds: {key: [seed files]} -> {key: chain}; seeds outside the window are added to the pool."""
    pool = sorted(set(pool if pool is not None else candidates(since_ts, projects))
                  | {f for v in seeds.values() for f in v})
    graph = build_graph(pool)
    return {k: closure(v, graph, owned) for k, v in seeds.items()}, graph


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cli", nargs="+")
    ap.add_argument("--since", default=None, help="window start (ISO); default 30 days back")
    ap.add_argument("--projects", default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    import time
    since = parse_ts(a.since) if a.since else time.time() - 30 * 86400
    chains, _ = resolve({c: files_named(c, a.projects) for c in a.cli}, since, a.projects)
    out = {}
    for c, ch in chains.items():
        segs = []
        for m in ch["members"]:
            t = tail_facts(m)
            segs.append({"path": m, "bytes": t["bytes"], "last_turn": iso(t["last_turn_ts"]),
                         })
        out[c] = {"segments": segs, "pre_window_links": ch["pre_window"]}
    if a.json:
        print(json.dumps(out, indent=1))
        return
    for c, v in out.items():
        print(f"{c}  segments {len(v['segments'])}  pre-window links {len(v['pre_window_links'])}")
        for s in v["segments"]:
            print(f"   {s['bytes'] // 1024:>7}K  last turn {s['last_turn']}  {s['path']}")


if __name__ == "__main__":
    main()
