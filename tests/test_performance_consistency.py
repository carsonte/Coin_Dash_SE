from __future__ import annotations

import pytest

from coin_dash.exec.paper import PaperBroker
from coin_dash.performance.tracker import PerformanceTracker


def test_manual_close_realized_rr_and_net_pnl():
    broker = PaperBroker(10000.0, fee_rate=0.001)
    trade = broker.open(
        symbol="BTCUSDm",
        side="open_long",
        entry=100.0,
        stop=95.0,
        take=110.0,
        qty=1.0,
        ts=0,
        trade_type="trend",
        mode="trending",
        rr=2.0,
    )
    assert trade is not None
    closed = broker.close(trade.trade_id, price=102.0, ts=1, reason="manual")
    assert closed is not None

    expected_rr = (102.0 - 100.0) / (100.0 - 95.0)
    expected_open_fee = 100.0 * 1.0 * 0.001
    expected_close_fee = 102.0 * 1.0 * 0.001
    expected_pnl = (102.0 - 100.0) - expected_close_fee
    expected_net = expected_pnl - expected_open_fee

    assert closed.realized_rr == pytest.approx(expected_rr, rel=1e-6)
    assert closed.open_fee == pytest.approx(expected_open_fee, rel=1e-6)
    assert closed.close_fee == pytest.approx(expected_close_fee, rel=1e-6)
    assert closed.pnl == pytest.approx(expected_pnl, rel=1e-6)
    assert PaperBroker.net_pnl(closed) == pytest.approx(expected_net, rel=1e-6)


def test_tracker_uses_realized_rr_and_net_pnl():
    broker = PaperBroker(10000.0, fee_rate=0.001)
    trade = broker.open(
        symbol="BTCUSDm",
        side="open_long",
        entry=100.0,
        stop=95.0,
        take=110.0,
        qty=1.0,
        ts=0,
        trade_type="trend",
        mode="trending",
        rr=2.0,
    )
    assert trade is not None
    closed = broker.close(trade.trade_id, price=102.0, ts=1, reason="manual")
    assert closed is not None

    tracker = PerformanceTracker()
    rr_value = closed.realized_rr or closed.rr
    tracker.record(closed, "trend", rr_value, "trending")
    report = tracker.report()

    expected_net = PaperBroker.net_pnl(closed)
    mode_snapshot = report["modes"]["trending"]
    type_snapshot = report["types"]["trend"]
    symbol_snapshot = report["symbols"]["BTCUSDm"]

    assert mode_snapshot["avg_rr"] == pytest.approx(rr_value, rel=1e-6)
    assert type_snapshot["avg_rr"] == pytest.approx(rr_value, rel=1e-6)
    assert symbol_snapshot["avg_rr"] == pytest.approx(rr_value, rel=1e-6)
    assert mode_snapshot["pnl"] == pytest.approx(expected_net, rel=1e-6)
    assert type_snapshot["pnl"] == pytest.approx(expected_net, rel=1e-6)
    assert symbol_snapshot["pnl"] == pytest.approx(expected_net, rel=1e-6)
