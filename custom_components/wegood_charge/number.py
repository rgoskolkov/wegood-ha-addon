"""Charging current control for WeGoodCharge."""

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfElectricCurrent
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .entity import WeGoodEntity


class WeGoodChargingCurrent(WeGoodEntity, NumberEntity):
    _attr_device_class = NumberDeviceClass.CURRENT
    _attr_native_min_value = 8
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_mode = NumberMode.BOX

    def __init__(self, hub) -> None:
        super().__init__(hub, "charging_current", "Charging current")

    @property
    def available(self) -> bool:
        return self.hub.control_available("can_current")

    @property
    def native_max_value(self) -> float:
        return float(self.hub.settings.max_current_a)

    @property
    def native_value(self) -> float | None:
        value = self.hub.value("current_limit")
        return float(value) if value is not None else None

    async def async_set_native_value(self, value: float) -> None:
        ok, message = await self.hub.async_execute("current", int(value))
        if not ok:
            raise HomeAssistantError(message)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    async_add_entities([WeGoodChargingCurrent(hass.data[DOMAIN][entry.entry_id])])
