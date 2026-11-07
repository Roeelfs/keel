#!/usr/bin/env python3
"""codex_share.py — what share of delegated lanes ran on Codex, re-runnable over any window.

One command reproduces the Codex-share measurement, so a re-measure uses the same method:

    python3 codex_share.py --since 2026-11-03 --until 2026-11-06 [--json]

SOURCES (all under ~/.claude, override with --claude-home):
  * analytics/codex-dispatch.jsonl   one row per Codex gate consultation = one Codex lane
                                     (spawn-lane, codex-dispatch.sh and Workflow Codex lanes all ask).
  * projects/**/subagents/*.meta.json  one file per Claude subagent lane (Agent tool or Workflow
                                     agent()); `.model` is its model, a `/workflows/` path marks a
                                     Workflow lane. Filtered by file mtime.
  * projects/**/*.jsonl transcripts  tool_use blocks: Agent/Task dispatches (model, `Role:` line,
                                     `Native-why:` line), `spawn-lane.sh --mission` and
                                     `codex-dispatch.sh` Bash calls, Workflow calls. Blocks are
                                     deduplicated by (timestamp, kind, prompt/command head), since a
                                     resumed session repeats its history.
  * projects/<proj>/<session>/custom-title.json  a "[Manager]" title marks a manager session.
  * analytics/codex-first-gate.jsonl  deny/allow decisions; dispatch_runtime=native identifies
                                     new native attempts, native_why carries the exception reason.
                                     dispatch_routes compares these with transcript headless/Codex
                                     attempts, without adding denials to executed-lane shares.

SHARES:
  all          Codex gate rows / (Codex gate rows + Claude subagent lanes + Claude headless lanes)
  hand         hand-dispatched only, Workflows excluded:
               (spawn-lane codex + codex-dispatch.sh calls) /
               (that + Claude Agent-tool lanes + spawn-lane claude)
  qualifying   the target metric: Codex hand-dispatched lanes / (Codex hand-dispatched + Claude opus
               implementation lanes that state no reason to stay on Claude). A Claude lane counts
               here when it is an Agent `Role: implementation` dispatch at opus (or unset model)
               with no `Native-why:` line, or a `spawn-lane.sh` claude opus lane with no
               `--claude-reason` whose mission (when still readable) is not `Role: spec`.

RUNTIME OF A spawn-lane CALL: explicit `--runtime`; else `--model sonnet|haiku|opus` means claude;
else claude before --codex-default-from (the launcher defaulted to claude) and codex after it.

CAVEATS: meta.json mtime is the window filter for Claude subagent lanes; Codex gate rows include
lanes asked for but killed before running. Read the numbers as a trend measured one way every time.
"""
import argparse
import collections
import datetime as dt
import glob
import json
import os
import re
import shlex
import sys

ROLE_RE = re.compile(r"Role:\s*(\w+)")
NATIVE_WHY_RE = re.compile(r"(?im)^[ \t]*Native-why:[ \t]*([^\n\r\"'`]+)")
SPAWN_RE = re.compile(r"(^|[\s;&|(])(\S*/)?spawn-lane\.sh\s+")
DISPATCH_RE = re.compile(r"(^|[\s;&|(])(\S*/)?codex-dispatch\.sh\s+(\S+)")
READ_ONLY_RE = re.compile(r"^\s*(#|(cat|grep|rg|ls|sed|head|tail|bash -n|wc|less|jq|echo|printf)\b)")
CLAUDE_MECH = ("sonnet", "haiku")
DEEP = ("opus", "fable")


def parse_ts(s):
    s = s.strip()
    if len(s) == 10:
        s += "T00:00:00"
    t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def iso(t):
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def in_window(ts, since, until):
    return isinstance(ts, str) and since <= ts < until


def flag(argv, name):
    for i, a in enumerate(argv):
        if a == name and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return None


def spawn_argv(cmd):
    """argv after spawn-lane.sh in the first line that invokes it, or None."""
    for line in cmd.splitlines():
        m = SPAWN_RE.search(line)
        if not m or READ_ONLY_RE.match(line):
            continue
        try:
            return shlex.split(line[m.end():], posix=True)
        except ValueError:
            return line[m.end():].split()
    return None


