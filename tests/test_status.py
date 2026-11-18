import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "outage_status", Path(__file__).parents[1] / "custom_components/outage_watch/status.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
summarize = module.summarize

class StatusTests(unittest.TestCase):
    def evaluate(self, outcomes, feed=None, connected=True, run_start=0):
        samples = [(1000 + i * 15, outcome, 100 if outcome == "ok" else None)
                   for i, outcome in enumerate(outcomes)]
        return summarize(samples, feed or {}, connected, 1000 + len(samples) * 15, 120, run_start)

    def test_provider_and_local_failure_are_distinct(self):
        self.assertEqual(self.evaluate([], {"level": "major"})[:2], ("outage", "provider_outage"))
        self.assertEqual(self.evaluate(["failed"] * 3)[:2], ("outage", "unreachable"))

    def test_blocked_does_not_extend_failure_streak(self):
        self.assertEqual(self.evaluate(["failed", "failed", "blocked"])[:2], ("unknown", "blocked"))

    def test_reconnect_discards_pre_disconnect_failure_streak(self):
        self.assertEqual(self.evaluate(["failed"] * 3, connected=False)[:2], ("unknown", "internet_down"))
        self.assertEqual(self.evaluate(["failed"] * 3, run_start=1030)[:2], ("unknown", "failed"))

    def test_latency_baseline_needs_twenty_prior_successful_samples(self):
        history = [(i, "ok", 100) for i in range(20)]
        self.assertEqual(summarize(history + [(20, "ok", 400)], {}, True, 21, 120), ("possible_problems", "slow", 100))
        self.assertEqual(summarize(history[1:] + [(20, "ok", 400)], {}, True, 21, 120), ("operational", "ok", None))

    def test_no_fresh_feed_or_probe_is_unknown(self):
        self.assertEqual(self.evaluate([])[:2], ("unknown", "no_data"))

    def test_continuous_failure_through_maximum_backoff(self):
        interval = 300
        freshness = 5 * interval
        samples = []
        # After three failures the scheduler doubles the delay, up to four intervals.
        for minute in (0, 5, 10, 20, 40, 60, 80):
            now = minute * 60
            samples.append((now, "failed", None))
            if len(samples) >= 3:
                for offset in (0, interval * (2 if minute == 10 else 4) - 1):
                    with self.subTest(minute=minute, offset=offset):
                        self.assertEqual(summarize(samples, {}, True, now + offset, freshness)[:2],
                                         ("outage", "unreachable"))

        self.assertEqual(summarize(samples, {}, True, now + freshness, freshness)[:2],
                         ("unknown", "no_data"))
        self.assertEqual(summarize(samples, {"level": "major"}, True, now, freshness)[:2],
                         ("outage", "provider_outage"))
        self.assertEqual(summarize(samples, {}, True, now, freshness, run_start=now)[:2],
                         ("unknown", "failed"))
        samples.append((now + 4 * interval, "ok", 100))
        self.assertEqual(summarize(samples, {}, True, samples[-1][0], freshness)[:2],
                         ("operational", "ok"))

    def test_gap_in_observations_breaks_failure_streak(self):
        samples = [(0, "failed", None), (300, "failed", None), (3000, "failed", None)]
        self.assertEqual(summarize(samples, {}, True, 3000, 1500)[:2], ("unknown", "failed"))
