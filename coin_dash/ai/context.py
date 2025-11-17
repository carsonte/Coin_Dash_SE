from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Deque, Dict, List, Optional


@dataclass
class ConversationThread:
    symbol: str
    created_at: datetime
    last_refresh: datetime
    history: Deque[Dict[str, str]] = field(default_factory=deque)
    summary: Optional[str] = None

    def append(self, role: str, content: str, limit: int = 10) -> None:
        self.history.append({"role": role, "content": content})
        while len(self.history) > limit:
            self.history.popleft()
        self.last_refresh = datetime.now(timezone.utc)
        self.generate_summary(limit=limit)

    def generate_summary(self, limit: int = 10) -> Optional[str]:
        if len(self.history) >= limit:
            self.summary = (
                "过去48小时关键事件总结：聚合近期决策、复评与价格/止盈止损调整，保留摘要便于后续参考。"
            )
            self.history = deque([{"role": "summary", "content": self.summary}])
        return self.summary

    def snapshot(self) -> Dict[str, object]:
        return {"summary": self.summary, "messages": list(self.history)}


class ConversationManager:
    def __init__(self, ttl_hours: int = 48, keep: int = 10) -> None:
        self.ttl = timedelta(hours=ttl_hours)
        self.keep = keep
        self.threads: Dict[str, ConversationThread] = {}
        self.shared_events: Deque[Dict[str, object]] = deque()

    def ensure(self, key: str, symbol: str) -> ConversationThread:
        now = datetime.now(timezone.utc)
        thread = self.threads.get(key)
        if thread is None or now - thread.created_at > self.ttl:
            thread = ConversationThread(symbol=symbol, created_at=now, last_refresh=now)
            self.threads[key] = thread
        return thread

    def append(self, key: str, symbol: str, role: str, content: str) -> None:
        thread = self.ensure(key, symbol)
        thread.append(role, content, self.keep)

    def add_shared_event(self, event: Dict[str, object], limit: int = 20) -> None:
        payload = dict(event or {})
        payload.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        self.shared_events.append(payload)
        while len(self.shared_events) > limit:
            self.shared_events.popleft()

    def get_context(self, key: str, symbol: str) -> Dict[str, object]:
        thread = self.ensure(key, symbol)
        return {"thread": thread.snapshot(), "shared": self.get_shared_context()}

    def get_shared_context(self) -> List[Dict[str, object]]:
        return list(self.shared_events)

    def drop(self, key: str) -> None:
        self.threads.pop(key, None)
