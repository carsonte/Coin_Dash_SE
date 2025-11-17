from __future__ import annotations

from dataclasses import dataclass
from typing import List

import pandas as pd

from .timeframes import TimeframeRule
from ..indicators.core import atr


@dataclass
class ValidationOutput:
    frame: pd.DataFrame
    price_replaced: bool
    volume_capped: bool
    notes: List[str]


def validate_latest_bar(df: pd.DataFrame, rule: TimeframeRule) -> ValidationOutput:
    notes: List[str] = []
    if df.empty or len(df) < 20:
        return ValidationOutput(df, False, False, notes)
    df = df.copy()
    price_replaced = False
    volume_capped = False

    atr_series = atr(df["high"], df["low"], df["close"], period=14)
    last_atr = float(atr_series.iloc[-1]) if not atr_series.isna().iloc[-1] else 0.0
    price_delta = abs(df["close"].iloc[-1] - df["close"].iloc[-2])
    if last_atr and price_delta > last_atr * rule.atr_spike:
        for col in ["open", "high", "low", "close"]:
            df.iloc[-1, df.columns.get_loc(col)] = df[col].iloc[-2]
        price_replaced = True
        notes.append(f"price spike filtered at {rule.name}, delta={price_delta:.2f} atr={last_atr:.2f}")

    vol_avg = df["volume"].rolling(20).mean()
    vol_ma = float(vol_avg.iloc[-1]) if not vol_avg.isna().iloc[-1] else 0.0
    if vol_ma and df["volume"].iloc[-1] > vol_ma * rule.volume_jump:
        df.iloc[-1, df.columns.get_loc("volume")] = vol_ma
        volume_capped = True
        notes.append(f"volume spike filtered at {rule.name}, vol={df['volume'].iloc[-1]:.2f} cap={vol_ma:.2f}")

    return ValidationOutput(frame=df, price_replaced=price_replaced, volume_capped=volume_capped, notes=notes)
