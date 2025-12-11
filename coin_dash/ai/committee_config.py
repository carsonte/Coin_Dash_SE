from __future__ import annotations

import os

# 模型别名（用于权重匹配）；实际模型 ID 由环境变量提供
MODEL_DEEPSEEK = "deepseek"
MODEL_GPT4OMINI = "gpt-4o-mini"
MODEL_QWEN = "qwen"
QWEN_MODEL_ID = os.getenv("QWEN_MODEL") or "qwen-turbo-2025-07-15"

# 前置委员会权重（gpt-4o-mini + qwen）
FRONT_WEIGHTS = {
    MODEL_GPT4OMINI: 0.6,
    MODEL_QWEN: 0.4,
}

# 完整委员会权重（deepseek + gpt-4o-mini + qwen）
COMMITTEE_WEIGHTS = {
    MODEL_DEEPSEEK: 0.5,
    MODEL_GPT4OMINI: 0.3,
    MODEL_QWEN: 0.2,
}
