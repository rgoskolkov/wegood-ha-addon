"""Base entity for WeGoodCharge."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DEVICE_ID, DOMAIN
from .hub import WeGoodHub


class WeGoodEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hub: WeGoodHub, key: str, name: str) -> None:
        self.hub = hub
        self.key = key
        self._attr_name = name
        self._attr_unique_id = f"wegood_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, DEVICE_ID)},
            name="WeGood EV Charger",
            manufacturer="WeGood (community integration)",
            model="ICS_10 / WeGoodCharge",
            serial_number=self.hub.station_id,
        )

    @property
    def available(self) -> bool:
        return self.hub.gateway_online

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.hub.add_listener(self.async_write_ha_state))
