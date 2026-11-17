"""Common polling-free entity wiring."""
from homeassistant.helpers.dispatcher import async_dispatcher_connect

class WatchEntity:
    _attr_should_poll = False

    def __init__(self, monitor, service_id, kind, label):
        self.monitor = monitor
        self.service_id = service_id
        self._attr_unique_id = monitor.unique(service_id, kind)
        self._attr_name = label

    @property
    def service(self):
        return self.monitor.services.get(self.service_id)

    @property
    def info(self):
        return self.monitor.state(self.service) if self.service else {}

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(async_dispatcher_connect(
            self.hass, self.monitor.change, self.async_write_ha_state
        ))
