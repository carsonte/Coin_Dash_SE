from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List

import requests

from .errors import LLMClientError


DEFAULT_TIMEOUT = 30
DEFAULT_GLM_BASE = "https://open.bigmodel.cn/api/paas/v4/chat/completions"


def _validate_messages(messages: List[Dict[str, Any]]) -> None:
    if not isinstance(messages, list):
        raise LLMClientError("messages must be a list of dicts")
    for msg in messages:
        if not isinstance(msg, dict):
            raise LLMClientError("each message must be a dict")


def _sync_post(url: str, headers: Dict[str, str], payload: Dict[str, Any], timeout: float) -> Dict[str, Any]:
    resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    resp.raise_for_status()
    try:
        return resp.json()
    except ValueError as exc:  # noqa: TRY003
        raise LLMClientError("invalid JSON response from GLM-4.5V") from exc


async def call_glm45v(messages: List[Dict[str, Any]], **kwargs: Any) -> Dict[str, Any]:
    """
    调用官方 GLM-4.5V 接口，返回 OpenAI 风格 response dict。
    - 读取环境变量 GLM_API_KEY / GLM_API_BASE
    - 默认模型 glm-4.5v
    - 目前仅支持文本消息，后续可扩展 image_url/video_url。
    """
    api_key = os.getenv("GLM_API_KEY")
    base = os.getenv("GLM_API_BASE") or DEFAULT_GLM_BASE
    if not api_key:
        raise LLMClientError("GLM_API_KEY is missing")

    _validate_messages(messages)

    timeout = float(kwargs.pop("request_timeout", DEFAULT_TIMEOUT))
    model = kwargs.pop("model", "glm-4.5v")
    payload: Dict[str, Any] = {"model": model, "messages": messages}
    if kwargs:
        payload.update(kwargs)

    url = base.rstrip("/")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        return await asyncio.to_thread(_sync_post, url, headers, payload, timeout)
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "unknown"
        text = exc.response.text if exc.response is not None else str(exc)
        raise LLMClientError(f"GLM-4.5V request failed: status={status} body={text[:200]}") from exc
    except requests.RequestException as exc:  # noqa: BLE001
        raise LLMClientError(f"GLM-4.5V network error: {exc}") from exc

