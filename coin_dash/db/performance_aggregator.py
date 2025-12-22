from __future__ import annotations

from datetime import date

from ..exec.paper import Trade as PaperTrade
from .client import DatabaseClient
from .models import ModePerformance, PerformanceDaily, TradeTypePerformance
from .utils import utc_now


class PerformanceAggregator:
    def __init__(self, client: DatabaseClient) -> None:
        self.client = client

    def record_trade(self, trade: PaperTrade, trade_type: str, market_mode: str) -> None:
        if not self.client.enabled:
            return
        trade_date = utc_now().date()
        pnl_value = trade.pnl - float(getattr(trade, "open_fee", 0.0) or 0.0)
        win = 1 if pnl_value > 0 else 0
        profit = max(pnl_value, 0.0)
        loss = abs(min(pnl_value, 0.0))
        with self.client.session() as session:
            if session is None:
                return
            self._update_daily(session, trade_date, trade.symbol, pnl_value, win, profit, loss)
            self._update_mode(session, trade_date, trade.symbol, market_mode, pnl_value, win)
            self._update_trade_type(session, trade_date, trade.symbol, trade_type, pnl_value, win)

    def _update_daily(self, session, day: date, symbol: str, pnl: float, win: int, profit: float, loss: float) -> None:
        record = (
            session.query(PerformanceDaily)
            .filter(PerformanceDaily.date == day, PerformanceDaily.symbol == symbol)
            .one_or_none()
        )
        if record is None:
            extra = {"wins": win, "profit": profit, "loss": loss}
            win_rate = win
            profit_factor = (profit / loss) if loss else (float("inf") if profit > 0 else 0.0)
            record = PerformanceDaily(
                date=day,
                symbol=symbol,
                total_signals=1,
                win_rate=win_rate,
                profit_factor=profit_factor,
                pnl_total=pnl,
                extra=extra,
            )
            session.add(record)
            return
        extra = record.extra or {}
        extra["wins"] = extra.get("wins", 0) + win
        extra["profit"] = extra.get("profit", 0.0) + profit
        extra["loss"] = extra.get("loss", 0.0) + loss
        record.total_signals += 1
        record.pnl_total = (record.pnl_total or 0.0) + pnl
        record.win_rate = extra["wins"] / record.total_signals
        if extra["loss"]:
            record.profit_factor = extra["profit"] / extra["loss"]
        else:
            record.profit_factor = float("inf") if extra["profit"] > 0 else 0.0
        record.extra = extra

    def _update_mode(self, session, day: date, symbol: str, market_mode: str, pnl: float, win: int) -> None:
        record = (
            session.query(ModePerformance)
            .filter(
                ModePerformance.date == day,
                ModePerformance.symbol == symbol,
                ModePerformance.market_mode == market_mode,
            )
            .one_or_none()
        )
        if record is None:
            record = ModePerformance(
                date=day,
                symbol=symbol,
                market_mode=market_mode,
                signals_count=1,
                win_rate=win,
                profit_factor=1.0 if win else 0.0,
                pnl=pnl,
            )
            session.add(record)
            return
        prev = record.signals_count
        record.signals_count = prev + 1
        record.win_rate = ((record.win_rate * prev) + win) / record.signals_count
        record.pnl = (record.pnl or 0.0) + pnl

    def _update_trade_type(self, session, day: date, symbol: str, trade_type: str, pnl: float, win: int) -> None:
        record = (
            session.query(TradeTypePerformance)
            .filter(
                TradeTypePerformance.date == day,
                TradeTypePerformance.symbol == symbol,
                TradeTypePerformance.trade_type == trade_type,
            )
            .one_or_none()
        )
        if record is None:
            record = TradeTypePerformance(
                date=day,
                symbol=symbol,
                trade_type=trade_type,
                signals_count=1,
                win_rate=win,
                profit_factor=1.0 if win else 0.0,
                pnl=pnl,
            )
            session.add(record)
            return
        prev = record.signals_count
        record.signals_count = prev + 1
        record.win_rate = ((record.win_rate * prev) + win) / record.signals_count
        record.pnl = (record.pnl or 0.0) + pnl
