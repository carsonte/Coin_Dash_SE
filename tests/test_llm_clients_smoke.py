from __future__ import annotations

import asyncio
import os

import pytest

from coin_dash.llm_clients import LLMClientError, call_gpt4omini, call_qwen


def _messages():
    return [{"role": "user", "content": "你是 Coin Dash SE 的测试助手，只需回复 OK。"}]


def _has_message(resp: dict) -> bool:
    if not isinstance(resp, dict):
        return False
    choices = resp.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return False
    msg = choices[0].get("message")
    return isinstance(msg, dict) and "content" in msg


def test_gpt4omini_smoke():
    if not (os.getenv("AIZEX_API_KEY") and os.getenv("AIZEX_API_BASE")):
        pytest.skip("AIZEX env not set")
    try:
        resp = asyncio.run(call_gpt4omini(_messages()))
    except LLMClientError as exc:
        if "network error" in str(exc).lower():
            pytest.skip(f"Aizex network unavailable: {exc}")
        raise
    assert _has_message(resp)


def test_qwen_smoke():
    if not (os.getenv("QWEN_API_KEY") and os.getenv("QWEN_API_BASE")):
        pytest.skip("QWEN env not set")
    try:
        resp = asyncio.run(call_qwen(_messages()))
    except LLMClientError as exc:
        if "network error" in str(exc).lower():
            pytest.skip(f"Qwen network unavailable: {exc}")
        raise
    assert _has_message(resp)