def model_family(model):
    m = (model or "").lower()
    for fam in DEEP + CLAUDE_MECH:
        if m == fam or m.startswith("claude-" + fam):
            return fam
    return m


def spawn_runtime(argv, ts, codex_default_from):
    rt = flag(argv, "--runtime")
    if rt:
        return rt
    if model_family(flag(argv, "--model")) in DEEP + CLAUDE_MECH:
        return "claude"
    return "codex" if ts >= codex_default_from else "claude"


def mission_is_spec(argv, cwd):
    path = flag(argv, "--mission")
    if not path or path == "-":
        return False
    for base in (flag(argv, "--cwd") or "", cwd or "", ""):
        p = os.path.expanduser(os.path.join(base, path) if base else path)
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                return bool(re.search(r"(?i)Role:\s*spec\b", fh.read(65536)))
        except OSError:
            continue
    return False


def extract(home, since, until):
    """Deduplicated dispatch records from transcripts touched inside the window."""
    root = os.path.join(home, "projects")
    cut = parse_ts(since).timestamp()
    seen, out = set(), []
    for f in glob.glob(os.path.join(root, "*", "**", "*.jsonl"), recursive=True):
        try:
            if os.path.getmtime(f) < cut:
                continue
            fh = open(f, errors="ignore")
        except OSError:
            continue
        sub = "/subagents/" in f
        rel = f[len(root) + 1:].split("/")
        proj = rel[0]
        sess = f.split("/subagents/")[0].split("/")[-1] if sub else os.path.basename(f)[:-6]
        with fh:
            for line in fh:
                if '"tool_use"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                ts = d.get("timestamp", "")
                if not in_window(ts, since, until):
                    continue
                msg = d.get("message")
                content = msg.get("content") if isinstance(msg, dict) else None
                if not isinstance(content, list):
                    continue
                for b in content:
                    if not isinstance(b, dict) or b.get("type") != "tool_use":
                        continue
                    rec = classify(b.get("name"), b.get("input") or {})
                    if not rec:
                        continue
                    key = (ts, rec["kind"], rec.pop("_key"))
                    if key in seen:
                        continue
                    seen.add(key)
                    rec.update(ts=ts, session=sess, project=proj, nested=sub, cwd=d.get("cwd"))
                    out.append(rec)
    return out


def classify(name, i):
    if name in ("Agent", "Task"):
        p = i.get("prompt") or ""
        role = ROLE_RE.search(p)
        reason = any(len(m.group(1).strip()) >= 10 for m in NATIVE_WHY_RE.finditer(p))
        return {"kind": "agent", "model": i.get("model"), "subagent_type": i.get("subagent_type"),
                "role": role.group(1).lower() if role else None,
                "mentions_codex": "codex" in p.lower(), "native_why": bool(reason), "_key": p[:80]}
    if name == "Workflow":
        s = json.dumps(i)
        return {"kind": "workflow", "_key": s[:80]}
    if name == "Bash":
        cmd = i.get("command") or ""
        argv = spawn_argv(cmd) if "spawn-lane.sh" in cmd else None
        if argv is not None and "--mission" in argv:
            return {"kind": "spawn", "argv": argv, "_key": cmd[:120]}
        first = cmd.split("\n")[0]
        m = DISPATCH_RE.search(cmd)
        if m and not READ_ONLY_RE.match(first):
            return {"kind": "codex_dispatch", "class": m.group(3), "_key": cmd[:120]}
    return None


def codex_gate_rows(home, since, until):
    rows = []
    try:
        with open(os.path.join(home, "analytics/codex-dispatch.jsonl")) as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if in_window(r.get("ts"), since, until):
                    rows.append(r)
    except OSError:
        pass
    return rows


def claude_meta(home, since, until):
    lo, hi = parse_ts(since).timestamp(), parse_ts(until).timestamp()
    rows = []
    for f in glob.glob(os.path.join(home, "projects", "**", "subagents", "**", "*.meta.json"), recursive=True):
        try:
            mt = os.path.getmtime(f)
            if not lo <= mt < hi:
                continue
            with open(f) as fh:
                m = json.load(fh)
        except (OSError, ValueError):
            continue
        model = m.get("model") if isinstance(m, dict) else None
        rows.append({"model": model_family(model) or "inherit", "workflow": "/workflows/" in f})
    return rows


