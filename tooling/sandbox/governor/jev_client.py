"""Contended-only JEV admission client (spec §5.4, §5.6).

One owner module for the `/v1/evaluate` contract. Called only on a contended acquire, after §5.3
floors found nothing and no snapshot input is unknown. Falls back to rule D on any error, deadline
breach, open breaker, missing credential or contract error — 0 retries.
"""
from datetime import datetime, timezone
import fcntl
import json
import os
import subprocess
import time
import urllib.error
import urllib.request

from governor import admission

ENDPOINT = 'https://ai-gateway.vercel.sh/v1/evaluate'  # verified live 2026-09-29 (phase0.md); the
# credential is named vercel-ai-gateway for exactly this reason. An earlier api.digitalocean.com
# guess -- "digitalocean" is only the *resolvedProvider* the gateway picked, never the URL to call
# -- 404'd with {"id":"not_found","message":"Your request could not be routed."}; fixed before any
# JEV code shipped live.
CREDENTIAL_SERVICE = 'vercel-ai-gateway'
BREACH_THRESHOLD = 3
BREACH_WINDOW_S = 30 * 60
BREAKER_OPEN_S = 15 * 60
CREDENTIAL_TTL_S = 24 * 3600
CREDENTIAL_RETRY_S = 10 * 60
CREDENTIAL_TIMEOUT_S = 0.25


def _read_json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _write_json_locked(path, value):
    with path.open('a+') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.seek(0)
        stream.truncate()
        stream.write(json.dumps(value, sort_keys=True))
        stream.flush()


def breaker_open(directory, now=None):
    """Open only while inside the 15-minute open window that followed the 3rd failure.

    Once that window expires the breaker is closed, even if all 3 failures are still inside the
    30-minute failure-count window -- `record_failure` resets the failure count on the next call
    after expiry, so it takes a fresh 3 failures to reopen it.
    """
    now = now or time.time()
    state = _read_json(directory / 'breaker.json') or {}
    opened_at = state.get('opened_at')
    return bool(opened_at and now - opened_at < BREAKER_OPEN_S)


def record_failure(directory, now=None):
    now = now or time.time()
    path = directory / 'breaker.json'
    with path.open('a+') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.seek(0)
        raw = stream.read()
        state = {}
        if raw:
            try:
                state = json.loads(raw)
            except json.JSONDecodeError:
                state = {}
        opened_at = state.get('opened_at')
        if opened_at and now - opened_at >= BREAKER_OPEN_S:
            state = {}  # the open window has expired; a fresh cycle needs a fresh 3 failures
            opened_at = None
        failures = [t for t in state.get('failures', []) if now - t < BREACH_WINDOW_S]
        failures.append(now)
        if len(failures) >= BREACH_THRESHOLD and not opened_at:
            opened_at = now
        state = {'failures': failures, 'opened_at': opened_at}
        stream.seek(0)
        stream.truncate()
        stream.write(json.dumps(state, sort_keys=True))


def record_success(directory):
    _write_json_locked(directory / 'breaker.json', {'failures': [], 'opened_at': None})


def read_credential(directory, run=None, now=None):
    """`{ok, key}` — only reads Keychain when credential.json says fresh+ok (§5.6)."""
    now = now or time.time()
    state = _read_json(directory / 'credential.json') or {}
    if not state.get('ok') or now - state.get('checked_at', 0) >= CREDENTIAL_TTL_S:
        return {'ok': False, 'key': None}
    runner = run or subprocess.run
    try:
        result = runner(['/usr/bin/security', 'find-generic-password', '-s', CREDENTIAL_SERVICE, '-w'],
                         capture_output=True, text=True, timeout=CREDENTIAL_TIMEOUT_S, check=True)
    except (OSError, subprocess.SubprocessError):
        return {'ok': False, 'key': None}
    return {'ok': True, 'key': result.stdout.strip()}


def probe_credential(directory, run=None):
    """`governor probe-credential` — records freshness so the hot path never blocks on Keychain."""
    runner = run or subprocess.run
    try:
        runner(['/usr/bin/security', 'find-generic-password', '-s', CREDENTIAL_SERVICE, '-w'],
               capture_output=True, text=True, timeout=CREDENTIAL_TIMEOUT_S, check=True)
        ok = True
    except (OSError, subprocess.SubprocessError):
        ok = False
    state = {'ok': ok, 'checked_at': time.time()}
    _write_json_locked(directory / 'credential.json', state)
    return state


