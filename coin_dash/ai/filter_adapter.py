from __future__ import annotations

import json
import asyncio
import logging
import os
from typing import Any, Dict, List, Optional, Sequence, TYPE_CHECKING

from coin_dash.llm_clients import call_qwen
from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from ..config import GLMFilterCfg, LLMEndpointCfg

LOGGER = logging.getLogger(__name__)

TrendConsistency = tuple[str, ...]
VolatilityStatus = tuple[str, ...]
StructureRelevance = tuple[str, ...]
PatternCandidate = tuple[str, ...]

TREND_LEVELS: TrendConsistency = ("strong", "medium", "weak", "conflicting")
VOL_LEVELS: VolatilityStatus = ("low", "normal", "high", "extreme")
STRUCTURE_LEVELS: StructureRelevance = ("near_support", "near_resistance", "breakout_zone", "mid_range", "structure_missing")
PATTERN_LEVELS: PatternCandidate = ("none", "breakout", "reversal", "trend_continuation")


def _append_unique(target: List[str], values: Sequence[str]) -> None:
    for val in values:
        if val not in target:
            target.append(val)


def _normalize_enum(value: Any, allowed: Sequence[str], default: str) -> str:
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in allowed:
            return lowered
    return default


class GlmFilterResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    should_call_deepseek: bool = True
    reason: str = "ok: glm_filter"
    trend_consistency: str = "weak"
    volatility_status: str = "normal"
    structure_relevance: str = "structure_missing"
    pattern_candidate: str = "none"
    danger_flags: List[str] = Field(default_factory=list)
    met_conditions: List[str] = Field(default_factory=list)
    failed_conditions: List[str] = Field(default_factory=list)

    @classmethod
    def from_response(cls, data: Dict[str, Any]) -> "GlmFilterResult":
        should = data.get("should_call_deepseek")
        if should is None:
            should = data.get("should_call")
        base = {
            "should_call_deepseek": bool(should) if should is not None else True,
            "reason": str(data.get("reason") or "ok: glm_decision"),
            "trend_consistency": _normalize_enum(data.get("trend_consistency"), TREND_LEVELS, "weak"),
            "volatility_status": _normalize_enum(data.get("volatility_status"), VOL_LEVELS, "normal"),
            "structure_relevance": _normalize_enum(data.get("structure_relevance"), STRUCTURE_LEVELS, "structure_missing"),
            "pattern_candidate": _normalize_enum(data.get("pattern_candidate"), PATTERN_LEVELS, "none"),
            "danger_flags": [str(flag).strip().lower() for flag in data.get("danger_flags", []) if flag is not None],
            "met_conditions": [str(flag).strip().lower() for flag in data.get("met_conditions", []) if flag is not None],
            "failed_conditions": [str(flag).strip().lower() for flag in data.get("failed_conditions", []) if flag is not None],
        }
        return cls(**base)

    def model_dump_safe(self) -> Dict[str, Any]:
        return self.model_dump()


