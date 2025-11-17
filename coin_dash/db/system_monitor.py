from __future__ import annotations

from typing import Any, Dict

from .client import DatabaseClient
from .models import SystemEvent


class SystemMonitor:
    def __init__(self, client: DatabaseClient) -> None:
        self.client = client

    def record_event(self, event_type: str, severity: str, description: str, payload: Dict[str, Any] | None = None) -> None:
        if not self.client.enabled:
            return
        with self.client.session() as session:
            if session is None:
                return
            session.add(
                SystemEvent(
                    event_type=event_type,
                    severity=severity,
                    description=description,
                    payload=payload,
                )
            )
