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


@dataclass
class ReviewDecision:
    action: str          # close | adjust | hold
    new_stop_loss: Optional[float] = None
    new_take_profit: Optional[float] = None
    new_rr: Optional[float] = None
    reason: str = ""
    context_summary: str = ""
    confidence: float = 0.0
