from coin_dash.exec.paper import Trade
from coin_dash.performance.tracker import PerformanceTracker


def make_trade(
    trade_id: str,
    symbol: str,
    pnl: float,
    trade_type: str = "trend",
    market_mode: str = "trending",
) -> Trade:
    return Trade(
        trade_id=trade_id,
        symbol=symbol,
        side="open_long",
        entry=100.0,
        stop=95.0,
        take=110.0,
        qty=1.0,
        opened_at=0,
        trade_type=trade_type,
        market_mode=market_mode,
        rr=2.0,
        closed_at=1,
        pnl=pnl,
    )


def test_tracker_reports_symbol_breakdown() -> None:
    tracker = PerformanceTracker()
    tracker.record(make_trade("T1", "BTCUSDT", pnl=50.0), "trend", 2.0, "trending")
    tracker.record(make_trade("T2", "ETHUSDT", pnl=-25.0, trade_type="reverse"), "reverse", 1.5, "mixed")

    report = tracker.report()
    symbols = report["symbols"]

    assert symbols["BTCUSDT"]["count"] == 1
    assert symbols["BTCUSDT"]["wins"] == 1
    assert symbols["ETHUSDT"]["count"] == 1
    assert symbols["ETHUSDT"]["wins"] == 0
    # ensure pnl aggregation keeps precision
    assert symbols["BTCUSDT"]["pnl"] == 50.0
    assert symbols["ETHUSDT"]["pnl"] == -25.0
