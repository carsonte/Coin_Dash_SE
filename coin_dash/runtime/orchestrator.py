from __future__ import annotations
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from ..config import AppConfig
from ..data.fetcher import LiveDataFetcher
from ..data.pipeline import DataPipeline
from ..exec.paper import PaperBroker
from ..features.multi_timeframe import compute_feature_context
from ..features.trend import classify_trade_type
from ..notify.lark import (
    send_signal_card,
    send_exit_card,
    send_mode_alert_card,
    send_anomaly_card,
    send_review_close_card,
    send_review_adjust_card,
    send_performance_card,
    send_watch_card,
    ModeSwitchAlertPayload,
    AnomalyAlertPayload,
    ReviewClosePayload,
    ReviewAdjustPayload,
    WatchPayload,
)
from ..ai.deepseek_adapter import DeepSeekClient
from ..ai.safe_fallback import apply_fallback
from ..verify.validator import ValidationContext, validate_signal
from ..risk.position import position_size
from ..signals.manager import SignalManager, SignalRecord
from ..state_manager import StateManager, PositionState
from ..notify.lark import ExitEventPayload
from ..backtest.engine import _make_decision
from ..db import DatabaseServices
from ..performance.safe_mode import DailySafeMode


STATE_PATH = Path(__file__).resolve().parents[1] / "state" / "state.json"


