from __future__ import annotations

from sqlalchemy import text

from coin_dash.ai.committee_engine import decide_front_gate_sync
from coin_dash.ai.committee_schemas import ModelDecision
from coin_dash.config import DatabaseCfg
from coin_dash.db.services import DatabaseServices


def test_front_gate_conflict():
    gpt_md = ModelDecision(model_name="gpt-4o-mini", bias="long", confidence=0.8)
    glm_md = ModelDecision(model_name="glm-4.5v", bias="short", confidence=0.8)
    committee = decide_front_gate_sync(
        "BTCUSDm",
        {"features": {"price_30m": 100}},
        overrides={"gpt-4o-mini": gpt_md, "glm-4.5v": glm_md},
    )
    assert committee.final_decision == "no-trade"
    assert committee.conflict_level == "high"


def test_front_gate_low_confidence():
    gpt_md = ModelDecision(model_name="gpt-4o-mini", bias="long", confidence=0.5)
    glm_md = ModelDecision(model_name="glm-4.5v", bias="long", confidence=0.6)
    committee = decide_front_gate_sync(
        "BTCUSDm",
        {"features": {"price_30m": 100}},
        overrides={"gpt-4o-mini": gpt_md, "glm-4.5v": glm_md},
    )
    assert committee.final_decision == "no-trade"
    assert committee.conflict_level in ("medium", "low")


def test_front_gate_persistence():
    db_cfg = DatabaseCfg(enabled=True, dsn="sqlite:///:memory:", auto_migrate=True, pool_size=5, echo=False)
    services = DatabaseServices(db_cfg, run_id="run-1")
    gpt_md = ModelDecision(model_name="gpt-4o-mini", bias="long", confidence=0.8)
    glm_md = ModelDecision(model_name="glm-4.5v", bias="long", confidence=0.75)
    committee = decide_front_gate_sync(
        "BTCUSDm",
        {"features": {"price_30m": 100}},
        ai_logger=services.ai_logger,
        overrides={"gpt-4o-mini": gpt_md, "glm-4.5v": glm_md},
    )
    with services.client.session() as session:
        rows = session.execute(text("SELECT model_name, committee_id, is_final FROM ai_decisions")).fetchall()
    assert len(rows) == 3  # 2 模型 + 1 front committee
    committees = [r for r in rows if r[2]]
    assert len(committees) == 1
    cid = committees[0][1]
    assert all(r[1] == cid for r in rows)
    assert committee.final_decision in ("long", "short", "no-trade")
