from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, TYPE_CHECKING

import requests

from ..config import DeepSeekCfg
from .context import ConversationManager
from .models import Decision, ReviewDecision
from .usage_tracker import AIUsageTracker, BudgetExceeded, BudgetInfo

if TYPE_CHECKING:
    from ..db.ai_decision_logger import AIDecisionLogger


class DeepSeekClient:
    def __init__(
        self,
        cfg: DeepSeekCfg,
        conversation: Optional[ConversationManager] = None,
        budget_callback: Optional[Callable[[BudgetInfo], None]] = None,
        decision_logger: Optional["AIDecisionLogger"] = None,
    ) -> None:
        self.cfg = cfg
        self.session = requests.Session()
        self.conversation = conversation or ConversationManager()
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        self.api_base = os.getenv("DEEPSEEK_API_BASE", cfg.api_base).rstrip("/")
        state_dir = Path(__file__).resolve().parents[1] / "state"
        self.usage_tracker = AIUsageTracker(cfg.budget.daily_tokens, cfg.budget.warn_ratio, state_dir / "ai_usage.json")
        self.budget_callback = budget_callback
        self.ai_logger = decision_logger

    def enabled(self) -> bool:
        return self.cfg.enabled and bool(self.api_key)

    def record_market_event(self, event: Dict[str, object]) -> None:
        self.conversation.add_shared_event(event)

    def record_position_event(self, position_id: str, symbol: str, event: Dict[str, object]) -> None:
        self.conversation.append(position_id, symbol, "system", json.dumps(event, ensure_ascii=False))

    def record_open_pattern(self, symbol: str, event: Dict[str, object]) -> None:
        self.conversation.append(f"open:{symbol}", symbol, "system", json.dumps(event, ensure_ascii=False))
        self.conversation.add_shared_event(event)

    def decide_trade(self, symbol: str, payload: Dict[str, Any]) -> Decision:
        context = self.conversation.get_context(f"open:{symbol}", symbol)
        shared = self.conversation.get_shared_context()
        content, tokens_used, latency_ms = self._chat_completion(
            model=self.cfg.model,
            system_prompt=(
                "You are a professional-level crypto trading AI operating in SE mode.\n"
                "Reply strictly in JSON.\n"
                "All explanations must be in Simplified Chinese.\n"
                "You have full autonomy to decide entries, stop loss, take profit, risk-reward, and position size.\n\n"
                "You will receive multi-timeframe OHLCV, indicators, trend slopes, environment labels, and global market temperature.\n\n"
                "You MUST explicitly use:\n"
                "- trend_slope fields (ema20_slope, ema60_slope, macd_hist_slope, rsi_trend, atr_trend, bb_width_trend)\n"
                "- environment (volatility, regime, noise_level, liquidity)\n"
                "- global_temperature (risk level, correlation, temperature)\n"
                "to evaluate trend strength, volatility regime, and risk conditions.\n\n"
                "You must explain in Chinese why you open/hold/close based on these fields.\n\n"
                "Output JSON with:\n"
                "decision, entry_price, stop_loss, take_profit, risk_reward, confidence, reason, position_size."
            ),
            user_payload={
                "task": "trade_decision",
                "symbol": symbol,
                "data": payload,
                "context": context,
                "shared_memory": shared,
                "environment": payload.get("environment"),
                "global_temperature": payload.get("global_temperature"),
                "user_guidance": "请结合 trend_slope、environment、global_temperature 来判断趋势强弱、风险、波动结构，并据此决定止损位置、止盈目标和仓位大小。",
                "format": {
                    "decision": "open_long|open_short|hold",
                    "entry_price": "float",
                    "stop_loss": "float",
                    "take_profit": "float",
                    "risk_reward": "float",
                    "confidence": "0-100",
                    "reason": "string (Simplified Chinese rationale for the trade)",
                    "position_size": "float (contract/lot size to open; you decide the size)",
                },
                "language": "zh-CN",
                "notes": "Ensure the `reason` field is a concise Simplified Chinese explanation. You control sizing.",
            },
        )
        data = self._parse_json(content)
        self.conversation.append(
            f"open:{symbol}",
            symbol,
            "assistant",
            f"decision={data.get('decision')} rr={data.get('risk_reward')} pos={data.get('position_size')} reason={data.get('reason')}",
        )
        self.conversation.add_shared_event(
            {
                "type": "open_decision",
                "symbol": symbol,
                "mode": payload.get("market_mode"),
                "trend": payload.get("trend_grade"),
                "decision": data.get("decision"),
                "rr": data.get("risk_reward"),
            },
        )
        if self.ai_logger:
            self.ai_logger.log_decision(
                "decision",
                symbol,
                payload,
                data,
                tokens_used,
                latency_ms,
            )
        return Decision(
            decision=data.get("decision", "hold"),
            entry_price=float(data.get("entry_price", 0.0)),
            stop_loss=float(data.get("stop_loss", 0.0)),
            take_profit=float(data.get("take_profit", 0.0)),
            risk_reward=float(data.get("risk_reward", 0.0)),
            confidence=float(data.get("confidence", 0.0)),
            reason=str(data.get("reason", "")),
            position_size=self._to_float(data.get("position_size")) or 0.0,
            meta=data,
        )

    def review_position(self, symbol: str, position_id: str, payload: Dict[str, Any]) -> ReviewDecision:
        note = payload.get("context_note") or f"review request for {symbol}"
        self.conversation.append(position_id, symbol, "user", note)
        context = self.conversation.get_context(position_id, symbol)
        shared = self.conversation.get_shared_context()
        user_payload = {
            "task": "position_review",
            "symbol": symbol,
            "position_id": position_id,
            "context": context,
            "shared_memory": shared,
            "data": payload,
            "environment": payload.get("environment"),
            "global_temperature": payload.get("global_temperature"),
            "format": {
                "action": "close|adjust|hold",
                "new_stop_loss": "float|null",
                "new_take_profit": "float|null",
                "new_rr": "float|null",
                "reason": "string",
                "context_summary": "string",
                "confidence": "0-100",
            },
        }
        user_payload["language"] = "zh-CN"
        content, tokens_used, latency_ms = self._chat_completion(
            model=self.cfg.review_model,
            system_prompt=(
                "You are DeepSeek risk reviewer.\n"
                "Reply strictly in JSON.\n"
                "Return all explanations in Simplified Chinese.\n"
                "You MUST use trend slope changes, environment labels, and global market temperature to decide whether the existing position should adjust stop loss, take profit, or close."
            ),
            user_payload=user_payload,
        )
        data = self._parse_json(content)
        self.conversation.append(
            position_id,
            symbol,
            "assistant",
            f"review_action={data.get('action')} sl={data.get('new_stop_loss')} tp={data.get('new_take_profit')} rr={data.get('new_rr')} reason={data.get('reason')}",
        )
        if self.ai_logger:
            self.ai_logger.log_decision("review", symbol, user_payload, data, tokens_used, latency_ms)
        if data.get("context_summary"):
            self.conversation.append(position_id, symbol, "assistant", data["context_summary"])
        return ReviewDecision(
            action=data.get("action", "hold"),
            new_stop_loss=self._to_float(data.get("new_stop_loss")),
            new_take_profit=self._to_float(data.get("new_take_profit")),
            new_rr=self._to_float(data.get("new_rr")),
            reason=str(data.get("reason", "")),
            context_summary=str(data.get("context_summary", "")),
            confidence=float(data.get("confidence", 0.0)),
        )

    def _chat_completion(self, model: str, system_prompt: str, user_payload: Dict[str, Any]) -> Tuple[str, int, float]:
        if not self.enabled():
            raise RuntimeError("DeepSeek not enabled or API key missing")
        url = f"{self.api_base}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ]
        body = {
            "model": model,
            "messages": messages,
            "temperature": self.cfg.temperature,
            "max_tokens": self.cfg.max_tokens,
            "stream": self.cfg.stream,
            "response_format": {"type": "json_object"},
        }
        attempts = max(1, self.cfg.retry.max_attempts)
        backoff = max(0.5, self.cfg.retry.backoff_seconds)
        last_exc: Optional[Exception] = None
        for attempt in range(1, attempts + 1):
            try:
                start = time.perf_counter()
                resp = self.session.post(url, json=body, headers=headers, timeout=self.cfg.timeout)
                resp.raise_for_status()
                duration_ms = (time.perf_counter() - start) * 1000
                data = resp.json()
                tokens = data.get("usage", {}).get("total_tokens", 0)
                warn_info, exceed_info = self.usage_tracker.record(user_payload.get("task", "unknown"), tokens, duration_ms)
                if warn_info and self.budget_callback:
                    self.budget_callback(warn_info)
                if exceed_info:
                    if self.budget_callback:
                        self.budget_callback(exceed_info)
                    raise BudgetExceeded(exceed_info)
                content = data["choices"][0]["message"]["content"]
                return content, tokens, duration_ms
            except BudgetExceeded:
                raise
            except requests.HTTPError as exc:
                last_exc = exc
                status = exc.response.status_code if exc.response is not None else None
                if status in (429, 500, 502, 503, 504) and attempt < attempts:
                    time.sleep(backoff * attempt)
                    continue
                raise
            except requests.RequestException as exc:
                last_exc = exc
                if attempt < attempts:
                    time.sleep(backoff * attempt)
                    continue
                raise
        if last_exc:
            raise last_exc
        raise RuntimeError("DeepSeek request failed unexpectedly")

    @staticmethod
    def _parse_json(content: str) -> Dict[str, Any]:
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"无法解析 DeepSeek 返回内容为 JSON：{content}") from exc

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None
