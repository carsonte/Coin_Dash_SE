from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class Decision:
    decision: str        # open_long | open_short | hold
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_reward: float
    confidence: float
    reason: str
    position_size: float = 0.0
    meta: Dict[str, Any] = field(default_factory=dict)
    risk_score: float = 0.0
    quality_score: float = 0.0
    glm_snapshot: Optional[Dict[str, Any]] = None

    def recompute_rr(self) -> float:
        """
        Recalculate RR based on entry/stop/take to avoid inconsistencies with model output.
        """
        entry = self.entry_price
        stop = self.stop_loss
        take = self.take_profit
        rr = 0.0
        if self.decision == "open_long":
            risk = max(1e-9, entry - stop)
            reward = max(0.0, take - entry)
            rr = reward / risk if risk > 0 else 0.0
        elif self.decision == "open_short":
            risk = max(1e-9, stop - entry)
            reward = max(0.0, entry - take)
            rr = reward / risk if risk > 0 else 0.0
        self.risk_reward = rr
        return rr


@dataclass
class ReviewDecision:
    action: str          # close | adjust | hold
    new_stop_loss: Optional[float] = None
    new_take_profit: Optional[float] = None
    new_rr: Optional[float] = None
    reason: str = ""
    context_summary: str = ""
    confidence: float = 0.0
