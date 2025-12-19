from __future__ import annotations

from dataclasses import dataclass
import math
from typing import List, Dict, Optional

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
        self.exchange_id = exchange_id
        if self.provider == "mt5_api":
            from .fetcher_mt5 import MT5APIFetcher

            base_url = ""
            if data_cfg and getattr(data_cfg, "mt5_api", None):
                base_url = getattr(data_cfg.mt5_api, "base_url", "") or ""
            self.client = MT5APIFetcher(base_url=base_url)
            # 备用行情源：Binance USDT-M
            self.backup_client: Optional[CCXTOHLCVClient] = CCXTOHLCVClient(exchange="binanceusdm", rate_limit=True)
            self.backup_exchange_id = "binanceusdm"
        else:
            self.client = CCXTOHLCVClient(exchange=exchange_id, rate_limit=self.cfg.exchange.rate_limit)
            self.backup_client = None
            self.backup_exchange_id = None
        self.has_backup = bool(self.backup_client)
        self.base_minutes = min(tf.minutes for tf in self.cfg.timeframes.defs.values())
        self.max_minutes = max(tf.minutes for tf in self.cfg.timeframes.defs.values())
        self.base_label = minutes_to_label(self.base_minutes)
        if self.provider == "mt5_api":
            from .fetcher_mt5 import SUPPORTED_MT5_TIMEFRAMES

            if self.base_label not in SUPPORTED_MT5_TIMEFRAMES:
                raise ValueError(f"MT5 provider does not support timeframe {self.base_label}")

    def fetch_dataframe(self, symbol: str, use_backup: bool = False) -> pd.DataFrame:
        # 拉取足够的底层 bars，用于重采样出 4h/1d 等高周期，避免 early window 数据不足
        limit = max(self.cfg.timeframes.lookback_bars + 50, self._coverage_limit())
        client, ex_id = self._select_client(use_backup)
        if client is None:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        if self.provider == "mt5_api" and not use_backup:
            return client.fetch_ohlc(symbol, timeframe=self.base_label, limit=limit)
        mapped = self._map_symbol(symbol, exchange_id=ex_id)
        if mapped is None:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        rows = client.fetch_ohlcv(mapped, timeframe=self.base_label, limit=limit)
        return ohlcv_to_dataframe(rows)

    def fetch_price(self, symbol: str, use_backup: bool = False) -> Dict[str, float]:
        # MT5 adapter exposes fetch_price; CCXT fallback uses ticker.
        client, ex_id = self._select_client(use_backup)
        if client is None:
            return {}
        if hasattr(client, "fetch_price") and not use_backup:
            try:
                return client.fetch_price(symbol)
            except Exception:
                return {}
        try:
            mapped = self._map_symbol(symbol, exchange_id=ex_id)
            if mapped is None:
                return {}
            ticker = client._ex.fetch_ticker(mapped)
            return {
                "symbol": symbol,
                "bid": float(ticker.get("bid") or 0.0),
                "ask": float(ticker.get("ask") or 0.0),
                "last": float(ticker.get("last") or ticker.get("close") or 0.0),
                "time": int(ticker.get("timestamp") / 1000) if ticker.get("timestamp") else 0,
            }
        except Exception:
            return {}

    def _coverage_limit(self) -> int:
        """
        计算覆盖高周期所需的最小底层 bars 数：约等于最高周期 20 根 + 少量缓冲。
        例如 base=15m、max=1d -> ceil(1440/15*20) ≈ 1920。
        """
        if self.base_minutes <= 0 or self.max_minutes <= 0:
            return self.cfg.timeframes.lookback_bars + 50
        multiplier = self.max_minutes / self.base_minutes
        needed = int(math.ceil(multiplier * 20))
        return needed + 50  # 再加一点缓冲

    def fetch_timeframes(self, symbol: str, names: List[str], use_backup: bool = False) -> Dict[str, pd.DataFrame]:
        """
        直接按指定周期拉取（如 1h/4h/1d），键使用配置中的周期名。
        仅当 provider 支持多 timeframe 直拉时生效。
        """
        frames: Dict[str, pd.DataFrame] = {}
        if not names:
            return frames
        client, ex_id = self._select_client(use_backup)
        if client is None:
            return frames
        for name in names:
            tf_def = self.cfg.timeframes.defs.get(name)
            if not tf_def:
                continue
            label = minutes_to_label(tf_def.minutes)
            limit = max(self.cfg.timeframes.lookback_bars + 10, 120)
            try:
                if self.provider == "mt5_api" and not use_backup:
                    df = client.fetch_ohlc(symbol, timeframe=label, limit=limit)
                else:
                    mapped = self._map_symbol(symbol, exchange_id=ex_id)
                    if mapped is None:
                        df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
                    else:
                        rows = client.fetch_ohlcv(mapped, timeframe=label, limit=limit)
                        df = ohlcv_to_dataframe(rows)
            except Exception:
                df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
            if not df.empty:
                frames[name] = df
        return frames

    def _map_symbol(self, symbol: str, exchange_id: Optional[str] = None) -> Optional[str]:
        """
        针对 CCXT 备源做符号映射：Binance USDT-M 需要 BTC/USDT:USDT 这种写法。
        MT5 保持原符号。
        """
        ex_id = exchange_id or self.exchange_id
        # MT5 主源直接返回；备源 binanceusdm 需要映射
        if self.provider == "mt5_api" and ex_id != "binanceusdm":
            return symbol
        if ex_id == "binanceusdm" and symbol.upper().startswith("XAU"):
            # Binance USDT-M 无 XAU 合约，返回 None 以便上层跳过
            return None
        # binanceusdm/USDT-M 合约
        if ex_id == "binanceusdm" and symbol.endswith("USDm"):
            base = symbol[:-4]  # strip USDm -> BTC/ETH
            return f"{base}/USDT:USDT"
        return symbol

    def _select_client(self, use_backup: bool):
        if use_backup and self.backup_client:
            return self.backup_client, self.backup_exchange_id
        return self.client, self.exchange_id
