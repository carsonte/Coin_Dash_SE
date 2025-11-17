from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple


@dataclass
class BudgetInfo:
    date: str
    total_tokens: int
    budget: int
    level: str  # warn | exceed


class BudgetExceeded(RuntimeError):
    def __init__(self, info: BudgetInfo) -> None:
        super().__init__("DeepSeek budget exceeded")
        self.info = info


class AIUsageTracker:
    def __init__(self, daily_budget: int, warn_ratio: float, path: Path) -> None:
        self.daily_budget = daily_budget
        self.warn_ratio = warn_ratio
        self.path = path
        self.data = self._load()

    def _load(self) -> Dict:
        if self.path.exists():
            return json.loads(self.path.read_text(encoding="utf-8"))
        return {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def record(self, task: str, tokens: int, latency_ms: float) -> Tuple[Optional[BudgetInfo], Optional[BudgetInfo]]:
        if tokens <= 0:
            return None, None
        date = datetime.now(timezone.utc).date().isoformat()
        day_entry = self.data.setdefault(date, {"total_tokens": 0, "warned": False, "tasks": {}, "latency_ms": []})
        day_entry["total_tokens"] += tokens
        day_entry["tasks"][task] = day_entry["tasks"].get(task, 0) + tokens
        latencies = day_entry["latency_ms"]
        latencies.append(latency_ms)
        if len(latencies) > 100:
            del latencies[:-100]
        warn_info = exceed_info = None
        if self.daily_budget > 0:
            total = day_entry["total_tokens"]
            if not day_entry["warned"] and total >= self.daily_budget * self.warn_ratio:
                day_entry["warned"] = True
                warn_info = BudgetInfo(date=date, total_tokens=total, budget=self.daily_budget, level="warn")
            if total >= self.daily_budget:
                exceed_info = BudgetInfo(date=date, total_tokens=total, budget=self.daily_budget, level="exceed")
        self._save()
        return warn_info, exceed_info
