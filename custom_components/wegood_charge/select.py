"""Charging mode control for WeGoodCharge."""

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CHARGING_MODES, DOMAIN
from .entity import WeGoodEntity


class WeGoodChargingMode(WeGoodEntity, SelectEntity):
    _attr_options = CHARGING_MODES
    _attr_icon = "mdi:ev-plug-type2"

    def __init__(self, hub) -> None:
        super().__init__(hub, "charging_mode", "Charging mode")

    @property
    def available(self) -> bool:
        return self.hub.control_available("can_mode")

    @property
    def current_option(self) -> str | None:
        value = self.hub.value("mode")
        return value if value in self.options else None

    async def async_select_option(self, option: str) -> None:
        ok, message = await self.hub.async_execute("mode", mode=option)
        if not ok:
            raise HomeAssistantError(message)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    async_add_entities([WeGoodChargingMode(hass.data[DOMAIN][entry.entry_id])])
