import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "outage_statuspage", Path(__file__).parents[1] / "custom_components/outage_watch/statuspage.py"
)
statuspage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(statuspage)


class ProviderSummaryTests(unittest.TestCase):
    def test_summary_only_reports_impacted_components(self):
        payload = {"page": {"name": "Example"}, "status": {"indicator": "minor"}, "components": [
            {"name": "Relay", "status": "degraded_performance"},
            {"name": "Login", "status": "operational"},
        ]}
        result = statuspage.parse_feed(payload, summary_only=True)
        self.assertEqual(result["level"], "minor")
        self.assertEqual(result["components"], ["Relay"])

    def test_missing_incidents_is_only_allowed_for_known_summary_feeds(self):
        payload = {"status": {"indicator": "none"}, "page": {"name": "Example"}, "components": []}
        with self.assertRaises(KeyError):
            statuspage.parse_feed(payload)
        self.assertEqual(statuspage.parse_feed(payload, summary_only=True)["level"], "none")
