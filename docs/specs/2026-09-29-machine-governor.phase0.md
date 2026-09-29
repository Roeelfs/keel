# Phase-0 evidence: JEV Keychain credential + one live smoke call

> Evidence for docs/specs/2026-09-29-machine-governor.md §5.6 (Keychain resolution) and phase-0
> item 1. Recorded 2026-09-29 by the keel-side phase-1 implementation session, against the real
> machine (`security` Keychain, live `ai-gateway.vercel.sh`). No install into `~/.keel`/`~/.claude`
> happened as part of this; the client's on-disk state (breaker/cache/credential.json) was written
> to a throwaway temp directory, not the real `~/.keel/governor`.

## Credential probe (§5.6, phase-0 item 1)

`/usr/bin/security find-generic-password -s vercel-ai-gateway -w`, run twice (once bare with a 3s
`timeout`, once via `governor.jev_client.probe_credential()`): **both returned immediately (exit
0) with no Keychain/securityd prompt.** The founder's one-time interactive grant
(`security add-generic-password -U -s vercel-ai-gateway -a "$USER" -T /usr/bin/security -w
"<key>"`) was already in place before this session started. `probe_credential()` wrote a fresh
`{ok: true, checked_at: <now>}` to the (temp-directory) `credential.json`, matching the §5.6
contract.

**Conclusion: phase-0 item 1 is satisfied.** JEV can read its credential from both a plain Bash
context and from `governor.jev_client`'s own code path with zero interactive friction.

## Endpoint correction (found during this smoke test)

`jev_client.py`'s `ENDPOINT` constant was a guess (`https://api.digitalocean.com/v1/evaluate`),
reasoning from `resp4.json`'s `providerMetadata.gateway.routing.resolvedProvider: "digitalocean"`
field — that field names the upstream provider the gateway routed to, not the URL to call. Calling
it live 404'd:

```
HTTP Error 404: Not Found
{"id":"not_found","message":"Your request could not be routed."}
```

The credential's Keychain service name, `vercel-ai-gateway`, was the actual clue. The correct
endpoint, per `/tmp/governor/spec-author/SPEC.bak.md:172` (an earlier probe log from the spec's own
authoring session): `POST https://ai-gateway.vercel.sh/v1/evaluate`. Fixed in
`tooling/sandbox/governor/jev_client.py` before any of this shipped live (`governor_mode` and
`jev_admission` both still default to `shadow`, so this constant was never on a real admission
path). Both wrong-endpoint attempts count against this session's live-call budget below.

## Live smoke call (phase-0 item 1, one call of record)

**Request:** `decide('cynap-verify-quick', <realistic contended snapshot>, Policy(jev_admission=
'enforce'), <temp dir>)` — no injected `http_post`, so this made a real network call through
`_default_http_post` to `https://ai-gateway.vercel.sh/v1/evaluate` with the real Keychain key as a
Bearer token.

Synthetic-but-realistic snapshot (this machine had no genuinely contended acquire at the moment of
the test, so the state was hand-built from the spec's own `req4.json` shape): `mem_free_percent=
22`, `mem_pressure_level=2`, `swap_used_mb=5200/7168`, `swap_growth_mb_per_min=15`, `disk_free_gib=
40`, 2 live leases (`wt-verify` 900MB/12s, `cynap-verify-quick` 2400MB/210s), `queued=3`,
`deferrals_last_60m=2`, `class_stats.cynap-verify-quick={run_p50_s:362, run_p90_s:600,
rss_p90_mb:3100, n:40}`.

**Result:**

| Field | Value |
|---|---|
| `source` | `jev` (the live verdict was used, not a fallback) |
| `admit` | `false` |
| `slots_now` | `2` |
| `latency_ms` | `1158.8` (within the 1500ms `jev_deadline_ms` budget) |
| `usage` | `{inputTokens: 659, outputTokens: 95}` |
| `resolved_provider` | `null` (this response's `providerMetadata.gateway.routing.resolvedProvider` was absent/null this call, unlike the historical `resp4.json` sample which showed `digitalocean`) |
| Keychain prompt? | **No** — confirmed no prompt on either the bare `security` probe or the live `decide()` call |
| Breaker state after | `{failures: [], opened_at: None}` (clean; `record_success` ran) |
| Decision cached | Yes, under `decision.cynap-verify-quick.json` for the 20s TTL |

The contract parsed cleanly: `admit`/`saturation`/`headroom_slots` answers were all present and
well-typed, so `_map_answers` ran without raising. `saturation`/`headroom_slots` confidence values
were not separately preserved outside the mapped decision (only `admit`/`slots_now`/`source`/
`usage` are cached per §5.4's ADMIT contract) — a future session wanting the full per-answer
probabilities back should log the raw response, not just the mapped decision.

**Live-call budget for this session: 3 of the allowed ≤3 used** — 2 against the wrong (guessed)
endpoint (404, no real JEV work done), 1 successful call against the corrected endpoint (this
result). No further live JEV calls were made after this.

## Still unproven from phase-0's list

- Item 2 (`governor replay --mode lock-only` for k=2..6) — not run; needs the replay CLI, which is
  phase-2/future work beyond this session's scope.
- Item 3 (session-archive tool probe) and item 4 (`ListAgents` local-session visibility) — both
  require a live `-p` lane, which this session (a leaf agent barred from spawning) could not run.
- Item 5 (`governor-snapshot --json` p95 timing) — a single live run of `snapshot.take()` against
  this machine measured `took_ms=65.5` (well under the 300ms budget) with `registry.build()` adding
  another ~237ms for a 49-entry session registry, total 329ms end to end for the CONTEXT block.
  That is one sample, not the 10x p95 phase-0 asks for.
- Item 6 (`spawn-lane.sh --effort`/`--allowed-tools` argv test) — moot: lane spawning was dropped
  by the 2026-09-29 founder rescope and is not part of this phase-1 build.
