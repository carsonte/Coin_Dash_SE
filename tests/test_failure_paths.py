from __future__ import annotations

from pathlib import Path

import pandas as pd

from coin_dash.ai.deepseek_adapter import DeepSeekClient
from coin_dash.backtest.engine import run_backtest
from coin_dash.config import load_config


ROOT = Path(__file__).resolve().parents[1]


def _load_sample_df() -> pd.DataFrame:
    path = ROOT / "data" / "sample" / "BTCUSDT_30m.sample.csv"
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    return df.set_index("timestamp").sort_index()


def test_backtest_handles_deepseek_exception(monkeypatch):
    cfg = load_config(None)
    cfg.qwen_filter.enabled = False
    cfg.deepseek.enabled = True
    cfg.enable_multi_model_committee = False
    cfg.notifications.backtest_enabled = False

    df = _load_sample_df()

    def _stub_enabled(self) -> bool:
        return True

    def _stub_decide_trade(self, symbol: str, payload: dict, glm_result=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(DeepSeekClient, "enabled", _stub_enabled)
    monkeypatch.setattr(DeepSeekClient, "decide_trade", _stub_decide_trade)

    report = run_backtest(df, "BTCUSDm", cfg, use_deepseek=True, db_services=None)
    assert report.summary["trades"] == 0
    assert any("deepseek_unavailable" in line for line in report.logs)


def test_backtest_handles_front_committee_failure(monkeypatch):
    cfg = load_config(None)
    cfg.qwen_filter.enabled = False
    cfg.deepseek.enabled = True
    cfg.enable_multi_model_committee = True
    cfg.notifications.backtest_enabled = False

    df = _load_sample_df()

    def _stub_enabled(self) -> bool:
        return True

    def _stub_decide_front_gate(*_args, **_kwargs):
        raise RuntimeError("front gate failed")

    monkeypatch.setattr(DeepSeekClient, "enabled", _stub_enabled)
    monkeypatch.setattr("coin_dash.backtest.engine.decide_front_gate_sync", _stub_decide_front_gate)

    report = run_backtest(df, "BTCUSDm", cfg, use_deepseek=True, db_services=None)
    assert report.summary["trades"] == 0
    assert any("front_committee_failed" in line for line in report.logs)
