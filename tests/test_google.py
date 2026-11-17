import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "outage_google", Path(__file__).parents[1] / "custom_components/outage_watch/google.py"
)
google = importlib.util.module_from_spec(spec)
spec.loader.exec_module(google)


class GoogleWorkspaceTests(unittest.TestCase):
    def test_outage_outranks_disruption_and_resolved_incidents_are_ignored(self):
        incidents = [
            {"id": "1", "begin": "2026-01-01", "end": "2026-01-02",
             "status_impact": "SERVICE_OUTAGE", "affected_products": [{"title": "Drive"}]},
            {"id": "2", "begin": "2026-01-02", "status_impact": "SERVICE_DISRUPTION",
             "affected_products": [{"title": "Gmail"}]},
            {"id": "3", "begin": "2026-01-02", "status_impact": "SERVICE_OUTAGE",
             "affected_products": [{"title": "Calendar"}]},
        ]
        result = google.parse_workspace(incidents)
        self.assertEqual(result["level"], "major")
        self.assertEqual(result["components"], ["Calendar", "Gmail"])
        self.assertEqual(google.parse_workspace(incidents[:1])["level"], "none")
        self.assertEqual(google.parse_workspace(incidents[1:2])["level"], "minor")

    def test_unexpected_payload_is_rejected(self):
        with self.assertRaises(ValueError):
            google.parse_workspace({"status": "ok"})
