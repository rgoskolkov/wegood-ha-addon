"""Sensors for WeGoodCharge."""

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EntityCategory,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .entity import WeGoodEntity

SENSORS = (
    ("state", "State", None, None, None, None),
    ("power", "Power", SensorDeviceClass.POWER, UnitOfPower.WATT, SensorStateClass.MEASUREMENT, None),
    ("session_energy", "Session energy", SensorDeviceClass.ENERGY, UnitOfEnergy.KILO_WATT_HOUR, None, None),
    ("observed_total_energy", "Observed total energy", SensorDeviceClass.ENERGY, UnitOfEnergy.KILO_WATT_HOUR, SensorStateClass.TOTAL_INCREASING, None),
    ("observed_today_energy", "Observed energy today", SensorDeviceClass.ENERGY, UnitOfEnergy.KILO_WATT_HOUR, SensorStateClass.TOTAL_INCREASING, None),
    ("observed_month_energy", "Observed energy this month", SensorDeviceClass.ENERGY, UnitOfEnergy.KILO_WATT_HOUR, SensorStateClass.TOTAL_INCREASING, None),
    ("session_minutes", "Session time", SensorDeviceClass.DURATION, UnitOfTime.MINUTES, SensorStateClass.MEASUREMENT, None),
    ("temperature", "Temperature", SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS, SensorStateClass.MEASUREMENT, None),
    ("voltage", "Voltage", SensorDeviceClass.VOLTAGE, UnitOfElectricPotential.VOLT, SensorStateClass.MEASUREMENT, None),
    ("connector", "Connector", None, None, None, None),
    ("valid_frames", "Valid frames", None, None, SensorStateClass.TOTAL_INCREASING, EntityCategory.DIAGNOSTIC),
    ("relay_failures", "Relay failures", None, None, SensorStateClass.TOTAL_INCREASING, EntityCategory.DIAGNOSTIC),
    ("observed_sessions", "Observed sessions", None, None, None, EntityCategory.DIAGNOSTIC),
)


class WeGoodSensor(WeGoodEntity, SensorEntity):
    def __init__(self, hub, key, name, device_class, unit, state_class, category) -> None:
        super().__init__(hub, key, name)
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit
        self._attr_state_class = state_class
        self._attr_entity_category = category

    @property
    def native_value(self):
        value = self.hub.value(self.key)
        if value is None:
            return None
        if self._attr_native_unit_of_measurement is not None or self._attr_state_class is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                return value
        return value


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    hub = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(WeGoodSensor(hub, *spec) for spec in SENSORS)
