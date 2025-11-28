from __future__ import annotations

import time
from typing import Dict, Optional

import pandas as pd
import requests


SUPPORTED_MT5_TIMEFRAMES = {"1m", "5m", "15m", "30m", "1h", "4h", "1d"}


class MT5APIFetcher:
    def __init__(self, base_url: str, timeout: int = 8, max_retries: int = 3, backoff: float = 1.5) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max(1, max_retries)
        self.backoff = max(0.5, backoff)
        self.session = requests.Session()

    def _request_json(self, url: str) -> Optional[Dict]:
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.get(url, timeout=self.timeout)
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    time.sleep(self.backoff * attempt)
                    continue
                raise
        if last_exc:
            raise last_exc
        return None

    def fetch_ohlc(self, symbol: str, timeframe: str, limit: int = 500) -> pd.DataFrame:
        if timeframe not in SUPPORTED_MT5_TIMEFRAMES:
            raise ValueError(f"Unsupported MT5 timeframe: {timeframe}")
        url = f"{self.base_url}/ohlc/{symbol}/{timeframe}/{limit}"
        try:
            data = self._request_json(url)
        except Exception:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        if not data:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        df = pd.DataFrame(data)
        if df.empty or "time" not in df:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        # Rename tick_volume -> volume and coerce numeric types
        if "tick_volume" in df.columns:
            df["volume"] = df["tick_volume"]
        df = df.rename(columns={"tick_volume": "volume"})
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df["timestamp"] = pd.to_datetime(pd.to_numeric(df["time"], errors="coerce"), unit="s", utc=True)
        df = df.dropna(subset=["timestamp"])
        df = df.set_index("timestamp").sort_index()
        df.index.name = "timestamp"
        return df[["open", "high", "low", "close", "volume"]]

    def fetch_price(self, symbol: str) -> Dict[str, float]:
        url = f"{self.base_url}/price/{symbol}"
        try:
            data = self._request_json(url) or {}
        except Exception:
            return {}
        return {
            "symbol": data.get("symbol", symbol),
            "bid": float(data.get("bid") or 0.0),
            "ask": float(data.get("ask") or 0.0),
            "last": float(data.get("last") or 0.0),
            "time": int(data.get("time") or 0),
        }
