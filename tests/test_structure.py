import pandas as pd

from coin_dash.ai.models import Decision
from coin_dash.features.structure import (
    StructureBundle,
    StructureLevels,
    compute_levels,
    stop_outside_structure,
)


def test_stop_outside_structure_allows_when_no_levels() -> None:
    decision = Decision(
        decision="open_long",
        entry_price=100.0,
        stop_loss=99.0,
        take_profit=104.0,
        risk_reward=2.0,
        confidence=80.0,
        reason="test",
    )
    bundle = StructureBundle(levels={})
    assert stop_outside_structure(decision, bundle, buffer_pct=0.01)


def test_stop_outside_structure_handles_basic_structure() -> None:
    decision = Decision(
        decision="open_short",
        entry_price=100.0,
        stop_loss=101.0,
        take_profit=95.0,
        risk_reward=2.0,
        confidence=75.0,
        reason="test",
    )
    levels = {
        "4h": StructureLevels(support=98.0, resistance=103.0, timeframe="4h"),
        "1d": StructureLevels(support=97.0, resistance=104.0, timeframe="1d"),
    }
    bundle = StructureBundle(levels=levels)
    assert stop_outside_structure(decision, bundle, buffer_pct=0.01)


def _flat_frame(low: float, high: float, periods: int, freq: str) -> pd.DataFrame:
    mid = (low + high) / 2
    idx = pd.date_range("2024-01-01", periods=periods, freq=freq)
    data = {
        "open": [mid] * periods,
        "high": [high] * periods,
        "low": [low] * periods,
        "close": [mid] * periods,
        "volume": [1_000] * periods,
    }
    return pd.DataFrame(data, index=idx)


def test_compute_levels_includes_short_timeframes() -> None:
    frames = {
        "30m": _flat_frame(9500.0, 9600.0, 100, "30min"),
        "1h": _flat_frame(9000.0, 9700.0, 80, "1h"),
        "4h": _flat_frame(8800.0, 9800.0, 60, "4h"),
        "1d": _flat_frame(8500.0, 9900.0, 40, "1d"),
    }
    bundle = compute_levels(frames, lookback=50, recent=10)
    assert {"30m", "1h", "4h", "1d"}.issubset(bundle.levels.keys())
    assert bundle.levels["30m"].support == 9500.0
    assert bundle.levels["1h"].resistance == 9700.0
