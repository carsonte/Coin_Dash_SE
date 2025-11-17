from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy.dialects.postgresql import insert

from .client import DatabaseClient
from .models import AIDecisionLog, ConversationLog, CostMonitoring
from .utils import utc_now


class AIDecisionLogger:
    def __init__(self, client: DatabaseClient) -> None:
        self.client = client

    def log_decision(
        self,
        decision_type: str,
        symbol: str,
        payload: Dict[str, Any],
        result: Dict[str, Any],
        tokens_used: Optional[int],
        latency_ms: Optional[float],
    ) -> None:
        if not self.client.enabled:
            return
        stmt = insert(AIDecisionLog).values(
            {
                "decision_type": decision_type,
                "symbol": symbol,
                "payload": payload,
                "result": result,
                "tokens_used": tokens_used,
                "latency_ms": latency_ms,
                "confidence": result.get("confidence"),
            }
        )
        with self.client.session() as session:
            if session is None:
                return
            session.execute(stmt)

    def record_conversation(self, context_key: str, messages: list, tokens: int) -> None:
        if not self.client.enabled:
            return
        stmt = insert(ConversationLog).values(
            {"context_key": context_key, "messages": messages, "tokens_accumulated": tokens, "updated_at": utc_now()}
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["context_key"],
            set_={"messages": messages, "tokens_accumulated": tokens, "updated_at": utc_now()},
        )
        with self.client.session() as session:
            if session is None:
                return
            session.execute(stmt)

    def log_cost(self, service: str, tokens_used: int, status: str) -> None:
        if not self.client.enabled:
            return
        today = utc_now().date()
        stmt = insert(CostMonitoring).values(
            {"date": today, "service": service, "tokens_used": tokens_used, "budget_status": status}
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["date", "service"],
            set_={"tokens_used": tokens_used, "budget_status": status},
        )
        with self.client.session() as session:
            if session is None:
                return
            session.execute(stmt)
