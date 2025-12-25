from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Dict, Any, List, Literal

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
    validation_enabled: bool = False


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


class LiveCfg(BaseModel):
    symbols: List[str] = Field(default_factory=lambda: ["BTCUSDm", "XAUUSDm"])


class BackupPolicyCfg(BaseModel):
    # 备用源策略：是否允许备源新开仓、价差阈值（相对主源最后价）
    allow_backup_open: bool = False
    deviation_pct: float = 0.0025  # 0.25%


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


class SymbolSpecCfg(BaseModel):
    # 合约规格与风控限制（纸盘/回测/实盘统一）
    contract_size: float = 1.0
    min_lot: float = 0.01
    lot_step: float = 0.01
    max_lot: float = 100.0
    max_leverage: float = 200.0
    margin_buffer: float = 1.2  # 保证金预留系数，例如 1.2 = 多算 20%
    volatility_discount: float = 1.0  # 高波动品种可在此折扣仓位


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
    max_same_direction: int = 3


class PerformanceCfg(BaseModel):
    report_hour_utc8: int = 23
    safe_mode_enabled: bool = False
    safe_mode: Dict[str, int] = Field(default_factory=dict)
    adaptive_thresholds: Dict[str, float] = Field(default_factory=dict)
    instant_push: bool = True
    instant_cooldown_minutes: int = 30


class NotificationsCfg(BaseModel):
    lark_webhook: str = ""
    lark_signing_secret: str = ""
    backtest_enabled: bool = True
    ai_anomaly_enabled: bool = False
    ai_anomaly_cooldown_minutes: int = 30


class LogCfg(BaseModel):
    level: str = "INFO"


class GLMFilterCfg(BaseModel):
    enabled: bool = True
    on_error: Literal["call_deepseek", "hold"] = "call_deepseek"


class EventTriggersCfg(BaseModel):
    enabled: bool = False


class LLMEndpointCfg(BaseModel):
    api_key: str = ""
    api_base: str = "https://api.ezworkapi.top"
    model: str = "qwen-turbo-2025-07-15"
    http_referer: str = ""
    http_title: str = ""


class LLMClientsCfg(BaseModel):
    # Qwen 为主字段，glm 为兼容别名
    qwen: LLMEndpointCfg = Field(default_factory=LLMEndpointCfg)
    glm: LLMEndpointCfg = Field(default_factory=LLMEndpointCfg)
    glm_fallback: LLMEndpointCfg = Field(default_factory=LLMEndpointCfg)
    gpt4omini: LLMEndpointCfg = Field(
        default_factory=lambda: LLMEndpointCfg(api_key="", api_base="", model="gpt-4o-mini")
    )


class AppConfig(BaseModel):
    # 启用 B1 前置双模型委员会（gpt-4o-mini + qwen），决定是否调用 DeepSeek
    enable_multi_model_committee: bool = True
    symbols: List[str] = Field(default_factory=lambda: ["BTCUSDm", "ETHUSDm", "XAUUSDm"])
    symbol_settings: Dict[str, SymbolSpecCfg] = Field(default_factory=dict)
    timeframes: TimeframeCfg = Field(default_factory=TimeframeCfg)
    market_filter: MarketFilterCfg = Field(default_factory=MarketFilterCfg)
    data: DataCfg = Field(default_factory=DataCfg)
    llm: LLMClientsCfg = Field(default_factory=LLMClientsCfg)
    live: LiveCfg = Field(default_factory=LiveCfg)
    risk: RiskCfg = Field(default_factory=RiskCfg)
    signals: SignalsCfg = Field(default_factory=SignalsCfg)
    deepseek: DeepSeekCfg = Field(default_factory=DeepSeekCfg)
    exchange: ExchangeCfg = Field(default_factory=ExchangeCfg)
    backtest: BacktestCfg = Field(default_factory=BacktestCfg)
    database: DatabaseCfg = Field(default_factory=DatabaseCfg)
    performance: PerformanceCfg = Field(default_factory=PerformanceCfg)
    notifications: NotificationsCfg = Field(default_factory=NotificationsCfg)
    log: LogCfg = Field(default_factory=LogCfg)
    event_triggers: EventTriggersCfg = Field(default_factory=EventTriggersCfg)
    backup_policy: BackupPolicyCfg = Field(default_factory=BackupPolicyCfg)
    # qwen_filter 为主字段，glm_filter 兼容旧字段；load_config 会同步
    qwen_filter: GLMFilterCfg = Field(default_factory=GLMFilterCfg)
    glm_filter: GLMFilterCfg = Field(default_factory=GLMFilterCfg)


