"""Read-only decoder for experimentally documented WGD ICS_10 V1.4 packets."""

import json
from dataclasses import dataclass


class PacketError(ValueError):
    """The message is not a valid WeGood frame."""


@dataclass(frozen=True)
class Frame:
    header: int
    command: int
    data: bytes

    @property
    def is_station_response(self) -> bool:
        return self.header == 0xAA

    @property
    def connector_event_candidate(self) -> str | None:
        # CMD116 code 5=connected and 1=disconnected on FW V1.4.
        if not self.is_station_response or self.command != 116:
            return None
        # First payload byte is event metadata; the actual event is byte 4
        # of the full packet (index 1 in its decoded payload).
        if len(self.data) < 2:
            return None
        return {5: "connected", 1: "disconnected"}.get(self.data[1])


@dataclass(frozen=True)
class Telemetry:
    status: str
    power_w: int
    energy_kwh: float
    session_minutes: int
    temperature_c: int
    voltage_v: int


@dataclass(frozen=True)
class StationConfig:
    mode: str
    mode_code: int
    current_limit_a: float


def decode_telemetry(frame: Frame) -> Telemetry | None:
    """Decode preliminary offsets; only confirmed for WGD ICS_10 FW V1.4."""
    if not frame.is_station_response or frame.command != 103 or len(frame.data) < 13:
        return None
    d = frame.data
    states = {1: "idle", 2: "charging", 5: "ready", 7: "waiting"}
    energy_raw = int.from_bytes(d[3:7], "little")
    return Telemetry(
        status=states.get(d[0], f"unknown_{d[0]}"),
        power_w=int.from_bytes(d[1:3], "little"),
        energy_kwh=energy_raw / 100,
        session_minutes=int.from_bytes(d[7:10], "little"),
        temperature_c=d[10],
        voltage_v=d[11],
    )


def decode_config(frame: Frame) -> StationConfig | None:
    if not frame.is_station_response or frame.command != 96 or len(frame.data) < 20:
        return None
    mode = frame.data[6]
    return StationConfig(
        mode={
            0: "standard",
            1: "free_card_swipe",
            2: "plug_and_charge",
        }.get(mode, f"unknown_{mode}"),
        mode_code=mode,
        current_limit_a=int.from_bytes(frame.data[18:20], "little") / 100,
    )


def decode_packet(values: list[int]) -> Frame:
    if not isinstance(values, list) or len(values) < 4:
        raise PacketError("Packet must be a list of at least four bytes")
    if any(type(byte) is not int or not 0 <= byte <= 255 for byte in values):
        raise PacketError("Packet contains a non-byte value")
    if values[0] not in (0x55, 0xAA):
        raise PacketError("Unknown packet header")
    if values[2] != len(values) - 4:
        raise PacketError("Invalid packet length")
    if sum(values[1:-1]) & 0xFF != values[-1]:
        raise PacketError("Invalid packet checksum")
    return Frame(header=values[0], command=values[1], data=bytes(values[3:-1]))


def decode_message(payload: bytes | str) -> Frame | None:
    """Return None for non-WeGood messages (e.g. MQTT discovery)."""
    if isinstance(payload, bytes):
        if len(payload) > 8192:
            return None
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError:
            return None
    try:
        body = json.loads(payload)
    except (ValueError, TypeError):
        return None
    if isinstance(body, dict):
        # Device responses use "data", while outgoing commands use
        # "com_chuankoudt". The article's samples show both envelopes.
        values = body.get("data")
        if values is None:
            values = body.get("com_chuankoudt")
    else:
        values = body
    if values is None:
        return None
    return decode_packet(values)


def make_read_telemetry_request() -> list[int]:
    """Known reference packet; never published without verified envelope."""
    return [85, 103, 1, 0, 104]


def build_request(command: int, payload: list[int], station_id: str, nonce: str) -> bytes:
    """Cloud/local envelope for the observed WGD ICS_10 V1.4 firmware."""
    if not station_id:
        raise ValueError("Station ID is required")
    if command not in (96, 97, 103, 104, 105):
        raise ValueError("Unsupported command")
    if not isinstance(payload, list) or len(payload) > 255:
        raise ValueError("Invalid data size")
    if any(type(v) is not int or not 0 <= v <= 255 for v in payload):
        raise ValueError("Invalid payload byte")
    packet = [85, command, len(payload), *payload]
    packet.append(sum(packet[1:]) & 0xFF)
    envelope = {
        "cmd": 75960,
        "com_chuankoudt": packet,
        "imei": station_id,
        "noncestr": nonce,
        "checksum": 1,
    }
    return json.dumps(envelope, separators=(",", ":")).encode("utf-8")


def start_payload() -> list[int]:
    return [1, 208, 7]


def stop_payload() -> list[int]:
    return [1]


def current_payload(amps: int, mode_code: int) -> list[int]:
    """V1.4-only reference layout; caller must verify mode and current rating."""
    if mode_code not in (0, 1, 2) or type(amps) is not int or not 8 <= amps <= 32:
        raise ValueError("Invalid station mode or current")
    raw = amps * 100
    # Other fields of this *specific* FW revision are fixed in the observed
    # packet layout. This is never used for unidentified stations.
    return [1, 8, 244, 1, 231, 3, mode_code, 208, 32, 7, 9, 5, 22,
            8, 5, raw & 255, raw >> 8, 1, 1]
