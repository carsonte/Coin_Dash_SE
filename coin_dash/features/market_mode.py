from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

import pandas as pd

from ..indicators.core import atr, bollinger, rsi, macd
from .trend import TrendProfile


MODE_PRIORITIES = {
    "trending": 0.25,
    "breakout": 0.22,
    "reversal": 0.20,
    "channeling": 0.18,
    "ranging": 0.15,
}

MODE_WEIGHTS = {
    "trending": {"1d": 0.4, "4h": 0.3, "1h": 0.2, "30m": 0.1},
    "ranging": {"4h": 0.4, "1h": 0.3, "30m": 0.2, "1d": 0.1},
    "breakout": {"1h": 0.35, "30m": 0.3, "4h": 0.25, "1d": 0.1},
    "reversal": {"4h": 0.35, "1h": 0.3, "1d": 0.2, "30m": 0.15},
    "channeling": {"4h": 0.35, "1h": 0.3, "30m": 0.25, "1d": 0.1},
}


@dataclass
class MarketMode:
    name: str
    confidence: float
    reasons: Dict[str, float]
    cycle_weights: Dict[str, float]
    trend_direction: str = "neutral"  # up | down | neutral


def _percentile(value: float, series: pd.Series) -> float:
    arr = series.dropna()
    if arr.empty:
        return 0.0
    rank = (arr < value).sum()
    return rank / len(arr)


def detect_market_mode(frames: Dict[str, pd.DataFrame], trend: TrendProfile) -> MarketMode:
    scores: Dict[str, float] = {}
    reasons: Dict[str, float] = {}
    directions: Dict[str, str] = {}

    frame_1h = frames.get("1h", pd.DataFrame())
    frame_4h = frames.get("4h", pd.DataFrame())
    frame_30m = frames.get("30m", pd.DataFrame())

    atr_pct = bb_pct = 0.0
    macd_near_zero = False
    rsi_last = 50.0

    price_ref = None
    if not frame_1h.empty:
        price_ref = float(frame_1h["close"].iloc[-1])
    elif not frame_30m.empty:
        price_ref = float(frame_30m["close"].iloc[-1])
    elif not frame_4h.empty:
        price_ref = float(frame_4h["close"].iloc[-1])

    if not frame_1h.empty:
        atr_series = atr(frame_1h["high"], frame_1h["low"], frame_1h["close"], 14)
        atr_pct = _percentile(float(atr_series.iloc[-1]), atr_series)
        _, _, _, bbw = bollinger(frame_1h["close"], 20, 2.0)
        bb_pct = _percentile(float(bbw.iloc[-1]), bbw)
        macd_line, _, _ = macd(frame_1h["close"])
        macd_near_zero = abs(float(macd_line.iloc[-1])) < 0.0005 * float(frame_1h["close"].iloc[-1])
        rsi_vals = rsi(frame_1h["close"], 14)
        rsi_last = float(rsi_vals.iloc[-1])

    ema_refs = []
    for name in ("4h", "1h"):
        snap = trend.snapshots.get(name)
        if snap:
            ema_refs.extend([snap.ema20, snap.ema60])

    price_above = price_ref is not None and ema_refs and all(price_ref >= val for val in ema_refs)
    price_below = price_ref is not None and ema_refs and all(price_ref <= val for val in ema_refs)

    trend_dir = "neutral"
    if trend.global_direction == 1 and price_above:
        trend_dir = "up"
    elif trend.global_direction == -1 and price_below:
        trend_dir = "down"

    # Trending mode
    if trend.grade in {"strong", "medium"} and atr_pct > 0.5 and bb_pct > 0.6 and trend_dir != "neutral":
        scores["trending"] = 0.85 if trend.grade == "strong" else 0.72
        reasons["trending"] = atr_pct
        directions["trending"] = trend_dir

    # Ranging mode
    if bb_pct < 0.3 and atr_pct < 0.35 and macd_near_zero:
        scores["ranging"] = 0.75
        reasons["ranging"] = bb_pct

    # Channeling
    if not frame_4h.empty:
        ema_fast = frame_4h["close"].ewm(span=20).mean()
        ema_slow = frame_4h["close"].ewm(span=60).mean()
        spread = float(abs(ema_fast.iloc[-1] - ema_slow.iloc[-1]))
        price = float(frame_4h["close"].iloc[-1])
        slope = float((ema_fast - ema_fast.shift(1)).iloc[-1])
        if spread < 0.01 * price and abs(slope) / price < 0.001 and 0.4 <= atr_pct <= 0.65:
            scores["channeling"] = 0.68
            reasons["channeling"] = spread / price

    # Breakout
    if not frame_30m.empty:
        _, _, _, bbw30 = bollinger(frame_30m["close"], 20, 2.0)
        if len(bbw30) > 30:
            recent = float(bbw30.tail(5).mean())
            min_recent = float(bbw30.tail(30).min())
            expansion = float(bbw30.iloc[-1]) / (recent + 1e-9)
            contraction = min_recent / (float(bbw30.tail(30).mean()) + 1e-9)
            vol_ratio = float(frame_30m["volume"].iloc[-1]) / (float(frame_30m["volume"].rolling(5).mean().iloc[-1]) + 1e-9)
            if contraction < 0.7 and expansion > 1.25 and vol_ratio > 1.5:
                scores["breakout"] = 0.82
                reasons["breakout"] = vol_ratio

    # Reversal
    if rsi_last >= 80 or rsi_last <= 20:
        vol_spike = 0.0
        if not frame_1h.empty:
            vol_spike = float(frame_1h["volume"].iloc[-1]) / (float(frame_1h["volume"].rolling(20).mean().iloc[-1]) + 1e-9)
        scores["reversal"] = 0.7 + min(0.2, vol_spike / 10)
        reasons["reversal"] = rsi_last

    if not scores:
        return MarketMode("mixed", 0.5, {}, MODE_WEIGHTS["ranging"], trend_direction="neutral")

    # choose by confidence then priority
    best_mode = max(
        scores.items(),
        key=lambda kv: (kv[1], MODE_PRIORITIES.get(kv[0], 0.0))
    )
    name, conf = best_mode
    if conf < 0.6:
        return MarketMode("mixed", conf, reasons, MODE_WEIGHTS.get("ranging", {}), trend_direction="neutral")
    return MarketMode(name, conf, reasons, MODE_WEIGHTS.get(name, {}), trend_direction=directions.get(name, "neutral"))
