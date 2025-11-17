from __future__ import annotations

import hashlib
import json
from typing import Any

from .models import Decision


def _log_fallback(reason: str, payload: Any, decision: Decision) -> None:
    try:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True) if payload is not None else ""
    except Exception:
        raw = str(payload)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8] if raw else "nohash"
    print(f"[fallback] reason={reason} hash={digest} decision_meta={decision.meta}")


def apply_fallback(decision: Decision, payload: Any = None) -> Decision:
    # Missing or invalid prices
    if decision.entry_price <= 0 or decision.stop_loss <= 0 or decision.take_profit <= 0:
        _log_fallback("invalid_price", payload, decision)
        decision.decision = "hold"
        decision.reason = f"{decision.reason} | fallback invalid_price"
        return decision

    # Wrong order for long/short
    if decision.decision == "open_long" and not (decision.stop_loss < decision.entry_price < decision.take_profit):
        _log_fallback("bad_long_levels", payload, decision)
        decision.decision = "hold"
        decision.reason = f"{decision.reason} | fallback bad_long_levels"
        return decision
    if decision.decision == "open_short" and not (decision.take_profit < decision.entry_price < decision.stop_loss):
        _log_fallback("bad_short_levels", payload, decision)
        decision.decision = "hold"
        decision.reason = f"{decision.reason} | fallback bad_short_levels"
        return decision

    # RR sanity
    if decision.risk_reward <= 0 or decision.risk_reward > 50:
        _log_fallback("rr_out_of_bounds", payload, decision)
        decision.decision = "hold"
        decision.reason = f"{decision.reason} | fallback rr_out_of_bounds"
        return decision

    return decision
