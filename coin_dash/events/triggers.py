from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd

from ..indicators.core import atr, ema
from ..features.structure import StructureBundle


def _atr_spike(frame: pd.DataFrame, window: int = 20, mult: float = 2.0) -> bool:
    if frame is None or len(frame) < window + 2:
        return False
    series = atr(frame["high"], frame["low"], frame["close"], 14).dropna()
    recent = series.tail(window + 1)
    if len(recent) < window + 1:
        return False
    latest = float(recent.iloc[-1])
    base = float(recent.iloc[:-1].mean())
    return base > 0 and latest >= base * mult


def _ema_crossover(frame: pd.DataFrame) -> bool:
    if frame is None or len(frame) < 3:
        return False
    e20 = ema(frame["close"], 20)
    e60 = ema(frame["close"], 60)
    diff = e20 - e60
    last = float(diff.iloc[-1])
    prev = float(diff.iloc[-2])
    return (last > 0 and prev < 0) or (last < 0 and prev > 0)


def _volume_spike(frame: pd.DataFrame, window: int = 20, mult: float = 2.0) -> bool:
    if frame is None or len(frame) < window + 1:
        return False
    vol = frame["volume"].tail(window + 1)
    base = float(vol.iloc[:-1].mean())
    latest = float(vol.iloc[-1])
    return base > 0 and latest >= base * mult


def _price_move(frame: pd.DataFrame, threshold: float = 0.003) -> bool:
    if frame is None or frame.empty:
        return False
    last = frame.iloc[-1]
    open_price = float(last["open"])
    close_price = float(last["close"])
    if open_price <= 0:
        return False
    return abs(close_price - open_price) / open_price >= threshold


def _structure_breakout(structure: StructureBundle, price: float, buffer: float = 0.001) -> bool:
    if structure is None or price <= 0:
        return False
    support = structure.nearest_support()
    resistance = structure.nearest_resistance()
    if resistance and price >= resistance * (1 + buffer):
        return True
    if support and price <= support * (1 - buffer):
        return True
    return False


def _extract(ctx: Any) -> tuple[Dict[str, float], Dict[str, pd.DataFrame], StructureBundle | None, str | None]:
    if isinstance(ctx, dict):
        features = ctx.get("features") or {}
        frames = ctx.get("frames") or {}
        structure = ctx.get("structure")
        symbol = ctx.get("symbol")
    else:
        features = getattr(ctx, "features", {}) or {}
        frames = getattr(ctx, "frames", {}) or {}
        structure = getattr(ctx, "structure", None)
        symbol = getattr(ctx, "symbol", None)
    return features, frames, structure, symbol


def detect_market_events(mtf_context) -> dict:
    """
    输入：
        mtf_context: 多周期特征上下文（包含 30m/1h/4h/1d 的价格、指标、结构等，
                     具体字段从现有 features / orchestrator 中复用）
    输出：
        dict, 例如：
        {
            "has_event": bool,
            "reasons": List[str],
            "severity": "low" | "medium" | "high"
        }
    """
    features, frames, structure, _ = _extract(mtf_context)
    reasons: List[str] = []

    volatility_spike = False
    ema_cross = False
    volume_event = False

    for tf in ("30m", "1h"):
        frame = frames.get(tf)
        if _atr_spike(frame):
            reasons.append(f"volatility_spike_{tf}")
            volatility_spike = True
        if _ema_crossover(frame):
            reasons.append(f"ema_crossover_{tf}")
            ema_cross = True
        if _volume_spike(frame):
            reasons.append(f"volume_spike_{tf}")
            volume_event = True
        if _price_move(frame):
            reasons.append(f"price_move_gt_0_3pct_{tf}")

    price_30m = float(features.get("price_30m", 0.0) or 0.0)
    price_1h = float(features.get("price_1h", 0.0) or 0.0)
    price_ref = price_30m or price_1h
    if _structure_breakout(structure, price_ref):
        reasons.append("structure_breakout")

    has_event = bool(reasons)
    severity = "low"
    if has_event:
        if volatility_spike and (ema_cross or "structure_breakout" in reasons):
            severity = "high"
        else:
            minor_only = all(
                r.startswith("price_move_gt_0_3pct") or r.startswith("volume_spike") for r in reasons
            )
            severity = "low" if minor_only else "medium"

    return {"has_event": has_event, "reasons": reasons, "severity": severity}
