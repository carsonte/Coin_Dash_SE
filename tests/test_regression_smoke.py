from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from coin_dash.ai.deepseek_adapter import DeepSeekClient
from coin_dash.ai.models import Decision
from coin_dash.backtest.engine import run_backtest
from coin_dash.config import load_config


ROOT = Path(__file__).resolve().parents[1]


def _load_sample_df() -> pd.DataFrame:
    path = ROOT / "data" / "sample" / "BTCUSDT_30m.sample.csv"
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    return df.set_index("timestamp").sort_index()


def test_backtest_pipeline_smoke(monkeypatch):
    cfg = load_config(None)
    cfg.qwen_filter.enabled = False
    cfg.deepseek.enabled = True
    cfg.enable_multi_model_committee = False
    cfg.notifications.backtest_enabled = False

    df = _load_sample_df()

    def _stub_enabled(self) -> bool:
        return True

    def _stub_decide_trade(self, symbol: str, payload: dict, glm_result=None) -> Decision:
        feats = payload.get("features") or {}
        price = feats.get("price_30m") or feats.get("price_1h") or feats.get("price_4h") or 0.0
        price = float(price or 0.0)
        if price <= 0:
            return Decision(
                "hold",
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                "stub_hold",
                position_size=0.0,
                meta={"adapter": "stub"},
            )
        risk = max(0.01, price * 0.002)
        stop = price - risk
        take = price + risk * 2.0
        rr = (take - price) / max(1e-9, price - stop)
        decision = Decision(
            "open_long",
            price,
            stop,
            take,
            rr,
            80.0,
            "stub_open",
            position_size=0.1,
            meta={"adapter": "stub"},
        )
        decision.recompute_rr()
        return decision

    monkeypatch.setattr(DeepSeekClient, "enabled", _stub_enabled)
    monkeypatch.setattr(DeepSeekClient, "decide_trade", _stub_decide_trade)

    report = run_backtest(df, "BTCUSDm", cfg, use_deepseek=True, db_services=None)
    assert report.summary["trades"] > 0
    assert report.summary["equity"] > 0.0


def test_deepseek_null_fields_hold(monkeypatch):
    cfg = load_config(None)
    cfg.qwen_filter.enabled = False
    cfg.deepseek.enabled = True

    client = DeepSeekClient(
        cfg.deepseek,
        glm_cfg=cfg.qwen_filter,
        glm_client_cfg=cfg.llm.qwen,
        glm_fallback_cfg=cfg.llm.glm_fallback,
    )

    payload = {"features": {"price_30m": 123.45}, "market_mode": "trending", "trend_grade": "strong"}

    def _stub_prefilter_gate(*_args, **_kwargs):
        return None

    def _stub_chat_completion(*_args, **_kwargs):
        content = json.dumps(
            {
                "decision": "hold",
                "entry_price": None,
                "stop_loss": None,
                "take_profit": None,
                "risk_reward": None,
                "confidence": None,
                "reason": "null_fields",
            }
        )
        return content, 0, 0.0

    monkeypatch.setattr(client, "_prefilter_gate", _stub_prefilter_gate)
    monkeypatch.setattr(client, "_chat_completion", _stub_chat_completion)

    decision = client.decide_trade("BTCUSDm", payload, glm_result=None)
    assert decision.decision == "hold"
    assert decision.entry_price == 123.45
    assert decision.stop_loss == 123.45
    assert decision.take_profit == 123.45
