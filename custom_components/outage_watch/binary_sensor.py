"""Connectivity and service problem indicators."""
from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from .entity import WatchEntity

async def async_setup_entry(hass, entry, async_add_entities):
    monitor = entry.runtime_data

    def problem(service_id):
        name = monitor.services[service_id]["name"]
        return Problem(monitor, service_id, "problem", f"{name} problem")

    @callback
    def add_service_entities(service_id):
        async_add_entities([problem(service_id)])

    entry.async_on_unload(async_dispatcher_connect(hass, monitor.added, add_service_entities))
    async_add_entities([
        Internet(monitor, "internet", "connectivity", "Outage Watch Internet"),
        *(problem(key) for key in monitor.services),
    ])

class Problem(WatchEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self):
        status = self.info.get("status")
        return None if status in (None, "unknown") else status in ("outage", "possible_problems")

class Internet(WatchEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    @property
    def is_on(self):
        return self.monitor.control
