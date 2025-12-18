from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Trade:
    trade_id: str
    symbol: str
    side: str
    entry: float
    stop: float
    take: float
    qty: float
    opened_at: int
    trade_type: str
    market_mode: str
    rr: float
    closed_at: Optional[int] = None
    pnl: float = 0.0
    history: list[str] = field(default_factory=list)
    exit_reason: Optional[str] = None
    exit_price: Optional[float] = None

    def record(self, message: str) -> None:
        self.history.append(message)


class PaperBroker:
    def __init__(self, equity: float, fee_rate: float = 0.0004) -> None:
        self.equity = equity
        self.fee_rate = fee_rate
        self.trades: list[Trade] = []
        self.counter = 0

    def has_open(self, symbol: str, max_open: int | None = None) -> bool:
        """
        Return True if there's an open trade for the symbol.
        - max_open is None: any existing open trade blocks.
        - max_open > 0: block only when open trades for symbol reach the limit.
        """
        opens = [t for t in self.trades if t.symbol == symbol and t.closed_at is None]
        if max_open is None:
            return bool(opens)
        return len(opens) >= max_open

    def open(self, symbol: str, side: str, entry: float, stop: float, take: float, qty: float, ts: int, trade_type: str, mode: str, rr: float) -> Trade:
        fee = entry * qty * self.fee_rate
        self.equity -= fee
        self.counter += 1
        trade_id = f"T{self.counter:05d}"
        t = Trade(trade_id=trade_id, symbol=symbol, side=side, entry=entry, stop=stop, take=take, qty=qty, opened_at=ts, trade_type=trade_type, market_mode=mode, rr=rr)
        self.trades.append(t)
        t.record(f"open {side} qty={qty:.4f} entry={entry:.2f}")
        return t

    def adjust(self, trade_id: str, new_stop: Optional[float] = None, new_take: Optional[float] = None, note: str = "") -> None:
        trade = next((t for t in self.trades if t.trade_id == trade_id), None)
        if trade is None or trade.closed_at is not None:
            return
        if new_stop is not None:
            if trade.side == "open_long" and new_stop > trade.stop:
                trade.stop = new_stop
            elif trade.side == "open_short" and new_stop < trade.stop:
                trade.stop = new_stop
        if new_take is not None:
            trade.take = new_take
        if note:
            trade.record(note)

    def step_markout(self, price: float, ts: int):
        for t in self.trades:
            if t.closed_at is not None:
                continue
            hit_take = price >= t.take if t.side == "open_long" else price <= t.take
            hit_stop = price <= t.stop if t.side == "open_long" else price >= t.stop
            exit_price = None
            reason = None
            if hit_take:
                exit_price = t.take
                reason = "take profit"
            elif hit_stop:
                exit_price = t.stop
                reason = "stop loss"
            if exit_price is not None:
                fee = exit_price * t.qty * self.fee_rate
                pnl = (exit_price - t.entry) * t.qty if t.side == "open_long" else (t.entry - exit_price) * t.qty
                pnl -= fee
                t.pnl = pnl
                self.equity += pnl
                t.closed_at = ts
                t.exit_reason = reason
                t.exit_price = exit_price
                t.record(f"close {reason} price={exit_price:.2f} pnl={pnl:.2f}")

    def close(self, trade_id: str, price: float, ts: int, reason: str) -> Optional[Trade]:
        """
        Close a trade manually (e.g., when live logic triggers a close) and return the trade.
        """
        trade = next((t for t in self.trades if t.trade_id == trade_id), None)
        if trade is None or trade.closed_at is not None:
            return None
        fee = price * trade.qty * self.fee_rate
        pnl = (price - trade.entry) * trade.qty if trade.side == "open_long" else (trade.entry - price) * trade.qty
        pnl -= fee
        trade.pnl = pnl
        self.equity += pnl
        trade.closed_at = ts
        trade.exit_reason = reason
        trade.exit_price = price
        trade.record(f"close {reason} price={price:.2f} pnl={pnl:.2f}")
        return trade

    def summary(self) -> dict:
        closed = [t for t in self.trades if t.closed_at is not None]
        wins = [t for t in closed if t.pnl > 0]
        losses = [t for t in closed if t.pnl < 0]
        total_profit = sum(t.pnl for t in wins)
        total_loss = abs(sum(t.pnl for t in losses))
        profit_factor = (total_profit / total_loss) if total_loss else float("inf") if total_profit else 0.0
        return {
            "equity": self.equity,
            "trades": len(self.trades),
            "closed": len(closed),
            "wins": len(wins),
            "win_rate": (len(wins) / len(closed)) if closed else 0.0,
            "pnl_total": sum(t.pnl for t in closed),
            "profit_factor": profit_factor,
        }
