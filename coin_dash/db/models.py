from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Date, DateTime, Float, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class KlineData(Base):
    __tablename__ = "kline_data"
    __table_args__ = (UniqueConstraint("symbol", "interval", "open_time", name="uq_kline_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    interval: Mapped[str] = mapped_column(String(10))
    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    close_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    open_price: Mapped[float] = mapped_column(Float)
    high_price: Mapped[float] = mapped_column(Float)
    low_price: Mapped[float] = mapped_column(Float)
    close_price: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(32), default="binance")
    indicators: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SignalEntry(Base):
    __tablename__ = "signals"
    __table_args__ = (
        UniqueConstraint("signal_id", name="uq_signal_id"),
        Index("idx_signals_symbol_created_at", "symbol", "created_at"),
        Index("idx_signals_run_id_created_at", "run_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    signal_id: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(20))
    direction: Mapped[str] = mapped_column(String(16))
    entry_price: Mapped[float] = mapped_column(Float)
    stop_loss: Mapped[float] = mapped_column(Float)
    take_profit: Mapped[float] = mapped_column(Float)
    risk_reward: Mapped[float] = mapped_column(Float)
    trade_type: Mapped[str] = mapped_column(String(20))
    market_mode: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="active")
    correlated: Mapped[bool] = mapped_column(default=False)
    notes: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    context: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TradeRecord(Base):
    __tablename__ = "trades"
    __table_args__ = (
        UniqueConstraint("trade_id", name="uq_trade_id"),
        Index("idx_trades_symbol_opened_at", "symbol", "opened_at"),
        Index("idx_trades_run_id_opened_at", "run_id", "opened_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    trade_id: Mapped[str] = mapped_column(String(64), index=True)
    signal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    symbol: Mapped[str] = mapped_column(String(20))
    side: Mapped[str] = mapped_column(String(16))
    entry_price: Mapped[float] = mapped_column(Float)
    stop_loss: Mapped[float] = mapped_column(Float)
    take_profit: Mapped[float] = mapped_column(Float)
    quantity: Mapped[float] = mapped_column(Float)
    rr: Mapped[float] = mapped_column(Float)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    exit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="open")
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PositionRecord(Base):
    __tablename__ = "positions"
    __table_args__ = (Index("idx_positions_run_id_created_at", "run_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    position_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    symbol: Mapped[str] = mapped_column(String(20))
    side: Mapped[str] = mapped_column(String(16))
    entry_price: Mapped[float] = mapped_column(Float)
    stop_loss: Mapped[float] = mapped_column(Float)
    take_profit: Mapped[float] = mapped_column(Float)
    rr: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), default="open")
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AIDecisionLog(Base):
    __tablename__ = "ai_decisions"
    __table_args__ = (
        Index("idx_ai_decisions_symbol_created_at", "symbol", "created_at"),
        Index("idx_ai_decisions_run_id_created_at", "run_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    committee_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(32), nullable=True)
    weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_final: Mapped[bool] = mapped_column(default=False)
    decision_type: Mapped[str] = mapped_column(String(20))
    symbol: Mapped[str] = mapped_column(String(20))
    payload: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)
    tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConversationLog(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    context_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    messages: Mapped[list | None] = mapped_column(JSON, nullable=True)
    tokens_accumulated: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PerformanceDaily(Base):
    __tablename__ = "performance_daily"
    __table_args__ = (UniqueConstraint("date", "symbol", name="uq_perf_daily"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[datetime] = mapped_column(Date)
    symbol: Mapped[str] = mapped_column(String(20))
    total_signals: Mapped[int] = mapped_column(Integer)
    win_rate: Mapped[float] = mapped_column(Float)
    profit_factor: Mapped[float] = mapped_column(Float)
    pnl_total: Mapped[float] = mapped_column(Float)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class ModePerformance(Base):
    __tablename__ = "mode_performance"
    __table_args__ = (UniqueConstraint("date", "symbol", "market_mode", name="uq_mode_perf"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[datetime] = mapped_column(Date)
    symbol: Mapped[str] = mapped_column(String(20))
    market_mode: Mapped[str] = mapped_column(String(20))
    signals_count: Mapped[int] = mapped_column(Integer)
    win_rate: Mapped[float] = mapped_column(Float)
    profit_factor: Mapped[float] = mapped_column(Float)
    pnl: Mapped[float] = mapped_column(Float)


class TradeTypePerformance(Base):
    __tablename__ = "trade_type_performance"
    __table_args__ = (UniqueConstraint("date", "symbol", "trade_type", name="uq_trade_type_perf"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[datetime] = mapped_column(Date)
    symbol: Mapped[str] = mapped_column(String(20))
    trade_type: Mapped[str] = mapped_column(String(20))
    signals_count: Mapped[int] = mapped_column(Integer)
    win_rate: Mapped[float] = mapped_column(Float)
    profit_factor: Mapped[float] = mapped_column(Float)
    pnl: Mapped[float] = mapped_column(Float)


class SystemEvent(Base):
    __tablename__ = "system_events"
    __table_args__ = (Index("idx_system_events_run_id_created_at", "run_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    event_type: Mapped[str] = mapped_column(String(50))
    severity: Mapped[str] = mapped_column(String(10))
    description: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CostMonitoring(Base):
    __tablename__ = "cost_monitoring"
    __table_args__ = (UniqueConstraint("date", "service", name="uq_cost_service"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[datetime] = mapped_column(Date)
    service: Mapped[str] = mapped_column(String(32))
    tokens_used: Mapped[int] = mapped_column(Integer)
    cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    budget_status: Mapped[str] = mapped_column(String(16))
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
