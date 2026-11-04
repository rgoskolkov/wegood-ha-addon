"""Stateful charging control for WeGoodCharge."""

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .entity import WeGoodEntity


class WeGoodChargingSwitch(WeGoodEntity, SwitchEntity):
    _attr_icon = "mdi:ev-station"

    def __init__(self, hub) -> None:
        super().__init__(hub, "charging", "Charging")

    @property
    def extra_state_attributes(self) -> dict[str, str | bool | None]:
        action, available, reason = self.hub.charging_control_state()
        return {
            "suggested_action": action,
            "control_available": available,
            "control_reason": reason,
        }

    @property
    def is_on(self) -> bool | None:
        value = self.hub.value("charging")
        return None if value is None else value == "ON"

    async def async_turn_on(self, **kwargs) -> None:
        ok, message = await self.hub.async_execute("start")
        if not ok:
            raise HomeAssistantError(message)

    async def async_turn_off(self, **kwargs) -> None:
        ok, message = await self.hub.async_execute("stop")
        if not ok:
            raise HomeAssistantError(message)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    async_add_entities([WeGoodChargingSwitch(hass.data[DOMAIN][entry.entry_id])])
