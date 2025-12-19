from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

import pandas as pd

from ..config import AppConfig
from .timeframes import to_rule, resample_frame, align_windows
from .validators import validate_latest_bar


@dataclass
class MultiTimeframeData:
    frames: Dict[str, pd.DataFrame]
    notes: List[str]

    def get(self, tf: str) -> pd.DataFrame:
        return self.frames.get(tf, pd.DataFrame())


class DataPipeline:
    def __init__(self, cfg: AppConfig) -> None:
        self.cfg = cfg

    def from_dataframe(self, symbol: str, df: pd.DataFrame, extra_frames: Dict[str, pd.DataFrame] | None = None) -> MultiTimeframeData:
        if df.empty:
            return MultiTimeframeData(frames={}, notes=[f"{symbol}: empty dataframe"])
        df = df.sort_index()
        base_minutes = self._infer_minutes(df)
        frames: Dict[str, pd.DataFrame] = {}
        notes: List[str] = []
        extras = extra_frames or {}
        for name, tf_def in self.cfg.timeframes.defs.items():
            if name in extras and not extras[name].empty:
                frame = extras[name].sort_index()
            else:
                if base_minutes and tf_def.minutes < base_minutes:
                    continue  # cannot upscale to higher resolution than we have
                if tf_def.minutes == base_minutes:
                    frame = df.copy()
                else:
                    frame = resample_frame(df, tf_def.minutes)
            limit = self.cfg.timeframes.lookback_bars
            if limit and len(frame) > limit:
                frame = frame.tail(limit)
            rule = to_rule(name, self.cfg.timeframes)
            val = validate_latest_bar(frame, rule)
            frames[name] = val.frame
            notes.extend(val.notes)
        frames = align_windows(frames)
        return MultiTimeframeData(frames=frames, notes=notes)

    @staticmethod
    def _infer_minutes(df: pd.DataFrame) -> int:
        if len(df) < 2:
            return 0
        delta = df.index[1] - df.index[0]
        return int(delta.total_seconds() // 60)
