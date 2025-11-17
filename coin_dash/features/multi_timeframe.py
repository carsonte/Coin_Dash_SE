from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

import pandas as pd

from ..indicators.core import ema, rsi, atr, macd, bollinger
from .trend import TrendProfile, build_trend_profile
from .structure import StructureBundle, compute_levels
from .market_mode import MarketMode, detect_market_mode


@dataclass
class FeatureContext:
    features: Dict[str, float]
    trend: TrendProfile
    structure: StructureBundle
    market_mode: MarketMode
    environment: Dict[str, str]
    global_temperature: Dict[str, object]
    reason: str


def _metrics(df: pd.DataFrame, prefix: str) -> Dict[str, float]:
    out: Dict[str, float] = {}
    if df.empty:
        return out
    e20 = ema(df["close"], 20)
    e60 = ema(df["close"], 60)
    rs = rsi(df["close"], 14)
    atr_val = atr(df["high"], df["low"], df["close"], 14)
    macd_line, signal, hist = macd(df["close"])
    _, _, _, width = bollinger(df["close"], 20, 2.0)
    out[f"price_{prefix}"] = float(df["close"].iloc[-1])
    out[f"ema20_{prefix}"] = float(e20.iloc[-1])
    out[f"ema60_{prefix}"] = float(e60.iloc[-1])
    out[f"ema_diff_{prefix}"] = out[f"ema20_{prefix}"] - out[f"ema60_{prefix}"]
    out[f"rsi_{prefix}"] = float(rs.iloc[-1])
    out[f"atr_{prefix}"] = float(atr_val.iloc[-1])
    out[f"macd_{prefix}"] = float(macd_line.iloc[-1])
    out[f"macd_hist_{prefix}"] = float(hist.iloc[-1])
    out[f"bb_width_{prefix}"] = float(width.iloc[-1])
    out[f"volume_{prefix}"] = float(df["volume"].iloc[-1])
    return out


def compute_feature_context(frames: Dict[str, pd.DataFrame]) -> FeatureContext:
        features: Dict[str, float] = {}
        for name in ["30m", "1h", "4h", "1d"]:
            df = frames.get(name)
            if df is None or df.empty:
                continue
            features.update(_metrics(df, name))
            features.update(_slope_metrics(df, name))
        environment = _environment_label(features, frames)
        trend = build_trend_profile(frames)
        structure = compute_levels(frames)
        market_mode = detect_market_mode(frames, trend)
        global_temp = _global_temperature(features, trend, frames)
        reason = f"mode={market_mode.name} trend={trend.grade} score={trend.score:.1f}"
        return FeatureContext(
            features=features,
            trend=trend,
            structure=structure,
            market_mode=market_mode,
            environment=environment,
            global_temperature=global_temp,
            reason=reason,
        )


def _slope(series: pd.Series, window: int = 5) -> float:
    if series.empty:
        return 0.0
    tail = series.tail(window)
    if len(tail) < 2:
        return 0.0
    return float(tail.iloc[-1] - tail.iloc[0]) / max(1, len(tail) - 1)


def _trend_label(series: pd.Series, window: int = 3, up_thr: float = 0.0) -> str:
    if len(series) < window:
        return "flat"
    vals = series.tail(window)
    delta = float(vals.iloc[-1] - vals.iloc[0])
    if delta > up_thr:
        return "rising"
    if delta < -up_thr:
        return "falling"
    return "flat"


def _slope_metrics(df: pd.DataFrame, prefix: str) -> Dict[str, float | str]:
    out: Dict[str, float | str] = {}
    price = df["close"]
    e20 = ema(price, 20)
    e60 = ema(price, 60)
    _, _, _, width = bollinger(price, 20, 2.0)
    _, _, hist = macd(price)
    atr_vals = atr(df["high"], df["low"], df["close"], 14)

    out[f"ema20_slope_{prefix}"] = _slope(e20, 5)
    out[f"ema60_slope_{prefix}"] = _slope(e60, 5)
    out[f"rsi_trend_{prefix}"] = _trend_label(rsi(price, 14), 3)
    out[f"macd_hist_slope_{prefix}"] = _slope(hist, 5)
    out[f"atr_trend_{prefix}"] = _trend_label(atr_vals, 5)
    out[f"bb_width_trend_{prefix}"] = _trend_label(width, 5)
    out[f"close_trend_{prefix}"] = _trend_label(price, 5)
    return out


def _quantile_label(value: float, low: float, high: float) -> str:
    if value <= low:
        return "low"
    if value >= high:
        return "high"
    return "normal"


def _environment_label(features: Dict[str, float], frames: Dict[str, pd.DataFrame]) -> Dict[str, str]:
    env: Dict[str, str] = {}
    # volatility based on fast ATR% price
    price = None
    atr_fast = None
    for key, val in features.items():
        if key.startswith("price_30m"):
            price = val
        if key.startswith("atr_30m"):
            atr_fast = val
    vol_ratio = (atr_fast / price) if price else 0.0
    env["volatility"] = _quantile_label(vol_ratio, 0.002, 0.01)

    # regime from trend + market mode
    env["regime"] = "mixed"
    direction = 0
    score = features.get("trend_score", 0.0)
    if "trend_score" in features:
        direction = 1 if score > 0 else -1 if score < 0 else 0
    mode = "mixed"
    if "mode_confidence" in features:
        mode = features.get("market_mode", "mixed")
    if mode == "trending" and direction >= 0:
        env["regime"] = "trending_up"
    elif mode == "trending" and direction < 0:
        env["regime"] = "trending_down"
    elif mode == "ranging":
        env["regime"] = "ranging"

    # noise from Bollinger width趋势
    bbw = None
    if "bb_width_30m" in features:
        bbw = features["bb_width_30m"]
    env["noise_level"] = _quantile_label((bbw or 0.0), 0.002, 0.01)

    # liquidity from volume vs rolling mean
    vol = None
    df = frames.get("30m")
    if df is not None and not df.empty:
        vol = float(df["volume"].iloc[-1]) / (float(df["volume"].rolling(20).mean().iloc[-1]) + 1e-9)
    env["liquidity"] = _quantile_label((vol or 0.0), 0.5, 1.5)
    return env


def _global_temperature(features: Dict[str, float], trend: TrendProfile, frames: Dict[str, pd.DataFrame]) -> Dict[str, object]:
    temp: Dict[str, object] = {}
    # Correlation placeholder between BTC/ETH if both present; otherwise 1.0
    temp["btc_eth_correlation"] = 1.0
    temp["overall_trend_alignment"] = trend.global_direction
    # Risk from volatility
    price = features.get("price_30m", 0.0)
    atr_fast = features.get("atr_30m", 0.0)
    vol_ratio = (atr_fast / price) if price else 0.0
    if vol_ratio >= 0.012:
        risk = "high"
    elif vol_ratio <= 0.004:
        risk = "low"
    else:
        risk = "medium"
    temp["market_risk"] = risk
    # Temperature combining trend strength + vol
    if risk == "high" and abs(trend.score) >= 60:
        temperature = "hot"
    elif risk == "medium" and abs(trend.score) >= 60:
        temperature = "warm"
    elif risk == "low" and abs(trend.score) <= 20:
        temperature = "cold"
    else:
        temperature = "neutral"
    temp["temperature"] = temperature
    return temp
