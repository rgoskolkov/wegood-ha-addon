"""Config and options flows for WeGoodCharge."""

from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .config import Settings
from .const import DOMAIN

PASSWORD_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def _defaults(data: dict | None = None) -> dict:
    base = Settings()
    result = {name: getattr(base, name) for name in base.__dataclass_fields__}
    if data:
        result.update(data)
    return result


def _common_schema(data: dict) -> vol.Schema:
    return vol.Schema({
        vol.Required("station_id", default=data.get("station_id", "")): str,
        vol.Required("integration_mode", default=data.get("integration_mode", "cloud")):
            vol.In({"cloud": "Cloud (default)", "local": "Local MQTT"}),
        vol.Required("protocol_variant", default=data.get("protocol_variant", "unverified")):
            vol.In({"unverified": "Unverified / read only", "ics10_v14": "ICS_10 V1.4"}),
        vol.Required("max_current_a", default=data.get("max_current_a", 16)):
            vol.All(vol.Coerce(int), vol.Range(min=8, max=32)),
        vol.Required("watchdog_seconds", default=data.get("watchdog_seconds", 35)):
            vol.All(vol.Coerce(int), vol.Range(min=10, max=86400)),
        vol.Required("telemetry_poll_seconds", default=data.get("telemetry_poll_seconds", 20)):
            vol.All(vol.Coerce(int), vol.Range(min=5, max=3600)),
        vol.Required("config_poll_seconds", default=data.get("config_poll_seconds", 120)):
            vol.All(vol.Coerce(int), vol.Range(min=5, max=3600)),
        vol.Required("night_schedule_enabled", default=data.get("night_schedule_enabled", False)): bool,
        vol.Required("night_start", default=data.get("night_start", "23:15")): str,
        vol.Required("night_end", default=data.get("night_end", "05:50")): str,
        vol.Required("night_timezone", default=data.get("night_timezone", "Asia/Novosibirsk")): str,
    })


def _cloud_schema(data: dict, *, local: bool = False) -> vol.Schema:
    schema = {}
    if local:
        schema.update({
            vol.Required("station_rx_topic", default=data.get("station_rx_topic", "")): str,
            vol.Required("station_tx_topic", default=data.get("station_tx_topic", "")): str,
            vol.Required("cloud_bridge_enabled", default=data.get("cloud_bridge_enabled", False)): bool,
        })
        host_key = vol.Optional("cloud_mqtt_host", default=data.get("cloud_mqtt_host", ""))
    else:
        host_key = vol.Required("cloud_mqtt_host", default=data.get("cloud_mqtt_host", ""))
    schema.update({
        host_key: str,
        vol.Required("cloud_mqtt_port", default=data.get("cloud_mqtt_port", 1883)):
            vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
        vol.Required("cloud_mqtt_tls", default=data.get("cloud_mqtt_tls", False)): bool,
        vol.Optional("cloud_mqtt_username", default=data.get("cloud_mqtt_username", "")): str,
        vol.Optional("cloud_mqtt_password", default=""): PASSWORD_SELECTOR,
        vol.Required("cloud_mqtt_client_id", default=data.get("cloud_mqtt_client_id", "wegood_ha_gateway_cloud")): str,
        vol.Optional("cloud_command_topic", default=data.get("cloud_command_topic", "")): str,
        vol.Optional("cloud_status_topic", default=data.get("cloud_status_topic", "")): str,
    })
    return vol.Schema(schema)


def _merge_password(values: dict, previous: dict) -> dict:
    if "cloud_mqtt_password" in values and values["cloud_mqtt_password"] == "":
        values["cloud_mqtt_password"] = previous.get("cloud_mqtt_password", "")
    return values


def _validate(values: dict) -> dict[str, str]:
    try:
        Settings.from_mapping(values).validate()
    except ValueError:
        return {"base": "invalid_config"}
    return {}


class WeGoodChargeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 2

    def __init__(self) -> None:
        self._pending = _defaults()

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            self._pending.update(user_input)
            station_id = self._pending["station_id"].strip()
            if not station_id:
                errors["station_id"] = "required"
            else:
                self._pending["station_id"] = station_id
                await self.async_set_unique_id(station_id)
                self._abort_if_unique_id_configured()
                if self._pending["integration_mode"] == "cloud":
                    return await self.async_step_cloud()
                return await self.async_step_local()
        return self.async_show_form(step_id="user", data_schema=_common_schema(self._pending), errors=errors)

    async def async_step_cloud(self, user_input=None):
        if user_input is None:
            return self.async_show_form(step_id="cloud", data_schema=_cloud_schema(self._pending))
        values = _merge_password(dict(user_input), self._pending)
        self._pending.update(values)
        errors = _validate(self._pending)
        if errors:
            return self.async_show_form(step_id="cloud", data_schema=_cloud_schema(self._pending), errors=errors)
        return self.async_create_entry(title=f"WeGoodCharge {self._pending['station_id']}", data=self._pending)

    async def async_step_local(self, user_input=None):
        if user_input is None:
            return self.async_show_form(step_id="local", data_schema=_cloud_schema(self._pending, local=True))
        values = _merge_password(dict(user_input), self._pending)
        self._pending.update(values)
        errors = _validate(self._pending)
        if errors:
            return self.async_show_form(step_id="local", data_schema=_cloud_schema(self._pending, local=True), errors=errors)
        return self.async_create_entry(title=f"WeGoodCharge {self._pending['station_id']}", data=self._pending)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return WeGoodChargeOptionsFlow(config_entry)


class WeGoodChargeOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry) -> None:
        self._entry = config_entry
        self._previous = _defaults({**config_entry.data, **config_entry.options})
        self._pending = dict(self._previous)

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            self._pending.update(user_input)
            if self._pending["integration_mode"] == "cloud":
                return await self.async_step_cloud()
            return await self.async_step_local()
        return self.async_show_form(step_id="init", data_schema=_common_schema(self._pending))

    async def async_step_cloud(self, user_input=None):
        if user_input is None:
            return self.async_show_form(step_id="cloud", data_schema=_cloud_schema(self._pending))
        self._pending.update(_merge_password(dict(user_input), self._previous))
        errors = _validate(self._pending)
        if errors:
            return self.async_show_form(step_id="cloud", data_schema=_cloud_schema(self._pending), errors=errors)
        return self.async_create_entry(title="", data=self._pending)

    async def async_step_local(self, user_input=None):
        if user_input is None:
            return self.async_show_form(step_id="local", data_schema=_cloud_schema(self._pending, local=True))
        self._pending.update(_merge_password(dict(user_input), self._previous))
        errors = _validate(self._pending)
        if errors:
            return self.async_show_form(step_id="local", data_schema=_cloud_schema(self._pending, local=True), errors=errors)
        return self.async_create_entry(title="", data=self._pending)
