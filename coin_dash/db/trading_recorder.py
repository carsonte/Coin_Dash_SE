from __future__ import annotations

from typing import Optional

from sqlalchemy.dialects.postgresql import insert

from ..signals.manager import SignalRecord
from ..state_manager import PositionState
from ..exec.paper import Trade as PaperTrade
from .client import DatabaseClient
from .models import PositionRecord, SignalEntry, TradeRecord
from .utils import utc_now


class TradingRecorder:
    def __init__(self, client: DatabaseClient) -> None:
        self.client = client

    def record_signal(self, signal: SignalRecord, correlated: bool, signal_id: Optional[str] = None) -> None:
        if not self.client.enabled:
            return
        identifier = signal_id or f"{signal.symbol}-{int(signal.created_at.timestamp())}"
        data = {
            "signal_id": identifier,
            "symbol": signal.symbol,
            "direction": signal.decision.decision,
            "entry_price": signal.decision.entry_price,
            "stop_loss": signal.decision.stop_loss,
            "take_profit": signal.decision.take_profit,
            "risk_reward": signal.decision.risk_reward,
            "trade_type": signal.trade_type,
            "market_mode": signal.market_mode.name,
            "status": "active",
            "correlated": correlated,
            "notes": {"notes": signal.notes},
            "context": {
                "trend": signal.trend.grade,
                "score": signal.trend.score,
            },
            "expires_at": signal.expires_at,
        }
        stmt = insert(SignalEntry).values(data)
        stmt = stmt.on_conflict_do_update(index_elements=["signal_id"], set_={"status": "active"})
        with self.client.session() as session:
            if session is None:
                return
            session.execute(stmt)

    def record_signal_status(self, signal_id: str, status: str) -> None:
        if not self.client.enabled:
            return
        with self.client.session() as session:
            if session is None:
                return
            session.query(SignalEntry).filter(SignalEntry.signal_id == signal_id).update({"status": status})

    def record_trade_open(self, trade: PaperTrade, signal_id: Optional[str] = None) -> None:
        if not self.client.enabled:
            return
        payload = {
            "trade_id": trade.trade_id,
            "signal_id": signal_id,
            "symbol": trade.symbol,
            "side": trade.side,
            "entry_price": trade.entry,
            "stop_loss": trade.stop,
            "take_profit": trade.take,
            "quantity": trade.qty,
            "rr": trade.rr,
            "opened_at": utc_now(),
            "status": "open",
            "extra": {"history": trade.history},
        }
        stmt = insert(TradeRecord).values(payload)
        stmt = stmt.on_conflict_do_update(
            index_elements=["trade_id"],
            set_={"status": "open", "entry_price": trade.entry, "stop_loss": trade.stop, "take_profit": trade.take},
        )
        with self.client.session() as session:
            if session is None:
                return
            session.execute(stmt)

    def record_trade_close(self, trade: PaperTrade) -> None:
        if not self.client.enabled:
            return
        exit_price = trade.exit_price
        if exit_price is None:
            exit_price = trade.take if trade.exit_reason == "take profit" else trade.stop
        update = {
            "exit_price": exit_price,
            "exit_reason": trade.exit_reason,
            "exit_at": utc_now(),
            "pnl": trade.pnl,
            "status": "closed",
        }
        with self.client.session() as session:
            if session is None:
                return
            session.query(TradeRecord).filter(TradeRecord.trade_id == trade.trade_id).update(update)

    def record_manual_close(
        self,
        position_id: str,
        symbol: str,
        side: str,
        entry_price: float,
        exit_price: float,
        reason: str,
        rr: float,
    ) -> None:
        if not self.client.enabled:
            return
        payload = {
            "trade_id": position_id,
            "signal_id": None,
            "symbol": symbol,
            "side": side,
            "entry_price": entry_price,
            "stop_loss": 0.0,
            "take_profit": 0.0,
            "quantity": 0.0,
            "rr": rr,
            "opened_at": utc_now(),
            "exit_price": exit_price,
            "exit_reason": reason,
            "exit_at": utc_now(),
            "pnl": exit_price - entry_price if side == "open_long" else entry_price - exit_price,
            "status": "closed",
            "extra": {"source": "live"},
        }
        stmt = insert(TradeRecord).values(payload)
        stmt = stmt.on_conflict_do_update(
            index_elements=["trade_id"],
            set_={
                "exit_price": payload["exit_price"],
                "exit_reason": reason,
                "exit_at": utc_now(),
                "pnl": payload["pnl"],
                "status": "closed",
            },
        )
        with self.client.session() as session:
            if session is None:
                return
            session.execute(stmt)

    def upsert_position(self, position: PositionState, status: str = "open") -> None:
        if not self.client.enabled:
            return
        payload = {
            "position_id": position.id,
            "symbol": position.symbol,
            "side": position.side,
            "entry_price": position.entry,
            "stop_loss": position.stop,
            "take_profit": position.take,
            "rr": position.rr,
            "status": status,
            "details": {"trade_type": position.trade_type, "market_mode": position.market_mode},
            "updated_at": utc_now(),
        }
        stmt = insert(PositionRecord).values(payload)
        stmt = stmt.on_conflict_do_update(
            index_elements=["position_id"],
            set_={
                "stop_loss": position.stop,
                "take_profit": position.take,
                "rr": position.rr,
                "status": status,
                "updated_at": utc_now(),
            },
        )
        with self.client.session() as session:
            if session is None:
                return
            session.execute(stmt)
