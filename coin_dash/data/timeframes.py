from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Dict

import pandas as pd

from ..config import TimeframeCfg


@dataclass(frozen=True)
class TimeframeRule:
    name: str
    minutes: int
    atr_spike: float
    volume_jump: float


def to_rule(name: str, cfg: TimeframeCfg) -> TimeframeRule:
    if name not in cfg.defs:
        raise KeyError(f"timeframe {name} not configured")
    tf = cfg.defs[name]
    return TimeframeRule(name=name, minutes=tf.minutes, atr_spike=tf.atr_spike, volume_jump=tf.volume_jump)


def resample_frame(df: pd.DataFrame, minutes: int) -> pd.DataFrame:
    if df.empty:
        return df
    rule = f"{minutes}min"
    agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }
    out = df.resample(rule, label="right", closed="right").agg(agg).dropna(how="any")
    return out


def align_windows(frames: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    # ensure all frames end on same timestamp by truncating to earliest last timestamp
    last_ts = None
    for df in frames.values():
        if df.empty:
            continue
        ts = df.index[-1]
        last_ts = ts if last_ts is None else min(last_ts, ts)
    if last_ts is None:
        return frames
    aligned = {}
    for name, df in frames.items():
        aligned[name] = df[df.index <= last_ts]
    return aligned


def expected_points(minutes: int, lookback: int) -> timedelta:
    return timedelta(minutes=minutes * lookback)
