from __future__ import annotations
import logging
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
from ..ai.filter_adapter import GlmFilterResult, PreFilterClient
from ..ai.safe_fallback import apply_fallback
from ..verify.validator import ValidationContext, validate_signal
from ..risk.position import position_size
from ..signals.manager import SignalManager, SignalRecord
from ..state_manager import StateManager, PositionState
from ..notify.lark import ExitEventPayload
from ..backtest.engine import _make_decision
from ..db import DatabaseServices
from ..performance.safe_mode import DailySafeMode
from ..events.triggers import detect_market_events


STATE_PATH = Path(__file__).resolve().parents[1] / "state" / "state.json"
LOGGER = logging.getLogger(__name__)


class LiveOrchestrator:
    def __init__(
        self, cfg: AppConfig, webhook: Optional[str] = None, db_services: Optional[DatabaseServices] = None, run_id: Optional[str] = None
    ) -> None:
        self.cfg = cfg
        self.fetcher = LiveDataFetcher(cfg)
        self.pipeline = DataPipeline(cfg)
        self.base_minutes = min(tf.minutes for tf in cfg.timeframes.defs.values())
        self.max_minutes = max(tf.minutes for tf in cfg.timeframes.defs.values())
        self.required_base_bars = int((self.max_minutes / self.base_minutes) * 20) if self.base_minutes else 0
        decision_logger = db_services.ai_logger if (db_services and db_services.ai_logger) else None
        self.deepseek = DeepSeekClient(
            cfg.deepseek,
            glm_cfg=cfg.qwen_filter,
            glm_client_cfg=cfg.llm.qwen,
            glm_fallback_cfg=cfg.llm.glm_fallback,
            decision_logger=decision_logger,
        )
        self.webhook = webhook or cfg.notifications.lark_webhook
        self.state = StateManager(STATE_PATH, base_equity=cfg.backtest.initial_equity)
        self.signal_manager = SignalManager(cfg.signals)
        self.db = db_services
        self.run_id = run_id or (db_services.run_id if db_services else None)
        self.event_triggers_enabled = bool(getattr(cfg, "event_triggers", None) and cfg.event_triggers.enabled)
        self.glm_filter_enabled = bool(getattr(cfg, "glm_filter", None) and cfg.qwen_filter.enabled)
        self.glm_prefilter = (
            PreFilterClient(cfg.qwen_filter, glm_client_cfg=cfg.llm.qwen, glm_fallback_cfg=cfg.llm.glm_fallback)
            if self.glm_filter_enabled
            else None
        )
        self.safe_mode_enabled = bool(getattr(cfg.performance, "safe_mode_enabled", False))
        safe_cfg = getattr(cfg.performance, "safe_mode", {}) or {}
        self.safe_mode_threshold = int(safe_cfg.get("consecutive_stop_losses", 0))
        if self.safe_mode_enabled and self.safe_mode_threshold > 0:
            saved_state = self.state.get_safe_mode_state()
            self.safe_mode = DailySafeMode.from_dict(self.safe_mode_threshold, saved_state)
        else:
            self.safe_mode = None
        self.last_perf_push: Optional[datetime] = None
        self.paper_broker = PaperBroker(cfg.backtest.initial_equity, cfg.backtest.fee_rate)
        self.paper_positions: Dict[str, str] = {}
        self.last_open: Dict[str, datetime] = {}
        self.last_quotes: Dict[str, Dict[str, float]] = {}
        self.primary_quotes: Dict[str, Dict[str, float]] = {}
        self.last_data_alert: Dict[str, datetime] = {}
        self.active_source: str = "primary"
        self.source_fail: Dict[str, int] = {"primary": 0, "backup": 0}
        self.source_recover_ok: int = 0
        self.primary_recheck_needed: bool = False
        self.source_fail_threshold: int = 3
        self.source_recover_threshold: int = 5
        self.has_backup = bool(getattr(self.fetcher, "has_backup", False))
        policy = getattr(cfg, "backup_policy", None) or {}
        self.allow_backup_open: bool = bool(getattr(policy, "allow_backup_open", False))
        self.backup_deviation_pct: float = float(getattr(policy, "deviation_pct", 0.0025))
        self.source_tags = {"primary": "MT5", "backup": "CCXT-Binance"}

    def run_cycle(self, symbols: List[str]) -> None:
        primary_probe_done = False
        for symbol in symbols:
            use_backup = self.active_source == "backup"
            quote, market_open = self._check_market_open(symbol, use_backup=use_backup)
            if not market_open:
                print(f"[info] {symbol} market closed / on break")
                continue
            try:
                df = self.fetcher.fetch_dataframe(symbol, use_backup=use_backup)
            except Exception as exc:
                self._send_anomaly(f"行情拉取失败：{exc}", impact=f"{symbol} 无法更新K线")
                self._record_source_failure(use_backup)
                continue
            if df.empty:
                self._alert_data_issue(symbol, "empty_frame", "行情返回为空，已跳过本轮")
                self._record_source_failure(use_backup)
                continue
            ok, reason = self._check_data_health(df)
            if not ok:
                self._alert_data_issue(symbol, "stale_or_short", reason)
                self._record_source_failure(use_backup)
                continue
            if not use_backup:
                # 记录主源报价基准
                try:
                    primary_quote = self.fetcher.fetch_price(symbol, use_backup=False) or {}
                    if primary_quote:
                        self.primary_quotes[symbol] = primary_quote
                except Exception:
                    pass
            price_ok, deviation = self._check_price_deviation(symbol, quote, use_backup)
            if use_backup and not price_ok:
                self._alert_data_issue(
                    symbol,
                    "price_deviation",
                    f"备源价差 {deviation*100:.2f}% 超阈值 {self.backup_deviation_pct*100:.2f}%，暂停新开仓/自动平仓，仅提醒",
                )
            self._record_source_success(use_backup)
            if use_backup and self.has_backup and not primary_probe_done:
                primary_probe_done = True
                if self._probe_primary(symbol):
                    self.source_recover_ok += 1
                    if self.source_recover_ok >= self.source_recover_threshold:
                        self.active_source = "primary"
                        self.source_fail["primary"] = 0
                        self.source_recover_ok = 0
                        self.primary_recheck_needed = True
                        self._send_anomaly("主源恢复：已切回 MT5", impact="行情恢复，切回 MT5 主源")
                else:
                    self.source_recover_ok = 0
            try:
                self._process_symbol(symbol, df, quote, use_backup=use_backup, price_ok=price_ok, deviation=deviation)
            except Exception as exc:
                traceback.print_exc()
                self._send_anomaly(f"行情拉取失败：{exc}", impact=f"{symbol} 无法更新K线")
        if self.primary_recheck_needed and self.active_source == "primary":
            self._recheck_positions_with_primary(symbols)
            self.primary_recheck_needed = False
        self._maybe_send_daily_summary()

    def run_heartbeat(self, symbols: List[str]) -> None:
        """轻量巡检心跳（中文）：
        - 频率：建议 5 分钟一次，对齐到 5 分钟边界。
        - 内容：仅更新市价/检测 TP/SL 触发；若短期价格偏离超过 ATR×阈值（signals.review_price_atr），触发临时 DeepSeek 复评。
        - 不做：新信号生成/模式告警/绩效汇总等重任务，减少无效调用与成本。
        """
        for symbol in symbols:
            use_backup = self.active_source == "backup"
            quote, market_open = self._check_market_open(symbol, use_backup=use_backup)
            if not market_open:
                print(f"[info] {symbol} market closed / on break")
                continue
            try:
                df = self.fetcher.fetch_dataframe(symbol, use_backup=use_backup)
                if df.empty:
                    continue
                multi = self.pipeline.from_dataframe(symbol, df)
                latest_row = df.iloc[-1]
                feature_ctx = compute_feature_context(multi.frames)
                price_ok, deviation = self._check_price_deviation(symbol, quote, use_backup)
                self._check_exit_events(symbol, latest_row, observe_only=use_backup and (not price_ok), deviation_note=deviation, source_tag=self._source_tag(use_backup))
                self._handle_reviews(
                    symbol,
                    feature_ctx,
                    latest_row,
                    observe_only=use_backup and (not price_ok),
                    deviation_note=deviation,
                    source_tag=self._source_tag(use_backup),
                )
            except Exception as exc:
                traceback.print_exc()
                self._send_anomaly(f"行情拉取失败：{exc}", impact=f"{symbol} 无法更新K线")

    def _process_symbol(
        self,
        symbol: str,
        df: pd.DataFrame,
        quote: Optional[Dict[str, float]] = None,
        use_backup: bool = False,
        price_ok: bool = True,
        deviation: float = 0.0,
    ) -> None:
        source_tag = self._source_tag(use_backup)
        extra_frames = self.fetcher.fetch_timeframes(symbol, ["1h", "4h", "1d"], use_backup=use_backup)
        multi = self.pipeline.from_dataframe(symbol, df, extra_frames=extra_frames)
        symbol_spec = self.cfg.symbol_settings.get(symbol)
        if self.db and self.db.kline_writer:
            self.db.kline_writer.record_frames(symbol, multi.frames)
        fast_df = multi.get(self.cfg.timeframes.filter_fast)
        slow_df = multi.get(self.cfg.timeframes.filter_slow)
        if fast_df.empty or slow_df.empty:
            return
        feature_ctx = compute_feature_context(multi.frames)
        self._handle_mode_alert(symbol, feature_ctx.market_mode, feature_ctx.environment)
        latest_row = df.iloc[-1]
        observe_only = bool(use_backup and (not price_ok))
        self._check_exit_events(symbol, latest_row, observe_only=observe_only, deviation_note=deviation, source_tag=self._source_tag(use_backup))
        self._handle_reviews(symbol, feature_ctx, latest_row, observe_only=observe_only, deviation_note=deviation, source_tag=self._source_tag(use_backup))
        now = datetime.now(timezone.utc)
        if self.safe_mode_enabled and self.safe_mode and not self.safe_mode.can_trade(now):
            print(f"[info] safe mode active, skip new opens for {symbol}")
            return
        if self.event_triggers_enabled:
            events = detect_market_events(
                {
                    "features": feature_ctx.features,
                    "structure": feature_ctx.structure,
                    "frames": multi.frames,
                    "symbol": symbol,
                }
            )
            LOGGER.info(
                "event gate checked symbol=%s severity=%s reasons=%s",
                symbol,
                events.get("severity"),
                events.get("reasons"),
            )
            if not events.get("has_event", False):
                LOGGER.info("event gate skip AI symbol=%s", symbol)
                return
        glm_result: GlmFilterResult | None = None
        if self.glm_filter_enabled and self.glm_prefilter:
            glm_context = {
                "features": feature_ctx.features,
                "market_mode": getattr(feature_ctx.market_mode, "name", None),
                "mode_confidence": getattr(feature_ctx.market_mode, "confidence", None),
                "trend": {
                    "score": feature_ctx.trend.score,
                    "grade": feature_ctx.trend.grade,
                    "global_direction": feature_ctx.trend.global_direction,
                },
                "structure": {
                    name: {"support": lvl.support, "resistance": lvl.resistance}
                    for name, lvl in feature_ctx.structure.levels.items()
                },
                "recent_ohlc": feature_ctx.recent_ohlc,
                "environment": feature_ctx.environment,
                "global_temperature": feature_ctx.global_temperature,
            }
            try:
                glm_result = self.glm_prefilter.should_call_deepseek(glm_context)
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("glm_screen_exception symbol=%s err=%s", symbol, exc)
                glm_result = GlmFilterResult(
                    should_call_deepseek=self.cfg.qwen_filter.on_error == "call_deepseek",
                    reason=f"prefilter_exception:{exc}",
                    danger_flags=["glm_error"],
                    failed_conditions=["glm_error"],
                )
            if self.db and getattr(self.db, "system_monitor", None):
                severity = "info"
                if glm_result and (
                    not glm_result.should_call_deepseek
                    or "prefilter_error" in glm_result.reason
                    or "prefilter_exception" in glm_result.reason
                ):
                    severity = "warning"
                self.db.system_monitor.record_event(
                    "FILTER_TRIGGER",
                    severity,
                    f"glm_filter_result symbol={symbol} reason={glm_result.reason if glm_result else 'missing'}",
                    payload={"symbol": symbol, "glm_filter": glm_result.model_dump_safe() if glm_result else {}},
                )
            if glm_result and not glm_result.should_call_deepseek:
                LOGGER.info("glm_screen_hold symbol=%s detail=%s", symbol, glm_result.model_dump_safe())
                reason = glm_result.reason
                watch_payload = WatchPayload(
                    symbol=symbol,
                    reason=(
                        f"[{source_tag}] GLM 预过滤：{reason} "
                        f"(trend={glm_result.trend_consistency}, vol={glm_result.volatility_status}, "
                        f"struct={glm_result.structure_relevance}, pattern={glm_result.pattern_candidate})"
                    ),
                    market_note=feature_ctx.reason,
                    confidence=None,
                    next_check=datetime.now(timezone.utc) + timedelta(minutes=self.cfg.signals.review_interval_minutes),
                )
                send_watch_card(self.webhook, watch_payload)
                return

        decision = _make_decision(self.cfg, self.deepseek, symbol, feature_ctx, glm_result)
        decision = apply_fallback(decision, payload=getattr(decision, "meta", {}))
        if decision.decision == "hold":
            if "fallback" in (decision.reason or ""):
                self.deepseek.record_market_event(
                    {
                        "type": "self_critique",
                        "symbol": symbol,
                        "summary": "上一轮决策因价格/结构异常被 fallback 拒绝，需要加强价格关系检查",
                    }
                )
            reason = decision.reason or "AI 选择观望"
            if getattr(decision, "meta", {}).get("adapter") == "prefilter":
                reason = f"Qwen 预过滤：{reason}（未调用 DeepSeek）"
            watch_payload = WatchPayload(
                symbol=symbol,
                reason=f"[{source_tag}] {reason}",
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
        if use_backup and ((not self.allow_backup_open) or (not price_ok)):
            reason = "备源模式不新开仓" if not self.allow_backup_open else f"备源价差 {deviation*100:.2f}% 超阈值，暂停新开仓"
            watch_payload = WatchPayload(
                symbol=symbol,
                reason=f"[{source_tag}] {reason}",
                market_note=feature_ctx.reason,
                confidence=decision.confidence,
                next_check=datetime.now(timezone.utc) + timedelta(minutes=self.cfg.signals.review_interval_minutes),
            )
            send_watch_card(self.webhook, watch_payload)
            return
        now = datetime.now(timezone.utc)
        cooldown = timedelta(minutes=self.cfg.signals.cooldown_minutes or 0)
        if cooldown and decision.decision in ("open_long", "open_short"):
            key = f"{symbol}:{decision.decision}"
            last = self.last_open.get(key)
            if last and (now - last) < cooldown:
                return
        max_same = int(self.cfg.signals.max_same_direction or 0)
        existing_positions = self.state.list_positions(symbol)
        if max_same and len(existing_positions) >= max_same:
            LOGGER.info("skip open: %s existing=%s limit=%s", symbol, len(existing_positions), max_same)
            watch_payload = WatchPayload(
                symbol=symbol,
                reason=f"[{source_tag}] 已有 {len(existing_positions)} 笔持仓，超过上限 {max_same}",
                market_note=feature_ctx.reason,
                confidence=decision.confidence,
                next_check=datetime.now(timezone.utc) + timedelta(minutes=self.cfg.signals.review_interval_minutes),
            )
            send_watch_card(self.webhook, watch_payload)
            return
        if quote is None:
            try:
                quote = self.fetcher.fetch_price(symbol, use_backup=use_backup)
            except Exception:
                quote = {}
        entry_price = decision.entry_price
        if quote:
            if decision.decision == "open_long":
                entry_price = float(quote.get("ask") or entry_price)
            else:
                entry_price = float(quote.get("bid") or entry_price)
        decision.entry_price = entry_price  # 用成交价估计做保证金/风险计算
        plan = position_size(self.paper_broker.available_equity, decision, trade_type, self.cfg.risk, spec=symbol_spec)
        if plan.qty <= 0:
            LOGGER.info("skip open %s: plan_qty=0 note=%s", symbol, plan.note)
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
        record.notes.append(f"source={source_tag}")
        correlated = self.signal_manager.correlated_warning(symbol, decision.decision)
        self.signal_manager.add(record)
        signal_id = f"{record.symbol}-{int(record.created_at.timestamp())}"
        if self.db and self.db.trading:
            self.db.trading.record_signal(record, correlated, signal_id=signal_id)
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
            margin_required=plan.margin_required,
        )
        if paper_trade is None:
            LOGGER.info(
                "open rejected for %s: margin insufficient qty=%.4f need=%.2f free=%.2f",
                symbol,
                plan.qty,
                plan.margin_required,
                self.paper_broker.available_equity,
            )
            return
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

    def _check_exit_events(self, symbol: str, candle: pd.Series, observe_only: bool = False, deviation_note: Optional[float] = None, source_tag: str = "MT5") -> None:
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
                if observe_only:
                    watch_payload = WatchPayload(
                        symbol=symbol,
                        reason=(
                            f"[{source_tag}] 备源价差 {deviation_note*100:.2f}% 超阈值，{exit_type or '止盈/止损'}仅提醒未执行"
                            if deviation_note is not None
                            else f"[{source_tag}] 备源模式仅提醒，不自动平仓"
                        ),
                        market_note=f"触发价 {triggered} stop={pos.stop} take={pos.take} side={pos.side}",
                        confidence=None,
                        next_check=datetime.now(timezone.utc) + timedelta(minutes=self.cfg.signals.review_interval_minutes),
                    )
                    send_watch_card(self.webhook, watch_payload)
                    continue
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

    def _handle_reviews(self, symbol: str, feature_ctx, candle: pd.Series, observe_only: bool = False, deviation_note: Optional[float] = None, source_tag: str = "MT5") -> None:
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
            need_review = False
            if atr_val and reverse_move >= atr_val * atr_threshold:
                need_review = True
            elif (datetime.now(timezone.utc) - pos.last_review_at) >= timedelta(minutes=interval):
                need_review = True
            if not need_review:
                continue
            if observe_only:
                note = (
                    f"备源价差 {deviation_note*100:.2f}% 超阈值，复评仅提醒未执行"
                    if deviation_note is not None
                    else "备源模式复评仅提醒未执行"
                )
                watch_payload = WatchPayload(
                    symbol=symbol,
                    reason=f"[{source_tag}] {note}",
                    market_note=feature_ctx.reason,
                    confidence=None,
                    next_check=datetime.now(timezone.utc) + timedelta(minutes=interval),
                )
                send_watch_card(self.webhook, watch_payload)
                # 刷新复评时间，避免高频重复提醒
                self.state.update_position_levels(symbol, pos.id)
                continue
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
            "features": feature_ctx.features,
            "structure": {
                name: {
                    "support": lvl.support,
                    "resistance": lvl.resistance,
                }
                for name, lvl in feature_ctx.structure.levels.items()
            },
            "market_mode": feature_ctx.market_mode.name,
            "trend_grade": feature_ctx.trend.grade,
            "mode_confidence": feature_ctx.market_mode.confidence,
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
                reason=f"[{self._source_tag(self.active_source == 'backup')}] {decision.reason}",
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
                    reason=f"[{self._source_tag(self.active_source == 'backup')}] {decision.reason}",
                    market_update=f"[{self._source_tag(self.active_source == 'backup')}] 复评调整",
                    next_review=datetime.now(timezone.utc) + timedelta(minutes=self.cfg.signals.review_interval_minutes),
                )
                send_review_adjust_card(self.webhook, review_payload)

    def _check_market_open(self, symbol: str, use_backup: bool = False) -> tuple[Dict[str, float], bool]:
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
            quote = self.fetcher.fetch_price(symbol, use_backup=use_backup) or {}
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
            self.db.system_monitor.record_event("anomaly", "high", message, {"impact": impact}, run_id=self.run_id)

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

    def _recheck_positions_with_primary(self, symbols: List[str]) -> None:
        """主源恢复后，用主源价重新复核持仓/止盈止损，避免备源基准偏移。"""
        for symbol in symbols:
            try:
                df = self.fetcher.fetch_dataframe(symbol, use_backup=False)
                if df.empty:
                    continue
                quote = self.fetcher.fetch_price(symbol, use_backup=False) or {}
                price_ok, deviation = True, 0.0
                self._process_symbol(symbol, df, quote, use_backup=False, price_ok=price_ok, deviation=deviation)
            except Exception as exc:
                LOGGER.warning("recheck_primary_failed symbol=%s err=%s", symbol, exc)
                continue

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
        trade = self.paper_broker.close(trade_id, price, ts, reason)
        if trade and self.db and getattr(self.db, "performance", None):
            self.db.performance.record_trade(trade, trade.trade_type, trade.market_mode)

    def _adjust_paper_trade(self, position_id: str, new_stop: float, new_take: float, note: str) -> None:
        trade_id = self.paper_positions.get(position_id)
        if not trade_id:
            return
        self.paper_broker.adjust(trade_id, new_stop=new_stop, new_take=new_take, note=note)

    def _check_data_health(self, df: pd.DataFrame) -> tuple[bool, str]:
        if df.empty:
            return False, "行情为空"
        last_ts = df.index[-1]
        if getattr(last_ts, "tzinfo", None) is None:
            last_ts = last_ts.tz_localize(timezone.utc)
        now = datetime.now(timezone.utc)
        age = now - last_ts
        tolerance = timedelta(minutes=max(self.base_minutes * 2, 5))
        if age > tolerance:
            return False, f"最新K线过旧 age={age} last={last_ts.isoformat()}"
        if self.required_base_bars and len(df) < self.required_base_bars:
            return False, f"底层K线不足 {len(df)}/{self.required_base_bars}，高周期无法判定"
        return True, ""

    def _alert_data_issue(self, symbol: str, code: str, detail: str) -> None:
        now = datetime.now(timezone.utc)
        key = f"{symbol}:{code}"
        last = self.last_data_alert.get(key)
        if last and (now - last) < timedelta(minutes=5):
            return
        self.last_data_alert[key] = now
        self._send_anomaly(f"行情异常 {symbol}: {detail}", impact=f"{symbol} 行情不可用，已跳过开仓")

    def _check_price_deviation(self, symbol: str, quote: Optional[Dict[str, float]], use_backup: bool) -> tuple[bool, float]:
        if not use_backup:
            return True, 0.0
        if not quote:
            try:
                quote = self.fetcher.fetch_price(symbol, use_backup=True) or {}
            except Exception:
                quote = {}
        primary_quote = self.primary_quotes.get(symbol) or self.last_quotes.get(symbol)
        if not primary_quote or not quote:
            return True, 0.0
        primary_mid = self._mid_price(primary_quote)
        backup_mid = self._mid_price(quote)
        if primary_mid <= 0 or backup_mid <= 0:
            return True, 0.0
        deviation = abs(backup_mid - primary_mid) / primary_mid
        return deviation <= self.backup_deviation_pct, deviation

    @staticmethod
    def _mid_price(quote: Dict[str, float]) -> float:
        bid = float(quote.get("bid") or 0.0)
        ask = float(quote.get("ask") or 0.0)
        last = float(quote.get("last") or 0.0)
        if bid and ask:
            return (bid + ask) / 2
        if last:
            return last
        return bid or ask or 0.0

    def _source_tag(self, use_backup: bool) -> str:
        return self.source_tags["backup" if use_backup else "primary"]

    def _record_source_failure(self, use_backup: bool) -> None:
        src = "backup" if use_backup else "primary"
        self.source_fail[src] = self.source_fail.get(src, 0) + 1
        if src == "primary":
            self.source_recover_ok = 0
        if src == "primary" and self.active_source == "primary" and self.source_fail[src] == self.source_fail_threshold:
            if self.has_backup:
                self.active_source = "backup"
                self.source_fail["backup"] = 0
                self.source_recover_ok = 0
                self._send_anomaly(
                    "主行情源连续失败，自动切换备用 CCXT（Binance USDT-M）",
                    impact="MT5 行情异常，已降级到 CCXT 行情，仅用于决策/纸盘，不触发实盘；价格基于 Binance USDT-M，可能与 MT5 有点差，请留意复评/止盈止损触发差异",
                )
            else:
                self._send_anomaly("主行情源连续失败且无备用源", impact="行情不可用，等待人工恢复")
        elif src == "backup" and self.source_fail[src] == self.source_fail_threshold:
            self._send_anomaly("备用行情源连续失败", impact="主/备用行情都不可用，暂停开仓等待人工")

    def _record_source_success(self, use_backup: bool) -> None:
        src = "backup" if use_backup else "primary"
        if self.source_fail.get(src, 0):
            self.source_fail[src] = 0
        if src == "primary":
            self.source_recover_ok = 0

    def _probe_primary(self, symbol: str) -> bool:
        try:
            df = self.fetcher.fetch_dataframe(symbol, use_backup=False)
        except Exception:
            return False
        if df.empty:
            return False
        ok, _ = self._check_data_health(df)
        if ok:
            self.source_fail["primary"] = 0
        return ok








