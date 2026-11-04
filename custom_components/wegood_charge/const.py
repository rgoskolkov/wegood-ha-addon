"""Constants for WeGoodCharge."""

from homeassistant.const import Platform

DOMAIN = "wegood_charge"
DEVICE_ID = "wegood_ev_charger"
PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.SELECT,
]
CHARGING_MODES = ["Standard Mode", "Free Card Swipe", "Plug and Charge"]
