from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List

import requests

from .errors import LLMClientError


DEFAULT_TIMEOUT = 30
DEFAULT_MODEL = "qwen-turbo-2025-07-15"


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
        raise LLMClientError("invalid JSON response from Qwen") from exc


async def call_qwen(messages: List[Dict[str, Any]], **kwargs: Any) -> Dict[str, Any]:
    """
    调用 Qwen（OpenAI 兼容接口）。
    - 读取环境变量 QWEN_API_KEY / QWEN_API_BASE / QWEN_MODEL
    - 默认模型 qwen-turbo-2025-07-15
    """
    api_key = kwargs.pop("api_key", None) or os.getenv("QWEN_API_KEY")
    base = kwargs.pop("api_base", None) or os.getenv("QWEN_API_BASE")
    model = kwargs.pop("model", None) or os.getenv("QWEN_MODEL", DEFAULT_MODEL)
    if not api_key:
        raise LLMClientError("QWEN_API_KEY is missing")
    if not base:
        raise LLMClientError("QWEN_API_BASE is missing")

    _validate_messages(messages)

    timeout = float(kwargs.pop("request_timeout", DEFAULT_TIMEOUT))
    payload: Dict[str, Any] = {"model": model, "messages": messages}
    if kwargs:
        payload.update(kwargs)

    url = f"{base.rstrip('/')}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        return await asyncio.to_thread(_sync_post, url, headers, payload, timeout)
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "unknown"
        text = exc.response.text if exc.response is not None else str(exc)
        raise LLMClientError(f"Qwen request failed: status={status} body={text[:200]}") from exc
    except requests.RequestException as exc:  # noqa: BLE001
        raise LLMClientError(f"Qwen network error: {exc}") from exc
