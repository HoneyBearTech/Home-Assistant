"""Exercise the real polling loops with simulated time and local HTTP responses."""
import asyncio
from importlib import import_module
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

# The repository checks run with the standard library. Isolate the integration's
# external imports so these tests can exercise its scheduler without starting HA.
package = ModuleType("polling_test_component")
package.__path__ = [str(Path(__file__).parents[1] / "custom_components/outage_watch")]
framework = {name: MagicMock() for name in (
    "homeassistant.helpers", "homeassistant.helpers.dispatcher", "homeassistant.helpers.storage",
    "aiohttp", "aiohttp.abc", "yarl",
)}
framework["aiohttp.abc"].AbstractResolver = object
framework["aiohttp"].ClientError = OSError
with patch.dict(sys.modules, {package.__name__: package, **framework}):
    monitor = import_module(package.__name__ + ".monitor")
    network = import_module(package.__name__ + ".network")
    polling = import_module(package.__name__ + ".polling")


class StopClock(Exception):
    """End a simulated watch loop."""


class HttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_deadlines_on_both_http_paths(self):
        session = MagicMock()
        response = Mock()
        session.request.return_value.__aenter__.return_value = response
        session.get.return_value.__aenter__.return_value = response
        with patch.object(polling, "time", return_value=100), patch.object(network, "public_url", str):
            for status, header, expected in [
                (429, "120", 220), (503, "Thu, 01 Jan 1970 00:03:00 GMT", 180),
                (429, None, 0), (503, "invalid", 0), (429, "-3", 0), (500, "999", 0),
            ]:
                with self.subTest(status=status, header=header):
                    response.status = status
                    response.headers = {"Retry-After": header} if header is not None else {}
                    result = await network.probe(session, "https://example.test/check")
                    self.assertEqual(result[2:], (status, expected))
                    self.assertEqual(await network.feed_update(session, "feed", {}), (None, expected))
        previous = {"data": {"level": "none"}, "etag": "abc"}
        response.status = 304
        self.assertEqual(await network.feed_update(session, "feed", previous), (previous, 0))
        session.get.assert_called_with("feed", headers={"If-None-Match": "abc"}, allow_redirects=False)


class MonitorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        entry = SimpleNamespace(entry_id="home-a", options={"scan_interval": 60})
        self.instance = monitor.Monitor(Mock(), entry, [])
        self.instance.control = True

    async def test_empty_list_and_task_lifecycle(self):
        m = self.instance
        m.watch_connection = AsyncMock(side_effect=lambda: None)
        m.watch = AsyncMock()
        m.start()
        self.assertIsNone(m.control_task)
        m.add({"id": "one"})
        first = m.control_task
        m.add({"id": "two"})
        self.assertIs(first, m.control_task)
        await asyncio.sleep(0)
        m.watch_connection.assert_awaited_once()
        await m.remove("one")
        self.assertIs(first, m.control_task)
        await m.remove("two")
        self.assertIsNone(m.control_task)
        self.assertIsNone(m.control)
        m.add({"id": "again"})
        self.assertIsNot(first, m.control_task)
        await m.remove("again")

    async def test_primary_fallback_and_two_failed_rounds(self):
        m = self.instance
        results = ["ok", "failed", "ok", "failed", "failed", "failed", "failed"]
        probe = AsyncMock(side_effect=[(r, None, None, 0) for r in results])
        states = []

        async def sleep(_):
            states.append(m.control)
            if len(states) == 5:
                raise StopClock

        with patch.object(monitor, "probe", probe), patch.object(monitor.asyncio, "sleep", sleep):
            with self.assertRaises(StopClock):
                await m.watch_connection()
        self.assertEqual(states, [True, True, True, True, False])
        primary, fallback = monitor.CONTROLS
        self.assertEqual([c.args[1] for c in probe.await_args_list],
                         [primary, primary, fallback, primary, fallback, primary, fallback])

    async def test_single_failed_round_rephases_without_resetting_failure_history(self):
        m = self.instance
        service = {"id": "svc", "run_start": 123}
        m.services[service["id"]] = service
        probe = AsyncMock(side_effect=[(r, None, None, 0) for r in ("failed", "failed", "ok")])
        states = []

        async def sleep(_):
            states.append((m.control, m.failures, m.generation))
            if len(states) == 3:
                raise StopClock

        with patch.object(monitor, "probe", probe), patch.object(monitor.asyncio, "sleep", sleep):
            with self.assertRaises(StopClock):
                await m.watch_connection()
        self.assertEqual(states, [(True, 0, 0), (True, 1, 0), (True, 0, 1)])
        self.assertEqual(service["run_start"], 123)

    def test_catalog_feed_changes_clear_only_the_old_feed_state(self):
        m = self.instance
        m.catalog["svc"] = {"id": "svc", "feed": "existing"}
        service = {"id": "svc", "feed": "existing", "provider": {"etag": "abc"},
                   "feed_retry_at": 123, "probe_retry_at": 456}
        m.apply_catalog_metadata(service)
        self.assertEqual(service["provider"], {"etag": "abc"})
        self.assertEqual(service["feed_retry_at"], 123)
        m.catalog["svc"]["feed"] = "replacement"
        m.apply_catalog_metadata(service)
        self.assertEqual(service, {"id": "svc", "feed": "replacement", "probe_retry_at": 456})

    async def test_reload_removes_retired_catalog_feed_and_preserves_probe_cooldown(self):
        m = self.instance
        m.catalog["svc"] = {"id": "svc", "url": "https://example.test"}
        saved = {"id": "svc", "url": "https://example.test", "feed": "retired-feed",
                 "feed_retry_at": 123, "probe_retry_at": 456, "provider": {"etag": "old"}}
        m.store.async_load = AsyncMock(return_value={"services": {"svc": saved}})
        await m.load()
        await m.load()
        self.assertNotIn("feed", m.services["svc"])
        self.assertNotIn("provider", m.services["svc"])
        self.assertNotIn("feed_retry_at", m.services["svc"])
        self.assertEqual(m.services["svc"]["probe_retry_at"], 456)
        self.assertEqual(m.state(m.services["svc"])["signal"], "Checks only")

    async def test_feed_backoff_and_recovery_preserve_both_provider_deadlines(self):
        m = self.instance
        now = 0
        feeds, probes = [], []
        offset = polling.poll_offset(m.entry.entry_id, "svc", m.interval)
        first = polling.next_slot(0, m.interval, offset)
        until = first + 601
        recovery_at = first + 65
        service = {"id": "svc", "url": "url", "feed": "feed", "samples": []}

        async def feed(*args):
            feeds.append(now)
            if len(feeds) == 1:
                return None, until
            if len(feeds) <= 4:
                return None, 0
            return {"data": {"level": "none"}}, 0

        async def probe(*args):
            probes.append(now)
            if len(probes) == 1:
                return "failed", None, 503, until
            return "ok", 12, 200, 0

        async def sleep(delay):
            nonlocal now
            if now < recovery_at <= now + delay:
                m.generation += 1
            now += delay
            if len(feeds) >= 6:
                raise StopClock
            self.assertLess(now, 3000, "scheduler never completed the expected requests")

        with (patch.object(monitor, "time", lambda: now), patch.object(monitor.asyncio, "sleep", sleep),
              patch.object(monitor, "feed_update", feed), patch.object(monitor, "probe", probe)):
            with self.assertRaises(StopClock):
                await m.watch(service)
        self.assertEqual(probes[:2], feeds[:2])
        self.assertGreaterEqual(probes[1], until)
        self.assertEqual([b - a for a, b in zip(feeds[1:], feeds[2:])], [240, 240, 240, 60])
        self.assertEqual(probes[2] - probes[1], 60)
        self.assertEqual(service["feed_retry_at"], 0)
        self.assertEqual(service["provider"]["data"]["level"], "none")

    def test_installations_keep_independent_phases(self):
        offsets = {polling.poll_offset(f"home-{n}", "same-service", 300) for n in range(20)}
        self.assertGreater(len(offsets), 10)
        for now in (10, 615, 6900):
            for offset in offsets:
                first = polling.next_slot(now, 300, offset)
                self.assertEqual(first % 300, offset)
                self.assertTrue(now < first <= now + 300)
                self.assertEqual(polling.next_slot(first + 2, 300, offset), first + 300)
