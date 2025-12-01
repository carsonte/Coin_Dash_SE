from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from typing import Any, Dict

import requests

LOGGER = logging.getLogger(__name__)

PROMPT = (
    "你是一名“交易机会初筛助手”，你的任务不是给出交易方向，\n"
    "而是判断当前市场是否值得调用更贵的大模型（DeepSeek）进行深度决策。\n\n"
    "输入为多周期特征上下文（mtf_context），其中包括：\n"
    "- 趋势评分（trend scores）\n"
    "- 市场模式（market mode）\n"
    "- 多周期关键结构位（support/resistance）\n"
    "- recent_ohlc（最近 K 线序列）\n"
    "- 波动率（ATR、波动比例）\n"
    "- 均线（EMA20/EMA60）\n"
    "- 成交量强弱（volume signal）\n\n"
    "【你的职责】\n"
    "请根据这些信息判断：\n"
    "1. 当前是否处于潜在的交易机会窗口？\n"
    "2. 是否需要让更贵的大模型 DeepSeek 介入？\n\n"
    "【should_call 的判断逻辑（必须遵守）】\n"
    "- 满足以下任意条件 → should_call = true\n"
    "    - 多周期趋势较一致（如 1h + 4h 同方向）\n"
    "    - 是否接近结构位/突破点位（结构边附近）\n"
    "    - ATR/波动放大，市场变得活跃\n"
    "    - 价格出现快速拉升/下跌\n"
    "    - 近期 K 线显示有明确方向性情绪\n\n"
    "- 满足以下任意条件 → should_call = false\n"
    "    - 多周期趋势严重分歧\n"
    "    - 当前价格处于区间中部（range_midzone）\n"
    "    - 波动极低、无方向性\n"
    "    - 没有明确结构边、没有风险边界\n"
    "    - K 线噪声大、方向不明\n\n"
    "【输出格式（必须严格 JSON）】\n"
    "只允许输出下面的 JSON 字段：\n\n"
    "{\n"
    '  "should_call": true 或 false,\n'
    '  "reason": "一句中文原因",\n'
    '  "next_check_minutes": 数字(建议 10 / 15 / 30)\n'
    "}\n\n"
    "你必须严格输出 JSON，不得包含额外文字，否则视为错误。\n"
)


def _default_fallback(reason: str = "fallback_due_to_glm_failure") -> Dict[str, Any]:
    """失败兜底：确保 should_call 为 True，避免漏掉机会。"""
    return {"should_call": True, "reason": reason, "next_check_minutes": 5}


async def _post_glm(payload: Dict[str, Any], timeout: float) -> str:
    """使用同步 requests 发送 GLM 请求，放入线程避免阻塞。"""
    api_key = os.getenv("ZHIPUAI_API_KEY") or ""
    if not api_key:
        raise RuntimeError("ZHIPUAI_API_KEY not set")
    base = (os.getenv("ZHIPUAI_API_BASE") or "https://open.bigmodel.cn/api/paas/v4").rstrip("/")
    url = f"{base}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    def _do_post() -> str:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    return await asyncio.to_thread(_do_post)


def _parse_json(content: str) -> Dict[str, Any]:
    """宽松解析 GLM 返回的 JSON，去掉 ```json 包裹。"""
    raw = content.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    return json.loads(raw)


async def call_glm_with_retry(payload: Dict[str, Any], max_retries: int = 3, timeout: float = 6.0) -> Dict[str, Any]:
    """带重试的 GLM 调用：网络/解析异常都会重试，全部失败则返回兜底。"""
    fallback = _default_fallback()
    for attempt in range(1, max_retries + 1):
        try:
            content = await asyncio.wait_for(_post_glm(payload, timeout), timeout=timeout + 1)
            return _parse_json(content)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("glm_call_failed attempt=%s err=%s", attempt, exc)
            if attempt < max_retries:
                await asyncio.sleep(0.3 + random.uniform(0, 0.5))
    return fallback


async def glm_screen_opportunity(mtf_context) -> Dict[str, Any]:
    """
    机会初筛：调用 GLM 判断是否需要 DeepSeek。
    - 解析失败或字段缺失时，should_call 强制为 True（兜底）。
    """
    model = os.getenv("ZHIPUAI_MODEL", "glm-4.5-flash")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": f"{PROMPT}\n\nmtf_context:\n{json.dumps(mtf_context, ensure_ascii=False, indent=2)}"}],
        "temperature": 0,
        "stream": False,
    }
    raw = await call_glm_with_retry(payload)
    if not isinstance(raw, dict):
        return _default_fallback("fallback_invalid_response_type")
    should_call = raw.get("should_call")
    reason = raw.get("reason")
    next_check = raw.get("next_check_minutes")
    if should_call is None or reason is None or next_check is None:
        return _default_fallback("fallback_missing_fields")
    try:
        return {
            "should_call": bool(should_call),
            "reason": str(reason),
            "next_check_minutes": int(next_check),
        }
    except Exception:
        return _default_fallback("fallback_cast_error")


def glm_screen_sync(mtf_context) -> Dict[str, Any]:
    """同步包装，便于在同步 orchestrator 中调用。"""
    try:
        return asyncio.run(glm_screen_opportunity(mtf_context))
    except RuntimeError:
        # 如果事件循环已存在，退回兜底
        return _default_fallback("fallback_event_loop_busy")
