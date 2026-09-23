"""Compact per-session digests for improve-harness lane A miners.

Why this matters: one real run's raw window was 378 transcripts / 2.7 GB — unreadable
by five miners; the per-bucket digests this script produces were 176-327 KB each.
Per session this keeps: human-typed turns, tool errors, identical tool calls repeated >=3x
(friction loops), hook denials, and assistant self-corrections. Both runtimes.
Usage: python3 digest.py --window <label> <buckets.json> <outdir>
  buckets.json = a JSON list of lists of transcript paths; one digest file (bucket-<i>.md)
  is written per bucket. <label> is a human-readable description of the window mined
  (e.g. "2026-09-16..23"), printed in each bucket's header.
"""
import argparse, collections, hashlib, json, os, re, sys

SELF_FLAG = re.compile(r"\b(I was wrong|my mistake|I mistakenly|that was wrong|I misread|correction:|I incorrectly|I should have|wrongly)\b", re.I)
SYS_PREFIX = ("<system-reminder", "<command-", "<local-command", "<task-notification", "<ci-monitor", "Caveat:", "[Request interrupted")
CAP_HUMAN, CAP_ERR, CAP_SELF = 25, 25, 8


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for c in content:
            if isinstance(c, dict) and c.get("type") in ("text", "input_text", "output_text"):
                out.append(c.get("text", ""))
        return "\n".join(out)
    return ""


def clip(s, n):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[:n] + "…"


def claude_session(path):
    human, errs, selfs, denials = [], [], [], []
    calls = collections.Counter(); names = {}
    for line in open(path, errors="replace"):
        try:
            o = json.loads(line)
        except Exception:
            continue
        t = o.get("type"); msg = o.get("message") or {}
        if t == "user" and not o.get("isSidechain"):
            c = msg.get("content")
            if isinstance(c, list) and any(isinstance(x, dict) and x.get("type") == "tool_result" for x in c):
                for x in c:
                    if isinstance(x, dict) and x.get("type") == "tool_result" and x.get("is_error"):
                        body = text_of(x.get("content")) if not isinstance(x.get("content"), str) else x["content"]
                        (denials if "hook" in (body or "").lower() else errs).append(clip(body, 220))
                continue
            s = text_of(c)
            if s and not s.lstrip().startswith(SYS_PREFIX):
                human.append(clip(s, 500))
        elif t == "assistant":
            for x in msg.get("content") or []:
                if not isinstance(x, dict):
                    continue
                if x.get("type") == "tool_use":
                    k = hashlib.md5((x.get("name", "") + json.dumps(x.get("input"), sort_keys=True)).encode()).hexdigest()
                    calls[k] += 1; names[k] = f"{x.get('name')} {clip(json.dumps(x.get('input')), 160)}"
                elif x.get("type") == "text" and SELF_FLAG.search(x.get("text", "")):
                    m = SELF_FLAG.search(x["text"]); a = max(0, m.start() - 120)
                    selfs.append(clip(x["text"][a:a + 320], 320))
    loops = [(n, names[k]) for k, n in calls.items() if n >= 3]
    return human, errs, selfs, denials, loops


def codex_session(path):
    human, errs, selfs, denials = [], [], [], []
    calls = collections.Counter(); names = {}
    for line in open(path, errors="replace"):
        try:
            o = json.loads(line)
        except Exception:
            continue
        p = o.get("payload") or {}
        pt = p.get("type")
        if pt == "message" and p.get("role") == "user":
            s = text_of(p.get("content"))
            if s and not s.lstrip().startswith(("<environment_context", "<user_instructions", "# AGENTS.md", "<permissions", "<INSTRUCTIONS")):
                human.append(clip(s, 500))
        elif pt == "message" and p.get("role") == "assistant":
            s = text_of(p.get("content"))
            m = SELF_FLAG.search(s or "")
            if m:
                a = max(0, m.start() - 120); selfs.append(clip(s[a:a + 320], 320))
        elif pt in ("function_call", "custom_tool_call", "local_shell_call"):
            args = p.get("arguments") or p.get("input") or json.dumps(p.get("action"))
            k = hashlib.md5(((p.get("name") or pt) + str(args)).encode()).hexdigest()
            calls[k] += 1; names[k] = f"{p.get('name') or pt} {clip(str(args), 160)}"
        elif pt in ("function_call_output", "custom_tool_call_output"):
            out = p.get("output")
            s = out if isinstance(out, str) else json.dumps(out)
            if re.search(r'"exit_code":\s*[1-9]|Exit code: [1-9]|\berror\b|denied|rejected', s or "", re.I):
                errs.append(clip(s, 220))
    loops = [(n, names[k]) for k, n in calls.items() if n >= 3]
    return human, errs, selfs, denials, loops


def build_digests(buckets, outdir, window):
    os.makedirs(outdir, exist_ok=True)
    paths = []
    for i, b in enumerate(buckets):
        parts = [f"# Digest bucket {i} — {len(b)} sessions (window {window})\n"
                 "Per session: HUMAN turns, TOOL ERRORS, HOOK DENIALS, REPEATED CALLS (identical call >=3x = friction-loop candidate), SELF-FLAGS. "
                 "Cite the session path in evidence. Raw JSONL is readable at the path if a quote needs context (parse with python, never grep).\n"]
        for f in b:
            fn = codex_session if "/.codex/" in f else claude_session
            try:
                h, e, s, d, l = fn(f)
            except Exception as ex:
                parts.append(f"\n## {f}\n(unreadable: {ex})\n"); continue
            if not (h or e or d or l or s):
                continue
            rt = "codex" if "/.codex/" in f else "claude"
            sec = [f"\n## [{rt}] {f}"]
            if h: sec.append("HUMAN (" + str(len(h)) + "): " + " || ".join(h[:CAP_HUMAN]))
            if e: sec.append(f"TOOL ERRORS ({len(e)}): " + " || ".join(e[:CAP_ERR]))
            if d: sec.append(f"HOOK DENIALS ({len(d)}): " + " || ".join(d[:CAP_ERR]))
            if l: sec.append("REPEATED CALLS: " + " || ".join(f"{n}x {c}" for n, c in sorted(l, reverse=True)[:12]))
            if s: sec.append(f"SELF-FLAGS ({len(s)}): " + " || ".join(s[:CAP_SELF]))
            parts.append("\n".join(sec) + "\n")
        p = os.path.join(outdir, f"bucket-{i}.md"); open(p, "w").write("".join(parts)); paths.append(p)
    return paths


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--window", required=True, help="human-readable window label, e.g. '2026-09-16..23'")
    ap.add_argument("buckets_json", help="path to a JSON list of lists of transcript paths")
    ap.add_argument("outdir", help="directory to write bucket-<i>.md digest files into")
    a = ap.parse_args(argv)
    buckets = json.load(open(a.buckets_json))
    paths = build_digests(buckets, a.outdir, a.window)
    for p in paths:
        print(p, os.path.getsize(p))


if __name__ == "__main__":
    main()
