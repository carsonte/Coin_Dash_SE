from __future__ import annotations

from typing import Optional

from ..config import DatabaseCfg
from .ai_decision_logger import AIDecisionLogger
from .client import DatabaseClient
from .kline_writer import KlineWriter
from .performance_aggregator import PerformanceAggregator
from .system_monitor import SystemMonitor
from .trading_recorder import TradingRecorder


class DatabaseServices:
    def __init__(self, cfg: DatabaseCfg, run_id: str | None = None) -> None:
        self.client = DatabaseClient(cfg)
        self.enabled = self.client.enabled
        self.run_id = run_id
        if not self.enabled:
            self.kline_writer = None
            self.trading = None
            self.ai_logger = None
            self.performance = None
            self.system_monitor = None
            return
        self.kline_writer = KlineWriter(self.client)
        self.trading = TradingRecorder(self.client, run_id=run_id)
        self.ai_logger = AIDecisionLogger(self.client, run_id=run_id)
        self.performance = PerformanceAggregator(self.client)
        self.system_monitor = SystemMonitor(self.client, run_id=run_id)

    def dispose(self) -> None:
        self.client.dispose()


def build_database_services(cfg: DatabaseCfg, run_id: str | None = None) -> Optional[DatabaseServices]:
    services = DatabaseServices(cfg, run_id=run_id)
    return services if services.enabled else None
