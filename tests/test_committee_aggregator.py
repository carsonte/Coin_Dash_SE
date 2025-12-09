from __future__ import annotations

from coin_dash.ai.committee_aggregator import aggregate_committee
from coin_dash.ai.committee_schemas import ModelDecision


def md(model_name: str, bias: str, conf: float = 0.5) -> ModelDecision:
    return ModelDecision(model_name=model_name, bias=bias, confidence=conf)


def test_long_long_short():
    decisions = [md("deepseek", "long"), md("gpt-4o-mini", "long"), md("glm-4.5-air", "short")]
    res = aggregate_committee(decisions)
    assert res.final_decision == "long"
    assert res.committee_score == 0.5 + 0.3 - 0.2
    assert res.conflict_level in ("medium", "low")


def test_ds_short_others_long_force_notrade():
    decisions = [md("deepseek", "short"), md("gpt-4o-mini", "long"), md("glm-4.5-air", "long")]
    res = aggregate_committee(decisions)
    assert res.final_decision == "no-trade"
    assert res.committee_score == 0.0
    assert res.conflict_level == "high"


def test_ds_long_others_short_force_notrade():
    decisions = [md("deepseek", "long"), md("gpt-4o-mini", "short"), md("glm-4.5-air", "short")]
    res = aggregate_committee(decisions)
    assert res.final_decision == "no-trade"
    assert res.committee_score == 0.0


def test_all_no_trade():
    decisions = [md("deepseek", "no-trade"), md("gpt-4o-mini", "no-trade"), md("glm-4.5-air", "no-trade")]
    res = aggregate_committee(decisions)
    assert res.final_decision == "no-trade"
    assert res.committee_score == 0.0
    assert res.conflict_level == "high"


def test_only_ds_long_others_neutral():
    decisions = [md("deepseek", "long"), md("gpt-4o-mini", "no-trade"), md("glm-4.5-air", "no-trade")]
    res = aggregate_committee(decisions)
    assert res.final_decision == "long"
    assert res.committee_score == 0.5
    assert res.conflict_level in ("medium", "low")