class LiveOrchestrator:
    def __init__(self, cfg: AppConfig, webhook: Optional[str] = None, db_services: Optional[DatabaseServices] = None) -> None:
        self.cfg = cfg
        self.fetcher = LiveDataFetcher(cfg)
        self.pipeline = DataPipeline(cfg)
        decision_logger = db_services.ai_logger if (db_services and db_services.ai_logger) else None
        self.deepseek = DeepSeekClient(cfg.deepseek, decision_logger=decision_logger)
        self.webhook = webhook or cfg.notifications.lark_webhook
        self.state = StateManager(STATE_PATH)
        self.signal_manager = SignalManager(cfg.signals)
        self.db = db_services
        self.safe_mode_threshold = 0
        self.safe_mode = None
        self.last_perf_push: Optional[datetime] = None
        self.paper_broker = PaperBroker(cfg.backtest.initial_equity, cfg.backtest.fee_rate)
        self.paper_positions: Dict[str, str] = {}
        self.last_open: Dict[str, datetime] = {}
        self.last_quotes: Dict[str, Dict[str, float]] = {}

    def run_cycle(self, symbols: List[str]) -> None:
        for symbol in symbols:
            quote, market_open = self._check_market_open(symbol)
            if not market_open:
                print(f"[info] {symbol} market closed / on break")
                continue
            try:
                df = self.fetcher.fetch_dataframe(symbol)
            except Exception as exc:
                self._send_anomaly(f"行情拉取失败：{exc}", impact=f"{symbol} 无法更新K线")
                continue
            if df.empty:
                continue
            try:
                self._process_symbol(symbol, df, quote)
            except Exception as exc:
                traceback.print_exc()
                self._send_anomaly(f"执行异常：{exc}", impact=f"{symbol} 处理失败")
        self._maybe_send_daily_summary()

    def run_heartbeat(self, symbols: List[str]) -> None:
        """轻量巡检心跳（中文）：
        - 频率：建议 5 分钟一次，对齐到 5 分钟边界。
        - 内容：仅更新市价/检测 TP/SL 触发；若短期价格偏离超过 ATR×阈值（signals.review_price_atr），触发临时 DeepSeek 复评。
        - 不做：新信号生成/模式告警/绩效汇总等重任务，减少无效调用与成本。
        """
        for symbol in symbols:
            quote, market_open = self._check_market_open(symbol)
            if not market_open:
                print(f"[info] {symbol} market closed / on break")
                continue
            try:
                df = self.fetcher.fetch_dataframe(symbol)
                if df.empty:
                    continue
                multi = self.pipeline.from_dataframe(symbol, df)
                latest_row = df.iloc[-1]
                feature_ctx = compute_feature_context(multi.frames)
                self._check_exit_events(symbol, latest_row)
                self._handle_reviews(symbol, feature_ctx, latest_row)
            except Exception as exc:
                traceback.print_exc()
                self._send_anomaly(f"心跳执行异常：{exc}", impact=f"{symbol} 心跳失败")

    def _process_symbol(self, symbol: str, df: pd.DataFrame, quote: Optional[Dict[str, float]] = None) -> None:
        multi = self.pipeline.from_dataframe(symbol, df)
        if self.db and self.db.kline_writer:
            self.db.kline_writer.record_frames(symbol, multi.frames)
        fast_df = multi.get(self.cfg.timeframes.filter_fast)
        slow_df = multi.get(self.cfg.timeframes.filter_slow)
        if fast_df.empty or slow_df.empty:
            return
        feature_ctx = compute_feature_context(multi.frames)
        self._handle_mode_alert(symbol, feature_ctx.market_mode, feature_ctx.environment)
        latest_row = df.iloc[-1]
        self._check_exit_events(symbol, latest_row)
        self._handle_reviews(symbol, feature_ctx, latest_row)

        decision = _make_decision(self.cfg, self.deepseek, symbol, feature_ctx)
        decision = apply_fallback(decision, payload=getattr(decision, "meta", {}))
        if decision.decision == "hold":
            if "fallback" in (decision.reason or ""):
                self.deepseek.record_market_event(
                    {
                        "type": "self_critique",
                        "symbol": symbol,
                        "summary": "上一轮决策因价格/结构异常被 fallback 拒绝，需加强价格关系检查。",
                    }
                )
            reason = decision.reason or "AI 选择观望"
            if getattr(decision, "meta", {}).get("adapter") == "prefilter":
                reason = f"GLM 预过滤：{reason}（未调用 DeepSeek）"
            watch_payload = WatchPayload(
                symbol=symbol,
                reason=reason,
                market_note=feature_ctx.reason,
                confidence=decision.confidence if getattr(decision, "confidence", None) is not None else None,
                next_check=datetime.now(timezone.utc) + timedelta(minutes=self.cfg.signals.review_interval_minutes),
            )
            send_watch_card(self.webhook, watch_payload)
            return
        trade_dir = 1 if decision.decision == "open_long" else -1
        trade_type = classify_trade_type(trade_dir, feature_ctx.trend)
        atr_key = f"atr_{self.cfg.timeframes.filter_fast}"
        atr_val = feature_ctx.features.get(atr_key, 0.0)
        vctx = ValidationContext(
            atr_value=atr_val,
            trade_type=trade_type,
            structure=feature_ctx.structure,
            risk_cfg=self.cfg.risk,
        )
        validation = validate_signal(decision, vctx)
        if not validation.ok:
            return
        now = datetime.now(timezone.utc)
        cooldown = timedelta(minutes=self.cfg.signals.cooldown_minutes or 0)
        if cooldown and decision.decision in ("open_long", "open_short"):
            key = f"{symbol}:{decision.decision}"
            last = self.last_open.get(key)
            if last and (now - last) < cooldown:
                return
        if quote is None:
            try:
                quote = self.fetcher.fetch_price(symbol)
            except Exception:
                quote = {}
        entry_price = decision.entry_price
        if quote:
            if decision.decision == "open_long":
                entry_price = float(quote.get("ask") or entry_price)
            else:
                entry_price = float(quote.get("bid") or entry_price)
        plan = position_size(self.cfg.backtest.initial_equity, decision, trade_type, self.cfg.risk)
        if plan.qty <= 0:
            return

        expires = now + timedelta(hours=self.cfg.signals.expiry_hours.get(feature_ctx.market_mode.name, 4))
        record = SignalRecord(
            symbol=symbol,
            decision=decision,
            trade_type=trade_type,
            market_mode=feature_ctx.market_mode,
            trend=feature_ctx.trend,
            structure=feature_ctx.structure,
            created_at=now,
            expires_at=expires,
            notes=[],
        )
        correlated = self.signal_manager.correlated_warning(symbol, decision.decision)
        self.signal_manager.add(record)
        signal_id = f"{record.symbol}-{int(record.created_at.timestamp())}"
        if self.db and self.db.trading:
            self.db.trading.record_signal(record, correlated, signal_id=signal_id)
        position = self.state.add_position(
            symbol,
            decision.decision,
            entry_price,
            decision.stop_loss,
            decision.take_profit,
            decision.risk_reward,
            trade_type,
            feature_ctx.market_mode.name,
            qty=plan.qty,
        )
        paper_trade = self.paper_broker.open(
            symbol=symbol,
            side=decision.decision,
            entry=entry_price,
            stop=decision.stop_loss,
            take=decision.take_profit,
            qty=plan.qty,
            ts=int(now.timestamp()),
            trade_type=trade_type,
            mode=feature_ctx.market_mode.name,
            rr=decision.risk_reward,
        )
        self.paper_positions[position.id] = paper_trade.trade_id
        if decision.decision in ("open_long", "open_short"):
            self.last_open[f"{symbol}:{decision.decision}"] = now
        now_ts = datetime.now(timezone.utc).isoformat()
        self.deepseek.record_open_pattern(
            symbol,
            {
                "type": "open",
                "symbol": symbol,
                "side": decision.decision,
                "price": decision.entry_price,
                "rr": decision.risk_reward,
                "pos": decision.position_size,
                "mode": feature_ctx.market_mode.name,
                "trend": feature_ctx.trend.grade,
                "time": now_ts,
                "reason": decision.reason,
            },
        )
        self.deepseek.record_position_event(
            position.id,
            symbol,
            {
                "type": "open",
                "symbol": symbol,
                "entry": decision.entry_price,
                "stop": decision.stop_loss,
                "take": decision.take_profit,
                "rr": decision.risk_reward,
                "time": now_ts,
                "reason": decision.reason,
            },
        )
        if self.db and self.db.trading:
            self.db.trading.upsert_position(position)
        send_signal_card(self.webhook, record, correlated)

    def _check_exit_events(self, symbol: str, candle: pd.Series) -> None:
        high = candle["high"]
        low = candle["low"]
        now = datetime.now(timezone.utc)
        for pos in self.state.list_positions(symbol):
            triggered = None
            reason = ""
            exit_type = ""
            if pos.side == "open_long":
                if low <= pos.stop:
                    triggered = pos.stop
                    reason = "止损触发"
                    exit_type = "stop_loss"
                elif high >= pos.take:
                    triggered = pos.take
                    reason = "止盈触发"
                    exit_type = "take_profit"
            else:
                if high >= pos.stop:
                    triggered = pos.stop
                    reason = "止损触发"
                    exit_type = "stop_loss"
                elif low <= pos.take:
                    triggered = pos.take
                    reason = "止盈触发"
                    exit_type = "take_profit"
            if triggered is not None:
                duration = self._format_duration(now - pos.created_at)
                payload = self.state.close_position(symbol, pos.id, triggered, exit_type, reason, duration)
                if payload:
                    send_exit_card(self.webhook, payload)
                    self._close_paper_trade(pos.id, triggered, exit_type, int(now.timestamp()))
                    now_ts = datetime.now(timezone.utc).isoformat()
                    self.deepseek.record_position_event(
                        pos.id,
                        symbol,
                        {
                            "type": "close",
                            "symbol": symbol,
                            "side": pos.side,
                            "exit_type": exit_type,
                            "exit_price": triggered,
                            "rr": pos.rr,
                            "time": now_ts,
                            "reason": reason,
                        },
                    )
                    self.deepseek.record_market_event(
                        {
                            "type": "self_critique",
                            "symbol": symbol,
                            "summary": f"关闭仓位 side={pos.side} exit={exit_type} rr={pos.rr}",
                        }
                    )
                    if self.db and self.db.trading:
                        self.db.trading.upsert_position(pos, status="closed")
                        self.db.trading.record_manual_close(
                            position_id=pos.id,
                            symbol=symbol,
                            side=pos.side,
                            entry_price=pos.entry,
                            exit_price=triggered,
                            reason=reason,
                            rr=pos.rr,
                        )
                    if exit_type == "stop_loss":
                        self._handle_safe_mode_stop(now)
                    self._publish_performance()

    def _handle_reviews(self, symbol: str, feature_ctx, candle: pd.Series) -> None:
        atr_key = f"atr_{self.cfg.timeframes.filter_fast}"
        atr_val = feature_ctx.features.get(atr_key, 0.0)
        price = candle["close"]
        interval = self.cfg.signals.review_interval_minutes
        atr_threshold = self.cfg.signals.review_price_atr
        for pos in self.state.positions_for_review(symbol, interval):
            # 中文：仅在“逆向波动”超过 ATR×阈值时触发临时复评
            if pos.side == "open_long":
                reverse_move = max(0.0, pos.entry - price)  # 多头的逆向为下跌
            else:
                reverse_move = max(0.0, price - pos.entry)  # 空头的逆向为上涨
            if atr_val and reverse_move >= atr_val * atr_threshold:
                self._trigger_review(symbol, pos, feature_ctx, price)
            elif (datetime.now(timezone.utc) - pos.last_review_at) >= timedelta(minutes=interval):
                # 常规复评（与执行主周期对齐，由调度保证 30m 边界会触发该路径）
                self._trigger_review(symbol, pos, feature_ctx, price)

    def _trigger_review(self, symbol: str, position: PositionState, feature_ctx, price: float) -> None:
        payload = {
            "position": {
                "symbol": symbol,
                "side": position.side,
                "entry": position.entry,
                "stop": position.stop,
                "take": position.take,
                "rr": position.rr,
            },
            "market": {
                "mode": feature_ctx.market_mode.name,
                "trend_score": feature_ctx.trend.score,
                "trend_grade": feature_ctx.trend.grade,
                "price": price,
            },
            "recent_ohlc": feature_ctx.recent_ohlc,
            "environment": feature_ctx.environment,
            "global_temperature": feature_ctx.global_temperature,
        }
        try:
            decision = self.deepseek.review_position(symbol, position.id, payload)
        except Exception:
            decision = None
        if not decision or decision.action == "hold":
            self.state.update_position_levels(symbol, position.id)
            return
        if decision.action == "close":
            duration = self._format_duration(datetime.now(timezone.utc) - position.created_at)
            self.state.close_position(symbol, position.id, price, "review_close", decision.reason, duration)
            self._close_paper_trade(position.id, price, "review_close", int(datetime.now(timezone.utc).timestamp()))
            if self.db and self.db.trading:
                self.db.trading.upsert_position(position, status="closed")
                self.db.trading.record_manual_close(
                    position_id=position.id,
                    symbol=symbol,
                    side=position.side,
                    entry_price=position.entry,
                    exit_price=price,
                    reason="review_close",
                    rr=position.rr,
                )
            review_payload = ReviewClosePayload(
                symbol=symbol,
                side="多头" if position.side == "open_long" else "空头",
                entry_price=position.entry,
                close_price=price,
                pnl=(price - position.entry) if position.side == "open_long" else (position.entry - price),
                rr=position.rr,
                reason=decision.reason,
                context=decision.context_summary or "复评触发",
                confidence=getattr(decision, "confidence", 80.0),
                action="提前平仓",
            )
            send_review_close_card(self.webhook, review_payload)
            self._publish_performance()
            self.deepseek.record_market_event(
                {
                    "type": "self_critique",
                    "symbol": symbol,
                    "summary": f"复评关闭，趋势={feature_ctx.trend.grade} score={feature_ctx.trend.score:.1f} 模式={feature_ctx.market_mode.name}",
                }
            )
        elif decision.action == "adjust":
            old_stop, old_take, old_rr = position.stop, position.take, position.rr
            new_stop = decision.new_stop_loss if decision.new_stop_loss is not None else old_stop
            new_take = decision.new_take_profit if decision.new_take_profit is not None else old_take
            # 禁止止损放宽
            if position.side == "open_long":
                new_stop = max(new_stop, old_stop)
            else:
                new_stop = min(new_stop, old_stop)

            def _calc_rr(entry: float, stop: float, take: float, side: str) -> float:
                stop_dist = entry - stop if side == "open_long" else stop - entry
                take_dist = take - entry if side == "open_long" else entry - take
                if stop_dist <= 0 or take_dist <= 0:
                    return old_rr
                return take_dist / stop_dist

            computed_rr = _calc_rr(position.entry, new_stop, new_take, position.side)
            new_rr = decision.new_rr if decision.new_rr is not None else computed_rr
            if new_rr <= 0:
                new_rr = computed_rr
            has_change = (new_stop != old_stop) or (new_take != old_take) or (new_rr != old_rr)
            if not has_change:
                # 仅刷新复评时间，避免无效卡片
                self.state.update_position_levels(symbol, position.id)
                return
            updated = self.state.update_position_levels(symbol, position.id, new_stop, new_take, new_rr)
            if updated:
                self._adjust_paper_trade(position.id, new_stop, new_take, "review_adjust")
                if self.db and self.db.trading:
                    self.db.trading.upsert_position(updated)
                review_payload = ReviewAdjustPayload(
                    symbol=symbol,
                    side="多头" if position.side == "open_long" else "空头",
                    entry_price=position.entry,
                    old_stop=old_stop,
                    new_stop=new_stop,
                    old_take=old_take,
                    new_take=new_take,
                    old_rr=old_rr,
                    new_rr=new_rr,
                    reason=decision.reason,
                    market_update="复评调整",
                    next_review=datetime.now(timezone.utc) + timedelta(minutes=self.cfg.signals.review_interval_minutes),
                )
                send_review_adjust_card(self.webhook, review_payload)

    def _check_market_open(self, symbol: str) -> tuple[Dict[str, float], bool]:
        """
        Detect simple market break/closed periods to avoid wasting API/DeepSeek calls.
        - BTCUSDm 视为 24h 开市。
        - XAUUSDm 若 bid/ask 缺失或 tick 时间超过阈值（默认 120s）判定休盘。
        """
        upper = symbol.upper()
        if not upper.startswith("XAU"):
            return {}, True
        quote: Dict[str, float] = {}
        try:
            quote = self.fetcher.fetch_price(symbol) or {}
            self.last_quotes[symbol] = quote
        except Exception:
            return {}, False
        bid = quote.get("bid")
        ask = quote.get("ask")
        ts = int(quote.get("time") or 0)
        if bid is None or ask is None:
            return quote, False
        now_ts = int(datetime.now(timezone.utc).timestamp())
        if ts and (now_ts - ts) > 180:
            return quote, False
        return quote, True

    def _handle_mode_alert(self, symbol: str, mode, environment=None) -> None:
        last_mode = self.state.last_mode(symbol)
        if last_mode != mode.name and mode.confidence >= 0.6:
            payload = ModeSwitchAlertPayload(
                symbol=symbol,
                from_mode=last_mode or "未知",
                to_mode=mode.name,
                confidence=mode.confidence * 100,
                affected_symbols=[symbol],
                risk_level="中",
                suggestion="谨慎开新仓",
                indicators=", ".join(f"{k}:{v:.2f}" for k, v in mode.reasons.items()),
            )
            send_mode_alert_card(self.webhook, payload)
            self.state.update_mode(symbol, mode.name)
            self.deepseek.record_market_event(
                {
                    "type": "regime_change",
                    "symbol": symbol,
                    "from": last_mode or "none",
                    "to": mode.name,
                    "environment": environment,
                }
            )

    def _send_anomaly(self, message: str, impact: str) -> None:
        payload = AnomalyAlertPayload(
            event_type=message,
            severity="高",
            occurred_at=datetime.now(timezone.utc),
            impact=impact,
            status="降级运行",
            actions="已记录日志，等待人工干预",
        )
        send_anomaly_card(self.webhook, payload)
        if self.db and self.db.system_monitor:
            self.db.system_monitor.record_event("anomaly", "high", message, {"impact": impact})

    def _persist_safe_mode(self) -> None:
        if self.safe_mode:
            self.state.save_safe_mode_state(self.safe_mode.to_dict())

    def _handle_safe_mode_stop(self, now: datetime) -> None:
        if not self.safe_mode:
            return
        activated = self.safe_mode.record_stop_loss(now)
        self._persist_safe_mode()
        if activated:
            self._send_anomaly("安全模式触发：连续止损超限", "暂停开仓等待人工确认")

    def _build_performance_snapshot(self) -> tuple[Dict[str, float], Dict, Dict, Dict]:
        stats = self.state.performance_stats()
        modes = self.state.grouped_stats("market_mode")
        trade_types = self.state.grouped_stats("trade_type")
        symbols = self.state.grouped_stats("symbol")
        return stats, modes, trade_types, symbols

    def _publish_performance(self, force: bool = False) -> Dict[str, float]:
        stats, modes, trade_types, symbols = self._build_performance_snapshot()
        should_send = bool(self.webhook)
        if should_send:
            if not force:
                if not self.cfg.performance.instant_push:
                    should_send = False
                elif self.last_perf_push and (
                    datetime.now(timezone.utc) - self.last_perf_push
                ) < timedelta(minutes=self.cfg.performance.instant_cooldown_minutes):
                    should_send = False
            if should_send:
                send_performance_card(self.webhook, stats, modes, trade_types, symbols)
                self.last_perf_push = datetime.now(timezone.utc)
        return stats

    def _maybe_send_daily_summary(self) -> None:
        now = datetime.now(timezone.utc)
        if not self.state.should_send_daily_summary(now, self.cfg.performance.report_hour_utc8):
            return
        stats = self._publish_performance(force=True)
        self._adjust_thresholds(stats)

    def _adjust_thresholds(self, stats: Dict[str, float]) -> None:
        # AI 全权决策，关闭基于表现对人工阈值的自动微调。
        return

    @staticmethod
    def _format_duration(delta: timedelta) -> str:
        total_minutes = int(delta.total_seconds() // 60)
        hours, minutes = divmod(total_minutes, 60)
        parts = []
        if hours:
            parts.append(f"{hours}h")
        parts.append(f"{minutes}m")
        return " ".join(parts)

    def _close_paper_trade(self, position_id: str, price: float, reason: str, ts: int) -> None:
        trade_id = self.paper_positions.pop(position_id, None)
        if not trade_id:
            return
        self.paper_broker.close(trade_id, price, ts, reason)

    def _adjust_paper_trade(self, position_id: str, new_stop: float, new_take: float, note: str) -> None:
        trade_id = self.paper_positions.get(position_id)
        if not trade_id:
            return
        self.paper_broker.adjust(trade_id, new_stop=new_stop, new_take=new_take, note=note)
