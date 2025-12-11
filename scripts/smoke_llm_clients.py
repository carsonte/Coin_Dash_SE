from __future__ import annotations

import asyncio
import os

from coin_dash.llm_clients import LLMClientError, call_gpt4omini, call_qwen


async def _run_client(name: str, func) -> None:
    messages = [{"role": "user", "content": "你是 Coin Dash SE 的测试助手，只需回复 OK。"}]
    try:
        resp = await func(messages)
        content = ""
        if isinstance(resp, dict):
            choices = resp.get("choices") or []
            if choices and isinstance(choices[0], dict):
                msg = choices[0].get("message") or {}
                content = str(msg.get("content") or "")
        print(f"{name}: ok -> {content[:50]!r}")
    except LLMClientError as exc:
        print(f"{name}: LLM error -> {exc}")
    except Exception as exc:  # noqa: BLE001
        print(f"{name}: unexpected error -> {exc}")


async def main() -> None:
    await _run_client("gpt-4o-mini@aizex", call_gpt4omini)
    qwen_name = os.getenv("QWEN_MODEL") or "qwen-turbo-2025-07-15"
    await _run_client(qwen_name, call_qwen)


if __name__ == "__main__":
    asyncio.run(main())
