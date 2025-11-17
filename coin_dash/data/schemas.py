from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class OHLCV:
    ts: datetime  # UTC
    open: float
    high: float
    low: float
    close: float
    volume: float

