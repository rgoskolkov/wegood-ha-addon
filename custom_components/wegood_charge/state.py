"""Thread-safe charger state and safety latches."""

from __future__ import annotations

import time
from collections import deque
from datetime import UTC, datetime
from threading import RLock

from .config import Settings
from .counters import EnergyCounters
from .protocol import Frame, decode_config, decode_telemetry

STOPPED_STATES = ("idle", "ready", "waiting")


class GatewayState:
    def __init__(self, settings: Settings, saved: dict | None = None, persist=None) -> None:
        self.settings = settings
        self.lock = RLock()
        self._persist = persist
        saved = saved if isinstance(saved, dict) else {}
        safety = saved.get("safety") if isinstance(saved.get("safety"), dict) else {}
        safety_valid = (
            saved.get("state_version") != 1
            or (type(safety.get("thermal_trip")) is bool
                and type(safety.get("thermal_shutdown_pending")) is bool
                and type(safety.get("auto_start_inhibited")) is bool)
        )
        if safety_valid:
            self.thermal_trip = bool(safety.get("thermal_trip", False))
            self.thermal_shutdown_pending = bool(safety.get("thermal_shutdown_pending", False))
            self.auto_start_inhibited = bool(safety.get("auto_start_inhibited", False))
        else:
            # A malformed previously-written safety state must never silently
            # clear a thermal shutdown latch.
            self.thermal_trip = True
            self.thermal_shutdown_pending = True
            self.auto_start_inhibited = True
        if self.thermal_trip or self.thermal_shutdown_pending:
            self.auto_start_inhibited = True
        self.counters = EnergyCounters(settings.night_timezone, saved.get("counters"), self._changed)

        self.local_mqtt_connected = False
        self.cloud_mqtt_connected = False
        self.relay_failures = 0
        self.valid_frames = 0
        self.invalid_frames = 0
        self.last_seen_at: float | None = None
        self.last_seen_mono: float | None = None
        self.last_telemetry_mono: float | None = None
        self.last_config_mono: float | None = None
        self.last_frame: dict | None = None
        self.candidate_connector = "unknown"
        self.last_connector_mono: float | None = None
        self.telemetry: dict | None = None
        self.station_config: dict | None = None
        self.pending_action: str | None = None
        self.pending_since: float | None = None
        self.expected_current_a: int | None = None
        self.expected_mode_code: int | None = None
        self.night_session = False
        self.recent = deque(maxlen=12)
        self.error: str | None = None

    def _changed(self) -> None:
        if self._persist:
            self._persist()

    def export_persistent(self) -> dict:
        with self.lock:
            return {
                "state_version": 1,
                "safety": {
                    "thermal_trip": self.thermal_trip,
                    "thermal_shutdown_pending": self.thermal_shutdown_pending,
                    "auto_start_inhibited": self.auto_start_inhibited,
                },
                "counters": self.counters.export(),
            }

    def on_frame(self, frame: Frame) -> None:
        if not frame.is_station_response:
            return
        sample = decode_telemetry(frame)
        configuration = decode_config(frame)
        now = time.time()
        meta = {
            "command": frame.command,
            "data_length": len(frame.data),
            "received_at": datetime.fromtimestamp(now, UTC).isoformat(),
        }
        persist = False
        with self.lock:
            self.valid_frames += 1
            self.last_seen_at = now
            self.last_seen_mono = time.monotonic()
            connector = frame.connector_event_candidate
            if connector is not None:
                self.candidate_connector = connector
                self.last_connector_mono = time.monotonic()
            if sample is not None:
                self.counters.observe(sample)
                before = (self.thermal_trip, self.thermal_shutdown_pending,
                          self.auto_start_inhibited)
                self.last_telemetry_mono = time.monotonic()
                self.telemetry = vars(sample).copy()
                if sample.status in ("charging", "ready", "waiting"):
                    self.candidate_connector = "connected"
                    self.last_connector_mono = time.monotonic()
                if sample.temperature_c > 70:
                    self.thermal_trip = True
                    self.auto_start_inhibited = True
                    if sample.status == "charging":
                        self.thermal_shutdown_pending = True
                elif sample.temperature_c <= 60:
                    self.thermal_trip = False
                if sample.status in STOPPED_STATES:
                    self.thermal_shutdown_pending = False
                persist = before != (self.thermal_trip, self.thermal_shutdown_pending,
                                     self.auto_start_inhibited)
                if ((self.pending_action == "start" and sample.status == "charging") or
                        (self.pending_action == "stop" and sample.status in STOPPED_STATES)):
                    self._clear_pending_locked()
            if configuration is not None:
                self.last_config_mono = time.monotonic()
                self.station_config = vars(configuration).copy()
                if (self.pending_action == "current" and self.expected_current_a is not None and
                        abs(configuration.current_limit_a - self.expected_current_a) < 0.01) or (self.pending_action == "mode" and self.expected_mode_code is not None and
                      configuration.mode_code == self.expected_mode_code):
                    self._clear_pending_locked()
            self.last_frame = meta
            self.recent.appendleft(meta)
        if persist:
            self._changed()

    def note_invalid(self) -> None:
        with self.lock:
            self.invalid_frames += 1

    def note_relay(self, success: bool) -> None:
        with self.lock:
            if not success:
                self.relay_failures += 1

    def station_disconnected(self) -> None:
        with self.lock:
            self.last_seen_mono = None
            self.last_telemetry_mono = None
            self.last_config_mono = None
            self.last_connector_mono = None
            self.candidate_connector = "unknown"
            self._clear_pending_locked()

    def snapshot(self) -> dict:
        with self.lock:
            mono = time.monotonic()
            age = mono - self.last_seen_mono if self.last_seen_mono is not None else None
            recent = age is not None and age < self.settings.watchdog_seconds
            telemetry_age = (mono - self.last_telemetry_mono
                             if self.last_telemetry_mono is not None else None)
            config_age = mono - self.last_config_mono if self.last_config_mono is not None else None
            connector_age = (mono - self.last_connector_mono
                             if self.last_connector_mono is not None else None)
            fresh_telemetry = telemetry_age is not None and telemetry_age < self.settings.watchdog_seconds
            fresh_config = config_age is not None and config_age < max(120, self.settings.config_poll_seconds * 2)
            if self.pending_since is not None and mono - self.pending_since > 20:
                self._clear_pending_locked()

            transport_up = (self.cloud_mqtt_connected if self.settings.integration_mode == "cloud"
                            else self.local_mqtt_connected)
            status = self.telemetry["status"] if self.telemetry else "unknown"
            control_limit = min(self.settings.watchdog_seconds, 300)
            control_telemetry_fresh = telemetry_age is not None and telemetry_age < control_limit
            control_connector_fresh = connector_age is not None and connector_age < control_limit
            control_ready = self.settings.controls_configured and transport_up and self.pending_action is None
            telemetry_ready = control_ready and control_telemetry_fresh and self.telemetry is not None
            can_start = (telemetry_ready and not self.thermal_trip and not self.thermal_shutdown_pending
                         and self.candidate_connector == "connected" and control_connector_fresh
                         and status in STOPPED_STATES)
            can_stop = telemetry_ready and status == "charging"
            can_current = (telemetry_ready and fresh_config and not self.thermal_trip
                           and self.station_config is not None
                           and self.station_config.get("mode_code") in (0, 1, 2))
            current = self.station_config.get("current_limit_a") if self.station_config else None
            valid_current = (type(current) in (int, float) and float(current).is_integer()
                             and 8 <= current <= self.settings.max_current_a)
            can_set_mode = (telemetry_ready and fresh_config and not self.thermal_trip
                            and not self.thermal_shutdown_pending and self.station_config is not None
                            and self.station_config.get("mode_code") in (0, 1, 2)
                            and valid_current and status in STOPPED_STATES)
            return {
                "integration_mode": self.settings.integration_mode,
                "cloud_bridge_enabled": self.settings.cloud_relay_enabled,
                "controls_configured": self.settings.controls_configured,
                "transport_connected": transport_up,
                "cloud_mqtt_connected": self.cloud_mqtt_connected,
                "local_mqtt_connected": self.local_mqtt_connected,
                "relay_failures": self.relay_failures,
                "station_online": bool(recent and transport_up),
                "telemetry_fresh": fresh_telemetry,
                "control_telemetry_fresh": control_telemetry_fresh,
                "control_connector_fresh": control_connector_fresh,
                "last_frame_age_seconds": round(age, 1) if age is not None else None,
                "last_seen_at": self.last_seen_at,
                "valid_frames": self.valid_frames,
                "invalid_frames": self.invalid_frames,
                "energy_counters": self.counters.snapshot(),
                "last_frame": dict(self.last_frame) if self.last_frame else None,
                "recent": list(self.recent),
                "connector_candidate": self.candidate_connector if recent else "unknown",
                "telemetry_preview": dict(self.telemetry) if fresh_telemetry and transport_up and self.telemetry else None,
                "telemetry_last": dict(self.telemetry) if self.telemetry else None,
                "station_config_preview": dict(self.station_config) if fresh_config and transport_up and self.station_config else None,
                "station_config_last": dict(self.station_config) if self.station_config else None,
                "can_start": can_start,
                "can_stop": can_stop,
                "can_set_current": can_current,
                "can_set_mode": can_set_mode,
                "pending_action": self.pending_action,
                "thermal_trip": self.thermal_trip,
                "thermal_shutdown_pending": self.thermal_shutdown_pending,
                "auto_start_inhibited": self.auto_start_inhibited,
                "night_session": self.night_session,
                "max_current_a": self.settings.max_current_a,
                "error": self.error,
            }

    def begin_command(self, action: str, expected_current_a: int | None = None,
                      expected_mode_code: int | None = None) -> None:
        with self.lock:
            self.pending_action = action
            self.pending_since = time.monotonic()
            self.expected_current_a = expected_current_a
            self.expected_mode_code = expected_mode_code

    def _clear_pending_locked(self) -> None:
        self.pending_action = None
        self.pending_since = None
        self.expected_current_a = None
        self.expected_mode_code = None

    def clear_pending(self) -> None:
        with self.lock:
            self._clear_pending_locked()

    def set_night_session(self, value: bool) -> None:
        with self.lock:
            self.night_session = value

    def manual_start_rearms_schedule(self) -> bool:
        changed = False
        with self.lock:
            if self.thermal_trip or self.thermal_shutdown_pending:
                return False
            if self.auto_start_inhibited:
                self.auto_start_inhibited = False
                changed = True
        if changed:
            self._changed()
        return True
