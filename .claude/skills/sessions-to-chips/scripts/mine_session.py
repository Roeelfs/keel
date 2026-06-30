#!/usr/bin/env python3
"""Deep-mine a Claude Code transcript JSONL for the WHOLE arc of a session — not just the tail.

Usage: mine_session.py <transcript.jsonl>

The old version printed only the last user msg + last assistant text + latest todos + last
tool uses. That is "surface-level": it tells you the last *step* but not the session's overall
*goal*, so a chip authored from it says "do the last thing" instead of "resume THIS mission".

This version surfaces, in priority order for reasoning about goal + continuation:
  - ORIGINAL GOAL ........... first substantive user message (the mission statement)
  - USER STEERING ARC ....... every human turn in order (how the intent evolved)
  - LATEST SESSION SUMMARY .. the freshest isCompactSummary block (canonical compaction summary:
                              "Primary Request and Intent / Key Technical Concepts / Pending
                              Tasks / Next Step" — the single richest artifact of goal + state)
  - EXACT LAST INSTRUCTION .. the last `last-prompt` (the literal final thing the user typed)
  - LAST USER MESSAGE / LAST ASSISTANT TEXT / LATEST TODOS / RECENT TOOL USES (the tail — where/why it stopped)
"""
import json, sys


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                out.append(b.get("text", ""))
        return "\n".join(out)
    return ""


def has_tool_result(content):
    if isinstance(content, list):
        return any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
    return False


def is_noise_user_text(txt):
    """System reminders, hook context, slash-command scaffolding, local-command echoes — not human intent."""
    if not txt:
        return True
    s = txt.strip()
    if len(s) <= 1:
        return True
    if s.startswith("<"):  # <system-reminder>, <command-name>, <local-command-stdout>, channel tags
        return True
    if s.startswith("Caveat:") or s.startswith("[Request interrupted"):
        return True
    return False


