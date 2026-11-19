#!/bin/bash
# Hermetic tests for tooling/harness/context-bar.sh (run: bash tooling/harness/test_context_bar.sh). Fake `claude` on PATH; temp CLAUDE_USAGE_DIR.
HERE=$(cd "$(dirname "$0")" && pwd)
T=$(mktemp -d "${TMPDIR:-/tmp}/cbtest.XXXX")
CB="$T/cb"; mkdir -p "$CB"
NEW="$HERE/context-bar.sh"
# Baseline = the script as of the commit before usage snapshots (immutable SHA).
git -C "$HERE" show 5cc5fe5:tooling/harness/context-bar.sh > "$CB/context-bar.sh.orig" 2>/dev/null || { echo "SKIP: baseline commit 5cc5fe5 unavailable"; rm -rf "$T"; exit 0; }
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/bin"
cat > "$T/bin/claude" <<'F'
#!/bin/bash
echo x >> "$FAKE_LOG"; sleep "${FAKE_SLEEP:-0}"
[[ -n "$FAKE_NOEMAIL" ]] && { echo '{"loggedIn":false}'; exit 1; }
echo '{"loggedIn":true,"email":"test.user@example.com","accessToken":"SECRET-TOKEN-XYZ","authMethod":"claude.ai"}'
F
chmod +x "$T/bin/claude"
export PATH="$T/bin:$PATH" FAKE_LOG="$T/claude.calls" CLAUDE_CONFIG_DIR="$T/cfg"
ACCT=$(echo '{"loggedIn":true,"email":"test.user@example.com"}' | jq -r .email)  # same email the stub claude returns
pass=0; fail=0
ok(){ echo "PASS $1"; pass=$((pass+1)); }
ko(){ echo "FAIL $1"; fail=$((fail+1)); }
waitf(){ for i in $(seq 1 30); do [[ -f "$1" ]] && return 0; sleep 0.1; done; return 1; }
same(){ # $1 name, $2 payload
  printf '%s' "$2" | bash "$CB/context-bar.sh.orig" > "$T/o.out" 2>"$T/o.err"; ro=$?
  printf '%s' "$2" | bash "$NEW"  > "$T/n.out" 2>"$T/n.err"; rn=$?
  if cmp -s "$T/o.out" "$T/n.out" && cmp -s <(sed -E "s/^[^:]+: line [0-9]+:/SCRIPT: line N:/" "$T/o.err") <(sed -E "s/^[^:]+: line [0-9]+:/SCRIPT: line N:/" "$T/n.err") && [[ $ro == $rn ]]; then
    ok "$1: stdout byte-identical, rc same, stderr same modulo script-name/line-no (rc=$ro, $(wc -c <"$T/o.out" | tr -d ' ') bytes, sha $(shasum "$T/o.out" | cut -c1-12))"
  else ko "$1: output differs"; diff <(xxd "$T/o.out") <(xxd "$T/n.out") | head; fi
}
BASE='"model":{"display_name":"Opus"},"cwd":"'$CB'","session_name":"s1","context_window":{"context_window_size":200000}'
WITH='{'$BASE',"rate_limits":{"five_hour":{"used_percentage":23.5,"resets_at":1738425600},"seven_day":{"used_percentage":41.2,"resets_at":1738857600},"spend_limit":{"used_percentage":62.8,"resets_at":1740787200,"used_usd":314.12,"limit_usd":500,"period":"monthly"}}}'
WITHOUT='{'$BASE'}'
ONLY5='{'$BASE',"rate_limits":{"five_hour":{"used_percentage":7,"resets_at":1738425600}}}'
BADRL='{'$BASE',"rate_limits":{"five_hour":{"used_percentage":"lots"},"seven_day":"x"}}'
MALFORMED='{"model":{"display_name":"Opus"},"rate_limits":{"five_hour":'

echo "== 1. with limits"
export CLAUDE_USAGE_DIR="$T/u1"; : > "$FAKE_LOG"
same with-limits "$WITH"
F="$CLAUDE_USAGE_DIR/$ACCT.json"
if waitf "$F"; then
  echo "snapshot: $(cat "$F")"
  jq -e '.account=="test.user@example.com" and .five_hour=={"used_percentage":23.5,"resets_at":1738425600} and .seven_day=={"used_percentage":41.2,"resets_at":1738857600} and (.written_at|type)=="number" and (keys==["account","five_hour","seven_day","written_at"])' "$F" >/dev/null && ok "snapshot content/shape" || ko "snapshot content"
