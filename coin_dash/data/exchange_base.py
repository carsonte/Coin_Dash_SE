from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Iterable, Optional, List

from .schemas import OHLCV


class ExchangeClient(ABC):
    @abstractmethod
    def fetch_ohlcv(self, symbol: str, timeframe: str, since: Optional[int] = None, limit: int = 500) -> List[OHLCV]:
        raise NotImplementedError


