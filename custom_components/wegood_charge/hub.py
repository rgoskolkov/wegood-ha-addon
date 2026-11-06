"""Native WeGoodCharge runtime and MQTT transports."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from homeassistant.components import mqtt as ha_mqtt
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers.storage import Store

from .config import Settings
from .const import DOMAIN
from .night import night_window
from .protocol import (
    PacketError,
    build_request,
    current_payload,
    decode_message,
    start_payload,
    stop_payload,
)
from .state import STOPPED_STATES, GatewayState

LOG = logging.getLogger(__name__)
CHARGING_MODES = {
    "Standard Mode": 0,
    "Free Card Swipe": 1,
    "Plug and Charge": 2,
}
MODE_LABELS = {value: key for key, value in CHARGING_MODES.items()}
PERMITTED_COMMANDS = {"start", "stop", "current", "mode"}
PENDING_TELEMETRY_POLL_SECONDS = 2
ACTIVE_TELEMETRY_POLL_SECONDS = 5


class WeGoodHub:
    """Own the charger protocol, transports, safety state, and HA listeners."""

    def __init__(self, hass: HomeAssistant, settings: Settings, entry_id: str) -> None:
        self.hass = hass
        self.settings = settings
        self.entry_id = entry_id
        self.state: GatewayState | None = None
        self.running = False
        self._listeners: set[Callable[[], None]] = set()
        self._unsubscribe_local: Callable[[], None] | None = None
        self._cloud_client = None
        self._watchdog_task: asyncio.Task | None = None
        self._store = Store(hass, 1, f"{DOMAIN}.{entry_id}")
        self._store_task: asyncio.Task | None = None
        self._command_lock = asyncio.Lock()
        self.next_telemetry_poll = 0.0
        self.next_config_poll = 0.0
        self.next_thermal_stop = 0.0
        self.next_night_stop = 0.0
        self.night_window_key: str | None = None
        self.night_attempted = False
        self.night_manual_override = False

    @property
    def station_id(self) -> str:
        return self.settings.station_id

    async def async_start(self) -> None:
        saved = await self._store.async_load()
        if not isinstance(saved, dict):
            saved = {}
        self.state = GatewayState(self.settings, saved, self._queue_store_save)

        if self.settings.integration_mode == "local":
            if "mqtt" not in self.hass.config.components:
                raise ConfigEntryNotReady("Home Assistant MQTT integration is required for local mode")
            self._unsubscribe_local = await ha_mqtt.async_subscribe(
                self.hass, self.settings.station_rx_topic, self._local_message_received, 1
            )
            self.state.local_mqtt_connected = True

        if self.settings.cloud_client_enabled:
            self._start_cloud_client()

        self.running = True
        self._watchdog_task = self.hass.async_create_task(self._watchdog_loop())
        self._notify()
        LOG.info("WeGoodCharge native runtime started in %s mode", self.settings.integration_mode)

    async def async_stop(self) -> None:
        self.running = False
        if self._watchdog_task is not None:
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except asyncio.CancelledError:
                pass
            self._watchdog_task = None
        if self._unsubscribe_local is not None:
            self._unsubscribe_local()
            self._unsubscribe_local = None
        if self.state is not None:
            self.state.local_mqtt_connected = False
            await self._store.async_save(self.state.export_persistent())
        if self._store_task is not None and not self._store_task.done():
            self._store_task.cancel()
            self._store_task = None
        client = self._cloud_client
        self._cloud_client = None
        if client is not None:
            await self.hass.async_add_executor_job(self._stop_cloud_client, client)
        self._notify()

    def _start_cloud_client(self) -> None:
        import paho.mqtt.client as paho

        client = paho.Client(
            callback_api_version=paho.CallbackAPIVersion.VERSION2,
            client_id=self.settings.cloud_mqtt_client_id,
        )
        if self.settings.cloud_mqtt_username:
            client.username_pw_set(
                self.settings.cloud_mqtt_username, self.settings.cloud_mqtt_password
            )
        if self.settings.cloud_mqtt_tls:
            client.tls_set()
        client.on_connect = self._on_cloud_connect
        client.on_disconnect = self._on_cloud_disconnect
        client.on_message = self._on_cloud_message
        client.reconnect_delay_set(min_delay=1, max_delay=60)
        client.connect_async(
            self.settings.cloud_mqtt_host, self.settings.cloud_mqtt_port, keepalive=60
        )
        client.loop_start()
        self._cloud_client = client

    @staticmethod
    def _stop_cloud_client(client) -> None:
        try:
            client.disconnect()
        finally:
            client.loop_stop()

    def _on_cloud_connect(self, client, _userdata, _flags, reason_code, _properties) -> None:
        connected = reason_code == 0
        if connected:
            if self.settings.integration_mode == "cloud":
                client.subscribe(self.settings.effective_cloud_status_topic, qos=1)
                client.subscribe(self.settings.effective_cloud_command_topic, qos=1)
            else:
                client.subscribe(self.settings.effective_cloud_command_topic, qos=1)
        self.hass.loop.call_soon_threadsafe(self._set_cloud_connected, connected, str(reason_code))

    @callback
    def _set_cloud_connected(self, connected: bool, reason: str) -> None:
        if self.state is None:
            return
        self.state.cloud_mqtt_connected = connected
        if connected:
            self.next_telemetry_poll = 0.0
            self.next_config_poll = 0.0
            LOG.info("WeGood cloud MQTT connected")
        else:
            LOG.warning("WeGood cloud MQTT connection rejected/disconnected: %s", reason)
            if self.settings.integration_mode == "cloud":
                self.state.station_disconnected()
                self.state.set_night_session(False)
                self.night_manual_override = True
        self._notify()

    def _on_cloud_disconnect(self, _client, _userdata, _flags, reason_code, _properties) -> None:
        self.hass.loop.call_soon_threadsafe(self._set_cloud_connected, False, str(reason_code))

    def _on_cloud_message(self, _client, _userdata, message) -> None:
        payload = bytes(message.payload)
        topic = str(message.topic)
        retain = bool(message.retain)
        self.hass.loop.call_soon_threadsafe(
            lambda: self.hass.async_create_task(
                self._async_handle_cloud_message(topic, payload, retain)
            )
        )

    @callback
    def _local_message_received(self, message) -> None:
        payload = message.payload
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        else:
            payload = bytes(payload)
        retain = bool(getattr(message, "retain", False))
        self.hass.async_create_task(self._async_handle_local_message(payload, retain))

    async def _async_handle_local_message(self, payload: bytes, retain: bool) -> None:
        accepted = await self._async_accept_station_payload(payload, retain)
        if accepted and self.settings.cloud_relay_enabled and self._cloud_connected:
            sent = self._publish_cloud(self.settings.effective_cloud_status_topic, payload)
            self._require_state().note_relay(sent)
            self._notify()

    async def _async_handle_cloud_message(self, topic: str, payload: bytes, retain: bool) -> None:
        if not self.running or self.state is None:
            return
        if self.settings.integration_mode == "cloud":
            if retain or not self._cloud_connected:
                return
            if topic == self.settings.effective_cloud_status_topic:
                await self._async_accept_station_payload(payload, False)
            elif topic == self.settings.effective_cloud_command_topic:
                self._observe_cloud_command(payload)
            return

        if topic != self.settings.effective_cloud_command_topic or retain or not self._cloud_connected:
            return
        command = self._decode_cloud_command(payload)
        if command is None:
            self.state.note_relay(False)
            self._notify()
            return
        snap = self.state.snapshot()
        if command in (97, 104, 105) and not snap["station_online"]:
            self.state.note_relay(False)
            self._notify()
            return
        if command in (97, 104) and (not snap["telemetry_fresh"] or snap["thermal_trip"]
                                     or snap["thermal_shutdown_pending"]):
            LOG.warning("Blocked cloud Start/config write without fresh safe telemetry")
            self.state.note_relay(False)
            self._notify()
            return
        try:
            await ha_mqtt.async_publish(
                self.hass, self.settings.station_tx_topic, payload, qos=0, retain=False
            )
            sent = True
        except (HomeAssistantError, ValueError, RuntimeError, OSError) as exc:
            LOG.warning("Local MQTT relay publish failed: %s", type(exc).__name__)
            sent = False
        if sent and command in (104, 105):
            self._manual_intervention()
            if command == 104:
                self.state.manual_start_rearms_schedule()
        self.state.note_relay(sent)
        self._notify()

    async def _async_accept_station_payload(self, payload: bytes, retain: bool) -> bool:
        if retain:
            return False
        state = self._require_state()
        if len(payload) > 8192:
            state.note_invalid()
            self._notify()
            return False
        try:
            body = json.loads(payload)
            if (not isinstance(body, dict) or body.get("cmd") != 75960
                    or body.get("imei") != self.settings.station_id or "data" not in body):
                return False
            frame = decode_message(payload)
        except (ValueError, UnicodeDecodeError, TypeError, PacketError):
            state.note_invalid()
            self._notify()
            return False
        if frame is None or not frame.is_station_response:
            return False
        state.on_frame(frame)
        if frame.command == 97 and frame.data and frame.data[0] == 1:
            self.next_config_poll = 0.0
        self._notify()
        await self._async_maybe_stop_for_heat()
        await self._async_tick_night()
        return True

    def _observe_cloud_command(self, payload: bytes) -> None:
        command = self._decode_cloud_command(payload)
        if command not in (104, 105):
            return
        try:
            body = json.loads(payload)
        except (ValueError, UnicodeDecodeError):
            return
        if body.get("noncestr") in ("ha_start", "ha_stop", "night_stop", "thermal_stop"):
            return
        self._manual_intervention()
        self._notify()

    def _decode_cloud_command(self, payload: bytes) -> int | None:
        if len(payload) > 8192:
            return None
        try:
            body = json.loads(payload)
            if (not isinstance(body, dict) or body.get("cmd") != 75960
                    or body.get("imei") != self.settings.station_id
                    or "com_chuankoudt" not in body or "data" in body):
                return None
            frame = decode_message(payload)
            if frame is None or frame.header != 0x55 or frame.command not in (96, 97, 103, 104, 105):
                return None
            if frame.command == 97:
                if len(frame.data) != 19 or frame.data[6] not in (0, 1, 2):
                    return None
                raw = int.from_bytes(frame.data[15:17], "little")
                if raw % 100 or not 8 <= raw // 100 <= self.settings.max_current_a:
                    return None
                if frame.data != bytes(current_payload(raw // 100, frame.data[6])):
                    return None
            return frame.command
        except (ValueError, UnicodeDecodeError, TypeError, PacketError):
            return None

    @property
    def _cloud_connected(self) -> bool:
        return bool(self.state and self.state.cloud_mqtt_connected)

    def _transport_connected(self) -> bool:
        state = self._require_state()
        return (state.cloud_mqtt_connected if self.settings.integration_mode == "cloud"
                else state.local_mqtt_connected)

    def _publish_cloud(self, topic: str, payload: bytes) -> bool:
        client = self._cloud_client
        if client is None or not topic or not self._cloud_connected:
            return False
        try:
            return client.publish(topic, payload, qos=1, retain=False).rc == 0
        except (ValueError, RuntimeError, OSError):
            return False

    async def _async_send_packet(self, code: int, data: list[int], nonce: str) -> bool:
        if not self._transport_connected():
            return False
        try:
            packet = build_request(code, data, self.settings.station_id, nonce)
            if self.settings.integration_mode == "cloud":
                return self._publish_cloud(self.settings.effective_cloud_command_topic, packet)
            await ha_mqtt.async_publish(
                self.hass, self.settings.station_tx_topic, packet, qos=1, retain=False
            )
            return True
        except (ValueError, RuntimeError, OSError) as exc:
            LOG.warning("Could not publish station packet: %s", type(exc).__name__)
            return False

    async def async_execute(self, action: str, amps: int | None = None, *,
                            mode: str | None = None, source: str = "manual") -> tuple[bool, str]:
        if action not in PERMITTED_COMMANDS:
            return False, "Неизвестная команда"
        if not self.settings.controls_configured:
            return False, "Запись доступна только для подтверждённого ICS_10 V1.4"
        if source not in ("manual", "night"):
            return False, "Неизвестный источник команды"
        state = self._require_state()
        async with self._command_lock:
            snap = state.snapshot()
            allowed = {
                "start": snap["can_start"],
                "stop": snap["can_stop"],
                "current": snap["can_set_current"],
                "mode": snap["can_set_mode"],
            }[action]
            if not allowed:
                return False, "Станция не готова к этой команде"
            if action == "current":
                if type(amps) is not int or not 8 <= amps <= self.settings.max_current_a:
                    return False, "Ток за пределами разрешённого диапазона"
                config = snap["station_config_preview"]
                if not config or config["mode_code"] not in (0, 1, 2):
                    return False, "Режим зарядки не подтверждён"
                if abs(config["current_limit_a"] - amps) < 0.01:
                    return True, "Ток уже установлен"
                code, data = 97, current_payload(amps, config["mode_code"])
            elif action == "mode":
                if mode not in CHARGING_MODES:
                    return False, "Неизвестный режим зарядки"
                config = snap["station_config_preview"]
                if not config or config["mode_code"] not in (0, 1, 2):
                    return False, "Конфигурация станции не подтверждена"
                current = config["current_limit_a"]
                if (type(current) not in (int, float) or not float(current).is_integer()
                        or not 8 <= current <= self.settings.max_current_a):
                    return False, "Текущий лимит станции не подтверждён"
                desired = CHARGING_MODES[mode]
                if config["mode_code"] == desired:
                    return True, "Режим уже установлен"
                code, data = 97, current_payload(int(current), desired)
            elif action == "start":
                code, data = 104, start_payload()
            else:
                code, data = 105, stop_payload()

            state.begin_command(
                action,
                amps if action == "current" else None,
                CHARGING_MODES[mode] if action == "mode" and mode is not None else None,
            )
            if not await self._async_send_packet(code, data, f"ha_{action}"):
                state.clear_pending()
                self._notify()
                return False, "Не удалось отправить MQTT-команду"
            if action in ("start", "stop"):
                # Confirm charging state promptly instead of waiting for the
                # regular telemetry interval.
                self.next_telemetry_poll = 0.0
            if source == "manual" and action in ("start", "stop"):
                self._manual_intervention()
                if action == "start":
                    state.manual_start_rearms_schedule()
            LOG.info("Station command %s published, confirmation pending", action)
            self._notify()
            return True, "Команда отправлена; ожидаем подтверждение станции"

    def _manual_intervention(self) -> None:
        self.night_manual_override = True
        self.night_attempted = True
        self._require_state().set_night_session(False)

    async def _async_maybe_stop_for_heat(self) -> None:
        state = self._require_state()
        snap = state.snapshot()
        if snap["thermal_trip"] or snap["thermal_shutdown_pending"]:
            self.night_manual_override = True
            self.night_attempted = True
            state.set_night_session(False)
        status = (snap["telemetry_preview"] or {}).get("status")
        allowed = self.settings.active_read_ready and self._transport_connected()
        if (not allowed or not (snap["thermal_trip"] or snap["thermal_shutdown_pending"])
                or (status != "charging" and not snap["thermal_shutdown_pending"])):
            return
        now = time.monotonic()
        if now < self.next_thermal_stop:
            return
        self.next_thermal_stop = now + 5
        LOG.warning("Thermal shutdown: requesting Stop until charging ceases")
        if (await self._async_send_packet(105, stop_payload(), "thermal_stop")
                and snap["pending_action"] != "stop"):
            state.begin_command("stop")
        self._notify()

    async def _async_tick_night(self) -> None:
        if not self.settings.night_schedule_enabled:
            return
        state = self._require_state()
        now = datetime.now(ZoneInfo(self.settings.night_timezone))
        active, key = night_window(now, self.settings.night_start, self.settings.night_end)
        if active and key != self.night_window_key:
            self.night_window_key = key
            self.night_attempted = False
            self.night_manual_override = False
        snap = state.snapshot()
        status = (snap["telemetry_preview"] or {}).get("status")
        if snap["station_online"] and snap["connector_candidate"] == "disconnected":
            state.set_night_session(False)
            self.night_attempted = False
            self.night_manual_override = False
        elif status in STOPPED_STATES and snap["night_session"] and snap["pending_action"] != "start":
            state.set_night_session(False)
        if snap["thermal_trip"] or snap["thermal_shutdown_pending"] or snap["auto_start_inhibited"]:
            self.night_manual_override = True
            self.night_attempted = True
            state.set_night_session(False)
            self._notify()
            return
        snap = state.snapshot()
        if active:
            if status == "charging" and not snap["night_session"]:
                self.night_manual_override = True
            if not self.night_attempted and not self.night_manual_override and snap["can_start"]:
                ok, _ = await self.async_execute("start", source="night")
                if ok:
                    self.night_attempted = True
                    state.set_night_session(True)
                    LOG.info("Night tariff: Start published for window %s", key)
        elif snap["night_session"] and status == "charging" and snap["station_online"]:
            mono = time.monotonic()
            if mono >= self.next_night_stop:
                self.next_night_stop = mono + 10
                if await self._async_send_packet(105, stop_payload(), "night_stop"):
                    if snap["pending_action"] != "stop":
                        state.begin_command("stop")
                    LOG.info("Night tariff ended: Stop requested")
        self._notify()

    async def _watchdog_loop(self) -> None:
        while True:
            await asyncio.sleep(2)
            if not self.running:
                return
            self._notify()
            await self._async_maybe_stop_for_heat()
            await self._async_tick_night()
            if not self.settings.read_poll_ready or not self._transport_connected():
                continue
            now = time.monotonic()
            if now >= self.next_telemetry_poll:
                snap = self.state.snapshot()
                status = (snap.get("telemetry_last") or {}).get("status")
                if snap.get("pending_action") in ("start", "stop"):
                    poll_seconds = min(
                        self.settings.telemetry_poll_seconds,
                        PENDING_TELEMETRY_POLL_SECONDS,
                    )
                elif status == "charging":
                    poll_seconds = min(
                        self.settings.telemetry_poll_seconds,
                        ACTIVE_TELEMETRY_POLL_SECONDS,
                    )
                else:
                    poll_seconds = self.settings.telemetry_poll_seconds
                self.next_telemetry_poll = now + poll_seconds
                if not await self._async_send_packet(103, [0], "gateway_poll"):
                    LOG.warning("Telemetry poll publish failed")
            if now >= self.next_config_poll:
                self.next_config_poll = now + self.settings.config_poll_seconds
                if not await self._async_send_packet(96, [0], "gateway_config"):
                    LOG.warning("Configuration poll publish failed")

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.add(listener)

        def remove() -> None:
            self._listeners.discard(listener)
        return remove

    @callback
    def _notify(self) -> None:
        for listener in tuple(self._listeners):
            listener()

    def snapshot(self) -> dict:
        if self.state is None:
            return {}
        return self.state.snapshot()

    @property
    def gateway_online(self) -> bool:
        return self.running

    @property
    def station_online(self) -> bool:
        return bool(self.snapshot().get("station_online"))

    def control_available(self, capability: str) -> bool:
        snap = self.snapshot()
        mapping = {
            "can_charging": bool(snap.get("can_start") or snap.get("can_stop")),
            "can_current": bool(snap.get("can_set_current")),
            "can_mode": bool(snap.get("can_set_mode")),
        }
        return self.running and mapping.get(capability, False)

    def charging_control_state(self) -> tuple[str, bool, str | None]:
        """Return the suggested charging action and why it may be blocked."""
        snap = self.snapshot()
        status = (snap.get("telemetry_last") or {}).get("status")
        action = "stop" if status == "charging" else "start"

        if not self.running:
            return action, False, "integration_offline"
        if not snap.get("controls_configured"):
            return action, False, "protocol_unverified"
        if not snap.get("transport_connected"):
            return action, False, "transport_offline"
        if not snap.get("control_telemetry_fresh"):
            return action, False, "telemetry_stale"
        if snap.get("thermal_trip") or snap.get("thermal_shutdown_pending"):
            return action, False, "thermal_trip"
        if snap.get("pending_action"):
            return action, False, "waiting_response"

        if action == "stop":
            if snap.get("can_stop"):
                return action, True, None
            return action, False, "station_not_ready"

        if (snap.get("connector_candidate") != "connected"
                or not snap.get("control_connector_fresh")):
            return action, False, "connect_vehicle"
        if snap.get("can_start"):
            return action, True, None
        return action, False, "station_not_ready"

    def value(self, key: str):
        snap = self.snapshot()
        telemetry = snap.get("telemetry_last") or {}
        config = snap.get("station_config_last") or {}
        counters = snap.get("energy_counters") or {}
        values = {
            "state": telemetry.get("status"),
            "power": telemetry.get("power_w"),
            "session_energy": telemetry.get("energy_kwh"),
            "session_minutes": telemetry.get("session_minutes"),
            "temperature": telemetry.get("temperature_c"),
            "voltage": telemetry.get("voltage_v"),
            "connector": snap.get("connector_candidate"),
            "current_limit": config.get("current_limit_a"),
            "mode": MODE_LABELS.get(config.get("mode_code")),
            "valid_frames": snap.get("valid_frames"),
            "relay_failures": snap.get("relay_failures"),
            "observed_total_energy": counters.get("total_kwh"),
            "observed_today_energy": counters.get("today_kwh"),
            "observed_month_energy": counters.get("month_kwh"),
            "observed_sessions": counters.get("sessions"),
            "station_seen": "ON" if snap.get("station_online") else "OFF",
            "cloud_connected": "ON" if snap.get("cloud_mqtt_connected") else "OFF",
            "thermal_trip": "ON" if snap.get("thermal_trip") else "OFF",
            "night_session": "ON" if snap.get("night_session") else "OFF",
            "auto_start_inhibited": "ON" if snap.get("auto_start_inhibited") else "OFF",
            "charging": ("ON" if telemetry.get("status") == "charging" else
                         "OFF" if telemetry.get("status") in STOPPED_STATES else None),
            "max_current": self.settings.max_current_a,
        }
        return values.get(key)

    def _queue_store_save(self) -> None:
        self.hass.loop.call_soon_threadsafe(self._schedule_store_save)

    @callback
    def _schedule_store_save(self) -> None:
        if self._store_task is None or self._store_task.done():
            self._store_task = self.hass.async_create_task(self._async_delayed_store_save())

    async def _async_delayed_store_save(self) -> None:
        await asyncio.sleep(1)
        if self.state is not None:
            data = self.state.export_persistent()
            await self._store.async_save(data)

    def _require_state(self) -> GatewayState:
        if self.state is None:
            raise RuntimeError("WeGoodCharge runtime is not started")
        return self.state
