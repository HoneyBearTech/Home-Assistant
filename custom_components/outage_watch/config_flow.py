import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

class ConfigFlow(config_entries.ConfigFlow, domain="outage_watch"):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        self._async_abort_entries_match()
        if user_input is not None:
            return self.async_create_entry(title="Outage Map", data={})
        return self.async_show_form(step_id="user", data_schema=vol.Schema({}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OptionsFlow()

class OptionsFlow(config_entries.OptionsFlowWithReload):
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        options = self.config_entry.options
        return self.async_show_form(step_id="init", data_schema=vol.Schema({
            vol.Required("scan_interval", default=options.get("scan_interval", 300)):
                vol.All(vol.Coerce(int), vol.Range(min=60, max=3600)),
            vol.Optional("notify_service", default=options.get("notify_service", "")):
                vol.Match(r"^(?:notify\.[a-z0-9_]+)?$"),
        }))
