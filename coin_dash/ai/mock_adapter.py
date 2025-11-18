from __future__ import annotations

from typing import Dict

from .models import Decision


def decide_mock(symbol: str, feats: Dict[str, float], cfg: Dict) -> Decision:
    price = feats["price"]
    e20 = feats["ema20"]
    e60 = feats["ema60"]
    rsi = feats["rsi"]
    atr = feats["atr"] or 1e-9

    sl_mult = cfg.get("sl_atr_mult", 1.5)
    tp_mult = cfg.get("tp_atr_mult", 3.0)

    # Simple trend-follow rule
    if price > e20 > e60 and rsi < 80:
        entry = price
        sl = max(0.0, entry - sl_mult * atr)
        tp = entry + tp_mult * atr
        rr = (tp - entry) / max(1e-9, entry - sl)
        decision = Decision(
            "open_long",
            entry,
            sl,
            tp,
            rr,
            85.0,
            "trend-up mock",
            position_size=cfg.get("mock_position_size", 1.0),
            meta={"symbol": symbol, "adapter": "mock"},
        )
        decision.recompute_rr()
        return decision

    if price < e20 < e60 and rsi > 20:
        entry = price
        sl = entry + sl_mult * atr
        tp = entry - tp_mult * atr
        rr = (entry - tp) / max(1e-9, sl - entry)
        decision = Decision(
            "open_short",
            entry,
            sl,
            tp,
            rr,
            85.0,
            "trend-down mock",
            position_size=cfg.get("mock_position_size", 1.0),
            meta={"symbol": symbol, "adapter": "mock"},
        )
        decision.recompute_rr()
        return decision

    return Decision(
        "hold",
        price,
        price,
        price,
        0.0,
        50.0,
        "no clear edge",
        position_size=0.0,
        meta={"symbol": symbol, "adapter": "mock"},
    )
