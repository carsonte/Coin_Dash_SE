from __future__ import annotations

from dataclasses import dataclass
from typing import List, Dict

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
        data_cfg = getattr(self.cfg, "data", None)
        self.provider = getattr(data_cfg, "provider", "ccxt") if data_cfg else "ccxt"
        exchange_id = self.cfg.exchange.name
        if self.cfg.exchange.type == "futures" and exchange_id == "binance":
            exchange_id = "binanceusdm"
        if self.provider == "mt5_api":
            from .fetcher_mt5 import MT5APIFetcher

            base_url = ""
            if data_cfg and getattr(data_cfg, "mt5_api", None):
                base_url = getattr(data_cfg.mt5_api, "base_url", "") or ""
            self.client = MT5APIFetcher(base_url=base_url)
        else:
            self.client = CCXTOHLCVClient(exchange=exchange_id, rate_limit=self.cfg.exchange.rate_limit)
        self.base_minutes = min(tf.minutes for tf in self.cfg.timeframes.defs.values())
        self.base_label = minutes_to_label(self.base_minutes)
        if self.provider == "mt5_api":
            from .fetcher_mt5 import SUPPORTED_MT5_TIMEFRAMES

            if self.base_label not in SUPPORTED_MT5_TIMEFRAMES:
                raise ValueError(f"MT5 provider does not support timeframe {self.base_label}")

    def fetch_dataframe(self, symbol: str) -> pd.DataFrame:
        limit = self.cfg.timeframes.lookback_bars + 50
        if self.provider == "mt5_api":
            return self.client.fetch_ohlc(symbol, timeframe=self.base_label, limit=limit)
        rows = self.client.fetch_ohlcv(symbol, timeframe=self.base_label, limit=limit)
        return ohlcv_to_dataframe(rows)

    def fetch_price(self, symbol: str) -> Dict[str, float]:
        # MT5 adapter exposes fetch_price; CCXT fallback uses ticker.
        if hasattr(self.client, "fetch_price"):
            try:
                return self.client.fetch_price(symbol)
            except Exception:
                return {}
        try:
            ticker = self.client._ex.fetch_ticker(symbol)
            return {
                "symbol": symbol,
                "bid": float(ticker.get("bid") or 0.0),
                "ask": float(ticker.get("ask") or 0.0),
                "last": float(ticker.get("last") or ticker.get("close") or 0.0),
                "time": int(ticker.get("timestamp") / 1000) if ticker.get("timestamp") else 0,
            }
        except Exception:
            return {}
