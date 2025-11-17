from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

import pandas as pd

from ..indicators.core import ema


@dataclass
class TrendSnapshot:
    direction: int  # 1 bull, -1 bear, 0 flat
    slope: float
    ema20: float
    ema60: float


@dataclass
class TrendProfile:
    snapshots: Dict[str, TrendSnapshot]
    score: float
    grade: str
    global_direction: int


TREND_WEIGHTS = {
    "1d": 40,
    "4h": 30,
    "1h": 20,
    "30m": 10,
}

MIN_LENGTH = {
    "1d": 20,
    "4h": 40,
    "1h": 60,
    "30m": 60,
}


def _direction_from(df: pd.DataFrame) -> TrendSnapshot:
    e20 = ema(df["close"], 20)
    e60 = ema(df["close"], 60)
    slope = float((e20 - e20.shift(1)).iloc[-1]) if len(e20) > 1 else 0.0
    ema20 = float(e20.iloc[-1])
    ema60 = float(e60.iloc[-1])
    direction = 0
    if ema20 > ema60 * 1.0005:
        direction = 1
    elif ema20 < ema60 * 0.9995:
        direction = -1
    return TrendSnapshot(direction=direction, slope=slope, ema20=ema20, ema60=ema60)


def build_trend_profile(frames: Dict[str, pd.DataFrame]) -> TrendProfile:
    snaps: Dict[str, TrendSnapshot] = {}
    for name, weight in TREND_WEIGHTS.items():
        df = frames.get(name)
        min_len = MIN_LENGTH.get(name, 60)
        if df is None or len(df) < min_len:
            continue
        snaps[name] = _direction_from(df)
    if not snaps:
        return TrendProfile(snaps, 0.0, "unknown", 0)

    weighted = 0.0
    total = 0.0
    for name, snap in snaps.items():
        weight = TREND_WEIGHTS.get(name, 0)
        weighted += weight * snap.direction
        total += weight
    global_dir = 1 if weighted > 0 else -1 if weighted < 0 else 0

    aligned = 0.0
    for name, snap in snaps.items():
        weight = TREND_WEIGHTS.get(name, 0)
        if snap.direction == global_dir and global_dir != 0:
            aligned += weight
        elif snap.direction == 0:
            aligned += weight * 0.5
    score = (aligned / total) * 100 if total else 0.0
    if score >= 80:
        grade = "strong"
    elif score >= 60:
        grade = "medium"
    elif score >= 40:
        grade = "weak"
    else:
        grade = "chaotic"
    return TrendProfile(snaps, score, grade, global_dir)


def classify_trade_type(signal_direction: int, profile: TrendProfile) -> str:
    day = profile.snapshots.get("1d")
    four_h = profile.snapshots.get("4h")
    if day is None or four_h is None:
        return "unknown"
    if signal_direction == day.direction == four_h.direction:
        return "trend"
    if signal_direction == (day.direction or 0) and signal_direction != (four_h.direction or 0):
        return "reverse_minor"
    return "reverse_major"
