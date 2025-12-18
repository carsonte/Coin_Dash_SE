from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .notify.lark import ExitEventPayload


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _serialize_dt(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


@dataclass
class PositionState:
    id: str
    symbol: str
    side: str
    entry: float
    stop: float
    take: float
    rr: float
    trade_type: str
    market_mode: str
    created_at: datetime
    updated_at: datetime
    last_review_at: datetime
    qty: float = 0.0
    status: str = "open"
    closed_at: Optional[datetime] = None

    def to_record(self) -> Dict:
        record = asdict(self)
        record["created_at"] = _serialize_dt(self.created_at)
        record["updated_at"] = _serialize_dt(self.updated_at)
        record["last_review_at"] = _serialize_dt(self.last_review_at)
        record["closed_at"] = _serialize_dt(self.closed_at)
        return record

    @classmethod
    def from_record(cls, record: Dict) -> "PositionState":
        return cls(
            id=record["id"],
            symbol=record["symbol"],
            side=record["side"],
            entry=record["entry"],
            stop=record["stop"],
            take=record["take"],
            rr=record.get("rr", 0.0),
            trade_type=record.get("trade_type", "trend"),
            market_mode=record.get("market_mode", "mixed"),
            created_at=_parse_dt(record.get("created_at")) or _utc_now(),
            updated_at=_parse_dt(record.get("updated_at")) or _utc_now(),
            last_review_at=_parse_dt(record.get("last_review_at")) or _utc_now(),
            qty=record.get("qty", 0.0),
            status=record.get("status", "open"),
            closed_at=_parse_dt(record.get("closed_at")),
        )


class StateManager:
    def __init__(self, storage_path: Path, base_equity: float = 1000.0) -> None:
        self.path = Path(storage_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._positions: Dict[str, List[PositionState]] = {}
        self._closed: List[Dict] = []
        self._thresholds: Dict[str, float] = {}
        self._modes: Dict[str, str] = {}
        self._safe_mode: Dict = {}
        self._daily_summary: Dict = {}
        self.base_equity = float(base_equity)
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text())
        except Exception:
            return
        for symbol, items in raw.get("positions", {}).items():
            self._positions[symbol] = [PositionState.from_record(rec) for rec in items]
        self._closed = raw.get("closed", [])
        self._thresholds = raw.get("thresholds", {})
        self._modes = raw.get("modes", {})
        self._safe_mode = raw.get("safe_mode", {})
        self._daily_summary = raw.get("daily_summary", {})
        self.base_equity = float(raw.get("base_equity", self.base_equity))

    def _dump(self) -> None:
        payload = {
            "positions": {
                symbol: [pos.to_record() for pos in items]
                for symbol, items in self._positions.items()
            },
            "closed": self._closed,
            "thresholds": self._thresholds,
            "modes": self._modes,
            "safe_mode": self._safe_mode,
            "daily_summary": self._daily_summary,
            "base_equity": self.base_equity,
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    def get_safe_mode_state(self) -> Dict:
        return dict(self._safe_mode)

    def save_safe_mode_state(self, payload: Dict) -> None:
        self._safe_mode = dict(payload or {})
        self._dump()

    def get_threshold_adjustment(self, symbol: str) -> float:
        return float(self._thresholds.get(symbol, 0.0))

    def bump_threshold(self, symbol: str, amount: float) -> None:
        self._thresholds[symbol] = self.get_threshold_adjustment(symbol) + float(amount)
        self._dump()

    def reset_threshold(self, symbol: str) -> None:
        if symbol in self._thresholds:
            self._thresholds[symbol] = 0.0
            self._dump()

    def add_position(
        self,
        symbol: str,
        side: str,
        entry: float,
        stop: float,
        take: float,
        rr: float,
        trade_type: str,
        market_mode: str,
        qty: float = 0.0,
    ) -> PositionState:
        now = _utc_now()
        pos = PositionState(
            id=f"{symbol}-{uuid.uuid4().hex[:8]}",
            symbol=symbol,
            side=side,
            entry=entry,
            stop=stop,
            take=take,
            rr=rr,
            trade_type=trade_type,
            market_mode=market_mode,
            created_at=now,
            updated_at=now,
            last_review_at=now,
            qty=qty,
        )
        self._positions.setdefault(symbol, []).append(pos)
        self._dump()
        return pos

    def list_positions(self, symbol: str) -> List[PositionState]:
        return [pos for pos in self._positions.get(symbol, []) if pos.status == "open"]

    def positions_for_review(self, symbol: str, interval_minutes: int) -> List[PositionState]:
        return self.list_positions(symbol)

    def update_position_levels(
        self,
        symbol: str,
        position_id: str,
        new_stop: Optional[float] = None,
        new_take: Optional[float] = None,
        new_rr: Optional[float] = None,
    ) -> Optional[PositionState]:
        pos = self._find_position(symbol, position_id)
        if not pos:
            return None
        if new_stop is not None:
            pos.stop = new_stop
        if new_take is not None:
            pos.take = new_take
        if new_rr is not None:
            pos.rr = new_rr
        pos.updated_at = _utc_now()
        pos.last_review_at = pos.updated_at
        self._dump()
        return pos

    def close_position(
        self,
        symbol: str,
        position_id: str,
        exit_price: float,
        exit_type: str,
        reason: str,
        duration: str,
        realized_pnl: Optional[float] = None,
        executed_qty: Optional[float] = None,
    ) -> Optional[ExitEventPayload]:
        pos = self._find_position(symbol, position_id)
        if not pos or pos.status == "closed":
            return None
        pos.status = "closed"
        pos.closed_at = _utc_now()
        pos.updated_at = pos.closed_at

        qty = executed_qty if executed_qty is not None else (pos.qty if pos.qty > 0 else 1.0)
        if realized_pnl is not None:
            pnl = realized_pnl
        else:
            price_diff = (exit_price - pos.entry) if pos.side == "open_long" else (pos.entry - exit_price)
            pnl = price_diff * qty
        record = {
            "symbol": pos.symbol,
            "trade_type": pos.trade_type,
            "market_mode": pos.market_mode,
            "rr": pos.rr,
            "pnl": pnl,
            "exit_type": exit_type,
            "closed_at": _serialize_dt(pos.closed_at),
            "qty": qty,
        }
        self._closed.append(record)
        self._dump()
        return ExitEventPayload(
            symbol=pos.symbol,
            side="多头" if pos.side == "open_long" else "空头",
            entry_price=pos.entry,
            exit_price=exit_price,
            pnl=pnl,
            rr=pos.rr,
            duration=duration,
            reason=reason,
            exit_type=exit_type,
        )

    def _find_position(self, symbol: str, position_id: str) -> Optional[PositionState]:
        for pos in self._positions.get(symbol, []):
            if pos.id == position_id:
                return pos
        return None

    def last_mode(self, symbol: str) -> Optional[str]:
        return self._modes.get(symbol)

    def update_mode(self, symbol: str, mode: str) -> None:
        self._modes[symbol] = mode
        self._dump()

    def should_send_daily_summary(self, now: datetime, report_hour_utc8: int) -> bool:
        local = now.astimezone(timezone(timedelta(hours=8)))
        if local.hour < report_hour_utc8:
            return False
        date_key = local.strftime("%Y-%m-%d")
        if self._daily_summary.get("date") == date_key and self._daily_summary.get("sent"):
            return False
        self._daily_summary = {"date": date_key, "sent": True, "sent_at": _serialize_dt(now)}
        self._dump()
        return True

    def performance_stats(self) -> Dict[str, float]:
        closed = self._closed
        trades = len(closed)
        pnl_total = sum(item.get("pnl", 0.0) for item in closed)
        wins = sum(1 for item in closed if item.get("pnl", 0.0) > 0)
        gross_profit = sum(item.get("pnl", 0.0) for item in closed if item.get("pnl", 0.0) > 0)
        gross_loss = abs(sum(item.get("pnl", 0.0) for item in closed if item.get("pnl", 0.0) < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0.0)
        equity = self.base_equity + pnl_total
        return {
            "equity": equity,
            "closed": trades,
            "trades": trades,
            "pnl_total": pnl_total,
            "win_rate": (wins / trades) if trades else 0.0,
            "profit_factor": profit_factor,
        }

    def grouped_stats(self, key: str) -> Dict[str, Dict[str, float]]:
        groups: Dict[str, Dict[str, float]] = {}
        for trade in self._closed:
            name = trade.get(key) or "unknown"
            bucket = groups.setdefault(name, {"count": 0, "wins": 0, "pnl": 0.0, "rr_sum": 0.0})
            bucket["count"] += 1
            pnl = trade.get("pnl", 0.0)
            bucket["pnl"] += pnl
            bucket["rr_sum"] += trade.get("rr", 0.0)
            if pnl > 0:
                bucket["wins"] += 1
        for name, bucket in groups.items():
            count = bucket["count"]
            bucket["win_rate"] = (bucket["wins"] / count) if count else 0.0
            bucket["avg_rr"] = (bucket["rr_sum"] / count) if count else 0.0
        return {
            name: {
                "count": bucket["count"],
                "wins": bucket["wins"],
                "win_rate": bucket["win_rate"],
                "avg_rr": bucket["avg_rr"],
                "pnl": bucket["pnl"],
            }
            for name, bucket in groups.items()
        }
