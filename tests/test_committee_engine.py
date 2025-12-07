from __future__ import annotations

from sqlalchemy import text

from coin_dash.ai.committee_engine import decide_with_committee_sync
from coin_dash.ai.committee_schemas import ModelDecision
from coin_dash.ai.models import Decision
from coin_dash.config import DatabaseCfg
from coin_dash.db.services import DatabaseServices


class StubDeepSeek:
    def __init__(self, decision: Decision, logger=None) -> None:
        self._decision = decision
        self.ai_logger = logger

    def decide_trade(self, symbol, payload, glm_result=None):  # noqa: ANN001, ANN201
        return self._decision


def test_decide_with_committee_long_wins(monkeypatch):
    ds_decision = Decision(
        decision="open_long",
        entry_price=100,
        stop_loss=90,
        take_profit=120,
        risk_reward=2.0,
        confidence=80,
        reason="ds",
    )
    gpt_md = ModelDecision(model_name="gpt-4o-mini", bias="long", confidence=0.6)
    glm_md = ModelDecision(model_name="glm-4.5v", bias="no-trade", confidence=0.1)
    committee, primary = decide_with_committee_sync(
        "BTCUSDm",
        {"features": {"price_30m": 100}},
        StubDeepSeek(ds_decision),
        overrides={"gpt-4o-mini": gpt_md, "glm-4.5v": glm_md},
    )
    assert primary is ds_decision
    assert committee.final_decision == "long"
    assert committee.committee_score == 0.5 + 0.3


def test_decide_with_committee_veto(monkeypatch):
    ds_decision = Decision(
        decision="open_long",
        entry_price=100,
        stop_loss=90,
        take_profit=120,
        risk_reward=2.0,
        confidence=80,
        reason="ds",
    )
    gpt_md = ModelDecision(model_name="gpt-4o-mini", bias="short", confidence=0.6)
    glm_md = ModelDecision(model_name="glm-4.5v", bias="short", confidence=0.6)
    committee, primary = decide_with_committee_sync(
        "BTCUSDm",
        {"features": {"price_30m": 100}},
        StubDeepSeek(ds_decision),
        overrides={"gpt-4o-mini": gpt_md, "glm-4.5v": glm_md},
    )
    assert committee.final_decision == "no-trade"
    assert primary is ds_decision


def test_committee_persistence():
    db_cfg = DatabaseCfg(enabled=True, dsn="sqlite:///:memory:", auto_migrate=True, pool_size=5, echo=False)
    services = DatabaseServices(db_cfg, run_id="run-1")
    ds_decision = Decision(
        decision="open_long",
        entry_price=100,
        stop_loss=90,
        take_profit=120,
        risk_reward=2.0,
        confidence=80,
        reason="ds",
    )
    gpt_md = ModelDecision(model_name="gpt-4o-mini", bias="long", confidence=0.6)
    glm_md = ModelDecision(model_name="glm-4.5v", bias="no-trade", confidence=0.1)
    committee, _ = decide_with_committee_sync(
        "BTCUSDm",
        {"features": {"price_30m": 100}},
        StubDeepSeek(ds_decision, logger=services.ai_logger),
        overrides={"gpt-4o-mini": gpt_md, "glm-4.5v": glm_md},
    )
    with services.client.session() as session:
        rows = session.execute(
            text("SELECT model_name, committee_id, is_final FROM ai_decisions")
        ).fetchall()
    assert len(rows) == 4  # 3 模型 + 1 委员会
    committees = [r for r in rows if r[2]]
    assert len(committees) == 1
    cid = committees[0][1]
    assert all(r[1] == cid for r in rows)  # 同一轮共享 committee_id
    assert committee.final_decision in ("long", "short", "no-trade")
