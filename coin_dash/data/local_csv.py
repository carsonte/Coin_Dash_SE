from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import List

import pandas as pd

from .schemas import OHLCV


def load_csv(path: Path) -> List[OHLCV]:
    df = pd.read_csv(path)
    # expected columns: timestamp (ms or iso), open, high, low, close, volume
    if "timestamp" not in df.columns:
        raise ValueError("CSV must contain 'timestamp' column")

    def parse_ts(x):
        try:
            # numeric ms
            return datetime.fromtimestamp(float(x) / 1000.0, tz=timezone.utc)
        except Exception:
            # ISO string
            return pd.to_datetime(x, utc=True).to_pydatetime()

    ts = df["timestamp"].apply(parse_ts)
    out: List[OHLCV] = []
    for i, row in df.iterrows():
        out.append(
            OHLCV(
                ts=ts.iloc[i],
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row.get("volume", 0.0)),
            )
        )
    return out

