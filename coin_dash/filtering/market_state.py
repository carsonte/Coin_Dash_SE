from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

import pandas as pd

from ..indicators.core import atr, bollinger


@dataclass
class MarketFilterResult:
    score: float
    active: bool
    reason: str
    fast_score: float
    slow_score: float


def _core_score(df: pd.DataFrame, weights: Dict[str, float]) -> float:
    if len(df) < 50:
        return 0.0
    a = atr(df["high"], df["low"], df["close"], 14)
    _, _, _, bb_width = bollinger(df["close"], 20, 2.0)
    atr_base = a.rolling(50).mean().bfill()
    bb_base = bb_width.rolling(50).mean().bfill()
    atr_norm = (a / (atr_base + 1e-9)).clip(lower=0).fillna(0)
    bb_norm = (bb_width / (bb_base + 1e-9)).clip(lower=0).fillna(0)
    vol_norm = (df["volume"] / (df["volume"].rolling(20).mean() + 1e-9)).clip(lower=0).fillna(0)
    atr_v = float(atr_norm.iloc[-1])
    bb_v = float(bb_norm.iloc[-1])
    vol_v = float(vol_norm.iloc[-1])
    score = (
        weights.get("atr_norm", 0.4) * atr_v +
        weights.get("bb_width_norm", 0.35) * bb_v +
        weights.get("vol_change_norm", 0.25) * vol_v
    )
    return score


def market_activity_score(
    fast_df: pd.DataFrame,
    slow_df: pd.DataFrame,
    symbol: str,
    cfg: Dict,
    aux_df: Optional[pd.DataFrame] = None,
) -> MarketFilterResult:
    if fast_df.empty or slow_df.empty:
        return MarketFilterResult(0.0, False, "insufficient data", 0.0, 0.0)
    weights = cfg.get("weights", {})
    smoothing = cfg.get("smoothing_weights", {"fast": 0.7, "slow": 0.3})
    threshold = cfg.get("score_thresholds", {}).get(symbol, 0.7)

    fast_score = _core_score(fast_df, weights)
    slow_score = _core_score(slow_df, weights)

    score = fast_score * smoothing.get("fast", 0.7) + slow_score * smoothing.get("slow", 0.3)
    if symbol.endswith("ETHUSDT") and aux_df is not None and not aux_df.empty:
        aux_score = _core_score(aux_df, weights)
        score = (score * 2 + aux_score) / 3

    active = score >= threshold
    reason = f"fast={fast_score:.2f} slow={slow_score:.2f} thr={threshold:.2f}"
    return MarketFilterResult(score=score, active=active, reason=reason, fast_score=fast_score, slow_score=slow_score)
