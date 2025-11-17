from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional


@dataclass
class DailySafeModeState:
    date: Optional[str] = None
    count: int = 0
    active: bool = False


class DailySafeMode:
    def __init__(self, threshold: int, state: Optional[DailySafeModeState] = None) -> None:
        self.threshold = max(0, threshold)
        self.state = state or DailySafeModeState()

    def _ensure_today(self, now: datetime) -> None:
        if self.threshold <= 0:
            return
        today = now.astimezone(timezone.utc).date().isoformat()
        if self.state.date != today:
            self.state.date = today
            self.state.count = 0
            self.state.active = False

    def can_trade(self, now: datetime) -> bool:
        if self.threshold <= 0:
            return True
        self._ensure_today(now)
        return not self.state.active

    def record_stop_loss(self, now: datetime) -> bool:
        """
        Returns True if this call newly activated safe mode.
        """
        if self.threshold <= 0:
            return False
        self._ensure_today(now)
        self.state.count += 1
        previously_active = self.state.active
        if self.state.count >= self.threshold:
            self.state.active = True
        return not previously_active and self.state.active

    def to_dict(self) -> Dict:
        return {
            "date": self.state.date,
            "count": self.state.count,
            "active": self.state.active,
        }

    @classmethod
    def from_dict(cls, threshold: int, payload: Optional[Dict]) -> "DailySafeMode":
        state = DailySafeModeState()
        if payload:
            state.date = payload.get("date")
            state.count = payload.get("count", 0)
            state.active = payload.get("active", False)
        return cls(threshold, state)
