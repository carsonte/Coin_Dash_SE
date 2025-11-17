from __future__ import annotations

from dataclasses import dataclass

from ..ai.models import Decision
from ..config import RiskCfg


@dataclass
class PositionPlan:
    qty: float
    risk_amount: float
    position_scale: float


def position_size(equity: float, decision: Decision, trade_type: str, cfg: RiskCfg, contract_size: float = 1.0) -> PositionPlan:
    ai_qty = getattr(decision, "position_size", 0.0) or decision.meta.get("position_size", 0.0)
    risk_per_unit = abs(decision.entry_price - decision.stop_loss)

    # AI 直接指定仓位时完全尊重其选择
    if ai_qty and ai_qty > 0:
        risk_amount = risk_per_unit * ai_qty * contract_size if risk_per_unit > 0 else 0.0
        return PositionPlan(qty=ai_qty, risk_amount=risk_amount, position_scale=1.0)

    # 未提供 position_size 时保留一个最低限度的默认算法
    risk_amount = max(0.0, equity * cfg.risk_per_trade)
    if risk_per_unit <= 1e-9:
        return PositionPlan(0.0, 0.0, 1.0)
    qty = (risk_amount / risk_per_unit) / contract_size
    return PositionPlan(qty=qty, risk_amount=risk_amount, position_scale=1.0)
