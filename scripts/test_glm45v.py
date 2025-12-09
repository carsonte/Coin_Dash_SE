from __future__ import annotations

import os
import sys
from typing import Any, Dict

import requests


def _build_payload(model: str) -> Dict[str, Any]:
    return {"model": model, "messages": [{"role": "user", "content": "只回复 OK"}]}


def main() -> int:
    key = os.getenv("ZHIPUAI_API_KEY")
    base = os.getenv("ZHIPUAI_API_BASE", "https://api.ezworkapi.top/api/paas/v4/chat/completions")
    model = os.getenv("ZHIPUAI_MODEL", "glm-4.5-air")
    if not key:
        print("missing ZHIPUAI_API_KEY", file=sys.stderr)
        return 1

    payload = _build_payload(model)
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    try:
        resp = requests.post(base, headers=headers, json=payload, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        print(f"glm-4.5-air ok -> {content[:200].strip()!r}")
        return 0
    except requests.HTTPError as exc:  # noqa: BLE001
        status = exc.response.status_code if exc.response is not None else "unknown"
        text = exc.response.text if exc.response is not None else str(exc)
        print(f"glm-4.5-air HTTP error status={status} body={text[:200]}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"glm-4.5-air unexpected error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
