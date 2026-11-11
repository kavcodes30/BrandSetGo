"""SQLite hands back naive datetimes; treat every stored timestamp as UTC."""
from __future__ import annotations

from datetime import datetime, timezone


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
