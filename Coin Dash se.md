# Coin Dash SE（AI 全权决策版）说明

这份文档对应当前 SE 版本：所有交易/仓位/风控决策由 AI 全权生成，人为规则基本放开，仅保留数据有效性校验和状态记录。

## 核心差异（相对旧版）
- **无限制 AI 决策**：RR、止损距离、仓位倍率、顺/逆势等限制全部移除；低波/静默过滤关闭；同向冷却取消。AI 说开仓就开，观望则推送观望卡。
- **AI 定仓**：AI 返回 `position_size`，系统直接使用；未提供时按兜底风险百分比计算。
- **更长记忆**：对话 TTL 48h、10 轮，且有跨币种共享记忆，记录开仓/平仓/模式切换/复评决策摘要，便于持续参考。
- **观望/退出提示**：AI 观望时推送观望卡；一键平仓命令会推送“请手动市价平仓”卡片。

## 主要流程
1) **数据管线**：`LiveDataFetcher` 拉取最小周期 K 线，`DataPipeline` 重采样成 30m/1h/4h/1d（保留 15m），`validate_latest_bar` 仅过滤异常价量。
2) **特征与结构**：`compute_feature_context` 产出多周期指标、趋势画像、结构支撑阻力、市场模式；结果传递给 DeepSeek。
3) **AI 决策**：
   - 开仓：`DeepSeekClient.decide_trade` 使用专属+共享上下文，AI 自定方向/价位/RR/仓位。
   - 观望：返回 `hold` 时发送观望卡，包含理由与下次复评时间。
   - 复评：带入 48h/10 轮上下文+共享事件（含跨币种模式/退出摘要），AI 可自由调整或关闭。
4) **执行与状态**：`SignalManager` 不再限频；`StateManager` 记录持仓/阈值/模式；平仓事件写入卡片和 DB（如启用）。
5) **通知**：信号卡标注“🤖 AI完全自主决策版本”，展示 AI 仓位；退出/观望卡同步提示。
6) **一键平仓**：命令 `python -m coin_dash.cli close-all [--symbols ...]` 将当前持仓标记为手动平仓，并推送提示卡。

## 最新更新：多周期原始 K 线输入
- `compute_feature_context` 新增 `recent_ohlc` 字段，截取 30m/50 根、1h/40 根、4h/30 根的原始 OHLCV（价格保留两位小数、成交量取 log10），让 DeepSeek 能“看到”真实走势；  
- 回测、实时与复评全流程都会携带 `recent_ohlc`、环境标签和全局温度发送给 DeepSeek，AI 在开仓/观望/复评时都能据此判断趋势结构、突破有效性与止损位置；  
- DeepSeek Prompt 及 `python -m coin_dash.cli deepseek-test` 示例 payload 已同步更新，明确要求参考多周期序列；  
- 测试：`python -m pytest`（现有用例全部通过），验证新增字段不会影响既有逻辑。

## 运行方式
- 回测：`python -m coin_dash.cli backtest --symbol BTCUSDT --csv data/sample/BTCUSDT_30m_2025-10_11.csv`
- 实时单次：`python -m coin_dash.cli live --symbols BTCUSDT`
- 循环实时：`python -m coin_dash.cli live --symbols BTCUSDT,ETHUSDT --loop`
- 飞书卡片自检：`python -m coin_dash.cli cards-test --symbol BTCUSDT`
- 一键平仓：`python -m coin_dash.cli close-all --symbols BTCUSDT,ETHUSDT`

## 配置速览
- `config/config.yaml`：仍保留时间框架、数据源、DeepSeek 参数、数据库、日志等；风险/阈值字段仅兜底或兼容。
- 数据库：默认 `sqlite:///state/coin_dash_se.db`。
- 依赖 Python 3.10+，需设置 `.env`：`DEEPSEEK_API_KEY`（可选 `DEEPSEEK_API_BASE`）、`LARK_WEBHOOK`、`LARK_SIGNING_SECRET`。

## 指标与权重（供 AI 参考的基础特征）
- **趋势权重**（`TREND_WEIGHTS`）：1d=40、4h=30、1h=20、30m=10；趋势一致性评分分档 strong/medium/weak/chaotic。
- **市场模式权重**（`MODE_WEIGHTS`）：  
  - trending：1d 0.4 / 4h 0.3 / 1h 0.2 / 30m 0.1  
  - ranging：4h 0.4 / 1h 0.3 / 30m 0.2 / 1d 0.1  
  - breakout：1h 0.35 / 30m 0.3 / 4h 0.25 / 1d 0.1  
  - reversal：4h 0.35 / 1h 0.3 / 1d 0.2 / 30m 0.15  
  - channeling：4h 0.35 / 1h 0.3 / 30m 0.25 / 1d 0.1  
  模式选择参考 ATR/布林宽度/RSI 及 price 相对 EMA20/60。
