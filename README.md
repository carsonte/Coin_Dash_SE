Coin Dash · AI 自主决策 SE
=========================

概述
----
Coin Dash 是一套多周期数字货币交易助手，彻底放开人工规则，由 DeepSeek（或 Mock）直接给出开仓/止盈/止损/RR/仓位。系统负责数据清洗、校验、记忆记录、纸盘同步与通知推送，并在 Prompt 中附带“反追涨杀跌”护栏（突破/反转二次确认，噪声区间禁止追价）。

核心特性
--------
- **AI 全权决策**：关闭活跃度/静默/顺逆势等限制，AI 输出即执行，`position_size` 直用。
- **反追涨杀跌护栏**：突破不得追第一根、回撤不砍第一根；chaotic/ranging/noise 高时禁止追价。
- **多周期输入**：30m/1h/4h/1d 特征 + 30m/1h/4h 原始 `recent_ohlc`，包含环境标签与全局温度。
- **提示特征**：`breakout_confirmed_*`/`momentum_decay_*`/`range_midzone_*` 仅用于 Prompt 引导。
- **纸盘联动**：实盘信号/止盈/止损/复评同步 `PaperBroker`，30m 内冷却一单。
- **复评与记忆**：保留 48h/10 轮上下文与跨币种共享事件，记录开仓、模式切换、复评、退出摘要。
- **通知**：飞书信号卡/观望/复评/退出/绩效卡，支持 DB 记录信号/行情/绩效。
- **GLM-4.5-Flash 预过滤层**：DeepSeek 前轻量判定是否需要调用，强触发（>0.3% 价格波动、结构突破、ATR 扩张、EMA 翻转、持仓 ±0.5 ATR 偏离）直接放行。

决策流程（实盘/回测共用）
------------------------
1. 数据管线：`data/pipeline.py` 重采样 30m/1h/4h/1d，生成对齐窗口。
2. 特征与结构：`features/multi_timeframe.py` 产出指标/确认提示；`features/structure.py` 识别支撑/阻力；`features/market_mode.py` 检测市场模式；`features/trend.py` 计算趋势评分。
3. 预过滤：`ai/filter_adapter.py` 调用 GLM-4.5-Flash 判定是否需要 DeepSeek（失败自动放行）。
4. Prompt 调用：`ai/deepseek_adapter.py` 组织上下文，向 DeepSeek 请求决策或复评。
5. 兜底与校验：`ai/safe_fallback.py` 检查价格顺序/RR，`verify/validator.py` 做基本合法性校验。
6. 执行与同步：`runtime/orchestrator.py` 写入 `StateManager`，推送飞书卡，记录共享记忆，同步纸盘并执行冷却。
7. 回测：`backtest/engine.py` 复用同一决策链，`exec/paper.py` 撮合并统计绩效。

运行方式
--------
1. 安装依赖（Python 3.10+）
   ```bash
   pip install -r requirements.txt  # 或按 pyproject/poetry.lock 安装
   ```
2. 配置环境  
   - 复制 `.env.example` 为 `.env`，至少设置 `DEEPSEEK_API_KEY`。  
   - 飞书通知：`LARK_WEBHOOK`、`LARK_SIGNING_SECRET`（可选）。  
   - 预过滤：`ZHIPUAI_API_KEY`（可选 `ZHIPUAI_API_BASE`），未配置时自动放行 DeepSeek。  
   - 数据源：`config/config.yaml` 里 `data.provider` 可选 `mt5_api`（默认）或 `ccxt`；MT5 API 需设置 `data.mt5_api.base_url`，符号使用 MT5 合约名（如 `BTCUSDm`、`ETHUSDm`）。  
   - 其它参数见 `config/config.yaml`（时间框架、数据源、DeepSeek、数据库、日志、安全模式等）。
3. 命令示例  
   - 回测：`python -m coin_dash.cli backtest --symbol BTCUSDm --csv data/sample/BTCUSDT_30m_2025-10_11.csv --deepseek`  
   - 实时单次：`python -m coin_dash.cli live --symbols BTCUSDm`  
   - 循环实时：`python -m coin_dash.cli live --symbols BTCUSDm,ETHUSDm --loop`  
   - 飞书卡片自检：`python -m coin_dash.cli cards-test --symbol BTCUSDm`  
   - 一键平仓：`python -m coin_dash.cli close-all --symbols BTCUSDm,ETHUSDm`

配置要点
--------
- **时间框架**：默认快周期 30m、慢周期 1h，附 4h/1d 供趋势与结构参考。  
- **信号冷却**：`signals.cooldown_minutes` 用于同向冷却（实盘纸盘同步）。  
- **复评**：`signals.review_interval_minutes`、`signals.review_price_atr` 控制定期/逆向波动触发复评。  
- **安全模式**：`performance.safe_mode` 可设置连续止损阈值（默认关闭）。  
- **通知**：`notifications` 中配置飞书 webhook 和签名秘钥。  
- **数据库**：`database` 可开启/关闭 SQLite 或其它 DSN。  
- **预过滤**：命中强触发直接进入 DeepSeek；否则 GLM-4.5-Flash 返回 `should_call`。异常/解析失败时放行；若 GLM 判定市场安静未调用 DeepSeek，观望卡会标注“GLM 预过滤（未调用 DeepSeek）”。  
- **MT5 实时数据源**：`data.provider=mt5_api` 时，行情来自 MT5 API（`/price`、`/ohlc`），tick_volume → volume；K 线按秒级时间戳升序写入 pipeline/特征；PaperBroker 开仓价取最新 bid/ask（多头用 ask，空头用 bid），不再依赖 CCXT。

目录索引
--------
- `coin_dash/data/` 数据拉取与重采样  
- `coin_dash/features/` 特征、结构、市场模式  
- `coin_dash/ai/` DeepSeek 适配、预过滤、模型定义、兜底  
- `coin_dash/runtime/orchestrator.py` 实时调度、信号/复评/纸盘/通知  
- `coin_dash/backtest/engine.py` 回测主循环  
- `coin_dash/exec/paper.py` 纸盘撮合  
- `coin_dash/notify/lark.py` 飞书卡片  
- `coin_dash/state_manager.py` 状态与绩效  
- `coin_dash/db/` 可选数据库接口

测试
----
- 2025-11-21：`pytest --maxfail=1 --disable-warnings` · passed  
- 预过滤层：未单测，GLM 请求异常或 JSON 解析错误自动放行 DeepSeek

注意
----
- AI 全权决策需自行风控，可能带来较大收益波动。  
- 数据缺失/价格为零会被过滤。  
- 纸盘映射当前未跨进程持久化，如需重启续跑请自行保存或扩展持久化。  
- risk/quality 仅作 Prompt 引导，不会阻塞执行链路。  

更多文档
--------
- 详见 `Coin Dash se.md` 获取流程细节、指标与目录说明。
