from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

import requests

from ..config import DeepSeekCfg, GLMFilterCfg
from .filter_adapter import GlmFilterResult, PreFilterClient
from .context import ConversationManager
from .models import Decision, ReviewDecision
if TYPE_CHECKING:
    from ..db.ai_decision_logger import AIDecisionLogger


class DeepSeekClient:
    def __init__(
        self,
        cfg: DeepSeekCfg,
        glm_cfg: Optional[GLMFilterCfg] = None,
        conversation: Optional[ConversationManager] = None,
        decision_logger: Optional["AIDecisionLogger"] = None,
    ) -> None:
        self.cfg = cfg
        self.session = requests.Session()
        self.conversation = conversation or ConversationManager()
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        self.api_base = os.getenv("DEEPSEEK_API_BASE", cfg.api_base).rstrip("/")
        self.ai_logger = decision_logger
        self.prefilter = PreFilterClient(glm_cfg)

    def enabled(self) -> bool:
        return self.cfg.enabled and bool(self.api_key)

    def record_market_event(self, event: Dict[str, object]) -> None:
        self.conversation.add_shared_event(event)

    def record_position_event(self, position_id: str, symbol: str, event: Dict[str, object]) -> None:
        self.conversation.append(position_id, symbol, "system", json.dumps(event, ensure_ascii=False))

    def record_open_pattern(self, symbol: str, event: Dict[str, object]) -> None:
        self.conversation.append(f"open:{symbol}", symbol, "system", json.dumps(event, ensure_ascii=False))
        self.conversation.add_shared_event(event)

    def decide_trade(self, symbol: str, payload: Dict[str, Any], glm_result: Optional[GlmFilterResult] = None) -> Decision:
        # Pre-filter: small/quiet market may skip DeepSeek to省调用；强触发已在 filter_adapter 兜底。
        if glm_result and "glm_filter_result" not in payload:
            payload["glm_filter_result"] = glm_result.model_dump_safe()
        prefilter = self._prefilter_gate(payload)
        if prefilter:
            payload["glm_filter_result"] = prefilter.model_dump_safe()
        if prefilter and not prefilter.should_call_deepseek:
            price = self._price_from_payload(payload)
            reason = prefilter.reason or "prefilter_hold"
            return Decision(
                decision="hold",
                entry_price=price,
                stop_loss=price,
                take_profit=price,
                risk_reward=0.0,
                confidence=0.0,
                reason=reason,
                meta={"adapter": "prefilter", "glm_filter": payload.get("glm_filter_result")},
                glm_snapshot=payload.get("glm_filter_result"),
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
                model_name="deepseek",
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
            glm_snapshot=payload.get("glm_filter_result"),
        )
        decision.recompute_rr()
        return decision

    def review_position(
        self, symbol: str, position_id: str, payload: Dict[str, Any], glm_result: Optional[GlmFilterResult] = None
    ) -> ReviewDecision:
        note = payload.get("context_note") or f"review request for {symbol}"
        self.conversation.append(position_id, symbol, "user", note)
        context = self.conversation.get_context(position_id, symbol)
        shared = self.conversation.get_shared_context()
        # 复评同样受预过滤保护，保持 hold 返回格式一致。
        if glm_result and "glm_filter_result" not in payload:
            payload["glm_filter_result"] = glm_result.model_dump_safe()
        prefilter = self._prefilter_gate(payload, position_state=payload.get("position"), next_review_time=payload.get("next_review"))
        if prefilter:
            payload["glm_filter_result"] = prefilter.model_dump_safe()
        if prefilter and not prefilter.should_call_deepseek:
            return ReviewDecision(action="hold", reason=prefilter.reason or "prefilter_hold")
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
            self.ai_logger.log_decision("review", symbol, payload, data, tokens_used, latency_ms, model_name="deepseek")
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
        if review:
            return (
                "仅输出 JSON，解释用简体中文。你是持仓复评的执行官，只负责在已有持仓基础上给出调整/平仓/继续持仓方案，默认接受上游的环境标签与偏好。输入包含 glm_filter_result、持仓信息与上下文；请给出结构化 JSON，只有在无法给出可控调整时才 hold，并说明原因与下一步条件。"
            )
        return (
            "仅输出 JSON，不要多余文字，解释用简体中文。你是执行交易员（Execution Trader），负责在既定方向/环境下设计可执行方案，不再重复判断大环境。上游已完成：GLM 预过滤提供趋势一致性/波动/结构与危险标签（glm_filter_result）；轻量双模型委员会（gpt-4o-mini + glm-4.5v）已讨论机会，结论在 committee_front，默认接受其倾向；只要有合理结构且风险可控，应倾向参与而非过度观望。你的职责：依据上游偏好给出方向、entry/stop/take/rr、position_size；结构一般可用轻仓试探代替观望。只有完全找不到可控止损位时才允许 hold，并写清结构冲突与等待条件。输出 JSON 字段（保持兼容）：decision(open_long/open_short/hold)、entry_price/stop_loss/take_profit/risk_reward、confidence(0-100)、reason(简洁中文)、position_size(浮点)、risk_score/quality_score(0-100 可选)，保留现有 meta 等字段，严禁输出非 JSON 文本。不要重复判断 GLM 环境标签，不要写市场故事，只生成清晰可执行方案。"
        )

    def _instruction_block(self, review: bool = False) -> str:
        return "以上为决策/复评的核心规则。"

    def _trade_task_text(self) -> str:
        return (
            "请输出 JSON：\n"
            "- decision: open_long | open_short | hold\n"
            "- entry_price, stop_loss, take_profit, risk_reward（浮点）\n"
            "- confidence: 0-100；reason: 简洁中文\n"
            "- position_size: 浮点，未提供视为 0\n"
            "- risk_score / quality_score: 0-100 可选\n"
            "结构不完美时优先给轻仓试探，避免空洞观望；只有在完全找不到可控止损位时才 hold。不得输出除 JSON 外的内容。"
        )

    def _review_task_text(self) -> str:
        return (
            "请评估当前持仓并输出 JSON：\n"
            "- action: close | adjust | hold\n"
            "- new_stop_loss, new_take_profit, new_rr（可为 null）\n"
            "- reason: 中文说明；context_summary: 简短总结\n"
            "- confidence: 0-100\n"
            "只针对持仓调整，不必重复判断大环境。"
        )

    def _build_trade_prompt(
        self,
        symbol: str,
        payload: Dict[str, Any],
        context: Optional[List[Any]],
        shared: Optional[List[Any]],
    ) -> str:
        glm_section = self._glm_context_block(payload.get("glm_filter_result"), review=False, has_position=False)
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
            "glm_filter": payload.get("glm_filter_result"),
            "context": context or [],
            "shared_memory": shared or [],
        }
        features_json = json.dumps(market_bundle, ensure_ascii=False, indent=2)
        sequences_json = json.dumps(payload.get("recent_ohlc") or {}, ensure_ascii=False, indent=2)
        sections = [
            "=== Instruction ===",
            self._instruction_block(),
            "=== GLM Market Filter ===",
            glm_section or "（未提供 GLM 标签，按常规方式评估。）",
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
        glm_section = self._glm_context_block(payload.get("glm_filter_result"), review=True, has_position=bool(payload.get("position")))
        review_bundle = {
            "symbol": symbol,
            "position": payload.get("position"),
            "market": payload.get("market"),
            "environment": payload.get("environment"),
            "global_temperature": payload.get("global_temperature"),
            "glm_filter": payload.get("glm_filter_result"),
            "context": context or [],
            "shared_memory": shared or [],
        }
        features_json = json.dumps(review_bundle, ensure_ascii=False, indent=2)
        sequences_json = json.dumps(payload.get("recent_ohlc") or {}, ensure_ascii=False, indent=2)
        sections = [
            "=== Instruction ===",
            self._instruction_block(review=True),
            "=== GLM Market Filter ===",
            glm_section or "（未提供 GLM 标签，按常规方式评估。）",
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
    def _glm_context_block(glm: Optional[Dict[str, Any]], review: bool = False, has_position: bool = False) -> Optional[str]:
        if not glm:
            return None
        danger = glm.get("danger_flags") or []
        danger_text = ", ".join(danger) if danger else "无"
        lines = [
            "当前由轻量级过滤模型（GLM）给出的市场环境标签：",
            f"- 趋势一致性：{glm.get('trend_consistency')}",
            f"- 波动状态：{glm.get('volatility_status')}",
            f"- 结构位置：{glm.get('structure_relevance')}",
            f"- 形态候选：{glm.get('pattern_candidate')}",
            f"- 风险标记：{danger_text}",
            "请信任以上标签，不要重复判断大环境；专注形态真假、是否值得交易、入场/止损/止盈/仓位设计。",
        ]
        if danger:
            lines.append(
                "若无持仓且存在高风险标记（atr_extreme/low_liquidity/wick_noise 等），应偏向观望；"
                "复评场景应优先考虑减仓/移动止损/平仓，避免激进加仓。"
            )
        if review:
            lines.append("本次为持仓复评，重点关注风险管理与止损/止盈调整。")
        return "\n".join(lines)

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
    ) -> Optional[GlmFilterResult]:
        try:
            if payload.get("glm_filter_result"):
                return GlmFilterResult.from_response(payload["glm_filter_result"])
            feature_context = {
                "features": payload.get("features") or {},
                "structure": payload.get("structure") or {},
                "market_mode": payload.get("market_mode"),
                "trend_grade": payload.get("trend_grade"),
                "mode_confidence": payload.get("mode_confidence"),
                "recent_ohlc": payload.get("recent_ohlc") or {},
            }
            return self.prefilter.should_call_deepseek(
                feature_context,
                position_state,
                next_review_time,
                is_review=bool(position_state),
            )
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
