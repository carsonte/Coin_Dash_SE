from __future__ import annotations

from typing import Dict, List

from .committee_schemas import CommitteeDecision, ModelDecision


WEIGHTS: Dict[str, float] = {
    "deepseek": 0.5,
    "gpt-4o-mini": 0.3,
    "glm-4.5-air": 0.2,
}


def _bias_to_score(bias: str) -> int:
    if bias == "long":
        return 1
    if bias == "short":
        return -1
    return 0


def _conflict_level(score_abs: float) -> str:
    if score_abs > 0.75:
        return "low"
    if score_abs >= 0.4:
        return "medium"
    return "high"


def aggregate_committee(decisions: List[ModelDecision]) -> CommitteeDecision:
    """
    根据三模型投票规则计算最终决策。
    - 权重：deepseek=0.5, gpt-4o-mini=0.3, glm-4.5-air=0.2
    - bias 映射：long=+1, short=-1, no-trade=0
    - final_score = Σ(weight_i * mapped_bias_i)
    - |score| < 0.25 -> 分歧过大，返回 no-trade
    - 若 deepseek 与另外两者完全对立（deepseek long / 二者 short，或反之），强制 no-trade
    - |score| >0.25 -> long/short；其他 no-trade
    - conflict_level：|score|>0.75 low；0.4~0.75 medium；<0.4 high
    - final_confidence：使用 |score| 截断到 [0,1]
    """
    if len(decisions) != 3:
        raise ValueError("committee expects exactly three model decisions")

    # 映射得分
    score = 0.0
    bias_map: Dict[str, int] = {}
    for d in decisions:
        bias_val = _bias_to_score(d.bias)
        weight = WEIGHTS.get(d.model_name, 0.0)
        bias_map[d.model_name] = bias_val
        score += weight * bias_val

    # 深度对冲：deepseek 与其他两人完全相反时强制 no-trade
    ds_bias = bias_map.get("deepseek", 0)
    others = [name for name in bias_map if name != "deepseek"]
    if len(others) == 2:
        o1, o2 = others
        if ds_bias == 1 and bias_map.get(o1) == -1 and bias_map.get(o2) == -1:
            score = 0.0
        if ds_bias == -1 and bias_map.get(o1) == 1 and bias_map.get(o2) == 1:
            score = 0.0

    final_decision = "no-trade"
    if score > 0.25:
        final_decision = "long"
    elif score < -0.25:
        final_decision = "short"

    score_abs = abs(score)
    conflict = _conflict_level(score_abs)
    final_confidence = max(0.0, min(1.0, score_abs))

    return CommitteeDecision(
        final_decision=final_decision,
        final_confidence=final_confidence,
        committee_score=score,
        conflict_level=conflict,
        members=decisions,
    )
