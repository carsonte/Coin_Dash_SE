from __future__ import annotations

import os

# 统一管理前置/委员会模型名称与权重，便于更换接口/模型时集中修改。
MODEL_DEEPSEEK = "deepseek"
MODEL_GPT4OMINI = "gpt-4o-mini"
MODEL_GLM = os.getenv("GLM_MODEL") or "glm-4.5-air"

# 前置委员会权重（gpt-4o-mini + glm-4.5-air）。
FRONT_WEIGHTS = {
    MODEL_GPT4OMINI: 0.6,
    MODEL_GLM: 0.4,
}

# 完整委员会权重（deepseek + gpt-4o-mini + glm-4.5-air）。
COMMITTEE_WEIGHTS = {
    MODEL_DEEPSEEK: 0.5,
    MODEL_GPT4OMINI: 0.3,
    MODEL_GLM: 0.2,
}
