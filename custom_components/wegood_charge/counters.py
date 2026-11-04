"""Observed energy counters for the native integration."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


class EnergyCounters:
    def __init__(self, timezone: str = "UTC", saved: dict | None = None, on_change=None) -> None:
        self.zone = ZoneInfo(timezone)
        self.on_change = on_change
        self.total_kwh = 0.0
        self.today_kwh = 0.0
        self.month_kwh = 0.0
        self.sessions = 0
        self.last_energy = None
        self.last_minutes = None
        self.last_status = None
        self.day = None
        self.month = None
        self.restore(saved or {})

    def restore(self, data: dict) -> None:
        if not data:
            return
        if data.get("version") != 1:
            return
        try:
            for key in ("total_kwh", "today_kwh", "month_kwh"):
                value = float(data[key])
                if not 0 <= value < 1e9:
                    return
                setattr(self, key, value)
            self.sessions = max(0, int(data["sessions"]))
            self.last_energy = data.get("last_energy")
            self.last_minutes = data.get("last_minutes")
            self.last_status = data.get("last_status")
            self.day = data.get("day")
            self.month = data.get("month")
        except (ValueError, TypeError, KeyError):
            return

    def observe(self, telemetry) -> None:
        current = datetime.now(self.zone)
        day, month = current.strftime("%Y-%m-%d"), current.strftime("%Y-%m")
        if self.day != day:
            self.today_kwh = 0.0
        if self.month != month:
            self.month_kwh = 0.0
        self.day, self.month = day, month
        energy = float(telemetry.energy_kwh)
        minutes = int(telemetry.session_minutes)
        status = telemetry.status
        reset = (self.last_energy is not None and
                 (energy < self.last_energy or
                  (self.last_minutes is not None and minutes < self.last_minutes)))
        if self.last_energy is not None and not reset:
            delta = energy - self.last_energy
            if 0 <= delta <= 10:
                self.total_kwh += delta
                self.today_kwh += delta
                self.month_kwh += delta
        if status == "charging" and self.last_status != "charging" or reset and status == "charging" and self.last_status == "charging":
            self.sessions += 1
        self.last_energy, self.last_minutes, self.last_status = energy, minutes, status
        if self.on_change:
            self.on_change()

    def snapshot(self) -> dict:
        now = datetime.now(self.zone)
        return {
            "total_kwh": round(self.total_kwh, 3),
            "today_kwh": round(self.today_kwh if self.day == now.strftime("%Y-%m-%d") else 0, 3),
            "month_kwh": round(self.month_kwh if self.month == now.strftime("%Y-%m") else 0, 3),
            "sessions": self.sessions,
            "estimated": True,
        }

    def export(self) -> dict:
        return {
            "version": 1,
            "total_kwh": self.total_kwh,
            "today_kwh": self.today_kwh,
            "month_kwh": self.month_kwh,
            "sessions": self.sessions,
            "last_energy": self.last_energy,
            "last_minutes": self.last_minutes,
            "last_status": self.last_status,
            "day": self.day,
            "month": self.month,
        }