class PreFilterClient:
    """
    Market-state filter backed by Qwen（OpenAI 兼容接口）。
    - 输出结构化标签（趋势一致性、波动、结构位置、形态候选等）。
    - 按规则挡掉危险/垃圾行情，作为 DeepSeek 的成本守门人。
    """

    def __init__(
        self,
        cfg: Optional["GLMFilterCfg"] = None,
        glm_client_cfg: Optional["LLMEndpointCfg"] = None,
        api_key: Optional[str] = None,
        endpoint: Optional[str] = None,
        glm_fallback_cfg: Optional["LLMEndpointCfg"] = None,
    ) -> None:
        self.enabled = bool(getattr(cfg, "enabled", True))
        self.on_error = (getattr(cfg, "on_error", None) or "call_deepseek").lower()
        primary_key = glm_client_cfg.api_key if glm_client_cfg else None
        fallback_key = glm_fallback_cfg.api_key if glm_fallback_cfg else None
        self.api_key = api_key or primary_key or os.getenv("QWEN_API_KEY") or fallback_key or ""

        primary_model = glm_client_cfg.model if glm_client_cfg else None
        fallback_model = glm_fallback_cfg.model if glm_fallback_cfg else None
        self.model = (
            primary_model
            or os.getenv("QWEN_MODEL")
            or fallback_model
            or "qwen-turbo-2025-07-15"
        )

        primary_base = glm_client_cfg.api_base if glm_client_cfg else None
        fallback_base = glm_fallback_cfg.api_base if glm_fallback_cfg else None
        self.endpoint = (
            endpoint
            or primary_base
            or os.getenv("QWEN_API_BASE")
            or fallback_base
            or "https://api.ezworkapi.top"
        ).rstrip("/")
        self.session = None

    def should_call_deepseek(
        self,
        feature_context: Dict[str, Any],
        position_state: Optional[Dict[str, Any]] = None,
        next_review_time: Optional[str] = None,
        is_review: bool = False,
    ) -> GlmFilterResult:
        # 关闭或缺少 key 时，保持原行为：直接放行。
        if not self.enabled:
            return GlmFilterResult(
                should_call_deepseek=True,
                reason="prefilter_disabled",
                trend_consistency="weak",
                volatility_status="normal",
                structure_relevance="structure_missing",
                pattern_candidate="none",
            )
        strong = self._strong_triggers(feature_context, position_state)
        if not self.api_key:
            return GlmFilterResult(
                should_call_deepseek=True,
                reason="prefilter_skipped_no_api_key",
                trend_consistency="weak",
                volatility_status="normal",
                structure_relevance="structure_missing",
                pattern_candidate="none",
                met_conditions=strong,
            )
        try:
            payload = self._build_prompt(feature_context, position_state, next_review_time, model=self.model, strong_triggers=strong)
            resp = self._chat_completion(payload)
            data = self._parse_json(resp)
            glm_result = GlmFilterResult.from_response(data)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("qwen_prefilter_error err=%s", exc)
            return self._fallback_on_error(str(exc))
        glm_result = self._apply_rules(glm_result, is_review=is_review, strong_triggers=strong)
        return glm_result

    @staticmethod
    def _current_price(features: Dict[str, Any]) -> float:
        for key in ("price_30m", "price_1h", "price_4h"):
            if key in features:
                return float(features[key])
        return 0.0

    def _strong_triggers(self, feature_context: Dict[str, Any], position_state: Optional[Dict[str, Any]]) -> list[str]:
        features = feature_context.get("features") or {}
        structure = feature_context.get("structure") or {}
        recent = feature_context.get("recent_ohlc") or {}
        price = self._current_price(features)
        atr_val = float(features.get("atr_30m", 0.0) or 0.0)
        triggers: list[str] = []

        # 价格快速波动：最近两根收盘超过 0.3%
        last_closes = (recent.get("30m") or [])[-2:]
        if len(last_closes) == 2:
            prev_close = float(last_closes[0].get("close", 0.0))
            last_close = float(last_closes[1].get("close", 0.0))
            if prev_close > 0:
                move = abs(last_close - prev_close) / prev_close
                if move >= 0.003:
                    triggers.append("price_move_gt_0.3pct")

        # 结构突破：价格越过最近支撑/阻力 0.1%
        if structure:
            supports = [lvl.get("support", 0.0) for lvl in structure.values() if lvl]
            resistances = [lvl.get("resistance", 0.0) for lvl in structure.values() if lvl]
            sup = min(supports) if supports else 0.0
            res = max(resistances) if resistances else 0.0
            if price and res and price >= res * 1.001:
                triggers.append("structure_breakout_up")
            if price and sup and price <= sup * 0.999:
                triggers.append("structure_breakout_down")

        # 波动加速：ATR 向上趋势
        if features.get("atr_trend_30m") == "rising" or features.get("atr_trend_1h") == "rising":
            triggers.append("atr_expanding")

        # EMA 翻转：快线与慢线跨周期方向相反
        ema_diff = float(features.get("ema20_30m", 0.0) - features.get("ema60_30m", 0.0))
        ema_diff_1h = float(features.get("ema20_1h", 0.0) - features.get("ema60_1h", 0.0))
        if ema_diff * ema_diff_1h < 0:
            triggers.append("ema_flip_cross_tf")

        # 持仓偏离：现价相对入场偏离超过 0.5 ATR
        if position_state and atr_val > 0 and price > 0:
            entry = float(position_state.get("entry", 0.0))
            if entry > 0:
                if abs(price - entry) >= 0.5 * atr_val:
                    triggers.append("position_price_deviation_gt_0.5atr")

        return triggers

    def _build_prompt(
        self,
        feature_context: Dict[str, Any],
        position_state: Optional[Dict[str, Any]],
        next_review_time: Optional[str],
        model: str,
        strong_triggers: Sequence[str],
    ) -> Dict[str, Any]:
        schema = (
            "返回严格的 JSON（无多余文字）：\n"
            '{\n'
            '  "should_call_deepseek": true/false,\n'
            '  "reason": "ok: ... / blocked: ...",\n'
            '  "trend_consistency": "strong|medium|weak|conflicting",\n'
            '  "volatility_status": "low|normal|high|extreme",\n'
            '  "structure_relevance": "near_support|near_resistance|breakout_zone|mid_range|structure_missing",\n'
            '  "pattern_candidate": "none|breakout|reversal|trend_continuation",\n'
            '  "danger_flags": ["..."],\n'
            '  "met_conditions": ["..."],\n'
            '  "failed_conditions": ["..."]\n'
            "}\n"
        )
        guardrails = [
            "必须挡掉（should_call_deepseek=false）：趋势冲突、ATR 极端、长影/whipsaw、结构缺失或中轴、没有形态候选、流动性差。",
            "应该放行：趋势 strong/medium，波动 normal/适度 high，结构在支撑/阻力/突破区，存在 breakout/reversal/trend_continuation 候选。",
            "边界情况 trend=weak 或 high 波动可标记 marginal，附上 danger_flags，但仍可调用。",
        ]
        content = [
            "你是“市场状态过滤器 + 成本守门人”，为 DeepSeek 决策做预筛。",
            "仅输出 JSON，不要任何 Markdown 或解释。",
            schema,
            "决策规则（务必遵守）：",
            *[f"- {line}" for line in guardrails],
            "对输入的多周期特征做标签提取并给出 should_call_deepseek。",
            f"strong_triggers: {json.dumps(list(strong_triggers), ensure_ascii=False)}",
            f"feature_context: {json.dumps(feature_context, ensure_ascii=False)}",
        ]
        if position_state:
            content.append(f"position_state: {json.dumps(position_state, ensure_ascii=False)}")
        if next_review_time:
            content.append(f"next_review_time: {next_review_time}")
        messages = [{"role": "user", "content": "\n".join(content)}]
        return {"model": model, "messages": messages, "temperature": 0, "stream": False}

    def _chat_completion(self, payload: Dict[str, Any]) -> str:
        attempts = 3
        last_exc: Exception | None = None
        last_exc: Exception | None = None
        for _ in range(attempts):
            try:
                resp = asyncio.run(
                    call_qwen(
                        payload.get("messages") or [],
                        api_key=self.api_key,
                        api_base=self.endpoint,
                        model=self.model,
                        request_timeout=8,
                        temperature=payload.get("temperature", 0),
                    )
                )
                if isinstance(resp, dict):
                    choices = resp.get("choices") or []
                    if choices and isinstance(choices[0], dict):
                        return str((choices[0].get("message") or {}).get("content") or "")
                raise ValueError("qwen_prefilter_empty_response")
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                continue
        if last_exc:
            raise last_exc

    @staticmethod
    def _parse_json(content: str) -> Dict[str, Any]:
        raw = content.strip()
        # Many providers wrap JSON in ```json fences; unwrap them before parsing.
        if raw.startswith("```"):
            lines = raw.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            raw = "\n".join(lines).strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            # Last attempt: extract the largest {...} block.
            start = raw.find("{")
            end = raw.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(raw[start : end + 1])
                except Exception:
                    pass
            raise ValueError(f"prefilter JSON parse error: {content}") from exc

    def _apply_rules(self, result: GlmFilterResult, is_review: bool, strong_triggers: Sequence[str]) -> GlmFilterResult:
        res = result.copy(deep=True)
        _append_unique(res.met_conditions, strong_triggers)

        def block(reason: str, flag: Optional[str] = None, failed: Optional[str] = None) -> None:
            res.should_call_deepseek = False
            res.reason = reason
            if flag:
                _append_unique(res.danger_flags, [flag])
            if failed:
                _append_unique(res.failed_conditions, [failed])

        # 硬性挡掉
        if res.trend_consistency == "conflicting":
            block("blocked: trend_conflict", "trend_conflict", "trend_conflict")
        if res.volatility_status == "extreme":
            block("blocked: atr_extreme", "atr_extreme", "atr_extreme")
        if res.structure_relevance == "mid_range":
            block("blocked: mid_range_structure", "no_structure_edge", "mid_range_structure")
        if res.structure_relevance == "structure_missing":
            block("blocked: structure_missing", "structure_missing", "structure_missing")
        if res.pattern_candidate == "none":
            block("blocked: no_pattern_candidate", "no_pattern_candidate", "no_pattern_candidate")
        if any(flag in res.danger_flags for flag in ("wick_noise", "whipsaw", "wick", "noise")):
            block("blocked: wick_noise", "wick_noise", "wick_noise")
        if any(flag in res.danger_flags for flag in ("low_liquidity",)):
            block("blocked: low_liquidity", "low_liquidity", "low_liquidity")
        if any(flag in res.danger_flags for flag in ("chop_range", "choppy", "chop")):
            block("blocked: chop_range", "chop_range", "chop_range")

        # 记录满足/不满足的条件
        allow_trend = res.trend_consistency in ("strong", "medium")
        allow_vol = res.volatility_status in ("normal", "high")
        allow_structure = res.structure_relevance in ("near_support", "near_resistance", "breakout_zone")
        allow_pattern = res.pattern_candidate in ("breakout", "reversal", "trend_continuation")
        if allow_trend:
            _append_unique(res.met_conditions, ["trend_ok"])
        else:
            _append_unique(res.failed_conditions, ["trend_weak"])
        if allow_vol:
            _append_unique(res.met_conditions, ["volatility_ok"])
        else:
            _append_unique(res.failed_conditions, ["volatility_outside"])
        if allow_structure:
            _append_unique(res.met_conditions, ["structure_ok"])
        else:
            _append_unique(res.failed_conditions, ["structure_not_ready"])
        if allow_pattern:
            _append_unique(res.met_conditions, ["pattern_candidate_ok"])
        else:
            _append_unique(res.failed_conditions, ["pattern_missing"])

        if not res.should_call_deepseek:
            return res

        good = allow_trend and allow_vol and allow_structure and allow_pattern
        marginal = allow_structure and allow_pattern and res.trend_consistency != "conflicting" and res.volatility_status != "extreme"

        if good:
            res.should_call_deepseek = True
            res.reason = res.reason or "ok: good_opportunity"
        elif is_review:
            res.should_call_deepseek = True
            res.reason = res.reason or "ok: review_priority"
        elif marginal:
            res.should_call_deepseek = True
            res.reason = res.reason or "ok: marginal"
        else:
            res.should_call_deepseek = False
            res.reason = res.reason or "blocked: insufficient_edge"
        return res

    def _fallback_on_error(self, detail: str) -> GlmFilterResult:
        should_call = self.on_error == "call_deepseek"
        reason = f"prefilter_error:{detail}"
        return GlmFilterResult(
            should_call_deepseek=should_call,
            reason=reason,
            trend_consistency="weak",
            volatility_status="normal",
            structure_relevance="structure_missing",
            pattern_candidate="none",
            danger_flags=["prefilter_error"],
            failed_conditions=["prefilter_error"],
        )