- **特征集**：对 30m/1h/4h/1d 计算 price、EMA20/60、RSI14、ATR14、MACD 线/柱、布林带宽、成交量。
- **结构位**：30m/1h/4h/1d 提取近期支撑/阻力，用于卡片与参考（不强约束止损）。
- **ATR/成交量异常过滤**：仅对最新 K 线做 spike 过滤（1d 5x / 4h 4x / 1h 3.5x / 30m 3x / 15m 2.8x；成交量阈值类似）。
- **记忆与上下文**：开仓/复评/模式切换/退出会写入 48h/10 轮上下文；共享记忆用于跨币种参考（如 BTC/ETH 联动、整体风险情绪）。
- **风控参数**：配置文件保留 `risk_per_trade=1%`、`rr_bounds 1.5-5` 等作为兜底参考；但已不拦截 AI 的 RR/止损/仓位决策。

## 记忆与学习点（SE）
- 开仓/复评/模式切换/退出事件写入共享记忆，跨币种可见（如 BTC/ETH 联动、整体风险偏好）。
- 对话保留 48h、10 轮，方便 DeepSeek 参考近期市场变化、策略效果与风险偏好调整。
- 可按需扩展记忆事件：`DeepSeekClient.record_market_event / record_position_event / record_open_pattern`。

## 目录结构（关键文件）
- `coin_dash/cli.py`：命令入口（backtest/live/cards-test/deepseek-test/healthcheck/close-all）。
- `coin_dash/data/`：数据重采样、时间框架定义、校验、CCXT 拉取。
- `coin_dash/features/`：趋势画像、市场模式、特征汇总、结构位提取。
- `coin_dash/ai/`：DeepSeek 客户端、上下文记忆、Mock 决策、使用统计。
- `coin_dash/runtime/orchestrator.py`：实时调度、观望/开仓/复评/模式告警/退出处理。
- `coin_dash/backtest/engine.py`：回测循环、纸交易撮合、绩效汇总。
- `coin_dash/notify/lark.py`：飞书卡片（信号、观望、退出、模式、复评、绩效、健康检查）。
- `coin_dash/risk/`：仓位计算（AI 自定为主）、安全模式（默认停用）。
- `coin_dash/signals/`：信号状态管理（已移除冷却限制）。
- `coin_dash/state_manager.py`：持仓/阈值/模式/安全模式/日结状态持久化。
- `coin_dash/config.py` & `config/config.yaml`：配置模型与默认配置。
- `tests/`：基础测试示例。

## 目录结构（完整列表与说明）
- 顶层文件/目录
  - `Coin Dash se.md`：当前说明文档（AI 全权版）。
  - `README.md`：简版快速说明。
  - `.env/.env.example`：环境变量示例。
  - `pyproject.toml`、`poetry.lock`：依赖定义。
  - `Dockerfile`：容器构建。
  - `config/`：运行配置（`config.yaml`）。
  - `data/sample/`：示例 CSV。
  - `tests/`：单元测试。
  - `coin_dash/`：主代码。
- `coin_dash/ai/`
  - `deepseek_adapter.py`：DeepSeek 客户端（上下文记忆、开仓/复评）。
  - `context.py`：对话/共享记忆（TTL 48h，10 轮）。
  - `mock_adapter.py`：Mock 决策。
  - `models.py`：Decision/ReviewDecision（含 position_size）。
  - `usage_tracker.py`：调用预算统计。
- `coin_dash/backtest/`
  - `engine.py`：回测主循环、纸交易撮合、记录信号/绩效。
- `coin_dash/data/`
  - `fetcher.py`：CCXT 拉取与 DataFrame 转换。
  - `pipeline.py`：重采样、多周期对齐、异常校验。
  - `validators.py`：ATR/量能 spike 过滤。
  - `timeframes.py`：周期定义/转换。
  - `exchanges/ccxt_client.py`：CCXT 封装。
- `coin_dash/db/`
  - `services.py`：数据库服务聚合（K 线、交易、AI 日志、绩效、监控）。
  - 其余文件：客户端/模型/写入器/聚合器等。
- `coin_dash/exec/`
  - `paper.py`：纸交易撮合、订单/交易对象。
- `coin_dash/features/`
  - `multi_timeframe.py`：特征汇总。
  - `trend.py`：趋势画像与交易类型分类。
  - `market_mode.py`：市场模式识别与权重。
  - `structure.py`：支撑/阻力提取。
- `coin_dash/filtering/`
  - `market_state.py`、`silent_state.py`：活跃度/静默（AI 版已不拦截）。
- `coin_dash/indicators/`
  - `core.py`：EMA/RSI/ATR/MACD/布林等指标。
- `coin_dash/notify/`
  - `lark.py`：飞书卡片（信号、观望、复评、退出、模式、绩效、健康检查）。
- `coin_dash/performance/`
  - `tracker.py`：绩效聚合。
  - `safe_mode.py`：安全模式（默认停用）。
- `coin_dash/risk/`
  - `position.py`：仓位计算（优先用 AI 的 position_size）。
- `coin_dash/runtime/`
  - `orchestrator.py`：实时调度（开仓/观望/复评/模式告警/退出、记忆写入）。
- `coin_dash/signals/`
  - `manager.py`：信号状态管理（已移除冷却/同向限制）。
- `coin_dash/state_manager.py`：持仓/模式/日结/安全模式持久化。
- `coin_dash/utils/`
  - `time.py`：时间工具。
- `coin_dash/verify/`
  - `validator.py`：信号基础校验（仅拦截 hold 或价格非法）。
