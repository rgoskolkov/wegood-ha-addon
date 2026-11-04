"""WeGoodCharge integration."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from homeassistant.components import frontend
from homeassistant.components import mqtt as ha_mqtt
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_when_setup

from .config import Settings
from .const import DOMAIN, PLATFORMS
from .hub import WeGoodHub

LOG = logging.getLogger(__name__)
CARD_URL = "/wegood_charge/wegood-charge-card.js"
CARD_PATH = Path(__file__).parent / "frontend" / "wegood-charge-card.js"
CARD_CACHE_VERSION = hashlib.sha256(CARD_PATH.read_bytes()).hexdigest()[:12]
RETIRED_ENTITY_UNIQUE_IDS = (
    "wegood_current_limit",
    "wegood_mode",
    "wegood_cloud_to_station",
    "wegood_station_to_cloud",
    "wegood_last_response",
)
LEGACY_DISCOVERY_TOPICS = {
    "sensor": (
        "valid_frames",
        "last_response",
        "cloud_to_station",
        "station_to_cloud",
        "relay_failures",
        "state",
        "power",
        "session_energy",
        "observed_total_energy",
        "observed_today_energy",
        "observed_month_energy",
        "observed_sessions",
        "session_minutes",
        "temperature",
        "voltage",
        "current_limit",
        "mode",
        "connector",
    ),
    "binary_sensor": (
        "station_seen",
        "cloud_connected",
        "thermal_trip",
        "night_session",
        "auto_start_inhibited",
    ),
    "switch": ("charging",),
    "number": ("charging_current",),
    "select": ("charging_mode",),
    "button": ("start", "stop"),
}


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register the bundled Lovelace card once per Home Assistant start."""
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(CARD_PATH), False)]
    )
    frontend.add_extra_js_url(hass, f"{CARD_URL}?v={CARD_CACHE_VERSION}")
    async_when_setup(hass, "mqtt", _async_clear_legacy_mqtt_discovery)
    return True


async def _async_clear_legacy_mqtt_discovery(
    hass: HomeAssistant, _component: str
) -> None:
    """Remove retained MQTT Discovery configs published by the retired add-on."""
    try:
        for domain, suffixes in LEGACY_DISCOVERY_TOPICS.items():
            for suffix in suffixes:
                await ha_mqtt.async_publish(
                    hass,
                    f"homeassistant/{domain}/wegood_{suffix}/config",
                    "",
                    qos=1,
                    retain=True,
                )
    except (HomeAssistantError, ValueError, RuntimeError, OSError) as exc:
        LOG.warning("Could not clear legacy WeGoodCharge MQTT Discovery: %s", type(exc).__name__)
        return
    LOG.info("Cleared legacy WeGoodCharge MQTT Discovery configs")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    merged = {**entry.data, **entry.options}
    settings = Settings.from_mapping(merged)
    try:
        settings.validate()
    except ValueError as exc:
        raise ConfigEntryNotReady(
            "WeGoodCharge requires connection settings; open integration Configure"
        ) from exc
    hub = WeGoodHub(hass, settings, entry.entry_id)
    await hub.async_start()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = hub
    _remove_retired_entities(hass)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


def _remove_retired_entities(hass: HomeAssistant) -> None:
    """Remove obsolete duplicate/internal entities from the entity registry."""
    registry = er.async_get(hass)
    for unique_id in RETIRED_ENTITY_UNIQUE_IDS:
        entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
        if entity_id is not None:
            registry.async_remove(entity_id)


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    hub: WeGoodHub = hass.data[DOMAIN].pop(entry.entry_id)
    await hub.async_stop()
    if not hass.data[DOMAIN]:
        hass.data.pop(DOMAIN)
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Keep existing config entries on the current schema version."""
    if entry.version < 2:
        hass.config_entries.async_update_entry(entry, version=2)
    return True
