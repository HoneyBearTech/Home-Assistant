"""Service status and successful probe duration."""
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from .entity import WatchEntity

async def async_setup_entry(hass, entry, async_add_entities):
    monitor = entry.runtime_data

    def entities(service_id):
        name = monitor.services[service_id]["name"]
        result = [Status(monitor, service_id, "status", f"{name} status")]
        if monitor.services[service_id].get("url"):
            result.append(Latency(monitor, service_id, "response_time", f"{name} response time"))
        return result

    @callback
    def add_service_entities(service_id):
        async_add_entities(entities(service_id))

    entry.async_on_unload(async_dispatcher_connect(hass, monitor.added, add_service_entities))
    async_add_entities([item for key in monitor.services for item in entities(key)])

class Status(WatchEntity, SensorEntity):
    @property
    def native_value(self):
        return self.info.get("status", "unknown")

    @property
    def extra_state_attributes(self):
        return {key: value for key, value in self.info.items() if key != "status"}

class Latency(WatchEntity, SensorEntity):
    _attr_native_unit_of_measurement = "ms"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        return self.info.get("latency")
