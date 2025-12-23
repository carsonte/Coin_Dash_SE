from __future__ import annotations

from typing import Any, Dict, Iterable

from .client import DatabaseClient
from .models import SystemEvent

# 标准事件类型枚举，便于前端下拉与校验
STANDARD_EVENT_TYPES = {
    "DATA_FETCH_ERROR",
    "MT5_DISCONNECT",
    "FILTER_TRIGGER",
    "DEEPSEEK_FAIL",
    "FRONT_GATE_FAIL",
    "SAFE_MODE_ON",
    "SAFE_MODE_OFF",
    "TRADE_EXECUTED",
    "TRADE_CLOSED",
    "PERFORMANCE_WARNING",
    "EXTREME_PROTECTION_TRIGGER",
}


class SystemMonitor:
    def __init__(self, client: DatabaseClient, run_id: str | None = None, allowed_types: Iterable[str] | None = None) -> None:
        self.client = client
        self.run_id = run_id
        self.allowed_types = set(allowed_types or STANDARD_EVENT_TYPES)

    def record_event(
        self,
        event_type: str,
        severity: str,
        description: str,
        payload: Dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> None:
        if not self.client.enabled:
            return
        final_type = event_type if event_type in self.allowed_types else "CUSTOM"
        with self.client.session() as session:
            if session is None:
                return
            session.add(
                SystemEvent(
                    run_id=run_id or self.run_id,
                    event_type=final_type,
                    severity=severity,
                    description=description,
                    payload=payload,
                )
            )
