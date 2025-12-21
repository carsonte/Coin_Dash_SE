from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from ..features.structure import StructureBundle, stop_outside_structure
from ..config import RiskCfg


@dataclass
class ValidationResult:
    ok: bool
    reason: str


@dataclass
class ValidationContext:
    atr_value: float
    trade_type: str
    structure: StructureBundle
    risk_cfg: RiskCfg


def validate_signal(decision, ctx: ValidationContext) -> ValidationResult:
    if decision.decision not in ("open_long", "open_short"):
        return ValidationResult(False, "hold")
    if decision.entry_price <= 0 or decision.stop_loss <= 0 or decision.take_profit <= 0:
        return ValidationResult(False, "invalid prices")
    if ctx.risk_cfg.validation_enabled:
        if decision.decision == "open_long" and not (decision.stop_loss < decision.entry_price < decision.take_profit):
            return ValidationResult(False, "bad long levels")
        if decision.decision == "open_short" and not (decision.take_profit < decision.entry_price < decision.stop_loss):
            return ValidationResult(False, "bad short levels")
        rr_min = max(0.0, float(getattr(ctx.risk_cfg.rr_bounds, "min", 0.0) or 0.0))
        if rr_min and decision.risk_reward < rr_min:
            return ValidationResult(False, f"rr below min {rr_min}")
    return ValidationResult(True, "ok")