def titles(home):
    out = {}
    for f in glob.glob(os.path.join(home, "projects", "*", "*", "custom-title.json")):
        try:
            with open(f) as fh:
                t = json.load(fh).get("customTitle") or ""
        except (OSError, ValueError, AttributeError):
            continue
        out[os.path.basename(os.path.dirname(f))] = t
    return out


def gate_log(home, since, until):
    c = collections.Counter()
    try:
        with open(os.path.join(home, "analytics/codex-first-gate.jsonl")) as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if in_window(r.get("ts", "")[:19] + "Z", since, until) and not r.get("synthetic"):
                    c[(r.get("surface"), r.get("verdict"))] += 1
                    # Attempts, not executed lanes: denied native calls never ran. Keep these
                    # separate from meta-based shares and historical rows without the field.
                    if r.get("dispatch_runtime") == "native":
                        c[("native", r.get("verdict"))] += 1
    except OSError:
        pass
    return {"%s/%s" % k: v for k, v in sorted(c.items())}


def pct(a, b):
    return round(100.0 * a / b, 1) if b else None


def measure(home, since, until, codex_default_from):
    gate = codex_gate_rows(home, since, until)
    meta = claude_meta(home, since, until)
    recs = extract(home, since, until)
    tt = titles(home)
    agents = [r for r in recs if r["kind"] == "agent"]
    top_agents = [r for r in agents if not r["nested"]]
    spawns = [r for r in recs if r["kind"] == "spawn"]
    for r in spawns:
        r["runtime"] = spawn_runtime(r["argv"], r["ts"], codex_default_from)
        r["model"] = model_family(flag(r["argv"], "--model") or ("sonnet" if r["runtime"] == "claude" else ""))
        r["claude_reason"] = bool(flag(r["argv"], "--claude-reason"))
    disp = [r for r in recs if r["kind"] == "codex_dispatch"]
    spawn_claude = [r for r in spawns if r["runtime"] == "claude"]
    spawn_codex = [r for r in spawns if r["runtime"] == "codex"]
    meta_agent = [m for m in meta if not m["workflow"]]

    codex_hand = len(spawn_codex) + len(disp)
    impl = [r for r in top_agents if r["role"] == "implementation"]
    impl_deep = [r for r in impl if model_family(r["model"]) in DEEP or not r["model"]]
    agent_unjustified = [r for r in impl_deep if not r["native_why"]]
    spawn_unjustified = [r for r in spawn_claude if r["model"] in DEEP and not r["claude_reason"]
                         and not mission_is_spec(r["argv"], r.get("cwd"))]

    def is_mgr(r):
        return tt.get(r["session"], "").startswith("[Manager]")
    mgr = collections.Counter()
    for r in top_agents + spawns + disp:
        side = "manager" if is_mgr(r) else "other"
        lane = {"agent": "claude_agent", "codex_dispatch": "codex_dispatch"}.get(r["kind"]) or "spawn_" + r["runtime"]
        mgr[(side, lane)] += 1
    by_side = {}
    for side in ("manager", "other"):
        c = {k[1]: v for k, v in mgr.items() if k[0] == side}
        cx = c.get("spawn_codex", 0) + c.get("codex_dispatch", 0)
        by_side[side] = dict(c, codex_share_pct=pct(cx, sum(c.values())))

    decisions = gate_log(home, since, until)
    return {
        "window": {"since": since, "until": until, "codex_default_from": codex_default_from},
        "codex_lanes": {"gate_rows": len(gate),
                        "by_model": dict(collections.Counter(r.get("model") for r in gate)),
                        "refuse": sum(1 for r in gate if r.get("verdict") == "refuse")},
        "claude_subagent_lanes": {"total": len(meta), "workflow": sum(m["workflow"] for m in meta),
                                  "agent_tool": len(meta_agent),
                                  "by_model": dict(collections.Counter(m["model"] for m in meta))},
        "top_level_agent_dispatches": {
            "total": len(top_agents),
            "by_model": dict(collections.Counter(r["model"] or "unset" for r in top_agents)),
            "by_role": dict(collections.Counter(r["role"] or "none" for r in top_agents)),
            "opus_implementation": len(impl_deep),
            "opus_implementation_mentioning_codex": sum(r["mentions_codex"] for r in impl_deep),
            "opus_implementation_with_native_why": sum(r["native_why"] for r in impl_deep)},
        "workflow_invocations": sum(1 for r in recs if r["kind"] == "workflow" and not r["nested"]),
        "spawn_lane": {"total": len(spawns), "claude": len(spawn_claude), "codex": len(spawn_codex),
                       "claude_by_model": dict(collections.Counter(r["model"] or "unset" for r in spawn_claude)),
                       "claude_with_reason": sum(r["claude_reason"] for r in spawn_claude)},
        "codex_dispatch_calls": len(disp),
        "managers": by_side,
        "dispatch_gate": decisions,
        "dispatch_routes": {"native_allowed": decisions.get("native/allow", 0),
                            "native_denied": decisions.get("native/deny", 0),
                            "headless_claude": len(spawn_claude), "headless_codex": len(spawn_codex),
                            "codex_document": len(disp)},
        "shares_pct": {
            "all": pct(len(gate), len(gate) + len(meta) + len(spawn_claude)),
            "hand": pct(codex_hand, codex_hand + len(meta_agent) + len(spawn_claude)),
            "spawn_lane_codex": pct(len(spawn_codex), len(spawns)),
            "qualifying": pct(codex_hand, codex_hand + len(agent_unjustified) + len(spawn_unjustified)),
        },
        "qualifying_inputs": {"codex_hand": codex_hand, "claude_agent_opus_impl_no_reason": len(agent_unjustified),
                              "claude_spawn_opus_no_reason": len(spawn_unjustified)},
    }


