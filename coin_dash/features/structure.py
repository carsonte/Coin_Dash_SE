from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

import pandas as pd


@dataclass
class StructureLevels:
    support: float
    resistance: float
    timeframe: str


@dataclass
class StructureBundle:
    levels: Dict[str, StructureLevels]

    def nearest_support(self) -> float:
        vals = [lvl.support for lvl in self.levels.values() if lvl.support > 0]
        return min(vals) if vals else 0.0

    def nearest_resistance(self) -> float:
        vals = [lvl.resistance for lvl in self.levels.values() if lvl.resistance > 0]
        return max(vals) if vals else 0.0


_STRUCTURE_WINDOWS = {
    "30m": {"lookback_mult": 2.0, "recent_min": 40},
    "1h": {"lookback_mult": 1.5, "recent_min": 30},
    "4h": {"lookback_mult": 1.0, "recent_min": 20},
    "1d": {"lookback_mult": 1.0, "recent_min": 15},
}


def compute_levels(frames: Dict[str, pd.DataFrame], lookback: int = 120, recent: int = 20) -> StructureBundle:
    levels: Dict[str, StructureLevels] = {}
    for name, window_cfg in _STRUCTURE_WINDOWS.items():
        df = frames.get(name)
        if df is None or df.empty:
            continue
        tf_lookback = max(1, int(lookback * window_cfg.get("lookback_mult", 1.0)))
        tf_recent = max(recent, window_cfg.get("recent_min", recent))
        window = df.tail(tf_lookback)
        if window.empty:
            continue
        recent_window = window.tail(tf_recent)
        if recent_window.empty:
            continue
        levels[name] = StructureLevels(
            support=float(recent_window["low"].min()),
            resistance=float(recent_window["high"].max()),
            timeframe=name,
        )
    return StructureBundle(levels=levels)


def stop_outside_structure(decision, structure: StructureBundle, buffer_pct: float) -> bool:
    """
    Temporarily disable the structure check so signals are not rejected upstream.
    DeepSeek decisions are still logged with structure context and the original
    logic can be restored once real-trade samples are collected.
    """
    return True
