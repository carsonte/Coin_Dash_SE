from __future__ import annotations

import asyncio
import os

import pytest

from coin_dash.llm_clients import LLMClientError, call_glm45v, call_gpt4omini


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
    resp = asyncio.run(call_gpt4omini(_messages()))
    assert _has_message(resp)


def test_glm45v_smoke():
    if not os.getenv("GLM_API_KEY"):
        pytest.skip("GLM_API_KEY not set")
    resp = asyncio.run(call_glm45v(_messages()))
    assert _has_message(resp)
