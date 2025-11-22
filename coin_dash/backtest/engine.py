from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Set

import pandas as pd

from ..config import AppConfig
from ..data.pipeline import DataPipeline
from ..features.multi_timeframe import compute_feature_context
from ..features.trend import classify_trade_type
from ..ai.mock_adapter import decide_mock
from ..ai.deepseek_adapter import DeepSeekClient
from ..ai.models import Decision
from ..ai.safe_fallback import apply_fallback
from ..verify.validator import validate_signal, ValidationContext
from ..signals.manager import SignalManager, SignalRecord
from ..risk.position import position_size
from ..exec.paper import PaperBroker
from ..performance.tracker import PerformanceTracker
from ..performance.safe_mode import DailySafeMode
from ..notify.lark import send_signal_card, send_performance_card
from ..db import DatabaseServices


@dataclass
class BacktestReport:
    summary: Dict
    logs: List[str]
    modes: Dict[str, Dict[str, float]]
    trade_types: Dict[str, Dict[str, float]]


def _signal_storage_id(record: SignalRecord) -> str:
    return f"{record.symbol}-{int(record.created_at.timestamp())}"


def run_backtest(
    df: pd.DataFrame,
    symbol: str,
    cfg: AppConfig,
    use_deepseek: bool = True,
    db_services: Optional[DatabaseServices] = None,
) -> BacktestReport:
    df = df.sort_index()
    pipeline = DataPipeline(cfg)
    signal_mgr = SignalManager(cfg.signals)
    broker = PaperBroker(cfg.backtest.initial_equity, cfg.backtest.fee_rate)
    tracker = PerformanceTracker()
    decision_logger = db_services.ai_logger if (db_services and db_services.ai_logger) else None
    deepseek_client = DeepSeekClient(cfg.deepseek, decision_logger=decision_logger) if use_deepseek else None
    safe_mode_cfg = cfg.performance.safe_mode or {}
    safe_mode_threshold = safe_mode_cfg.get("consecutive_stop_losses", 0)
    safe_mode = DailySafeMode(safe_mode_threshold)

    logs: List[str] = []
    recorded_closes: Set[str] = set()

    base_minutes = _infer_minutes(df)
    if base_minutes == 0:
        raise ValueError("Cannot infer base timeframe from data")

    webhook = os.getenv("LARK_WEBHOOK") or cfg.notifications.lark_webhook

    for idx in range(len(df)):
        window = df.iloc[: idx + 1]
        if len(window) < 120:
            continue
        ts = window.index[-1]
        price_now = float(window["close"].iloc[-1])
        broker.step_markout(price_now, int(ts.timestamp()))
        safe_mode_triggered = _record_closed_trades(broker, tracker, recorded_closes, safe_mode, db_services)
        if safe_mode_triggered:
            logs.append(f"{ts} enter safe mode after cumulative stop losses")

        multi = pipeline.from_dataframe(symbol, window)
        if db_services and db_services.kline_writer:
            db_services.kline_writer.record_frames(symbol, multi.frames)
        fast_df = multi.get(cfg.timeframes.filter_fast)
        slow_df = multi.get(cfg.timeframes.filter_slow)
        if fast_df.empty or slow_df.empty:
            continue

        now_dt = datetime.fromtimestamp(ts.timestamp(), timezone.utc)
        feature_ctx = compute_feature_context(multi.frames)
        decision = _make_decision(cfg, deepseek_client, symbol, feature_ctx)
        decision = apply_fallback(decision, payload=getattr(decision, "meta", {}))
        if decision.decision == "hold":
            logs.append(f"{ts} hold reason={decision.reason}")
            continue

        trade_dir = 1 if decision.decision == "open_long" else -1
        trade_type = classify_trade_type(trade_dir, feature_ctx.trend)
        atr_key = f"atr_{cfg.timeframes.filter_fast}"
        atr_val = feature_ctx.features.get(atr_key, 0.0)
        vctx = ValidationContext(
            atr_value=atr_val,
            trade_type=trade_type,
            structure=feature_ctx.structure,
            risk_cfg=cfg.risk,
        )
        validation = validate_signal(decision, vctx)
        if not validation.ok:
            logs.append(f"{ts} reject {symbol} {decision.decision} reason={validation.reason}")
            continue

        plan = position_size(broker.equity, decision, trade_type, cfg.risk)
        if plan.qty <= 0:
            logs.append(f"{ts} plan qty=0")
            continue

        expiry_hours = cfg.signals.expiry_hours.get(feature_ctx.market_mode.name, 4)
        record = SignalRecord(
            symbol=symbol,
            decision=decision,
            trade_type=trade_type,
            market_mode=feature_ctx.market_mode,
            trend=feature_ctx.trend,
            structure=feature_ctx.structure,
            created_at=now_dt,
            expires_at=now_dt + timedelta(hours=expiry_hours),
            notes=[feature_ctx.reason],
        )
        correlated = signal_mgr.correlated_warning(symbol, decision.decision)
        if correlated:
            record.notes.append("high correlation warning")
        signal_mgr.add(record)
        if db_services and db_services.trading:
            db_services.trading.record_signal(record, correlated)
        send_signal_card(webhook, record, correlated)
        if deepseek_client:
            deepseek_client.record_open_pattern(
                symbol,
                f"{decision.decision} mode={feature_ctx.market_mode.name} trend={feature_ctx.trend.grade} rr={decision.risk_reward:.2f} pos={decision.position_size}",
            )

        opened_trade = broker.open(
            symbol=symbol,
            side=decision.decision,
            entry=decision.entry_price,
            stop=decision.stop_loss,
            take=decision.take_profit,
            qty=plan.qty,
            ts=int(ts.timestamp()),
            trade_type=trade_type,
            mode=feature_ctx.market_mode.name,
            rr=decision.risk_reward,
        )
        if db_services and db_services.trading:
            db_services.trading.record_trade_open(opened_trade, signal_id=_signal_storage_id(record))
        logs.append(
            f"{ts} {symbol} {decision.decision} rr={decision.risk_reward:.2f} type={trade_type} mode={feature_ctx.market_mode.name}"
        )

    safe_mode_triggered = _record_closed_trades(broker, tracker, recorded_closes, safe_mode, db_services)
    if safe_mode_triggered:
        logs.append("safe mode triggered during final reconciliation")
    summary = broker.summary()
    perf_report = tracker.report()
    send_performance_card(
        webhook,
        summary,
        perf_report["modes"],
        perf_report["types"],
        perf_report.get("symbols", {}),
    )
    return BacktestReport(summary=summary, logs=logs, modes=perf_report["modes"], trade_types=perf_report["types"])


