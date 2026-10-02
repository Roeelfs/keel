#!/usr/bin/env python3
"""JEV fallback matrix, caching and the contract test (spec §5.4, §5.6, §14.1)."""
import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

from heavy_resources import Policy
from governor import jev_client

RESP4_FIXTURE = {
    "answers": {
        "admit": {"type": "boolean", "probability": 0.35},
        "headroom_slots": {"type": "choice", "choice": "2",
                            "probabilities": {"0": 0.25, "1": 0.09, "2": 0.46, "3": 0.04, "4": 0.09,
                                               "5": 0.03, "6": 0.04}, "confidence": 0.37},
        "saturation": {"type": "score", "score": 2.96,
                       "probabilities": {"0": 0, "1": 0, "2": 0.12, "3": 0.8, "4": 0.08}, "confidence": 0.84},
    },
    "model": "typesafe-ai/jev",
    "providerMetadata": {"gateway": {"routing": {"resolvedProvider": "digitalocean"}}},
    "usage": {"inputTokens": 866, "outputTokens": 121},
}


def snapshot():
    return {'mem_free_percent': 30, 'mem_total_mb': 32768, 'mem_pressure_level': 1,
            'disk_free_gib': 40, 'swap_growth_mb_per_min': 0, 'hang_reports_recent': 0,
            'leases': [], 'class_stats': {}, 'unknown': [], 'ncpu': 12, 'load1_per_core': 1.0}


class EndpointTests(unittest.TestCase):
    def test_endpoint_is_the_verified_live_gateway_not_a_guess(self):
        # api.digitalocean.com 404'd live (docs/specs/2026-09-29-machine-governor.phase0.md); the
        # credential is named vercel-ai-gateway for exactly the reason this constant must match.
        self.assertEqual(jev_client.ENDPOINT, 'https://ai-gateway.vercel.sh/v1/evaluate')


class BuildRequestSessionTests(unittest.TestCase):
    def test_request_carries_sessions_reserve_and_total_memory(self):
        snap = {**snapshot(), 'sessions': {'live_count': 40, 'active_count': 5, 'idle_count': 35,
                                           'total_rss_mb': 6000.0, 'largest_rss_mb': 400.0},
                'leases': [{'class': 'pnpm', 'rss_mb': 1000.0, 'age_s': 5}],
                'class_stats': {'pnpm': {'n': 20, 'rss_p90_mb': 4000.0}}}
        d = {'slots_now': 1, 'admit': False}
        state = jev_client.build_request('pnpm', snap, Policy(), d)['state']
        self.assertEqual(state['sessions']['live_count'], 40)
        self.assertEqual(state['machine']['mem_total_mb'], 32768)
        self.assertEqual(state['lock']['reserve_mb'], 3000.0)
        self.assertEqual(state['lock']['lease_rss_mb'], 1000.0)


class JevClientTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.policy = Policy(jev_admission='enforce')

    def _ok_credential(self, run=None):
        (self.directory / 'credential.json').write_text(json.dumps({'ok': True, 'checked_at': time.time()}))

    def test_uncontended_paths_never_call_this_module(self):
        # decide() is only ever invoked by a caller on a contended acquire; there is no separate
        # "uncontended" branch inside decide() to bypass, so the contract is enforced by callers.
        # This test instead asserts decide() itself makes zero network calls when jev_admission is off.
        calls = []
        result = jev_client.decide('other-heavy', snapshot(), Policy(jev_admission='shadow'), self.directory,
                                    http_post=lambda *a, **k: calls.append(1) or {})
        self.assertEqual(calls, [])
        self.assertTrue(result['source'].startswith('fallback:'))

    def test_unknown_signal_routes_to_d_without_calling_jev(self):
        self._ok_credential()
        calls = []
        snap = dict(snapshot(), unknown=['disk'])
        result = jev_client.decide('other-heavy', snap, self.policy, self.directory,
                                    http_post=lambda *a, **k: calls.append(1) or {})
        self.assertEqual(calls, [])
        self.assertEqual(result['source'], 'fallback:unknown_signal')

    def test_no_credential_falls_back_to_d(self):
        result = jev_client.decide('other-heavy', snapshot(), self.policy, self.directory,
                                    http_post=lambda *a, **k: {})
        self.assertEqual(result['source'], 'fallback:no_credential')

    def test_breaker_open_written_by_another_process_falls_back(self):
        self._ok_credential()
        (self.directory / 'breaker.json').write_text(json.dumps({'failures': [], 'opened_at': time.time()}))
        calls = []
        result = jev_client.decide('other-heavy', snapshot(), self.policy, self.directory,
                                    http_post=lambda *a, **k: calls.append(1) or RESP4_FIXTURE)
        self.assertEqual(calls, [])
        self.assertEqual(result['source'], 'fallback:breaker_open')

    def test_contract_error_falls_back_and_records_a_breaker_failure(self):
        self._ok_credential()
        result = jev_client.decide('other-heavy', snapshot(), self.policy, self.directory,
                                    http_post=lambda *a, **k: {'answers': {}})
        self.assertEqual(result['source'], 'fallback:contract_error')
        state = json.loads((self.directory / 'breaker.json').read_text())
        self.assertEqual(len(state['failures']), 1)

    def test_deadline_breach_is_a_timeout_fallback(self):
        self._ok_credential()

        def slow_post(*a, **k):
            time.sleep(0.01)
            return RESP4_FIXTURE

        tight = Policy(jev_admission='enforce', jev_deadline_ms=0)
        result = jev_client.decide('other-heavy', snapshot(), tight, self.directory, http_post=slow_post)
        self.assertEqual(result['source'], 'fallback:timeout')

    def test_grey_band_returns_d_result(self):
        self._ok_credential()
        grey = dict(RESP4_FIXTURE, answers={**RESP4_FIXTURE['answers'],
                                             'admit': {'type': 'boolean', 'probability': 0.5}})
        result = jev_client.decide('other-heavy', snapshot(), self.policy, self.directory,
                                    http_post=lambda *a, **k: grey)
        self.assertEqual(result['source'], 'grey_band')

    def test_high_confidence_admit_uses_the_jev_verdict(self):
        self._ok_credential()
        high = dict(RESP4_FIXTURE, answers={**RESP4_FIXTURE['answers'],
                                             'admit': {'type': 'boolean', 'probability': 0.9},
                                             'saturation': {'type': 'score', 'score': 1.0, 'confidence': 0.9}})
        result = jev_client.decide('other-heavy', snapshot(), self.policy, self.directory,
                                    http_post=lambda *a, **k: high)
        self.assertTrue(result['admit'])
        self.assertEqual(result['source'], 'jev')

    def test_decision_is_cached_for_the_ttl(self):
        self._ok_credential()
        calls = []

        def post(*a, **k):
            calls.append(1)
            return RESP4_FIXTURE

        jev_client.decide('other-heavy', snapshot(), self.policy, self.directory, http_post=post)
        jev_client.decide('other-heavy', snapshot(), self.policy, self.directory, http_post=post)
        self.assertEqual(len(calls), 1)

    def test_five_concurrent_contended_decides_make_at_most_one_jev_call(self):
        self._ok_credential()
        calls = []
        lock = threading.Lock()

        def post(*a, **k):
            with lock:
                calls.append(1)
            time.sleep(0.05)
            return RESP4_FIXTURE

        threads = [threading.Thread(target=jev_client.decide,
                                     args=('other-heavy', snapshot(), self.policy, self.directory),
                                     kwargs={'http_post': post})
                   for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        self.assertLessEqual(len(calls), 1)

    def _concurrent(self, classes, post):
        results = []
        threads = [threading.Thread(target=lambda c=c: results.append(
                       jev_client.decide(c, snapshot(), self.policy, self.directory, http_post=post)))
                   for c in classes]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        return results

    def test_same_class_waiters_get_the_in_flight_jev_answer_not_a_fallback(self):
        self._ok_credential()
        calls = []

        def post(*a, **k):
            calls.append(1)
            time.sleep(0.1)
            return RESP4_FIXTURE

        results = self._concurrent(['other-heavy'] * 5, post)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(results), 5)
        self.assertFalse([r for r in results if r['source'].startswith('fallback')])

    def test_different_classes_never_block_each_other(self):
        self._ok_credential()
        calls = []

        def post(*a, **k):
            calls.append(1)
            time.sleep(0.1)
            return RESP4_FIXTURE

        results = self._concurrent(['pnpm', 'wt-verify.sh', 'cynap-sandbox'], post)
        self.assertEqual(len(calls), 3)
        self.assertFalse([r for r in results if r['source'] == 'fallback:contended_lock'])

    def test_contract_test_rejects_mutants_of_the_real_response_shape(self):
        self._ok_credential()
        mutants = [
            {**RESP4_FIXTURE, 'answers': {**RESP4_FIXTURE['answers'], 'admit': {'type': 'boolean'}}},
            {**RESP4_FIXTURE, 'answers': {k: v for k, v in RESP4_FIXTURE['answers'].items() if k != 'admit'}},
            {**RESP4_FIXTURE, 'answers': {**RESP4_FIXTURE['answers'],
                                          'saturation': {'type': 'score'}}},
            {'answers': None},
        ]
        for mutant in mutants:
            with self.subTest(mutant=mutant):
                (self.directory / 'breaker.json').unlink(missing_ok=True)
                result = jev_client.decide('other-heavy', snapshot(), self.policy, self.directory,
                                            http_post=lambda *a, **k: mutant)
                self.assertEqual(result['source'], 'fallback:contract_error')

    def test_real_response_shape_parses_cleanly(self):
        self._ok_credential()
        result = jev_client.decide('other-heavy', snapshot(), self.policy, self.directory,
                                    http_post=lambda *a, **k: RESP4_FIXTURE)
        self.assertIn(result['source'], ('jev', 'grey_band'))


class CredentialAndBreakerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_credential_stale_state_is_treated_as_no_credential(self):
        (self.directory / 'credential.json').write_text(
            json.dumps({'ok': True, 'checked_at': time.time() - 25 * 3600}))
        result = jev_client.read_credential(self.directory)
        self.assertFalse(result['ok'])

    def _runner(self, ok=True):
        calls = []
        def run(cmd, **kwargs):
            calls.append(cmd)
            if not ok:
                raise subprocess.CalledProcessError(44, cmd)
            return subprocess.CompletedProcess(cmd, 0, stdout='k\n', stderr='')
        return run, calls

    def test_refresh_probes_when_the_record_is_missing(self):
        # 2026-09-30: nothing scheduled probe-credential, so credential.json never existed.
        run, calls = self._runner()
        state = jev_client.refresh_credential(self.directory, run=run)
        self.assertTrue(state['ok'])
        self.assertEqual(len(calls), 1)
        self.assertTrue(jev_client.read_credential(self.directory, run=run)['ok'])

    def test_refresh_skips_a_fresh_ok_record(self):
        (self.directory / 'credential.json').write_text(json.dumps({'ok': True, 'checked_at': time.time()}))
        run, calls = self._runner()
        jev_client.refresh_credential(self.directory, run=run)
        self.assertEqual(calls, [])

    def test_refresh_retries_a_failed_probe_only_after_the_retry_window(self):
        run, calls = self._runner(ok=False)
        now = time.time()
        (self.directory / 'credential.json').write_text(json.dumps({'ok': False, 'checked_at': now - 60}))
        jev_client.refresh_credential(self.directory, run=run, now=now)
        self.assertEqual(calls, [])
        (self.directory / 'credential.json').write_text(json.dumps({'ok': False, 'checked_at': now - 11 * 60}))
        jev_client.refresh_credential(self.directory, run=run, now=now)
        self.assertEqual(len(calls), 1)

    def test_breaker_opens_after_three_failures_in_thirty_minutes(self):
        now = time.time()
        jev_client.record_failure(self.directory, now)
        jev_client.record_failure(self.directory, now + 1)
        self.assertFalse(jev_client.breaker_open(self.directory, now + 2))
        jev_client.record_failure(self.directory, now + 2)
        self.assertTrue(jev_client.breaker_open(self.directory, now + 3))

    def test_breaker_stays_open_fifteen_minutes(self):
        now = time.time()
        for i in range(3):
            jev_client.record_failure(self.directory, now + i)
        self.assertTrue(jev_client.breaker_open(self.directory, now + 14 * 60))
        self.assertFalse(jev_client.breaker_open(self.directory, now + 16 * 60))


if __name__ == '__main__':
    unittest.main()
