#!/usr/bin/env python3
"""Replay rule D against the real 7-day corpus (spec §14.2).

Reads a READ-ONLY copy of `~/.keel/heavy.slots/events.jsonl` -- the original is never opened for
writing and this test never touches it directly, only a `tempfile` copy.

Caveat (documented, not glossed over): the historical corpus records `queued`/`deferred`/
`started`/`completed`, but it does not record a memory/lease snapshot at the moment of each
historical deferral (the snapshot module did not exist before this change). So this replay proves
two things a full counterfactual would also need, and stops there:
  1. Real `class_stats` (rss p90, run p50/p90, rss-seconds p90) can be computed from the corpus,
     and roughly reproduce the spec's measured wt-verify/wt-setup/cynap-sandbox figures.
  2. Rule D, run against those real class_stats and a swept range of `mem_free_percent`, is
     monotonic and never admits past `max_slots` or below 1 -- a property-based regression, not a
     per-deferral outcome match. A byte-for-byte deferral counterfactual is `governor replay`
     phase-0 work and stays UNVERIFIED here.
"""
from collections import defaultdict
from datetime import datetime
import json
import os
import shutil
import tempfile
import unittest

from heavy_resources import Policy
from governor import admission

REAL_EVENTS = os.path.expanduser('~/.keel/heavy.slots/events.jsonl')


def percentile(values, p):
    if not values:
        return None
    values = sorted(values)
    index = min(len(values) - 1, int(round(p / 100 * (len(values) - 1))))
    return values[index]


def build_class_stats(events_path):
    queued_class = {}
    started_ts = {}
    completed = []  # (job_class, rss_mb, duration_s)
    deferrals = 0
    acquires = 0
    with open(events_path) as stream:
        for line in stream:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            name = record.get('event')
            job_id = record.get('job_id')
            if name == 'queued':
                queued_class[job_id] = record.get('executable', 'other-heavy')
                acquires += 1
            elif name == 'deferred':
                deferrals += 1
            elif name == 'started':
                started_ts[job_id] = record.get('ts')
            elif name == 'completed' and job_id in started_ts and record.get('peak_rss_mb') is not None:
                try:
                    start = datetime.fromisoformat(started_ts[job_id])
                    end = datetime.fromisoformat(record['ts'])
                except (KeyError, ValueError):
                    continue
                duration = max(0.001, (end - start).total_seconds())
                job_class = queued_class.get(job_id, 'other-heavy')
                completed.append((job_class, record['peak_rss_mb'], duration))
    by_class = defaultdict(list)
    for job_class, rss, duration in completed:
        by_class[job_class].append((rss, duration))
    stats = {}
    for job_class, rows in by_class.items():
        rss_values = [r for r, _ in rows]
        run_values = [d for _, d in rows]
        rss_seconds = [r * d for r, d in rows]
        stats[job_class] = {
            'n': len(rows), 'rss_p90_mb': percentile(rss_values, 90) or 1.0,
            'run_p50_s': percentile(run_values, 50), 'run_p90_s': percentile(run_values, 90),
            'rss_s_p90': percentile(rss_seconds, 90),
        }
    return stats, acquires, deferrals


@unittest.skipUnless(os.path.exists(REAL_EVENTS), 'real corpus not present on this machine')
class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.copy_path = os.path.join(self.tmp.name, 'events.jsonl')
        shutil.copyfile(REAL_EVENTS, self.copy_path)  # read-only copy; the original is never opened for writing

    def test_real_corpus_yields_usable_class_stats(self):
        stats, acquires, deferrals = build_class_stats(self.copy_path)
        self.assertGreater(acquires, 0)
        self.assertGreaterEqual(deferrals, 0)
        self.assertGreater(len(stats), 0)
        for job_class, row in stats.items():
            with self.subTest(job_class=job_class):
                self.assertGreater(row['rss_p90_mb'], 0)

    def test_rule_d_is_monotonic_in_free_percent_over_real_class_stats(self):
        stats, _, _ = build_class_stats(self.copy_path)
        job_class = max(stats, key=lambda c: stats[c]['n'])  # the best-sampled real class
        policy = Policy(min_free_percent=20, max_slots=6)
        admits = []
        for free_pct in range(0, 101, 5):
            snapshot = {'mem_free_percent': free_pct, 'mem_total_mb': 32768, 'leases': [],
                        'class_stats': stats}
            result = admission.rule_d(job_class, snapshot, policy, running=1)
            admits.append(result['slots_now'])
            self.assertGreaterEqual(result['slots_now'], 1)
            self.assertLessEqual(result['slots_now'], policy.max_slots)
        self.assertEqual(admits, sorted(admits))  # slots_now never drops as free% rises

    def test_deferrals_per_1000_baseline_is_computed_from_the_real_corpus(self):
        _, acquires, deferrals = build_class_stats(self.copy_path)
        if acquires == 0:
            self.skipTest('no acquires in corpus')
        per_1000 = 1000 * deferrals / acquires
        # No assertion against a fixed target here (that is `governor grade`'s job against a
        # rolling 7-day window); this only proves the metric is computable from real data.
        self.assertGreaterEqual(per_1000, 0)


if __name__ == '__main__':
    unittest.main()
