from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Optional, Tuple
from uuid import uuid4

from .committee_aggregator import WEIGHTS, aggregate_committee
from .committee_schemas import CommitteeDecision, ModelDecision
from ..llm_clients import LLMClientError, call_glm45v, call_gpt4omini
from .models import Decision
from ..db.ai_decision_logger import AIDecisionLogger

LOGGER = logging.getLogger(__name__)


def _json_safe(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        return str(obj)


def _build_messages(symbol: str, payload: Dict[str, Any], role_hint: str) -> list[dict]:
    prompt = (
        "你是 Coin Dash SE 的{role}，请基于给定的市场特征做交易倾向判断，输出 JSON（不要有额外文本）：\n"
        '{\n  "bias": "long | short | no-trade",\n'
        '  "confidence": 0-1,\n'
        '  "entry": number | null,\n'
        '  "sl": number | null,\n'
        '  "tp": number | null,\n'
        '  "rr": number | null,\n'
        '  "meta": {"note": "可选的形态或结构说明"}\n'
        "}\n"
        "若价格字段不确定，可设为 null；请务必输出合法 JSON。"
    ).format(role=role_hint)
    return [
        {"role": "system", "content": prompt},
        {"role": "user", "content": f"symbol: {symbol}\nmarket_snapshot: {_json_safe(payload)}"},
    ]


def _parse_llm_json(raw_content: str, model_name: str) -> ModelDecision:
    try:
        data = json.loads(raw_content)
    except Exception as exc:  # noqa: BLE001
        return ModelDecision(
            model_name=model_name,
            bias="no-trade",
            confidence=0.0,
            raw_response={"error": f"json_parse_failed: {exc}", "content": raw_content},
        )
    bias = str(data.get("bias") or "no-trade").lower()
    if bias not in ("long", "short", "no-trade"):
        bias = "no-trade"
    confidence = data.get("confidence", 0.0)
    try:
        confidence = float(confidence)
    except Exception:  # noqa: BLE001
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    return ModelDecision(
        model_name=model_name,
        bias=bias,
        confidence=confidence,
        entry=data.get("entry"),
        sl=data.get("sl"),
        tp=data.get("tp"),
        rr=data.get("rr"),
        raw_response=data,
        meta=data.get("meta") or {},
    )


async def _call_gpt4omini(symbol: str, payload: Dict[str, Any]) -> ModelDecision:
    messages = _build_messages(symbol, payload, role_hint="趋势官")
    resp = await call_gpt4omini(messages, max_tokens=256)
    text = ""
    if isinstance(resp, dict):
        choices = resp.get("choices") or []
        if choices and isinstance(choices[0], dict):
            text = str((choices[0].get("message") or {}).get("content") or "")
    return _parse_llm_json(text, "gpt-4o-mini")


async def _call_glm45v(symbol: str, payload: Dict[str, Any]) -> ModelDecision:
    messages = _build_messages(symbol, payload, role_hint="结构官")
    resp = await call_glm45v(messages, model="glm-4.5v", max_tokens=256)
    text = ""
    if isinstance(resp, dict):
        choices = resp.get("choices") or []
        if choices and isinstance(choices[0], dict):
            text = str((choices[0].get("message") or {}).get("content") or "")
    return _parse_llm_json(text, "glm-4.5v")


def _decision_to_member(decision: Decision, model_name: str = "deepseek") -> ModelDecision:
    bias = "no-trade"
    if decision.decision == "open_long":
        bias = "long"
    elif decision.decision == "open_short":
        bias = "short"
    confidence_norm = decision.confidence / 100.0 if decision.confidence > 1 else decision.confidence
    return ModelDecision(
        model_name=model_name,
        bias=bias,
        confidence=max(0.0, min(1.0, confidence_norm)),
        entry=decision.entry_price,
        sl=decision.stop_loss,
        tp=decision.take_profit,
        rr=decision.risk_reward,
        raw_response=decision.meta,
        meta={"reason": decision.reason, "risk_score": decision.risk_score, "quality_score": decision.quality_score},
    )


FRONT_WEIGHTS: Dict[str, float] = {"gpt-4o-mini": 0.6, "glm-4.5v": 0.4}


async def decide_front_gate(
    symbol: str,
    payload: Dict[str, Any],
    ai_logger: Optional[AIDecisionLogger] = None,
    overrides: Optional[Dict[str, ModelDecision]] = None,
) -> CommitteeDecision:
    """前置双模型委员会（gpt-4o-mini + glm-4.5v），决定是否调用 DeepSeek。"""
    members: Dict[str, ModelDecision] = {}
    committee_id = uuid4().hex

    # GPT-4o-mini
    try:
        if overrides and "gpt-4o-mini" in overrides:
            members["gpt-4o-mini"] = overrides["gpt-4o-mini"]
        else:
            members["gpt-4o-mini"] = await _call_gpt4omini(symbol, payload)
    except (LLMClientError, Exception) as exc:  # noqa: BLE001
        LOGGER.warning("front_gate gpt-4o-mini failed: %s", exc)
        members["gpt-4o-mini"] = ModelDecision(
            model_name="gpt-4o-mini",
            bias="no-trade",
            confidence=0.0,
            raw_response={"error": str(exc)},
        )

    # GLM-4.5V
    try:
        if overrides and "glm-4.5v" in overrides:
            members["glm-4.5v"] = overrides["glm-4.5v"]
        else:
            members["glm-4.5v"] = await _call_glm45v(symbol, payload)
    except (LLMClientError, Exception) as exc:  # noqa: BLE001
        LOGGER.warning("front_gate glm-4.5v failed: %s", exc)
        members["glm-4.5v"] = ModelDecision(
            model_name="glm-4.5v",
            bias="no-trade",
            confidence=0.0,
            raw_response={"error": str(exc)},
        )

    m1 = members["gpt-4o-mini"]
    m2 = members["glm-4.5v"]

    final_decision = "no-trade"
    committee_score = 0.0
    final_confidence = 0.0
    conflict_level = "high" if m1.bias != m2.bias else "low"

    if m1.bias == m2.bias:
        conflict_level = "low"
        if m1.bias == "no-trade":
            final_decision = "no-trade"
        else:
            conf = min(m1.confidence, m2.confidence)
            if conf < 0.55:
                final_decision = "no-trade"
                final_confidence = conf
                committee_score = 0.0
                conflict_level = "medium"
            else:
                final_decision = m1.bias
                final_confidence = conf
                committee_score = conf * (1 if final_decision == "long" else -1)
    else:
        final_decision = "no-trade"
        committee_score = 0.0
        final_confidence = 0.0
        conflict_level = "high"

    committee = CommitteeDecision(
        final_decision=final_decision,
        final_confidence=final_confidence,
        committee_score=committee_score,
        conflict_level=conflict_level,
        members=[m1, m2],
    )

    def _log(md: ModelDecision, is_final: bool = False, extra: Optional[Dict[str, Any]] = None) -> None:
        if ai_logger is None:
            return
        ai_logger.log_decision(
            decision_type="decision",
            symbol=symbol,
            payload=payload,
            result=extra or md.model_dump(),
            tokens_used=None,
            latency_ms=None,
            model_name=md.model_name if not is_final else "committee_front",
            committee_id=committee_id,
            weight=FRONT_WEIGHTS.get(md.model_name) if not is_final else None,
            is_final=is_final,
        )

    _log(m1)
    _log(m2)
    _log(
        ModelDecision(
            model_name="committee_front",
            bias=committee.final_decision,
            confidence=committee.final_confidence,
            entry=None,
            sl=None,
            tp=None,
            rr=None,
            raw_response=committee.model_dump(),
        ),
        is_final=True,
        extra=committee.model_dump(),
    )
    return committee


def decide_front_gate_sync(
    symbol: str,
    payload: Dict[str, Any],
    ai_logger: Optional[AIDecisionLogger] = None,
    overrides: Optional[Dict[str, ModelDecision]] = None,
) -> CommitteeDecision:
    """同步封装，B1 前置双模型委员会。"""
    return asyncio.run(decide_front_gate(symbol, payload, ai_logger=ai_logger, overrides=overrides))


async def decide_with_committee(
    symbol: str,
    payload: Dict[str, Any],
    deepseek_client,
    ai_logger: Optional[AIDecisionLogger] = None,
    overrides: Optional[Dict[str, ModelDecision]] = None,
) -> Tuple[CommitteeDecision, Optional[Decision]]:
    """
    并行调用 DeepSeek / GPT-4o-mini / GLM-4.5V，聚合为委员会决策。
    - overrides 可用于测试，直接提供 ModelDecision 替换真实调用。
    """
    members: Dict[str, ModelDecision] = {}
    committee_id = uuid4().hex
    logger = ai_logger or getattr(deepseek_client, "ai_logger", None)
    ds_primary: Optional[Decision] = None

    # DeepSeek (同步客户端，放线程池)
    try:
        if overrides and "deepseek" in overrides:
            ds_member = overrides["deepseek"]
            ds_primary = None
        else:
            ds_primary = await asyncio.to_thread(deepseek_client.decide_trade, symbol, payload)
            ds_member = _decision_to_member(ds_primary, "deepseek")
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("committee deepseek failed: %s", exc)
        ds_member = ModelDecision(
            model_name="deepseek",
            bias="no-trade",
            confidence=0.0,
            raw_response={"error": str(exc)},
        )
        ds_primary = None
    members["deepseek"] = ds_member

    # GPT-4o-mini
    try:
        if overrides and "gpt-4o-mini" in overrides:
            members["gpt-4o-mini"] = overrides["gpt-4o-mini"]
        else:
            members["gpt-4o-mini"] = await _call_gpt4omini(symbol, payload)
    except (LLMClientError, Exception) as exc:  # noqa: BLE001
        LOGGER.warning("committee gpt-4o-mini failed: %s", exc)
        members["gpt-4o-mini"] = ModelDecision(
            model_name="gpt-4o-mini",
            bias="no-trade",
            confidence=0.0,
            raw_response={"error": str(exc)},
        )

    # GLM-4.5V
    try:
        if overrides and "glm-4.5v" in overrides:
            members["glm-4.5v"] = overrides["glm-4.5v"]
        else:
            members["glm-4.5v"] = await _call_glm45v(symbol, payload)
    except (LLMClientError, Exception) as exc:  # noqa: BLE001
        LOGGER.warning("committee glm-4.5v failed: %s", exc)
        members["glm-4.5v"] = ModelDecision(
            model_name="glm-4.5v",
            bias="no-trade",
            confidence=0.0,
            raw_response={"error": str(exc)},
        )

    ordered = [members.get("deepseek"), members.get("gpt-4o-mini"), members.get("glm-4.5v")]
    if any(m is None for m in ordered):
        raise RuntimeError("committee missing member decisions")

    committee = aggregate_committee(ordered)  # type: ignore[arg-type]

    def _log_member(md: ModelDecision, is_final: bool = False, extra_result: Optional[Dict[str, Any]] = None) -> None:
        if logger is None:
            return
        result_payload = extra_result or md.model_dump()
        logger.log_decision(
            decision_type="decision",
            symbol=symbol,
            payload=payload,
            result=result_payload,
            tokens_used=None,
            latency_ms=None,
            model_name=md.model_name if not is_final else "committee",
            committee_id=committee_id,
            weight=WEIGHTS.get(md.model_name) if not is_final else None,
            is_final=is_final,
        )

    # 记录成员
    for md in ordered:
        _log_member(md)
    # 记录委员会最终结果
    final_md = ModelDecision(
        model_name="committee",
        bias=committee.final_decision,
        confidence=committee.final_confidence,
        entry=None,
        sl=None,
        tp=None,
        rr=None,
        raw_response=committee.model_dump(),
        meta={"committee_score": committee.committee_score, "conflict_level": committee.conflict_level},
    )
    _log_member(final_md, is_final=True, extra_result=committee.model_dump())
    return committee, ds_primary


def decide_with_committee_sync(
    symbol: str,
    payload: Dict[str, Any],
    deepseek_client,
    ai_logger: Optional[AIDecisionLogger] = None,
    overrides: Optional[Dict[str, ModelDecision]] = None,
) -> Tuple[CommitteeDecision, Optional[Decision]]:
    """同步包装，便于在同步管线中使用。"""
    return asyncio.run(decide_with_committee(symbol, payload, deepseek_client, ai_logger=ai_logger, overrides=overrides))