def refresh_credential(directory, run=None, now=None):
    """Re-probe Keychain when `credential.json` is missing, past its TTL, or a failed probe older
    than CREDENTIAL_RETRY_S. Nothing scheduled `probe-credential`, so without this the record never
    existed and every decide() fell back with `no_credential` (2026-09-30). Only called off the
    ticket-heartbeat thread (heavy_runner.consult_jev), so a slow Keychain never stalls a waiter.
    """
    now = now or time.time()
    state = _read_json(directory / 'credential.json') or {}
    age = now - state.get('checked_at', 0)
    if state.get('ok') and age < CREDENTIAL_TTL_S:
        return state
    if not state.get('ok') and state and age < CREDENTIAL_RETRY_S:
        return state
    return probe_credential(directory, run=run)


def build_request(job_class, snapshot, policy, d_result):
    row = admission.class_row(snapshot.get('class_stats') or {}, job_class)
    leases = snapshot.get('leases') or []
    reserve = admission.reserve_mb(leases, snapshot.get('class_stats') or {})
    return {
        'model': 'typesafe-ai/jev',
        'state': {
            'job': {'class': job_class,
                    'est_run_p50_s': row.get('run_p50_s'),
                    'est_run_p90_s': row.get('run_p90_s'),
                    'est_peak_rss_mb': row.get('rss_p90_mb')},
            'machine': {'ncpu': snapshot.get('ncpu'), 'load1_per_core': snapshot.get('load1_per_core'),
                        'mem_pressure_level': snapshot.get('mem_pressure_level'),
                        'mem_free_percent': snapshot.get('mem_free_percent'),
                        'mem_total_mb': snapshot.get('mem_total_mb'),
                        'swap_used_mb': snapshot.get('swap_used_mb'), 'swap_total_mb': snapshot.get('swap_total_mb'),
                        'swap_growth_mb_per_min': snapshot.get('swap_growth_mb_per_min'),
                        'disk_free_gb': snapshot.get('disk_free_gib')},
            'lock': {'leases_live': len(snapshot.get('leases') or []),
                     'lease_ages_s': [l.get('age_s') for l in (snapshot.get('leases') or [])],
                     'lease_classes': [l.get('class') for l in (snapshot.get('leases') or [])],
                     'reserve_mb': round(reserve, 1),
                     'lease_rss_mb': round(sum(l.get('rss_mb') or 0.0 for l in leases), 1),
                     'queued': snapshot.get('queued'), 'deferrals_last_60m': snapshot.get('deferrals_last_60m')},
            'sessions': snapshot.get('sessions'),
            'desktop_apps_footprint_mb': snapshot.get('desktop_apps'),
            'd_rule': {'slots_now': d_result['slots_now'], 'admit': d_result['admit']},
        },
        'questions': {
            'admit': {'type': 'boolean',
                      'instructions': ('This machine also hosts state.sessions interactive Claude agent '
                                       'sessions, plus the interactive desktop apps in state.desktop_apps_footprint_mb (the ChatGPT app '
                                       'hosts the Codex desktop agent), none of which may be stalled or '
                                       'OOM-killed. Their memory can grow by GBs without warning; a ChatGPT or Claude tree over ~8000 MB is a hog that '
                                       'shrinks headroom. Running jobs will '
                                       'still grow by state.lock.reserve_mb toward their p90 peak. Can ONE '
                                       'more job of job.class start now? Admit only if free memory '
                                       '(mem_free_percent of mem_total_mb), after this job reaches '
                                       'est_peak_rss_mb AND the running jobs grow by reserve_mb, still leaves '
                                       'the interactive sessions comfortable: no critical memory pressure, '
                                       'no swap exhaustion, no unresponsive apps.')},
            'headroom_slots': {'type': 'choice', 'criteria': {str(n): str(n) for n in range(1, 7)}},
            'saturation': {'type': 'score', 'criteria': ['idle', 'light', 'moderate', 'heavy', 'thrashing']},
        },
    }


def _cache_path(directory, job_class):
    return directory / f'decision.{job_class}.json'


def _cached_decision(directory, job_class, now, max_age_s):
    cached = _read_json(_cache_path(directory, job_class))
    if not cached:
        return None
    if now - cached.get('cached_at', 0) > max_age_s:
        return None
    return cached['decision']


def invalidate_decision(directory, job_class):
    """Drop a class's cached verdict so the next waiter consults afresh (one admit = one job)."""
    _cache_path(directory, job_class).unlink(missing_ok=True)


