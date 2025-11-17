from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, List

import ccxt

from ..schemas import OHLCV
from ..exchange_base import ExchangeClient


class CCXTOHLCVClient(ExchangeClient):
    def __init__(self, exchange: str = "binance", rate_limit: bool = True) -> None:
        ex_cls = getattr(ccxt, exchange)
        self._ex = ex_cls({"enableRateLimit": rate_limit})

    def fetch_ohlcv(self, symbol: str, timeframe: str, since: Optional[int] = None, limit: int = 500) -> List[OHLCV]:
        rows = self._ex.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=limit)
        out: List[OHLCV] = []
        for t, o, h, l, c, v in rows:
            out.append(OHLCV(datetime.fromtimestamp(t / 1000, tz=timezone.utc), float(o), float(h), float(l), float(c), float(v)))
        return out

