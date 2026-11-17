import importlib.util
import json
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "outage_apple", Path(__file__).parents[1] / "custom_components/outage_watch/apple.py"
)
apple = importlib.util.module_from_spec(spec)
spec.loader.exec_module(apple)


def service(name, state, kind):
    return {"serviceName": name, "events": [
        {"eventStatus": state, "statusType": kind, "message": "Example incident"}
    ]}


class AppleStatusTests(unittest.TestCase):
    def test_resolved_icloud_and_active_unrelated_outage_do_not_affect_icloud(self):
        payload = {"services": [
            service("iCloud Drive", "resolved", "Outage"),
            service("App Store", "ongoing", "Outage"),
        ]}
        result = apple.parse_icloud(json.dumps(payload).encode())
        self.assertEqual(result["level"], "none")
        self.assertEqual(result["components"], [])

    def test_active_icloud_outage_outranks_performance_issue(self):
        payload = {"services": [
            service("iCloud Web Apps (iCloud.com)", "ongoing", "Performance"),
            service("iCloud Mail", "ongoing", "Outage"),
        ]}
        result = apple.parse_icloud(f"callback({json.dumps(payload)});".encode())
        self.assertEqual(result["level"], "major")
        self.assertEqual(result["components"], ["iCloud Mail", "iCloud Web Apps (iCloud.com)"])

    def test_missing_icloud_components_is_unavailable(self):
        with self.assertRaises(ValueError):
            apple.parse_icloud(b'{"services":[]}')