def main():
    path = sys.argv[1]
    first_user = None
    user_turns = []          # (ts, txt) substantive human steering turns, in order
    compact_summaries = []   # (ts, txt) isCompactSummary blocks
    last_prompt = None       # literal final user instruction (from last-prompt entries)
    last_assistant_text = None
    latest_todos = None
    tool_uses = []           # (ts, name, brief)
    compaction_count = 0
    seen_long = set()        # global de-dupe of replayed long instructions (short acks may repeat)

    with open(path, "r", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            t = o.get("type")
            ts = o.get("timestamp", "")

            if t == "last-prompt":
                lp = o.get("lastPrompt")
                if isinstance(lp, str) and lp.strip():
                    last_prompt = lp.strip()
                continue

            msg = o.get("message", {}) or {}
            content = msg.get("content")

            if t == "user":
                txt = text_of(content)
                if o.get("isCompactSummary"):
                    if txt.strip():
                        compact_summaries.append((ts, txt.strip()))
                    continue
                if o.get("isMeta") or has_tool_result(content):
                    continue
                if is_noise_user_text(txt):
                    continue
                s = txt.strip()
                # de-dupe immediate repeats, and globally drop replayed long instructions
                # (transcripts re-emit prompts on branch/queue replay → out-of-order dupes).
                # Short acknowledgements ("go", "yes", "proceed") may legitimately recur — keep those.
                if user_turns and user_turns[-1][1] == s:
                    continue
                if len(s) > 15:
                    key = " ".join(s.split())[:200]
                    if key in seen_long:
                        continue
                    seen_long.add(key)
                user_turns.append((ts, s))
                if first_user is None:
                    first_user = (ts, s)

            elif t == "assistant":
                txt = text_of(content)
                if txt.strip():
                    last_assistant_text = (ts, txt.strip())
                if isinstance(content, list):
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "tool_use":
                            name = b.get("name", "?")
                            inp = b.get("input", {}) or {}
                            if name == "TodoWrite":
                                latest_todos = inp.get("todos", inp)
                                brief = "TodoWrite"
                            elif name == "Bash":
                                brief = "$ " + str(inp.get("command", ""))[:160]
                            elif name in ("Edit", "Write", "Read"):
                                brief = f"{name} {inp.get('file_path', '')}"
                            elif name in ("Agent", "Task", "Workflow"):
                                brief = f"{name}: {str(inp.get('description') or inp.get('prompt') or '')[:120]}"
                            else:
                                brief = name + " " + json.dumps(inp)[:120]
                            tool_uses.append((ts, name, brief))

            elif t == "system" and (o.get("compactMetadata") or (o.get("subtype") == "compact")):
                compaction_count += 1

    # ---------- render ----------
    def hms(ts):
        return ts[11:19] if isinstance(ts, str) and len(ts) > 19 else ts

    print("===== SESSION OVERVIEW =====")
    print(f"human turns: {len(user_turns)}   compactions: {max(compaction_count, len(compact_summaries))}   "
          f"compaction-summaries captured: {len(compact_summaries)}   tool calls: {len(tool_uses)}")

    print("\n===== ORIGINAL GOAL (first human message) =====")
    if first_user:
        print(f"[{first_user[0]}]")
        print(first_user[1][:1800])
    else:
        print("(none — likely a /resume or programmatic start; lean on the summary + steering arc below)")

    print("\n===== USER STEERING ARC (how the intent evolved, oldest→newest) =====")
    if user_turns:
        # Show the first few, then the most recent — the arc plus recency, without dumping hundreds.
        HEAD, TAIL = 6, 26
        def one(i, pair):
            ts, txt = pair
            flat = " ".join(txt.split())
            print(f"  {i:>3}. [{hms(ts)}] {flat[:200]}")
        if len(user_turns) <= HEAD + TAIL:
            for i, p in enumerate(user_turns, 1):
                one(i, p)
        else:
            for i in range(HEAD):
                one(i + 1, user_turns[i])
            print(f"       … {len(user_turns) - HEAD - TAIL} earlier turns elided …")
            for i in range(len(user_turns) - TAIL, len(user_turns)):
                one(i + 1, user_turns[i])
    else:
        print("(no plain human turns captured)")

    print("\n===== LATEST SESSION SUMMARY (freshest compaction — the canonical goal+state digest) =====")
    if compact_summaries:
        ts, txt = compact_summaries[-1]
        print(f"[compaction @ {ts}]  (of {len(compact_summaries)} summaries; showing the most recent)")
        HEAD, TAIL, CAP = 5200, 3400, 9200
        if len(txt) <= CAP:
            print(txt)
        else:
            print(txt[:HEAD])
            print(f"\n…[summary middle elided — {len(txt) - HEAD - TAIL} chars; the Pending Tasks / Next Step sections are at the END below]…\n")
            print(txt[-TAIL:])
    else:
        print("(none — session never compacted; the steering arc + tail above ARE the full record)")

    print("\n===== EXACT LAST USER INSTRUCTION (literal final prompt) =====")
    print(last_prompt if last_prompt else "(none captured)")

    print("\n===== LAST USER MESSAGE (substantive) =====")
    if user_turns:
        ts, txt = user_turns[-1]
        print(f"[{ts}]")
        print(txt[:2000])
    else:
        print("(none)")

    print("\n===== LAST ASSISTANT TEXT (where it stopped) =====")
    if last_assistant_text:
        ts, txt = last_assistant_text
        print(f"[{ts}]")
        print(txt[:3500])
    else:
        print("(none)")

    print("\n===== LATEST TODOS =====")
    if latest_todos:
        for td in latest_todos:
            if isinstance(td, dict):
                st = td.get("status", "?")
                c = td.get("content") or td.get("activeForm") or ""
                mark = {"completed": "[x]", "in_progress": "[~]", "pending": "[ ]"}.get(st, "[?]")
                print(f"  {mark} {c}")
    else:
        print("(no todos)")

    print("\n===== RECENT TOOL USES (last 20) =====")
    for ts, name, brief in tool_uses[-20:]:
        print(f"[{hms(ts)}] {brief}")


if __name__ == "__main__":
    main()
