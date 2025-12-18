from __future__ import annotations

import math
from dataclasses import dataclass

from ..ai.models import Decision
from ..config import RiskCfg, SymbolSpecCfg


@dataclass
class PositionPlan:
    qty: float
    risk_amount: float
    position_scale: float
    margin_required: float = 0.0
    raw_qty: float = 0.0
    note: str = ""


def _quantize_qty(qty: float, spec: SymbolSpecCfg) -> float:
    if qty <= 0:
        return 0.0
    step = spec.lot_step if spec.lot_step > 0 else spec.min_lot
    if step <= 0:
        step = 0.01
    qty = max(spec.min_lot, qty)
    snapped = math.floor(qty / step) * step
    if spec.max_lot > 0:
        snapped = min(snapped, spec.max_lot)
    return snapped if snapped >= spec.min_lot else 0.0


def _calc_margin(price: float, qty: float, spec: SymbolSpecCfg) -> float:
    if price <= 0 or spec.max_leverage <= 0 or qty <= 0:
        return 0.0
    notional = price * spec.contract_size * qty
    return (notional / spec.max_leverage) * spec.margin_buffer


def position_size(
    equity_available: float,
    decision: Decision,
    trade_type: str,
    cfg: RiskCfg,
    spec: SymbolSpecCfg | None = None,
) -> PositionPlan:
    """
    先按 AI/风险占比算基础仓位，再按品种规格对齐步长和保证金。
    - equity_available: 可用资金（已扣保证金的余额）
    - spec: 品种合约/保证金限制，缺省则用通用 0.01 手、1:200、20% 缓冲
    """
    symbol_spec = spec or SymbolSpecCfg()
    ai_qty = getattr(decision, "position_size", 0.0) or decision.meta.get("position_size", 0.0)
    risk_per_unit = abs(decision.entry_price - decision.stop_loss)
    price = decision.entry_price or 0.0

    raw_qty = 0.0
    if ai_qty and ai_qty > 0:
        raw_qty = ai_qty * symbol_spec.volatility_discount
    else:
        risk_amount = max(0.0, equity_available * cfg.risk_per_trade)
        if risk_per_unit <= 1e-9 or price <= 0:
            return PositionPlan(0.0, 0.0, 1.0, raw_qty=raw_qty, note="no_risk_unit")
        qty = (risk_amount / risk_per_unit) / symbol_spec.contract_size
        raw_qty = qty * symbol_spec.volatility_discount

    snapped_qty = _quantize_qty(raw_qty, symbol_spec)
    if snapped_qty <= 0:
        return PositionPlan(0.0, 0.0, 1.0, raw_qty=raw_qty, note="qty_below_min")

    margin = _calc_margin(price, snapped_qty, symbol_spec)
    if equity_available > 0 and margin > equity_available:
        # 按可用资金反推可负担仓位，再按步长向下取整
        affordable = (equity_available / symbol_spec.margin_buffer) if symbol_spec.margin_buffer > 0 else 0.0
        if price > 0 and symbol_spec.contract_size > 0 and symbol_spec.max_leverage > 0:
            affordable_qty = affordable * symbol_spec.max_leverage / (price * symbol_spec.contract_size)
        else:
            affordable_qty = 0.0
        snapped_qty = _quantize_qty(affordable_qty, symbol_spec)
        margin = _calc_margin(price, snapped_qty, symbol_spec)
        if snapped_qty < symbol_spec.min_lot:
            return PositionPlan(0.0, 0.0, 1.0, raw_qty=raw_qty, note="insufficient_equity")

    risk_amount = risk_per_unit * snapped_qty * symbol_spec.contract_size if risk_per_unit > 0 else 0.0
    return PositionPlan(
        qty=snapped_qty,
        risk_amount=risk_amount,
        position_scale=1.0,
        margin_required=margin,
        raw_qty=raw_qty,
        note="ok",
    )
