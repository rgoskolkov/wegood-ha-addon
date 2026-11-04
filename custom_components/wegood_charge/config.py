"""Configuration model for the native WeGoodCharge integration."""

from __future__ import annotations

from dataclasses import dataclass, fields
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class Settings:
    integration_mode: str = "cloud"
    station_id: str = ""
    protocol_variant: str = "unverified"
    max_current_a: int = 16
    watchdog_seconds: int = 35
    telemetry_poll_seconds: int = 20
    config_poll_seconds: int = 120
    night_schedule_enabled: bool = False
    night_start: str = "23:15"
    night_end: str = "05:50"
    night_timezone: str = "Asia/Novosibirsk"

    station_rx_topic: str = ""
    station_tx_topic: str = ""

    cloud_bridge_enabled: bool = False
    cloud_mqtt_host: str = ""
    cloud_mqtt_port: int = 1883
    cloud_mqtt_tls: bool = False
    cloud_mqtt_username: str = ""
    cloud_mqtt_password: str = ""
    cloud_mqtt_client_id: str = "wegood_ha_gateway_cloud"
    cloud_command_topic: str = ""
    cloud_status_topic: str = ""

    @classmethod
    def from_mapping(cls, data: dict) -> Settings:
        valid = {f.name for f in fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in valid})

    def validate(self) -> None:
        if self.integration_mode not in ("cloud", "local"):
            raise ValueError("integration_mode must be cloud or local")
        if self.protocol_variant not in ("unverified", "ics10_v14"):
            raise ValueError("Unsupported protocol variant")
        if not isinstance(self.station_id, str) or not self.station_id or len(self.station_id) > 128:
            raise ValueError("Station ID is required")
        if any(c in self.station_id for c in ("\n", "\r", "\x00", "/", "+", "#")):
            raise ValueError("Invalid station ID")
        if type(self.max_current_a) is not int or not 8 <= self.max_current_a <= 32:
            raise ValueError("max_current_a must be between 8 and 32 A")
        if type(self.watchdog_seconds) is not int or not 10 <= self.watchdog_seconds <= 86400:
            raise ValueError("watchdog_seconds must be between 10 and 86400")
        for name in ("telemetry_poll_seconds", "config_poll_seconds"):
            value = getattr(self, name)
            if type(value) is not int or not 5 <= value <= 3600:
                raise ValueError(f"{name} must be between 5 and 3600 seconds")
        if type(self.night_schedule_enabled) is not bool:
            raise ValueError("night_schedule_enabled must be boolean")
        for value in (self.night_start, self.night_end):
            if (not isinstance(value, str) or len(value) != 5 or value[2] != ":"
                    or not value[:2].isdigit() or not value[3:].isdigit()
                    or int(value[:2]) > 23 or int(value[3:]) > 59):
                raise ValueError("Night schedule times must be HH:MM")
        if self.night_start == self.night_end:
            raise ValueError("Night schedule start and end must differ")
        try:
            ZoneInfo(self.night_timezone)
        except (ZoneInfoNotFoundError, TypeError, ValueError) as exc:
            raise ValueError("Invalid night_timezone") from exc

        if type(self.cloud_bridge_enabled) is not bool or type(self.cloud_mqtt_tls) is not bool:
            raise ValueError("Cloud bridge and TLS options must be boolean")
        if type(self.cloud_mqtt_port) is not int or not 1 <= self.cloud_mqtt_port <= 65535:
            raise ValueError("Cloud MQTT port must be between 1 and 65535")
        if any(c in self.cloud_mqtt_username for c in ("\n", "\r", ":")):
            raise ValueError("cloud_mqtt_username contains an invalid character")
        if any(c in self.cloud_mqtt_password for c in ("\n", "\r")):
            raise ValueError("cloud_mqtt_password contains an invalid character")
        if (not 1 <= len(self.cloud_mqtt_client_id) <= 128 or
                any(c in self.cloud_mqtt_client_id for c in ("\n", "\r", "\x00"))):
            raise ValueError("Invalid cloud MQTT client ID")
        if self.cloud_mqtt_client_id == self.station_id:
            raise ValueError("Cloud client ID must differ from station ID")

        for topic in (self.station_rx_topic, self.station_tx_topic,
                      self.cloud_command_topic, self.cloud_status_topic):
            if any(symbol in topic for symbol in ("#", "+", "\n", "\r", "\x00")):
                raise ValueError("MQTT topics must be exact and valid")
        if self.station_rx_topic and self.station_rx_topic == self.station_tx_topic:
            raise ValueError("Station command and response topics must differ")
        if self.effective_cloud_command_topic == self.effective_cloud_status_topic:
            raise ValueError("Cloud command and status topics must differ")
        if self.integration_mode == "cloud" and not self.cloud_mqtt_host:
            raise ValueError("Cloud MQTT host is required in cloud mode")
        if self.integration_mode == "local" and not self.station_rx_topic:
            raise ValueError("Station response topic is required in local mode")
        if self.integration_mode == "local" and not self.station_tx_topic:
            raise ValueError("Station command topic is required in local mode")
        if self.cloud_bridge_enabled and not self.cloud_bridge_ready:
            raise ValueError("Cloud relay needs cloud MQTT settings and exact local station topics")
        if self.night_schedule_enabled and not self.controls_configured:
            raise ValueError("Night schedule requires verified ICS_10 V1.4 control")

    @property
    def effective_cloud_status_topic(self) -> str:
        return self.cloud_status_topic or f"s_w1007_gd/{self.station_id}"

    @property
    def effective_cloud_command_topic(self) -> str:
        return self.cloud_command_topic or f"d_wt1206_d2113/{self.station_id}"

    @property
    def cloud_status_ready(self) -> bool:
        return bool(self.cloud_mqtt_host and self.station_id and self.effective_cloud_status_topic)

    @property
    def cloud_client_enabled(self) -> bool:
        return self.cloud_status_ready if self.integration_mode == "cloud" else self.cloud_relay_enabled

    @property
    def cloud_relay_enabled(self) -> bool:
        return self.integration_mode == "local" and self.cloud_bridge_enabled

    @property
    def station_topics_ready(self) -> bool:
        if self.integration_mode == "cloud":
            return self.cloud_status_ready
        return bool(self.station_rx_topic)

    @property
    def read_poll_ready(self) -> bool:
        command_topic = (self.effective_cloud_command_topic
                         if self.integration_mode == "cloud" else self.station_tx_topic)
        return bool(self.station_topics_ready and self.station_id and command_topic)

    @property
    def active_read_ready(self) -> bool:
        return self.read_poll_ready and self.protocol_variant == "ics10_v14"

    @property
    def controls_configured(self) -> bool:
        return self.active_read_ready

    @property
    def cloud_bridge_ready(self) -> bool:
        return bool(
            self.integration_mode == "local" and self.station_rx_topic and self.station_tx_topic
            and self.cloud_mqtt_host and self.effective_cloud_command_topic
            and self.effective_cloud_status_topic
        )
