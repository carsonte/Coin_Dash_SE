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
    return ValidationResult(True, "ok")
