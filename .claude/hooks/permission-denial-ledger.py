#!/usr/bin/env python3
"""Body of permission-denial-ledger.sh (stdin = hook payload, argv[1] = ledger path)."""
import hashlib, json, os, re, sys, time
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
ti = d.get("tool_input") or {}
raw = json.dumps(ti, sort_keys=True, ensure_ascii=False)
cmd = ti.get("command", "") if isinstance(ti, dict) else ""
fp = re.sub(r"'[^']*'|\"(?:\\.|[^\"\\])*\"", "Q", cmd, flags=re.S)
fp = " ".join(fp.split())[:80]
reason = str(d.get("reason") or "")
low = reason.lower()
if "temporarily unavailable" in low or "cannot determine the safety" in low or "classifier" in low:
    rtype = "classifier"
elif "🚦" in reason or "hook" in low:
    rtype = "hook"
elif "deny" in low or "permission" in low:
    rtype = "rule"
else:
    rtype = "other"
row = {
    "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    "session_id": d.get("session_id"),
    "cwd": d.get("cwd"),
    "tool_name": d.get("tool_name"),
    "input_sha256": hashlib.sha256(raw.encode()).hexdigest()[:16],
    "fingerprint": fp,
    "reason_type": rtype,
    "reason": reason[:300],
}
os.makedirs(os.path.dirname(sys.argv[1]), exist_ok=True)
with open(sys.argv[1], "a") as f:
    f.write(json.dumps(row, ensure_ascii=False) + "\n")
