from __future__ import annotations

from datetime import datetime, timezone


def to_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)

