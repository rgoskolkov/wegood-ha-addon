import importlib
import sys
import time
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CC = ROOT / "custom_components"
WG = CC / "wegood_charge"

# Import pure runtime modules without executing Home Assistant dependent __init__.py.
custom_components = types.ModuleType("custom_components")
custom_components.__path__ = [str(CC)]
sys.modules.setdefault("custom_components", custom_components)
package = types.ModuleType("custom_components.wegood_charge")
package.__path__ = [str(WG)]
sys.modules.setdefault("custom_components.wegood_charge", package)

config = importlib.import_module("custom_components.wegood_charge.config")
protocol = importlib.import_module("custom_components.wegood_charge.protocol")
state_mod = importlib.import_module("custom_components.wegood_charge.state")
counters_mod = importlib.import_module("custom_components.wegood_charge.counters")

Settings = config.Settings
Frame = protocol.Frame
GatewayState = state_mod.GatewayState
EnergyCounters = counters_mod.EnergyCounters


def settings(**overrides):
    data = {
        "integration_mode": "cloud",
        "station_id": "TEST-STATION",
        "protocol_variant": "ics10_v14",
        "cloud_mqtt_host": "example.invalid",
        "cloud_mqtt_client_id": "wegood_test_client",
        "watchdog_seconds": 35,
    }
    data.update(overrides)
    return Settings(**data)


def telemetry_frame(status=2, temp=25, power=2300, energy=123, minutes=7, voltage=230):
    data = bytearray(13)
    data[0] = status
    data[1:3] = int(power).to_bytes(2, "little")
    data[3:7] = int(energy).to_bytes(4, "little")
    data[7:10] = int(minutes).to_bytes(3, "little")
    data[10] = temp
    data[11] = voltage
    return Frame(0xAA, 103, bytes(data))


def config_frame(mode=0, amps=16):
    data = bytearray(33)
    data[6] = mode
    data[18:20] = int(amps * 100).to_bytes(2, "little")
    return Frame(0xAA, 96, bytes(data))


class SettingsTests(unittest.TestCase):
    def test_watchdog_accepts_one_day_and_unverified_is_read_only(self):
        s = settings(watchdog_seconds=86400, protocol_variant="unverified")
        s.validate()
        self.assertTrue(s.read_poll_ready)
        self.assertFalse(s.controls_configured)
        with self.assertRaises(ValueError):
            settings(watchdog_seconds=86401).validate()

    def test_local_requires_only_existing_ha_mqtt_topics(self):
        s = settings(
            integration_mode="local",
            cloud_mqtt_host="",
            station_rx_topic="station/status",
            station_tx_topic="station/command",
        )
        s.validate()
        self.assertTrue(s.controls_configured)
        self.assertFalse(s.cloud_client_enabled)


class ProtocolTests(unittest.TestCase):
    def test_all_three_modes_share_observed_write_layout(self):
        for mode in (0, 1, 2):
            payload = protocol.current_payload(15, mode)
            self.assertEqual(payload[6], mode)
            self.assertEqual(int.from_bytes(bytes(payload[15:17]), "little"), 1500)

    def test_read_requests_remain_available(self):
        packet = protocol.build_request(103, [0], "TEST-STATION", "gateway_poll")
        frame = protocol.decode_message(packet)
        self.assertEqual(frame.command, 103)
        self.assertEqual(frame.header, 0x55)


class StateTests(unittest.TestCase):
    def test_start_stop_freshness_uses_telemetry_and_caps_at_300_seconds(self):
        s = settings(watchdog_seconds=86400)
        st = GatewayState(s)
        st.cloud_mqtt_connected = True
        st.on_frame(telemetry_frame(status=1))
        st.on_frame(config_frame())
        st.candidate_connector = "connected"
        st.last_connector_mono = time.monotonic()
        self.assertTrue(st.snapshot()["can_start"])

        st.last_telemetry_mono = time.monotonic() - 301
        self.assertFalse(st.snapshot()["can_start"])
        self.assertTrue(st.snapshot()["station_online"])

    def test_thermal_trip_stops_rearm_until_manual_start(self):
        changed = []
        st = GatewayState(settings(), persist=lambda: changed.append(True))
        st.cloud_mqtt_connected = True
        st.on_frame(telemetry_frame(status=2, temp=71))
        snap = st.snapshot()
        self.assertTrue(snap["thermal_trip"])
        self.assertTrue(snap["thermal_shutdown_pending"])
        self.assertTrue(snap["auto_start_inhibited"])

        st.on_frame(telemetry_frame(status=1, temp=60))
        snap = st.snapshot()
        self.assertFalse(snap["thermal_trip"])
        self.assertFalse(snap["thermal_shutdown_pending"])
        self.assertTrue(snap["auto_start_inhibited"])
        self.assertTrue(st.manual_start_rearms_schedule())
        self.assertFalse(st.snapshot()["auto_start_inhibited"])
        self.assertTrue(changed)

    def test_persistent_safety_and_counters_round_trip(self):
        st = GatewayState(settings())
        st.on_frame(telemetry_frame(status=2, energy=100, minutes=1))
        st.on_frame(telemetry_frame(status=2, energy=125, minutes=2))
        saved = st.export_persistent()
        restored = GatewayState(settings(), saved)
        self.assertAlmostEqual(restored.counters.snapshot()["total_kwh"], 0.25, places=3)

    def test_corrupt_persisted_safety_fails_closed(self):
        restored = GatewayState(
            settings(),
            {"state_version": 1, "safety": {"thermal_trip": "broken"}},
        )
        snap = restored.snapshot()
        self.assertTrue(snap["thermal_trip"])
        self.assertTrue(snap["thermal_shutdown_pending"])
        self.assertTrue(snap["auto_start_inhibited"])


if __name__ == "__main__":
    unittest.main()