def _record_closed_trades(
    broker: PaperBroker,
    tracker: PerformanceTracker,
    recorded: Set[str],
    safe_mode: Optional[DailySafeMode] = None,
    db_services: Optional[DatabaseServices] = None,
) -> bool:
    triggered = False
    for trade in broker.trades:
        if trade.closed_at is not None and trade.trade_id not in recorded:
            tracker.record(trade, trade.trade_type, trade.rr, trade.market_mode)
            recorded.add(trade.trade_id)
            if db_services:
                if db_services.trading:
                    db_services.trading.record_trade_close(trade)
                if db_services.performance:
                    db_services.performance.record_trade(trade, trade.trade_type, trade.market_mode)
            if safe_mode and trade.exit_reason == "stop loss":
                when = datetime.fromtimestamp(trade.closed_at, timezone.utc)
                if safe_mode.record_stop_loss(when):
                    triggered = True
    return triggered


def _infer_minutes(df: pd.DataFrame) -> int:
    if len(df.index) < 2:
        return 0
    delta = df.index[1] - df.index[0]
    return int(delta.total_seconds() // 60)


def _make_decision(cfg: AppConfig, client: Optional[DeepSeekClient], symbol: str, feature_ctx) -> Decision:
    def _hold(reason: str) -> Decision:
        price = feature_ctx.features.get("price_30m")
        if price is None:
            # Fallback到任一周期的价格，避免返回 0
            price = feature_ctx.features.get("price_1h", 0.0)
        return Decision(
            decision="hold",
            entry_price=price,
            stop_loss=price,
            take_profit=price,
            risk_reward=0.0,
            confidence=0.0,
            reason=reason,
            meta={"adapter": "deepseek", "status": reason},
        )

    hints = _risk_quality_hint(feature_ctx)
    payload = {
        "market_mode": feature_ctx.market_mode.name,
        "mode_confidence": feature_ctx.market_mode.confidence,
        "trend_score": feature_ctx.trend.score,
        "trend_grade": feature_ctx.trend.grade,
        "features": feature_ctx.features,
        "environment": feature_ctx.environment,
        "global_temperature": feature_ctx.global_temperature,
        "cycle_weights": feature_ctx.market_mode.cycle_weights,
        "recent_ohlc": feature_ctx.recent_ohlc,
        "risk_score_hint": hints["risk"],
        "quality_score_hint": hints["quality"],
        "structure": {
            name: {
                "support": lvl.support,
                "resistance": lvl.resistance,
            }
            for name, lvl in feature_ctx.structure.levels.items()
        },
    }
    if client is None or not client.enabled():
        return _hold("deepseek_disabled")
    try:
        decision = client.decide_trade(symbol, payload)
        return decision
    except Exception:
        return _hold("deepseek_unavailable")


def _risk_quality_hint(feature_ctx) -> Dict[str, float]:
    risk = 0.0
    quality = 0.0
    for tf in ["30m", "1h", "4h"]:
        if feature_ctx.features.get(f"breakout_confirmed_{tf}", 0):
            quality += 15
        if feature_ctx.features.get(f"momentum_decay_{tf}", 0):
            quality += 10
        if feature_ctx.features.get(f"range_midzone_{tf}", 0):
            risk += 20
    mode = getattr(feature_ctx.market_mode, "name", "")
    if mode in ("chaotic", "ranging"):
        risk += 20
    return {"risk": min(risk, 100.0), "quality": min(quality, 100.0)}