def _map_answers(answers, policy, d_result):
    admit_p = answers.get('admit', {}).get('probability')
    saturation = answers.get('saturation', {})
    saturation_score = saturation.get('score')
    saturation_confidence = saturation.get('confidence', 0)
    headroom = answers.get('headroom_slots', {})
    headroom_choice = headroom.get('choice')
    headroom_confidence = headroom.get('confidence', 0)
    if admit_p is None or saturation_score is None:
        raise ValueError('contract error: missing admit or saturation answer')
    if admit_p >= policy.admit_p_hi and saturation_score < policy.saturation_deny:
        slots = int(headroom_choice) if headroom_choice and headroom_confidence >= 0.30 else d_result['slots_now']
        return {'admit': True, 'slots_now': max(1, min(slots, policy.max_slots))}
    if admit_p < policy.admit_p_lo or (saturation_score >= policy.saturation_deny and saturation_confidence >= 0.6):
        return {'admit': False, 'slots_now': d_result['slots_now']}
    return dict(d_result, source='grey_band')


LOCK_POLL_S = 0.025


def _acquire_within(lock_stream, timeout_s):
    """Take the class lock, waiting up to `timeout_s` for an in-flight consult to finish.

    The holder writes its verdict to the cache before releasing, so a waiter that gets the lock
    finds the fresh answer on its cache re-check instead of making a second call.
    """
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            fcntl.flock(lock_stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(LOCK_POLL_S)


def decide(job_class, snapshot, policy, directory, http_post=None, run=None, now=None):
    """Returns `{admit, slots_now, source, latency_ms}`. Never raises; falls back to D."""
    now = now or time.time()
    d_result = admission.rule_d(job_class, snapshot, policy)
    if policy.jev_admission != 'enforce' and policy.jev_admission != 'shadow':
        return {**d_result, 'source': 'fallback:jev_off', 'latency_ms': 0}
    if admission.any_unknown(snapshot):
        return {**d_result, 'source': 'fallback:unknown_signal', 'latency_ms': 0}
    # One lock per class: a call in flight for one class never blocks another class
    # (measured 2026-09-30: a single shared lock turned 21 of 147 consults into fallbacks).
    lock_path = directory / f'decide.{job_class}.lock'
    cached = _cached_decision(directory, job_class, now, policy.decision_ttl_s)
    if cached is not None:
        return {**cached, 'source': cached.get('source', 'cache'), 'latency_ms': 0}
    with lock_path.open('a') as lock_stream:
        if not _acquire_within(lock_stream, policy.jev_deadline_ms / 1000):
            stale = _cached_decision(directory, job_class, now, 40)
            return {**(stale or d_result), 'source': 'fallback:contended_lock', 'latency_ms': 0}
        try:
            cached = _cached_decision(directory, job_class, now, policy.decision_ttl_s)
            if cached is not None:
                return {**cached, 'source': cached.get('source', 'cache'), 'latency_ms': 0}
            if breaker_open(directory, now):
                return {**d_result, 'source': 'fallback:breaker_open', 'latency_ms': 0}
            credential = read_credential(directory, run=run, now=now)
            if not credential['ok']:
                return {**d_result, 'source': 'fallback:no_credential', 'latency_ms': 0}
            request = build_request(job_class, snapshot, policy, d_result)
            started = time.monotonic()
            poster = http_post or _default_http_post
            try:
                response = poster(ENDPOINT, request, credential['key'], policy.jev_deadline_ms / 1000)
                latency_ms = round((time.monotonic() - started) * 1000, 1)
                if latency_ms > policy.jev_deadline_ms:
                    record_failure(directory, now)
                    return {**d_result, 'source': 'fallback:timeout', 'latency_ms': latency_ms}
                mapped = _map_answers(response['answers'], policy, d_result)
                record_success(directory)
                decision = {'admit': mapped['admit'], 'slots_now': mapped['slots_now'],
                            'source': mapped.get('source', 'jev'),
                            'resolved_provider': response.get('providerMetadata', {}).get('resolvedProvider'),
                            'usage': response.get('usage')}
                _write_json_locked(_cache_path(directory, job_class),
                                    {'cached_at': now, 'decision': decision})
                return {**decision, 'latency_ms': latency_ms}
            except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError,
                    TypeError, AttributeError) as error:
                record_failure(directory, now)
                reason = 'timeout' if isinstance(error, TimeoutError) else 'contract_error'
                return {**d_result, 'source': f'fallback:{reason}', 'latency_ms': round((time.monotonic() - started) * 1000, 1)}
        finally:
            fcntl.flock(lock_stream, fcntl.LOCK_UN)


def _default_http_post(url, payload, key, timeout_s):
    request = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                      headers={'Content-Type': 'application/json',
                                               'Authorization': f'Bearer {key}'})
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        return json.loads(response.read())