else ko "snapshot not written"; fi
echo "== 2. cache: 5 more runs within TTL"
for i in 1 2 3 4 5; do printf '%s' "$WITH" | bash "$NEW" >/dev/null; done; sleep 0.5
# the two runs in test 1 (orig never calls claude) -> exactly 1 call total
c=$(wc -l < "$FAKE_LOG" | tr -d ' '); [[ $c == 1 ]] && ok "claude auth status spawned once across 6 runs (calls=$c)" || ko "calls=$c"
echo "== 3. stale cache (>10 min) refreshes"
touch -t 202001010000 "$CLAUDE_USAGE_DIR"/.identity-*; printf '%s' "$WITH" | bash "$NEW" >/dev/null; sleep 0.5
c=$(wc -l < "$FAKE_LOG" | tr -d ' '); [[ $c == 2 ]] && ok "stale cache re-spawned (calls=$c)" || ko "calls=$c"
echo "== 4. without limits"
export CLAUDE_USAGE_DIR="$T/u4"; : > "$FAKE_LOG"
same without-limits "$WITHOUT"; sleep 0.5
[[ -z "$(ls -A "$CLAUDE_USAGE_DIR" 2>/dev/null)" ]] && ok "nothing written, claude not spawned (calls=$(wc -l <"$FAKE_LOG"|tr -d ' '))" || ko "wrote: $(ls -A "$CLAUDE_USAGE_DIR")"
echo "== 5. malformed JSON"
export CLAUDE_USAGE_DIR="$T/u5"
same malformed "$MALFORMED"; sleep 0.5
[[ -z "$(ls -A "$CLAUDE_USAGE_DIR" 2>/dev/null)" ]] && ok "malformed: nothing written" || ko "malformed wrote"
echo "== 6. only five_hour"
export CLAUDE_USAGE_DIR="$T/u6"
same only-five-hour "$ONLY5"; F="$CLAUDE_USAGE_DIR/$ACCT.json"
waitf "$F" && jq -e '.five_hour.used_percentage==7 and .seven_day==null' "$F" >/dev/null && ok "partial window -> seven_day null" || ko "partial"
echo "== 7. rate_limits with non-numeric fields"
export CLAUDE_USAGE_DIR="$T/u7"
same bad-rate-limits "$BADRL"; sleep 0.5
[[ -z "$(ls -A "$CLAUDE_USAGE_DIR" 2>/dev/null)" ]] && ok "invalid windows: nothing written" || ko "bad-rl wrote"
echo "== 8. no identity obtainable"
export CLAUDE_USAGE_DIR="$T/u8" FAKE_NOEMAIL=1
same no-identity "$WITH"; sleep 0.5; unset FAKE_NOEMAIL
[[ -z "$(ls -A "$CLAUDE_USAGE_DIR" 2>/dev/null)" ]] && ok "no identity: nothing written (no cache either)" || ko "no-identity wrote: $(ls -A "$CLAUDE_USAGE_DIR")"
echo "== 9. no tokens anywhere"
grep -rl 'SECRET-TOKEN' "$T"/u* 2>/dev/null && ko "token leaked" || ok "fake token absent from all usage dirs"
ls -la "$T/u1" | sed 's/^/   /'
echo "== 10. latency: slow claude (FAKE_SLEEP=3), cold cache, 10 runs each"
export CLAUDE_USAGE_DIR="$T/u10" FAKE_SLEEP=3
t0=$(perl -MTime::HiRes=time -e 'printf "%.3f", time')
for i in $(seq 10); do printf '%s' "$WITH" | bash "$CB/context-bar.sh.orig" >/dev/null; done
t1=$(perl -MTime::HiRes=time -e 'printf "%.3f", time')
for i in $(seq 10); do printf '%s' "$WITH" | bash "$NEW" >/dev/null; done
t2=$(perl -MTime::HiRes=time -e 'printf "%.3f", time')
o=$(echo "($t1-$t0)*100" | bc); n=$(echo "($t2-$t1)*100" | bc)
echo "   orig avg ${o}ms/run, new avg ${n}ms/run (each new run had a 3s claude spawn pending)"
awk -v o="$o" -v n="$n" 'BEGIN{exit !(n < o + 50)}' && ok "no perceptible latency (<+50ms) even with 3s auth spawn" || ko "latency"
echo "== 11. stdout pipe closes immediately (Claude Code reads to EOF)"
s=$(perl -MTime::HiRes=time -e 'printf "%.3f", time'); printf '%s' "$WITH" | bash "$NEW" | cat >/dev/null
e=$(perl -MTime::HiRes=time -e 'printf "%.3f", time'); d=$(echo "($e-$s)*1000" | bc)
awk -v d="$d" 'BEGIN{exit !(d < 1000)}' && ok "pipe EOF after ${d}ms (bg writer does not hold stdout)" || ko "pipe held ${d}ms"
unset FAKE_SLEEP; sleep 3.5
echo "RESULT: $pass passed, $fail failed"
[[ $fail == 0 ]]
