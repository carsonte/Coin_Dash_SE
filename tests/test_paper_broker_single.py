from coin_dash.exec.paper import PaperBroker


def test_has_open_blocks_second_trade():
    broker = PaperBroker(equity=10000, fee_rate=0.0)
    assert broker.has_open("BTCUSDm") is False
    broker.open("BTCUSDm", "open_long", 100, 90, 110, 1, ts=0, trade_type="trend", mode="trending", rr=2.0)
    assert broker.has_open("BTCUSDm") is True
    # Close and ensure flag resets
    broker.close("T00001", price=110, ts=1, reason="take profit")
    assert broker.has_open("BTCUSDm") is False
