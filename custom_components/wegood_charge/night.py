"""Clock-only helper for overnight windows in the configured local timezone."""

from datetime import datetime, timedelta


def night_window(now: datetime, start: str, end: str) -> tuple[bool, str]:
    """Whether the tariff window is open, and its local starting date."""
    minute = now.hour * 60 + now.minute
    begin = int(start[:2]) * 60 + int(start[3:])
    finish = int(end[:2]) * 60 + int(end[3:])
    if begin < finish:
        return begin <= minute < finish, now.date().isoformat()
    if minute >= begin:
        return True, now.date().isoformat()
    if minute < finish:
        return True, (now.date() - timedelta(days=1)).isoformat()
    return False, now.date().isoformat()
