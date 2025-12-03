from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

import requests

from ..config import DeepSeekCfg
from .filter_adapter import PreFilterClient
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
        self.prefilter = PreFilterClient()

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
        # Pre-filter: small/quiet market may skip DeepSeek to省调用；强触发已在 filter_adapter 兜底。
        prefilter = self._prefilter_gate(payload)
        if prefilter and not prefilter.get("should_call", True):
            price = self._price_from_payload(payload)
            reason = prefilter.get("reason", "prefilter_hold")
            return Decision(
                decision="hold",
                entry_price=price,
                stop_loss=price,
                take_profit=price,
                risk_reward=0.0,
                confidence=0.0,
                reason=reason,
                meta={"adapter": "prefilter"},
            )
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
            risk_score=self._to_float(data.get("risk_score")) or 0.0,
            quality_score=self._to_float(data.get("quality_score")) or 0.0,
            meta=data,
        )
        decision.recompute_rr()
        return decision

    def review_position(self, symbol: str, position_id: str, payload: Dict[str, Any]) -> ReviewDecision:
        note = payload.get("context_note") or f"review request for {symbol}"
        self.conversation.append(position_id, symbol, "user", note)
        context = self.conversation.get_context(position_id, symbol)
        shared = self.conversation.get_shared_context()
        # 复评同样受预过滤保护，保持 hold 返回格式一致。
        prefilter = self._prefilter_gate(payload, position_state=payload.get("position"), next_review_time=payload.get("next_review"))
        if prefilter and not prefilter.get("should_call", True):
            return ReviewDecision(action="hold", reason=prefilter.get("reason", "prefilter_hold"))
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
        role = "决策" if not review else "复评"
        return (
            "Reply strictly in JSON and keep all explanations in Simplified Chinese.\n"
            f"当前任务：{role}。\n"
            "你是一位专业的多周期趋势交易分析师，与你对话的系统会提供完整的市场信息，包括技术指标、趋势评分、市场结构信息，以及多周期原始 OHLCV 序列。\n"
            "=== 核心规则 ===\n"
            "1. 原始多周期序列（30m/1h/4h）是最重要的信息源，具有最高优先级。\n"
            "   - 用于判断趋势方向、结构位置、突破有效性、震荡宽度、动能变化、吸筹出货、假突破与失败形态。\n"
            "   - 当指标与原始序列矛盾时，以原始序列为准。\n"
            "2. 技术指标仅作为数学总结：\n"
            "   - EMA20/60、RSI14、MACD、ATR、布林带宽、成交量等指标用于辅助理解，而不是决定方向。\n"
            "   - 指标背离、动能变化、趋势一致性，仅作为参考。\n"
            "3. 趋势评分/模式识别仅为提示性信息：\n"
            "   - 你可以参考趋势评分（strong/medium/weak/chaotic）和 market_mode（trending/ranging/breakout/reversal）。\n"
            "   - 但最终判断必须由你结合原始序列得出。\n"
            "4. 多周期执行逻辑：1h 定义主方向，30m 负责执行与入场细节，4h 仅用于风险过滤与极端背离警示，不要求完全一致。\n"
            "5. 入场确认与区间处理（硬规则，违背则默认 hold）：\n"
            "   - 突破第一根不追，第二根收盘确认或回踩确认后允许入场（可结合 breakout_confirmed_* 等特征）。\n"
            "   - 回撤/反手不得砍第一根，必须看到结构破位或动能衰减连续 2-3 根（如 momentum_decay_*），否则先持仓/复评。\n"
            "   - 区间可做小风险结构单：上沿尝试空、下沿尝试多，中轴/噪声区禁止开仓（可参考 range_midzone_* 避免中线入场）。\n"
            "补充规则（优化活跃度）：\n"
            " - 当趋势为 weak 或 market_mode 为 ranging 时，如果出现微结构突破（例如：局部高点被小幅突破、有 2~3 根连续推动、短期 EMA20 出现轻微发散、或局部低点未被跌破）则应尝试给出“轻量方案”。\n"
            " - 轻量方案包括：小仓位试探（position_size 可为较小值）、RR 较低但结构合理的入场（RR=1.0~1.5 也允许），\n"
            " - 不得因为趋势弱或价格噪声稍高而完全拒绝给出方案。\n"
            " - 只要结构不反对，允许给出早期入场建议，但必须在 reason 中说明风险点。\n"
            " - 若确实无法判断方向，请在 reason 中明确说明“不确定，但给出保守方向偏好”，避免简单 hold。\n"
            "6. 噪声与波动处理：当 market_mode=chaotic/ranging 或 noise_level 高时，一般不追价；但若出现 ATR 扩张、布林张口、EMA 扩散等动能触发且有结构支撑，应给出可执行的入场方案，不得过度 HOLD。\n"
            "7. 止损逻辑：\n"
            "   - 必须基于结构位，不得使用随意的固定距离。\n"
            "   - 止损放在结构低点/高点外、之前的防守位之外，避免放在影线密集、容易被扫的位置。\n"
            "8. RR 要求：\n"
            "   - RR 不固定，但必须符合结构；若结构只支持 RR=1.0~1.5，也必须如实给出。\n"
            "   - 不得凭空给不合理的远止盈。\n"
            "9. 输出内容：\n"
            "   - 开仓/观望/调整/退出；方向（long/short）；入场价、止损价、止盈价；RR、position_size；\n"
            "   - 清晰逻辑：趋势结构 + 动能 + 风险点 + 预期行为。\n"
            "请结合以上规则，对后续的特征信息与多周期序列信息进行整体推理，以专业交易员的角度给出决策。\n"
        )

    def _instruction_block(self, review: bool = False) -> str:
        return "以上为决策/复评的核心规则。"

    def _trade_task_text(self) -> str:
        return (
            "请根据以上信息生成 JSON：\n"
            "- decision: open_long | open_short | hold\n"
            "- entry_price, stop_loss, take_profit, risk_reward（浮点数）\n"
            "- confidence: 0-100\n"
            "- reason: 简洁的中文决策原因\n"
            "- position_size: 若需要开仓请给出仓位大小（浮点数，未提供视为 0）\n"
            "- risk_score: 0-100，追第一根/噪声区追价/结构不清则加分\n"
            "- quality_score: 0-100，有二次确认/动能衰减过滤/区间边缘入场则加分\n"
            "务必描述风险与行情结构，若追第一根突破/回撤或 quality_score < risk_score，请默认 hold。不要输出除 JSON 之外的内容。"
        )

    def _review_task_text(self) -> str:
        return (
            "请根据以上信息评估当前持仓，输出 JSON：\n"
            "- action: close | adjust | hold\n"
            "- new_stop_loss, new_take_profit, new_rr（可为 null）\n"
            "- reason: 中文说明\n"
            "- context_summary: 对本次复评的简洁总结\n"
            "- confidence: 0-100\n"
            "若建议调整，请说明止损/止盈逻辑；若建议平仓，说明风险来源。"
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
            "risk_score_hint": payload.get("risk_score_hint"),
            "quality_score_hint": payload.get("quality_score_hint"),
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
            raise ValueError(f"无法解析 DeepSeek 返回内容为 JSON：{content}") from exc

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _prefilter_gate(
        self,
        payload: Dict[str, Any],
        position_state: Optional[Dict[str, Any]] = None,
        next_review_time: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        try:
            feature_context = {
                "features": payload.get("features") or {},
                "structure": payload.get("structure") or {},
                "market_mode": payload.get("market_mode"),
                "trend_grade": payload.get("trend_grade"),
                "mode_confidence": payload.get("mode_confidence"),
                "recent_ohlc": payload.get("recent_ohlc") or {},
            }
            return self.prefilter.should_call_deepseek(feature_context, position_state, next_review_time)
        except Exception:
            return None

    @staticmethod
    def _price_from_payload(payload: Dict[str, Any]) -> float:
        feats = payload.get("features") or {}
        for key in ("price_30m", "price_1h", "price_4h"):
            val = feats.get(key)
            if val is not None:
                try:
                    return float(val)
                except (TypeError, ValueError):
                    continue
        return 0.0
