from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Dict

from ..exec.paper import Trade


@dataclass
class TradeMetric:
    count: int = 0
    wins: int = 0
    total_rr: float = 0.0
    pnl: float = 0.0

    def update(self, trade: Trade, rr: float) -> None:
        self.count += 1
        if trade.pnl > 0:
            self.wins += 1
        self.total_rr += rr
        self.pnl += trade.pnl

    def snapshot(self) -> Dict[str, float]:
        return {
            "count": self.count,
            "wins": self.wins,
            "win_rate": self.wins / self.count if self.count else 0.0,
            "avg_rr": self.total_rr / self.count if self.count else 0.0,
            "pnl": self.pnl,
        }


class PerformanceTracker:
    def __init__(self) -> None:
        self.mode_metrics: Dict[str, TradeMetric] = defaultdict(TradeMetric)
        self.type_metrics: Dict[str, TradeMetric] = defaultdict(TradeMetric)
        self.symbol_metrics: Dict[str, TradeMetric] = defaultdict(TradeMetric)
        self.last_update: datetime | None = None

    def record(self, trade: Trade, trade_type: str, rr: float, mode: str) -> None:
        self.mode_metrics[mode].update(trade, rr)
        self.type_metrics[trade_type].update(trade, rr)
        self.symbol_metrics[trade.symbol].update(trade, rr)
        self.last_update = datetime.utcnow()

    def report(self) -> Dict[str, Dict[str, float]]:
        return {
            "modes": {k: v.snapshot() for k, v in self.mode_metrics.items()},
            "types": {k: v.snapshot() for k, v in self.type_metrics.items()},
            "symbols": {k: v.snapshot() for k, v in self.symbol_metrics.items()},
        }
