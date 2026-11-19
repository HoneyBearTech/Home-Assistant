import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "xai", Path(__file__).resolve().parents[1] / "custom_components/outage_watch/xai.py"
)
xai = importlib.util.module_from_spec(spec)
spec.loader.exec_module(xai)


class XaiFeedTests(unittest.TestCase):
    def test_only_active_grok_incidents_affect_status(self):
        source = """<rss><channel><link>https://status.x.ai</link>
        <item><link>https://status.x.ai/cursor-com/1</link><category>outage</category></item>
        <item><link>https://status.x.ai/grok-com/2</link><category>outage</category>
        <category>resolved</category></item>
        <item><link>https://status.x.ai/api-global/3</link><category>disruption</category>
        <title>[API Global] Elevated errors</title></item>
        </channel></rss>"""
        status = xai.parse_xai(source)
        self.assertEqual(status["level"], "minor")
        self.assertEqual(status["incident"], "[API Global] Elevated errors")
        self.assertEqual(status["components"], ["API Global"])

    def test_rejects_invalid_xml(self):
        with self.assertRaises(ValueError):
            xai.parse_xai("<rss>")
