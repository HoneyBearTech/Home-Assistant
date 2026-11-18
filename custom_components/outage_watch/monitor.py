"""Manage independent probes, freshness, history and notification delivery."""
import asyncio
from hashlib import sha256
import logging
from time import time

import aiohttp
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store

from .network import PublicResolver, feed_update, probe, public_url
from .status import DAY, summarize

LOGGER = logging.getLogger(__name__)
CONTROLS = ("https://www.cloudflare.com/cdn-cgi/trace", "https://connectivitycheck.gstatic.com/generate_204")

class Monitor:
    def __init__(self, hass, entry, catalog):
        self.hass = hass
        self.entry = entry
        self.catalog = {item["id"]: item for item in catalog}
        self.catalog_by_url = {
            public_url(item["url"]): item for item in catalog if item.get("url")
        }
        self.interval = entry.options.get("scan_interval", 300)
        self.notify_action = entry.options.get("notify_service")
        self.store = Store(hass, 1, f"outage_watch.{entry.entry_id}")
        self.services = {}
        self.tasks = {}
        self.control = None
        self.failures = 0
        self.generation = 0
        self.resolver = PublicResolver()
        self.session = None
        self.lock = asyncio.Lock()

    async def load(self):
        data = await self.store.async_load() or {}
        self.services = data.get("services", {})
        for service in self.services.values():
            self.apply_catalog_metadata(service)
            self.prune(service)
            # The baseline survives restart. Failure streaks require fresh evidence.
            service["run_start"] = time()

    def catalog_item(self, service):
        item = self.catalog.get(service["id"])
        if item or not service.get("url"):
            return item
        return self.catalog_by_url.get(public_url(service["url"]))

    def apply_catalog_metadata(self, service):
        item = self.catalog_item(service)
        if item:
            if item.get("feed") != service.get("feed"):
                service.pop("provider", None)
            for field in ("feed", "official", "crowd", "feed_scope", "icon"):
                if item.get(field):
                    service[field] = item[field]

    def prune(self, service):
        cutoff = time() - DAY
        service["samples"] = [row for row in service.get("samples", []) if row[0] > cutoff][-1440:]

    def save(self):
        self.store.async_delay_save(lambda: {"services": self.services}, 5)

    @property
    def change(self):
        return f"outage_watch_{self.entry.entry_id}_change"

    @property
    def added(self):
        return f"outage_watch_{self.entry.entry_id}_added"

    def start(self):
        self.session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(resolver=self.resolver, limit=8),
            timeout=aiohttp.ClientTimeout(total=10),
            cookie_jar=aiohttp.DummyCookieJar(),
            headers={"User-Agent": "OutageMap/0.2.6 (+https://github.com/yanke7/Home-Assistant)"},
        )
        self.control_task = asyncio.create_task(self.watch_connection())
        for service in self.services.values():
            seed = int.from_bytes(sha256(service["id"].encode()).digest()[:4])
            delay = 0 if service.get("feed") and not service.get("provider") else seed % min(30, self.interval)
            self.schedule(service, delay)

    def schedule(self, service, delay):
        self.tasks[service["id"]] = asyncio.create_task(self.watch(service, delay))

    def add(self, service):
        self.apply_catalog_metadata(service)
        service.update(samples=[], run_start=time())
        self.services[service["id"]] = service
        async_dispatcher_send(self.hass, self.added, service["id"])
        self.schedule(service, 0)

    async def remove(self, service_id):
        task = self.tasks.pop(service_id)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self.services.pop(service_id)
        registry = er.async_get(self.hass)
        for domain, kind in (("sensor", "status"), ("sensor", "response_time"), ("binary_sensor", "problem")):
            entity_id = registry.async_get_entity_id(domain, "outage_watch", self.unique(service_id, kind))
            if entity_id:
                registry.async_remove(entity_id)
        async_dispatcher_send(self.hass, self.change)

    def unique(self, service_id, kind):
        return f"{self.entry.entry_id}_{service_id}_{kind}"

    async def close(self):
        tasks = [*self.tasks.values(), self.control_task]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.session.close()
        await self.resolver.close()
        await self.store.async_save({"services": self.services})

    async def watch_connection(self):
        while True:
            checks = await asyncio.gather(*(probe(self.session, url) for url in CONTROLS))
            reachable = any(outcome == "ok" for outcome, _, _ in checks)
            self.failures = 0 if reachable else self.failures + 1
            previous = self.control
            if reachable:
                self.control = True
            elif self.failures >= 2:
                self.control = False
            if self.control != previous:
                self.generation += 1
                for service in self.services.values():
                    service["run_start"] = time()
                async_dispatcher_send(self.hass, self.change)
            await asyncio.sleep(30)

    def state(self, service):
        now = time()
        samples = service.get("samples", [])
        cached = service.get("provider") or {}
        checked = cached.get("checked", 0)
        feed = cached.get("data", {}) if checked > now - self.interval * 3 else {}
        status, reason, baseline = summarize(
            samples, feed, self.control, now, self.interval * 5, service.get("run_start", 0)
        )
        latest = samples[-1] if samples else None
        return {
            "status": status, "reason": reason, "baseline": baseline,
            "latency": latest[2] if self.control and latest and latest[0] > now - self.interval * 5 else None,
            "checked": latest[0] if latest else None, "feed_checked": checked or None,
            "feed_fresh": bool(feed),
            "signal": "Feed + checks" if service.get("feed") and service.get("url") else
                      "Feed only" if service.get("feed") else "Checks only",
            **{key: feed.get(key) for key in ("incident", "components", "maintenance")},
        }

    def snapshot(self, admin):
        tracked_catalog = {
            item["id"] for service in self.services.values()
            if (item := self.catalog_item(service))
        }
        return {
            "connected": self.control, "can_manage": admin, "notify_configured": bool(self.notify_action),
            "catalog": [{key: item[key] for key in ("name", "id", "category")} for item in self.catalog.values()
                        if item["id"] not in tracked_catalog],
            "services": [{
                **{key: service.get(key) for key in ("id", "name", "official", "crowd", "icon", "alerts", "feed_scope")},
                "category": (self.catalog_item(service) or {}).get("category", "Custom"),
                **self.state(service),
                "history": [row for row in service["samples"] if row[0] > time() - DAY],
            } for service in self.services.values()],
        }

    async def watch(self, service, delay):
        await asyncio.sleep(delay)
        feed_due = check_due = 0
        backoff = 1
        generation = self.generation
        while True:
            now = time()
            if generation != self.generation:
                check_due = feed_due = 0
                backoff = 1
                generation = self.generation
            changed = False
            if self.control is True and self.failures == 0:
                if service.get("feed") and now >= feed_due:
                    current = await feed_update(self.session, service["feed"], service.get("provider") or {})
                    if current and generation == self.generation and self.failures == 0:
                        service["provider"] = {**current, "checked": time()}
                        changed = True
                    feed_due = time() + self.interval
                if service.get("url") and now >= check_due:
                    outcome, latency, code = await probe(self.session, service["url"])
                    if generation == self.generation and self.failures == 0:
                        service["samples"].append([time(), outcome, latency])
                        self.prune(service)
                        changed = True
                        if code == 429:
                            backoff = 4
                        elif outcome == "failed" and self.state(service)["reason"] == "unreachable":
                            backoff = min(4, backoff * 2)
                        else:
                            backoff = 1
                    check_due = time() + self.interval * backoff
                await self.notify(service, self.state(service)["status"])
                if changed:
                    self.save()
            async_dispatcher_send(self.hass, self.change)
            deadlines = [due for due in (feed_due, check_due) if due > time()]
            await asyncio.sleep(min(15, max(1, min(deadlines, default=time() + 5) - time())))

    async def notify(self, service, status):
        if not (service.get("alerts") and self.notify_action and self.control and self.failures == 0):
            return
        prior = service.get("alert_open", False)
        if not ((status == "outage" and not prior) or (status == "operational" and prior)):
            return
        action = self.notify_action.split(".", 1)[1]
        if not self.hass.services.has_service("notify", action):
            return
        label = "recovered" if prior else (
            "is unreachable from Home Assistant" if self.state(service)["reason"] == "unreachable"
            else "has a provider-reported outage"
        )
        try:
            await self.hass.services.async_call("notify", action, {
                "title": "Outage Map", "message": f"{service['name']} {label}."
            }, blocking=True)
        except Exception:
            LOGGER.exception("Could not deliver Outage Map notification")
        else:
            service["alert_open"] = not prior
            self.save()