def render(r):
    s, w = r["shares_pct"], r["window"]
    q = r["qualifying_inputs"]
    a = r["top_level_agent_dispatches"]
    lines = [
        "Codex share %s .. %s" % (w["since"], w["until"]),
        "  all delegated lanes:  %s%%  (Codex gate rows %d; Claude subagent lanes %d; Claude headless %d)"
        % (s["all"], r["codex_lanes"]["gate_rows"], r["claude_subagent_lanes"]["total"], r["spawn_lane"]["claude"]),
        "  hand-dispatched:      %s%%  (Codex %d = spawn-lane %d + codex-dispatch.sh %d; Claude Agent-tool %d)"
        % (s["hand"], q["codex_hand"], r["spawn_lane"]["codex"], r["codex_dispatch_calls"],
           r["claude_subagent_lanes"]["agent_tool"]),
        "  spawn-lane on Codex:  %s%%  (%d of %d)" % (s["spawn_lane_codex"], r["spawn_lane"]["codex"], r["spawn_lane"]["total"]),
        "  QUALIFYING (target):  %s%%  (Codex %d vs Claude opus impl with no reason: Agent %d + spawn-lane %d)"
        % (s["qualifying"], q["codex_hand"], q["claude_agent_opus_impl_no_reason"], q["claude_spawn_opus_no_reason"]),
        "  opus implementation Agent dispatches: %d, mentioning Codex %d, with Native-why %d"
        % (a["opus_implementation"], a["opus_implementation_mentioning_codex"], a["opus_implementation_with_native_why"]),
        "  managers: %s" % json.dumps(r["managers"]["manager"]),
        "  others:   %s" % json.dumps(r["managers"]["other"]),
        "  dispatch routes (attempts): %s" % json.dumps(r["dispatch_routes"]),
        "  dispatch gate: %s" % (json.dumps(r["dispatch_gate"]) or "{}"),
    ]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    now = dt.datetime.now(dt.timezone.utc)
    ap.add_argument("--since", default=iso(now - dt.timedelta(days=3)), help="UTC date or ISO time (inclusive)")
    ap.add_argument("--until", default=iso(now), help="UTC date or ISO time (exclusive)")
    ap.add_argument("--codex-default-from", default="2026-11-06",
                    help="when spawn-lane.sh began defaulting to codex (UTC date or ISO time)")
    ap.add_argument("--claude-home", default=os.path.expanduser("~/.claude"))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    r = measure(a.claude_home, iso(parse_ts(a.since)), iso(parse_ts(a.until)), iso(parse_ts(a.codex_default_from)))
    print(json.dumps(r, indent=2) if a.json else render(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
