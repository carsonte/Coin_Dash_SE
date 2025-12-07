from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field, ConfigDict


class ModelDecision(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_name: str = Field(description='模型名称，如 "deepseek" / "gpt-4o-mini" / "glm-4.5v"')
    bias: str = Field(description='交易倾向："long" / "short" / "no-trade"')
    confidence: float = Field(ge=0.0, le=1.0, description="模型内部置信度，0-1")
    entry: Optional[float] = Field(default=None, description="建议入场价")
    sl: Optional[float] = Field(default=None, description="止损")
    tp: Optional[float] = Field(default=None, description="止盈")
    rr: Optional[float] = Field(default=None, description="风险收益比")
    raw_response: Optional[Dict] = Field(default=None, description="原始 LLM 响应，便于调试")
    meta: Optional[Dict] = Field(default=None, description="附加结构信息，如形态标签")


class CommitteeDecision(BaseModel):
    final_decision: str = Field(description='最终方向："long" / "short" / "no-trade"')
    final_confidence: float = Field(ge=0.0, le=1.0, description="委员会置信度，0-1")
    committee_score: float = Field(description="加权得分，范围 [-1, 1]")
    conflict_level: str = Field(description='冲突程度："low" / "medium" / "high"')
    members: List[ModelDecision] = Field(description="参与投票的模型结果明细")