def load_config(path: Optional[Path] = None) -> AppConfig:
    cfg_path = path or ROOT / "config" / "config.yaml"
    with open(cfg_path, "r", encoding="utf-8") as f:
        data: Dict[str, Any] = yaml.safe_load(f) or {}
    # Ensure nested defaults exist
    data.setdefault("data", {})
    data.setdefault("live", {})
    data.setdefault("backup_policy", {})
    data.setdefault("symbol_settings", {})
    if not data["symbol_settings"]:
        for sym in data.get("symbols", []):
            data["symbol_settings"][sym] = {}
    else:
        for sym in data.get("symbols", []):
            data["symbol_settings"].setdefault(sym, {})
    # qwen_filter 为主字段，兼容 glm_filter
    data.setdefault("qwen_filter", data.get("glm_filter", {}))
    data.setdefault("glm_filter", data.get("qwen_filter", {}))
    llm_cfg = data.setdefault("llm", {})
    llm_cfg.setdefault("qwen", llm_cfg.get("glm", {}))
    llm_cfg.setdefault("glm", llm_cfg.get("qwen", {}))
    llm_cfg.setdefault("glm_fallback", llm_cfg.get("glm_fallback", {}))
    llm_cfg.setdefault("gpt4omini", llm_cfg.get("gpt4omini", {}))
    # 环境变量：QWEN/AIZEX（glm 字段兼容旧命名）
    env_qwen = os.getenv("QWEN_API_KEY") or os.getenv("GLM_API_KEY")
    env_qwen_base = os.getenv("QWEN_API_BASE") or os.getenv("GLM_API_BASE")
    env_qwen_model = os.getenv("QWEN_MODEL") or os.getenv("GLM_MODEL")
    if env_qwen:
        llm_cfg["qwen"]["api_key"] = env_qwen
        llm_cfg["glm"]["api_key"] = env_qwen
    if env_qwen_base:
        llm_cfg["qwen"]["api_base"] = env_qwen_base
        llm_cfg["glm"]["api_base"] = env_qwen_base
    if env_qwen_model:
        llm_cfg["qwen"]["model"] = env_qwen_model
        llm_cfg["glm"]["model"] = env_qwen_model
    env_glm_fb = os.getenv("GLM_FALLBACK_API_KEY")
    env_glm_fb_base = os.getenv("GLM_FALLBACK_API_BASE")
    if env_glm_fb:
        llm_cfg["glm_fallback"]["api_key"] = env_glm_fb
    if env_glm_fb_base:
        llm_cfg["glm_fallback"]["api_base"] = env_glm_fb_base
    env_gpt = os.getenv("AIZEX_API_KEY")
    env_gpt_base = os.getenv("AIZEX_API_BASE")
    if env_gpt:
        llm_cfg["gpt4omini"]["api_key"] = env_gpt
    if env_gpt_base:
        llm_cfg["gpt4omini"]["api_base"] = env_gpt_base
    # 兼容 OpenRouter HTTP 头
    referer = os.getenv("ZHIPU_HTTP_REFERER") or os.getenv("OPENROUTER_HTTP_REFERER")
    title = os.getenv("ZHIPU_HTTP_TITLE") or os.getenv("OPENROUTER_HTTP_TITLE")
    if referer:
        llm_cfg["qwen"]["http_referer"] = referer
        llm_cfg["glm"]["http_referer"] = referer
    if title:
        llm_cfg["qwen"]["http_title"] = title
        llm_cfg["glm"]["http_title"] = title

    env_notifications = data.setdefault("notifications", {})
    env_webhook = os.getenv("LARK_WEBHOOK")
    if env_webhook:
        env_notifications["lark_webhook"] = env_webhook
    env_sign = os.getenv("LARK_SIGNING_SECRET")
    if env_sign:
        env_notifications["lark_signing_secret"] = env_sign
    # 同步兼容字段
    data["glm_filter"] = data.get("qwen_filter", data.get("glm_filter", {}))
    llm_cfg["glm"] = llm_cfg.get("qwen", llm_cfg.get("glm", {}))
    return AppConfig(**data)

