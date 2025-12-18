import math

from coin_dash.ai.models import Decision
from coin_dash.config import RiskCfg, SymbolSpecCfg
from coin_dash.exec.paper import PaperBroker
from coin_dash.risk.position import position_size


def _decision(position_size: float = 0.0) -> Decision:
    return Decision(
        decision="open_long",
        entry_price=50_000.0,
        stop_loss=49_500.0,
        take_profit=51_000.0,
        risk_reward=2.0,
        confidence=90.0,
        reason="",
        position_size=position_size,
        meta={},
    )


def test_position_size_quantizes_and_respects_margin_buffer() -> None:
    spec = SymbolSpecCfg(contract_size=1, min_lot=0.01, lot_step=0.01, max_leverage=200, margin_buffer=1.2)
    plan = position_size(10.0, _decision(), "trend", RiskCfg(), spec=spec)
    assert plan.qty == 0.01
    assert math.isclose(plan.margin_required, 3.0, rel_tol=1e-3)
    assert plan.note == "ok"


def test_position_size_shrinks_when_margin_insufficient() -> None:
    spec = SymbolSpecCfg(contract_size=1, min_lot=0.01, lot_step=0.01, max_leverage=200, margin_buffer=1.2)
    plan = position_size(5.0, _decision(position_size=0.05), "trend", RiskCfg(), spec=spec)
    # 原始 0.05 手需要 ~15 保证金，5 不够，应下调到 0.01 手
    assert plan.qty == 0.01
    assert plan.margin_required <= 5.0


def test_paper_broker_reserves_and_releases_margin() -> None:
    broker = PaperBroker(equity=100.0, fee_rate=0.0)
    denied = broker.open(
        symbol="BTCUSDm",
        side="open_long",
        entry=100.0,
        stop=90.0,
        take=110.0,
        qty=1.0,
        ts=0,
        trade_type="trend",
        mode="trending",
        rr=2.0,
        margin_required=150.0,
    )
    assert denied is None

    trade = broker.open(
        symbol="BTCUSDm",
        side="open_long",
        entry=100.0,
        stop=90.0,
        take=110.0,
        qty=1.0,
        ts=1,
        trade_type="trend",
        mode="trending",
        rr=2.0,
        margin_required=30.0,
    )
    assert trade is not None
    assert math.isclose(broker.used_margin, 30.0, rel_tol=1e-9)
    assert math.isclose(broker.available_equity, 70.0, rel_tol=1e-9)

    broker.close(trade.trade_id, price=110.0, ts=2, reason="test_close")
    assert broker.used_margin == 0.0
