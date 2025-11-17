from __future__ import annotations

from dataclasses import dataclass
from typing import List

import pandas as pd

from .exchanges.ccxt_client import CCXTOHLCVClient
from ..config import AppConfig


SUPPORTED_TIMEFRAMES = {
    1: "1m",
    3: "3m",
    5: "5m",
    15: "15m",
    30: "30m",
    60: "1h",
    120: "2h",
    180: "3h",
    240: "4h",
    360: "6h",
    720: "12h",
    1440: "1d",
}


def minutes_to_label(minutes: int) -> str:
    if minutes not in SUPPORTED_TIMEFRAMES:
        raise ValueError(f"Unsupported timeframe {minutes} minutes for Binance futures")
    return SUPPORTED_TIMEFRAMES[minutes]


def ohlcv_to_dataframe(rows) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    data = {
        "open": [row.open for row in rows],
        "high": [row.high for row in rows],
        "low": [row.low for row in rows],
        "close": [row.close for row in rows],
        "volume": [row.volume for row in rows],
    }
    index = pd.to_datetime([row.ts for row in rows], utc=True)
    df = pd.DataFrame(data, index=index).sort_index()
    df.index.name = "timestamp"
    return df


@dataclass
class LiveDataFetcher:
    cfg: AppConfig

    def __post_init__(self) -> None:
        exchange_id = self.cfg.exchange.name
        if self.cfg.exchange.type == "futures" and exchange_id == "binance":
            exchange_id = "binanceusdm"
        self.client = CCXTOHLCVClient(exchange=exchange_id, rate_limit=self.cfg.exchange.rate_limit)
        self.base_minutes = min(tf.minutes for tf in self.cfg.timeframes.defs.values())
        self.base_label = minutes_to_label(self.base_minutes)

    def fetch_dataframe(self, symbol: str) -> pd.DataFrame:
        limit = self.cfg.timeframes.lookback_bars + 50
        rows = self.client.fetch_ohlcv(symbol, timeframe=self.base_label, limit=limit)
        return ohlcv_to_dataframe(rows)
