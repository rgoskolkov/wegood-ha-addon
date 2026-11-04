"""Binary sensors for WeGoodCharge."""

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .entity import WeGoodEntity

BINARY_SENSORS = (
    ("station_seen", "Station online", None, EntityCategory.DIAGNOSTIC),
    ("cloud_connected", "Cloud MQTT", None, EntityCategory.DIAGNOSTIC),
    ("thermal_trip", "Thermal trip", BinarySensorDeviceClass.PROBLEM, None),
    ("night_session", "Night session", None, None),
    ("auto_start_inhibited", "Automatic start inhibited", BinarySensorDeviceClass.PROBLEM, EntityCategory.DIAGNOSTIC),
)


class WeGoodBinarySensor(WeGoodEntity, BinarySensorEntity):
    def __init__(self, hub, key, name, device_class, category) -> None:
        super().__init__(hub, key, name)
        self._attr_device_class = device_class
        self._attr_entity_category = category

    @property
    def is_on(self) -> bool | None:
        value = self.hub.value(self.key)
        return None if value is None else value == "ON"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    hub = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(WeGoodBinarySensor(hub, *spec) for spec in BINARY_SENSORS)
