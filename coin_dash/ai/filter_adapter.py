from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

import requests


class PreFilterClient:
    """
    Lightweight pre-decider backed by GLM-4.5-Flash to decide whether a DeepSeek
    call is necessary. Falls back to True on any failure.
    """

    def __init__(self, api_key: Optional[str] = None, endpoint: Optional[str] = None) -> None:
        self.api_key = api_key or os.getenv("ZHIPUAI_API_KEY") or ""
        self.model = os.getenv("ZHIPUAI_MODEL", "glm-4.5-flash")
        self.endpoint = (
            endpoint
            or os.getenv("ZHIPUAI_API_BASE")
            or "https://open.bigmodel.cn/api/paas/v4/chat/completions"
        ).rstrip("/")
        # OpenRouter 兼容：可选填 HTTP-Referer/X-Title（不填也能用）
        self.extra_headers: Dict[str, str] = {}
        referer = os.getenv("ZHIPU_HTTP_REFERER") or os.getenv("OPENROUTER_HTTP_REFERER")
        title = os.getenv("ZHIPU_HTTP_TITLE") or os.getenv("OPENROUTER_HTTP_TITLE")
        if referer:
            self.extra_headers["HTTP-Referer"] = referer
        if title:
            self.extra_headers["X-Title"] = title
        self.session = requests.Session()

    def should_call_deepseek(
        self,
        feature_context: Dict[str, Any],
        position_state: Optional[Dict[str, Any]] = None,
        next_review_time: Optional[str] = None,
    ) -> Dict[str, Any]:
        try:
            # Fast-path: strong triggers always force DeepSeek (no extra LLM call).
            strong = self._strong_triggers(feature_context, position_state)
            if strong:
                return {"should_call": True, "reason": "; ".join(strong)}
            if not self.api_key:
                # No GLM key: keep behavior identical to原流程，直接放行 DeepSeek。
                return {"should_call": True, "reason": "prefilter_skipped_no_api_key"}
            payload = self._build_prompt(feature_context, position_state, next_review_time, model=self.model)
            resp = self._chat_completion(payload)
            data = self._parse_json(resp)
            should_call = bool(data.get("should_call", True))
            reason = str(data.get("reason", "glm_decision"))
            return {"should_call": should_call, "reason": reason}
        except Exception as exc:
            return {"should_call": True, "reason": f"prefilter_fallback:{exc}"}

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
    ) -> Dict[str, Any]:
        content = [
            "You are a JSON-only pre-decider. Reply with a JSON object: {\"should_call\": true/false, \"reason\": \"...\"}.",
            "Goal: decide if we should call DeepSeek (trading LLM). Only skip when market is quiet or redundant.",
            "Consider:",
            "- recent price change (e.g., <0.1% over last bars -> maybe skip)",
            "- structure proximity or breakout",
            "- ATR expansion/volatility",
            "- EMA alignment/flip",
            "- open position drift vs entry",
            "- next review time if provided",
            "Be conservative: default should_call=true when uncertain.",
            f"feature_context: {json.dumps(feature_context, ensure_ascii=False)}",
        ]
        if position_state:
            content.append(f"position_state: {json.dumps(position_state, ensure_ascii=False)}")
        if next_review_time:
            content.append(f"next_review_time: {next_review_time}")
        messages = [{"role": "user", "content": "\n".join(content)}]
        return {"model": model, "messages": messages, "temperature": 0}

    def _chat_completion(self, payload: Dict[str, Any]) -> str:
        url = f"{self.endpoint}"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        headers.update(self.extra_headers)
        resp = self.session.post(url, json=payload, headers=headers, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

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
