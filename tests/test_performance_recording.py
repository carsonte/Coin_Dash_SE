from coin_dash.exec.paper import PaperBroker
from coin_dash.state_manager import StateManager
from coin_dash.runtime.orchestrator import LiveOrchestrator


def test_state_manager_base_equity_persists(tmp_path) -> None:
    path = tmp_path / "state.json"
    sm = StateManager(path, base_equity=5000)
    sm._dump()
    sm2 = StateManager(path, base_equity=1000)
    assert sm2.base_equity == 5000


def test_close_paper_trade_records_performance() -> None:
    class DummyPerf:
        def __init__(self) -> None:
            self.records = []

        def record_trade(self, trade, trade_type, market_mode) -> None:
            self.records.append((trade, trade_type, market_mode))

    class DummyDB:
        def __init__(self) -> None:
            self.performance = DummyPerf()

    orch = LiveOrchestrator.__new__(LiveOrchestrator)
    orch.paper_broker = PaperBroker(10000, fee_rate=0.0)
    orch.paper_positions = {}
    orch.db = DummyDB()

    trade = orch.paper_broker.open(
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
    )
    orch.paper_positions["pos1"] = trade.trade_id

    orch._close_paper_trade("pos1", price=110.0, reason="test", ts=1)

    assert orch.db.performance.records, "performance should record closed trade"
    recorded_trade, trade_type, market_mode = orch.db.performance.records[0]
    assert recorded_trade.trade_id == trade.trade_id
    assert trade_type == "trend"
    assert market_mode == "trending"
