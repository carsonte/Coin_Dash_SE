from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Dict, Any, List

import yaml
from pydantic import BaseModel, Field


ROOT = Path(__file__).resolve().parents[1]


class TimeframeDef(BaseModel):
    minutes: int
    atr_spike: float
    volume_jump: float


class TimeframeCfg(BaseModel):
    lookback_bars: int = 320
    filter_fast: str = "30m"
    filter_slow: str = "1h"
    eth_aux: str = "15m"
    defs: Dict[str, TimeframeDef] = Field(default_factory=dict)


class MarketFilterCfg(BaseModel):
    score_thresholds: Dict[str, float] = Field(default_factory=dict)
    weights: Dict[str, float] = Field(default_factory=dict)
    smoothing_weights: Dict[str, float] = Field(default_factory=dict)
    silent: Dict[str, int] = Field(default_factory=dict)


class RRBoundsCfg(BaseModel):
    min: float = 1.5
    max: float = 3.5


class TradeTypeModifier(BaseModel):
    position_scale: float
    min_confidence: float
    min_rr: float
    stop_atr_mult: Optional[float] = None


class RiskCfg(BaseModel):
    risk_per_trade: float = 0.01
    rr_bounds: RRBoundsCfg = Field(default_factory=RRBoundsCfg)
    sl_atr_mult: float = 1.5
    tp_atr_mult: float = 3.0
    stop_buffer_pct: float = 0.02
    stop_atr_cap: float = 2.5
    trade_type_modifiers: Dict[str, TradeTypeModifier] = Field(default_factory=dict)


class DeepSeekBudgetCfg(BaseModel):
    daily_tokens: int = 0
    warn_ratio: float = 0.8


class DeepSeekRetryCfg(BaseModel):
    max_attempts: int = 3
    backoff_seconds: float = 1.5


class DataMT5APICfg(BaseModel):
    base_url: str = "http://localhost:8000"


class DataCfg(BaseModel):
    provider: str = "ccxt"  # ccxt | mt5_api
    mt5_api: DataMT5APICfg = Field(default_factory=DataMT5APICfg)


class DeepSeekCfg(BaseModel):
    enabled: bool = False
    model: str = "deepseek-chat"
    review_model: str = "deepseek-chat"
    api_base: str = "https://api.deepseek.com"
    timeout: int = 30
    temperature: float = 0.1
    max_tokens: int = 2000
    stream: bool = False
    budget: DeepSeekBudgetCfg = Field(default_factory=DeepSeekBudgetCfg)
    retry: DeepSeekRetryCfg = Field(default_factory=DeepSeekRetryCfg)


class ExchangeCfg(BaseModel):
    name: str = "binance"
    type: str = "futures"
    rate_limit: bool = True


class BacktestCfg(BaseModel):
    initial_equity: float = 10000.0
    fee_rate: float = 0.0004


class DatabaseCfg(BaseModel):
    enabled: bool = True
    dsn: str = "sqlite:///state/coin_dash.db"
    pool_size: int = 5
    echo: bool = False
    auto_migrate: bool = True


class SignalsCfg(BaseModel):
    cooldown_minutes: int = 30
    review_interval_minutes: int = 30
    review_price_atr: float = 0.8
    review_max_context: int = 5
    expiry_hours: Dict[str, int] = Field(default_factory=dict)
    max_same_direction: int = 1


class PerformanceCfg(BaseModel):
    report_hour_utc8: int = 23
    safe_mode: Dict[str, int] = Field(default_factory=dict)
    adaptive_thresholds: Dict[str, float] = Field(default_factory=dict)
    instant_push: bool = True
    instant_cooldown_minutes: int = 30


class NotificationsCfg(BaseModel):
    lark_webhook: str = ""
    lark_signing_secret: str = ""


class LogCfg(BaseModel):
    level: str = "INFO"


class AppConfig(BaseModel):
    symbols: List[str] = Field(default_factory=lambda: ["BTCUSDT"])
    timeframes: TimeframeCfg = Field(default_factory=TimeframeCfg)
    market_filter: MarketFilterCfg = Field(default_factory=MarketFilterCfg)
    data: DataCfg = Field(default_factory=DataCfg)
    risk: RiskCfg = Field(default_factory=RiskCfg)
    signals: SignalsCfg = Field(default_factory=SignalsCfg)
    deepseek: DeepSeekCfg = Field(default_factory=DeepSeekCfg)
    exchange: ExchangeCfg = Field(default_factory=ExchangeCfg)
    backtest: BacktestCfg = Field(default_factory=BacktestCfg)
    database: DatabaseCfg = Field(default_factory=DatabaseCfg)
    performance: PerformanceCfg = Field(default_factory=PerformanceCfg)
    notifications: NotificationsCfg = Field(default_factory=NotificationsCfg)
    log: LogCfg = Field(default_factory=LogCfg)


def load_config(path: Optional[Path] = None) -> AppConfig:
    cfg_path = path or ROOT / "config" / "config.yaml"
    with open(cfg_path, "r", encoding="utf-8") as f:
        data: Dict[str, Any] = yaml.safe_load(f) or {}
    # Ensure nested defaults exist
    data.setdefault("data", {})
    env_notifications = data.setdefault("notifications", {})
    env_webhook = os.getenv("LARK_WEBHOOK")
    if env_webhook:
        env_notifications["lark_webhook"] = env_webhook
    env_sign = os.getenv("LARK_SIGNING_SECRET")
    if env_sign:
        env_notifications["lark_signing_secret"] = env_sign
    return AppConfig(**data)
