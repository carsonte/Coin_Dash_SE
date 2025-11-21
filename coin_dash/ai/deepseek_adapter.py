from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

import requests

from ..config import DeepSeekCfg
from .context import ConversationManager
from .models import Decision, ReviewDecision
if TYPE_CHECKING:
    from ..db.ai_decision_logger import AIDecisionLogger


class DeepSeekClient:
    def __init__(
        self,
        cfg: DeepSeekCfg,
        conversation: Optional[ConversationManager] = None,
        decision_logger: Optional["AIDecisionLogger"] = None,
    ) -> None:
        self.cfg = cfg
        self.session = requests.Session()
        self.conversation = conversation or ConversationManager()
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        self.api_base = os.getenv("DEEPSEEK_API_BASE", cfg.api_base).rstrip("/")
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
        prompt_text = self._build_trade_prompt(symbol, payload, context, shared)
        content, tokens_used, latency_ms = self._chat_completion(
            model=self.cfg.model,
            system_prompt=self._instruction_header(),
            user_content=prompt_text,
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
        decision = Decision(
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
        decision.recompute_rr()
        return decision

    def review_position(self, symbol: str, position_id: str, payload: Dict[str, Any]) -> ReviewDecision:
        note = payload.get("context_note") or f"review request for {symbol}"
        self.conversation.append(position_id, symbol, "user", note)
        context = self.conversation.get_context(position_id, symbol)
        shared = self.conversation.get_shared_context()
        review_prompt = self._build_review_prompt(symbol, payload, context, shared)
        content, tokens_used, latency_ms = self._chat_completion(
            model=self.cfg.review_model,
            system_prompt=self._instruction_header(review=True),
            user_content=review_prompt,
        )
        data = self._parse_json(content)
        self.conversation.append(
            position_id,
            symbol,
            "assistant",
            f"review_action={data.get('action')} sl={data.get('new_stop_loss')} tp={data.get('new_take_profit')} rr={data.get('new_rr')} reason={data.get('reason')}",
        )
        if self.ai_logger:
            self.ai_logger.log_decision("review", symbol, payload, data, tokens_used, latency_ms)
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

    def _chat_completion(self, model: str, system_prompt: str, user_content: str) -> Tuple[str, int, float]:
        if not self.enabled():
            raise RuntimeError("DeepSeek not enabled or API key missing")
        url = f"{self.api_base}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
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
                content = data["choices"][0]["message"]["content"]
                return content, tokens, duration_ms
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

    def _instruction_header(self, review: bool = False) -> str:
        role = (
            "You are a professional-level crypto trading AI operating in SE mode."
            if not review
            else "You are DeepSeek risk reviewer operating in SE mode."
        )
        return (
            f"{role}\n"
            "Reply strictly in JSON and keep all explanations in Simplified Chinese.\n"
            "Stay disciplined, avoid hallucinations, and respect the provided multi-timeframe context.\n"
            "Raw multi-timeframe OHLC sequences have highest priority; indicators are secondary summaries."
        )

    def _instruction_block(self, review: bool = False) -> str:
        base = (
            "你将获得多个周期的原始 K 线序列（未经过指标加工）：\n"
            "- 30 分钟周期：最近 50 根 K 线\n"
            "- 1 小时周期：最近 40 根 K 线\n"
            "- 4 小时周期：最近 30 根 K 线\n\n"
            "每根 K 线包含 open、high、low、close、volume（已做 log10 压缩）。请基于这些序列判断：\n"
            "- 趋势方向（多/空/震荡）与结构（高低点形态、假突破、震荡宽度）\n"
            "- 动能变化（加速或衰减）与量价关系（爆量/缩量、配合或背离）\n"
            "- 支撑/压力是否有效、风险等级、合理的止损/止盈/RR\n"
            "- 当前是否适合开仓、持仓或观望，并说明理由\n\n"
            "原始序列具有最高优先级；技术指标（EMA、RSI、MACD、ATR、布林等）仅作总结性参考。当指标与原始序列矛盾时，以原始序列表现为准。"
        )
        if review:
            return "复评任务说明：\n" + base
        return base

    def _trade_task_text(self) -> str:
        return (
            "璇锋牴鎹互涓婁俊鎭敓鎴?JSON锛歕n"
            "- decision: open_long | open_short | hold\n"
            "- entry_price, stop_loss, take_profit, risk_reward锛堟诞鐐规暟锛塡n"
            "- confidence: 0-100\n"
            "- reason: 绠€娲佺殑涓枃鍐崇瓥鍘熷洜\n"
            "- position_size: 鑻ラ渶瑕佸紑浠撹缁欏嚭浠撲綅澶у皬锛堟诞鐐规暟锛屾湭鎻愪緵瑙嗕负 0锛塡n"
            "鍔″繀鎻忚堪椋庨櫓涓庤鎯呯粨鏋勩€?
        )

    def _review_task_text(self) -> str:
        return (
            "璇锋牴鎹互涓婁俊鎭瘎浼板綋鍓嶆寔浠擄紝杈撳嚭 JSON锛歕n"
            "- action: close | adjust | hold\n"
            "- new_stop_loss, new_take_profit, new_rr锛堝彲涓?null锛塡n"
            "- reason: 涓枃璇存槑\n"
            "- context_summary: 瀵规湰娆″璇勭殑绠€娲佹€荤粨\n"
            "- confidence: 0-100\n"
            "鑻ュ缓璁皟鏁达紝璇疯鏄庢鎹?姝㈢泩閫昏緫锛涜嫢寤鸿骞充粨锛岃鏄庨闄╂潵婧愩€?
        )

    def _build_trade_prompt(
        self,
        symbol: str,
        payload: Dict[str, Any],
        context: Optional[List[Any]],
        shared: Optional[List[Any]],
    ) -> str:
        market_bundle = {
            "symbol": symbol,
            "market_mode": payload.get("market_mode"),
            "mode_confidence": payload.get("mode_confidence"),
            "trend_score": payload.get("trend_score"),
            "trend_grade": payload.get("trend_grade"),
            "cycle_weights": payload.get("cycle_weights"),
            "features": payload.get("features"),
            "environment": payload.get("environment"),
            "global_temperature": payload.get("global_temperature"),
            "structure": payload.get("structure"),
            "context": context or [],
            "shared_memory": shared or [],
        }
        features_json = json.dumps(market_bundle, ensure_ascii=False, indent=2)
        sequences_json = json.dumps(payload.get("recent_ohlc") or {}, ensure_ascii=False, indent=2)
        sections = [
            "=== Instruction ===",
            self._instruction_block(),
            "=== Market Features ===",
            features_json,
            "=== Multi-Timeframe Price Sequences ===",
            sequences_json,
            "=== End Sequences ===",
            "=== Task ===",
            self._trade_task_text(),
        ]
        return "\n".join(sections)

    def _build_review_prompt(
        self,
        symbol: str,
        payload: Dict[str, Any],
        context: Optional[List[Any]],
        shared: Optional[List[Any]],
    ) -> str:
        review_bundle = {
            "symbol": symbol,
            "position": payload.get("position"),
            "market": payload.get("market"),
            "environment": payload.get("environment"),
            "global_temperature": payload.get("global_temperature"),
            "context": context or [],
            "shared_memory": shared or [],
        }
        features_json = json.dumps(review_bundle, ensure_ascii=False, indent=2)
        sequences_json = json.dumps(payload.get("recent_ohlc") or {}, ensure_ascii=False, indent=2)
        sections = [
            "=== Instruction ===",
            self._instruction_block(review=True),
            "=== Market Features ===",
            features_json,
            "=== Multi-Timeframe Price Sequences ===",
            sequences_json,
            "=== End Sequences ===",
            "=== Task ===",
            self._review_task_text(),
        ]
        return "\n".join(sections)

    @staticmethod
    def _parse_json(content: str) -> Dict[str, Any]:
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"鏃犳硶瑙ｆ瀽 DeepSeek 杩斿洖鍐呭涓?JSON锛歿content}") from exc

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None
