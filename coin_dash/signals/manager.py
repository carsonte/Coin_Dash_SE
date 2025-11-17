from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List

from ..ai.models import Decision
from ..features.market_mode import MarketMode
from ..features.trend import TrendProfile
from ..features.structure import StructureBundle
from ..config import SignalsCfg


@dataclass
class SignalRecord:
    symbol: str
    decision: Decision
    trade_type: str
    market_mode: MarketMode
    trend: TrendProfile
    structure: StructureBundle
    created_at: datetime
    expires_at: datetime
    notes: List[str] = field(default_factory=list)

    @property
    def direction(self) -> str:
        return self.decision.decision


class SignalManager:
    def __init__(self, cfg: SignalsCfg) -> None:
        self.cfg = cfg
        self.active: Dict[str, List[SignalRecord]] = {}
        self.last_emit: Dict[str, datetime] = {}

    def can_emit(self, symbol: str, direction: str, now: datetime) -> bool:
        self._cleanup(now)
        if direction == "hold":
            return False
        return True

    def add(self, record: SignalRecord) -> None:
        self.active.setdefault(record.symbol, []).append(record)
        self.last_emit[f"{record.symbol}:{record.direction}"] = record.created_at

    def correlated_warning(self, symbol: str, direction: str) -> bool:
        for sym, records in self.active.items():
            if sym == symbol:
                continue
            for rec in records:
                if rec.direction == direction and rec.expires_at > datetime.now(timezone.utc):
                    return True
        return False

    def _cleanup(self, now: datetime) -> None:
        for sym, records in list(self.active.items()):
            self.active[sym] = [r for r in records if r.expires_at > now]
            if not self.active[sym]:
                self.active.pop(sym, None)
