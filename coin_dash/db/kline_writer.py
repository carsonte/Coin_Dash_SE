from __future__ import annotations

from typing import Dict

import pandas as pd
from sqlalchemy.dialects.postgresql import insert

from .client import DatabaseClient
from .models import KlineData
from .utils import utc_now


class KlineWriter:
    def __init__(self, client: DatabaseClient) -> None:
        self.client = client

    def record_frames(self, symbol: str, frames: Dict[str, pd.DataFrame]) -> None:
        if not self.client.enabled or not frames:
            return
        rows = []
        for interval, df in frames.items():
            if df is None or df.empty:
                continue
            last = df.iloc[-1]
            close_time = pd.Timestamp(df.index[-1]).to_pydatetime()
            row = {
                "symbol": symbol,
                "interval": interval,
                "open_time": close_time,
                "close_time": close_time,
                "open_price": float(last["open"]),
                "high_price": float(last["high"]),
                "low_price": float(last["low"]),
                "close_price": float(last["close"]),
                "volume": float(last.get("volume", 0.0)),
                "created_at": utc_now(),
            }
            rows.append(row)
        if not rows:
            return
        stmt = insert(KlineData).values(rows)
        stmt = stmt.on_conflict_do_nothing(index_elements=["symbol", "interval", "open_time"])
        with self.client.session() as session:
            if session is None:
                return
            session.execute(stmt)
