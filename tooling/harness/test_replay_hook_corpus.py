#!/usr/bin/env python3
"""Regression fixtures for the real-command hook corpus replayer."""
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


HELPER = Path(__file__).resolve().parent / "replay-hook-corpus.py"


# This is deliberately a test-local copy of the pre-helper corpus contract.  It is
# the oracle for byte equivalence, not an implementation shared with the helper.
REFERENCE = r'''#!/usr/bin/env bash
set -uo pipefail
HOOKS="$HOME/.claude/hooks"; PROJ="$HOME/.claude/projects"
die() { printf '%s\n' "$*" >&2; exit 1; }
envelope() { python3 -c '
import json,sys
print(json.dumps({"session_id":"replay","transcript_path":"/dev/null","cwd":sys.argv[2], "hook_event_name":"PreToolUse","tool_name":"Bash", "tool_input":{"command":sys.argv[1],"description":"replay"}}))' "$1" "$2"; }
run_hook() { local out ec; out="$(envelope "$2" "$3" | bash "$HOOKS/$1" 2>&1)"; ec=$?; printf '%s|%s' "$ec" "$(printf '%s' "$out" | tr '\n' ' ' | cut -c1-160)"; }
cmd_corpus() {
  local hook="$1" glob="${2:-*}" max="${3:-4000}"
  [ -f "$HOOKS/$hook" ] || die "no such hook: $hook"
  local tmp; tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' RETURN
  python3 - "$PROJ" "$glob" "$max" "$tmp/cmds.jsonl" <<'PY'
import sys, json, glob, os
proj, pat, mx, out = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
files = sorted(glob.glob(os.path.join(proj, pat, "*.jsonl")), key=os.path.getmtime, reverse=True)
n = 0
with open(out, "w") as w:
    for f in files:
        if n >= mx: break
        try: fh = open(f, errors="ignore")
        except OSError: continue
        with fh:
            for line in fh:
                if '"Bash"' not in line: continue
                try: rec = json.loads(line)
                except Exception: continue
                msg = rec.get("message") or {}; c = msg.get("content")
                if not isinstance(c, list): continue
                for b in c:
                    if b.get("type") == "tool_use" and b.get("name") == "Bash":
                        cmd = (b.get("input") or {}).get("command")
                        if cmd:
                            w.write(json.dumps({"cmd": cmd, "cwd": rec.get("cwd") or "", "src": os.path.basename(f), "multi": "\n" in cmd}) + "\n"); n += 1
                if n >= mx: break
print(f"extracted {n} real Bash calls from {len(files)} transcripts", file=sys.stderr)
PY
  local total=0 multi=0 fired=0 fired_multi=0
  while IFS= read -r row; do
    local c cwd isml v ec
    c="$(printf '%s' "$row" | python3 -c 'import sys,json;print(json.load(sys.stdin)["cmd"])')"
    cwd="$(printf '%s' "$row" | python3 -c 'import sys,json;print(json.load(sys.stdin)["cwd"])')"
    isml="$(printf '%s' "$row" | python3 -c 'import sys,json;print(1 if json.load(sys.stdin)["multi"] else 0)')"
    v="$(run_hook "$hook" "$c" "$cwd")"; ec="${v%%|*}"
    total=$((total+1)); [ "$isml" = 1 ] && multi=$((multi+1))
    if [ "$ec" != "0" ]; then fired=$((fired+1)); [ "$isml" = 1 ] && fired_multi=$((fired_multi+1)); printf '%s\t%s\n' "$ec" "$(printf '%s' "$c" | tr '\n' '⏎' | cut -c1-110)" >> "$tmp/fired.txt"; fi
  done < "$tmp/cmds.jsonl"
  printf '\n=== %s over %s real calls (%s multi-line, %s%%) ===\n' "$hook" "$total" "$multi" "$(( multi * 100 / (total>0?total:1) ))"
  printf 'fired: %s  (of which multi-line: %s)\n' "$fired" "$fired_multi"
  [ -s "$tmp/fired.txt" ] && { printf '\n--- sample ---\n'; sort -u "$tmp/fired.txt" | head -25; }
  printf '\nREVIEW EVERY LINE ABOVE: a fire on a legitimate command is a wedge.\n'
}
case "$1" in corpus) shift; cmd_corpus "$@";; esac
'''


def record(cwd, blocks):
    return {"cwd": cwd, "message": {"content": blocks}}


def bash(command):
    return {"type": "tool_use", "name": "Bash", "input": {"command": command}}


class ReplayHookCorpusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name) / "home"
        self.claude = self.home / ".claude"
        self.projects = self.claude / "projects" / "fixture"
        self.hooks = self.claude / "hooks"
        self.projects.mkdir(parents=True); self.hooks.mkdir()
        (self.hooks / "fixture.sh").write_text("""#!/usr/bin/env bash
payload=$(cat)
command=$(printf '%s' "$payload" | python3 -c 'import json,sys; print(json.load(sys.stdin)["tool_input"]["command"])')
if [[ "$command" == fire* ]]; then
  printf 'blocked: %s\\nsecond line\\n' "$command" >&2
  exit 2
fi
printf 'allowed: %s\\n' "$command"
""")
        (self.hooks / "newline.sh").write_text("""#!/usr/bin/env bash
if IFS= read -r payload; then
  exit 0
fi
printf 'missing terminal newline\\n' >&2
exit 2
""")
        self.reference = Path(self.temp.name) / "reference.sh"
        self.reference.write_text(REFERENCE); self.reference.chmod(0o755)
        old = self.projects / "old.jsonl"
        fresh = self.projects / "fresh.jsonl"
        newest = self.projects / "newest.jsonl"
        old.write_text("\n".join([json.dumps(record("/old", [bash("fire duplicate") ])), json.dumps(record("/old", [bash("echo one\necho two")]))]) + "\n")
        fresh.write_text("\n".join(["{ malformed \\\"Bash\\\"", json.dumps(record("/fresh", [{"type": "tool_use", "name": "Read", "input": {"path": "x"}}])), json.dumps(record("/fresh", [bash("fire " + "a" * 120), bash("fire duplicate")]))]) + "\n")
        newest.write_text(json.dumps(record("/newest", [bash("fire multi\nline"), bash("ok newest")])) + "\n")
        now = time.time()
        for index, path in enumerate((old, fresh, newest)):
            os.utime(path, (now + index, now + index))
        self.env = {**os.environ, "HOME": str(self.home)}

    def tearDown(self): self.temp.cleanup()

    def invoke(self, argv, **kwargs):
        return subprocess.run(argv, env=self.env, capture_output=True, **kwargs)

    def test_helper_is_byte_equivalent_to_shell_contract(self):
        reference = self.invoke(["bash", str(self.reference), "corpus", "fixture.sh", "*", "4000"])
        actual = self.invoke(["python3", str(HELPER), str(self.claude / "projects"), str(self.hooks), "fixture.sh", "*", "4000"])
        self.assertEqual((actual.returncode, actual.stdout, actual.stderr), (reference.returncode, reference.stdout, reference.stderr))
        self.assertIn(b"extracted 6 real Bash calls from 3 transcripts\n", actual.stderr)
        self.assertIn(b"over 6 real calls (2 multi-line, 33%)", actual.stdout)
        self.assertEqual(actual.stdout.count(b"2\tfire duplicate\n"), 1)  # sample is unique/sorted
        self.assertIn(b"2\tfire multi", actual.stdout)
        long_sample = next(line for line in actual.stdout.splitlines() if line.startswith(b"2\tfire a"))
        self.assertEqual(len(long_sample), 112)  # exit, tab, and exactly the 110-char command sample

    def test_helper_stops_at_max_in_mtime_and_extraction_order(self):
        reference = self.invoke(["bash", str(self.reference), "corpus", "fixture.sh", "*", "3"])
        actual = self.invoke(["python3", str(HELPER), str(self.claude / "projects"), str(self.hooks), "fixture.sh", "*", "3"])
        self.assertEqual((actual.returncode, actual.stdout, actual.stderr), (reference.returncode, reference.stdout, reference.stderr))
        self.assertIn(b"extracted 4 real Bash calls from 3 transcripts\n", actual.stderr)
        self.assertIn(b"over 4 real calls (1 multi-line, 25%)", actual.stdout)

    def test_helper_preserves_terminal_newline_in_envelope_stdin(self):
        reference = self.invoke(["bash", str(self.reference), "corpus", "newline.sh", "*", "1"])
        actual = self.invoke(["python3", str(HELPER), str(self.claude / "projects"), str(self.hooks), "newline.sh", "*", "1"])
        self.assertEqual((actual.returncode, actual.stdout, actual.stderr), (reference.returncode, reference.stdout, reference.stderr))
        self.assertIn(b"fired: 0", actual.stdout)

    def test_100_command_control_preserves_bytes_with_fewer_orchestration_processes(self):
        perf = self.claude / "projects" / "perf"
        perf.mkdir()
        perf.joinpath("commands.jsonl").write_text(json.dumps(record("/perf", [bash(f"ok {n}") for n in range(100)])) + "\n")
        self.hooks.joinpath("perf.sh").write_text("#!/usr/bin/env bash\ncat >/dev/null\n")
        shim = Path(self.temp.name) / "shim"
        shim.mkdir()
        log = Path(self.temp.name) / "python.log"
        shim.joinpath("python3").write_text(
            "#!/bin/sh\nprintf x >> \"$PYTHON_LOG\"\nexec " + shlex.quote(sys.executable) + " \"$@\"\n"
        )
        shim.joinpath("python3").chmod(0o755)
        env = {**self.env, "PATH": f"{shim}:{os.environ['PATH']}", "PYTHON_LOG": str(log)}
        started = time.monotonic()
        reference = subprocess.run(["bash", str(self.reference), "corpus", "perf.sh", "perf", "100"], env=env, capture_output=True)
        reference_seconds = time.monotonic() - started
        reference_processes = len(log.read_text())
        log.write_text("")
        started = time.monotonic()
        actual = subprocess.run(["python3", str(HELPER), str(self.claude / "projects"), str(self.hooks), "perf.sh", "perf", "100"], env=env, capture_output=True)
        helper_seconds = time.monotonic() - started
        helper_processes = len(log.read_text())
        self.assertEqual((actual.returncode, actual.stdout, actual.stderr), (reference.returncode, reference.stdout, reference.stderr))
        self.assertEqual(reference_processes, 401)  # extraction + envelope + 3 JSON reads
        self.assertEqual(helper_processes, 1)  # the single runner process
        self.assertLess(helper_processes, reference_processes)
        print(f"100-command control: reference={reference_seconds:.3f}s/{reference_processes} python processes; helper={helper_seconds:.3f}s/{helper_processes} python processes")


if __name__ == "__main__":
    unittest.main(verbosity=2)
