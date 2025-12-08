Coin Dash · AI 自主决策 SE
=========================

概述
----
Coin Dash 是一套多周期数字货币交易助手，彻底放开人工规则，由 DeepSeek（或 Mock）直接给出开仓/止盈/止损/RR/仓位。系统负责数据清洗、校验、记忆记录、纸盘同步与通知推送，并在 Prompt 中附带“反追涨杀跌”护栏（突破/反转二次确认，噪声区间禁止追价）。

近期更新
--------
- **多模型委员会**：新增 `enable_multi_model_committee`（默认开启），DeepSeek + GPT-4o-mini(Aizex) + GLM-4.5V 权重 0.5/0.3/0.2 投票，冲突自动降级为观望，主决策附带委员会评分/冲突等级。
- **LLM 客户端**：新增 Aizex `gpt-4o-mini`、官方 `glm-4.5v` 客户端；`.env` 增加 `AIZEX_API_KEY`/`AIZEX_API_BASE`、`GLM_API_KEY`/`GLM_API_BASE`，提供 `scripts/smoke_llm_clients.py` 冒烟脚本。
- **决策持久化/接口**：`ai_decisions` 增加 `model_name`/`committee_id`/`weight`/`is_final`，三模型+委员会各一条记录；API `/api/decisions` 支持按 `committee_id`/`model_name` 过滤并返回新字段（向后兼容）。
- **决策 Prompt 更新**：突破第一根不追、第二根确认可入场；区间上沿空/下沿多（小风险结构单）；1h 定主方向、30m 执行、4h 仅作风险过滤；高噪声下若 ATR 扩张/布林张口/EMA 扩散触发需给出可执行方案，避免过度 HOLD；弱趋势/盘整且出现微结构突破（2-3 根连续推动、EMA20 轻微发散等）时须给出“小仓/低 RR 可执行方案”（允许 RR=1.0~1.5），不得因噪声略高直接全局观望。
- **MT5 实时行情**：新增 `mt5_api` 数据源（默认启用），从 MT5 API 拉取 `/ohlc`、`/price`；tick_volume → volume，秒级时间戳升序。`data.provider` 可切换回 `ccxt`。
- **符号切换**：默认符号改为 MT5 合约 `BTCUSDm`、`ETHUSDm`，并新增黄金 `XAUUSDm`（可在 `config.live.symbols` 直接跑多品种），live/backtest 示例命令同步更新。
- **成交价来源**：PaperBroker 开仓价使用最新 bid/ask（多头用 ask，空头用 bid），确保模拟成交贴合盘口。
- **GLM 预过滤升级**：预过滤输出结构化 `GlmFilterResult`（趋势一致性/波动/结构位置/形态候选/危险标签），按“市场状态过滤器 + 成本守门人”规则挡掉趋势冲突、ATR 极端、结构中轴/缺失、无形态候选、whipsaw/流动性差；`glm_filter.on_error` 可选 `call_deepseek/hold` 兜底，标签透传给 DeepSeek 提升决策上下文。
- **飞书推送验证**：`LARK_WEBHOOK` 写入 `.env` 后，可用 `python -m coin_dash.cli cards-test --symbol BTCUSDm` 快速发送测试卡片验证 webhook。
- **黄金休盘检测**：`XAUUSDm` 若 bid/ask 缺失或最新 tick 超 180s 判定休盘，跳过 K 线/特征/DeepSeek/信号/纸盘；恢复有新 tick 后自动继续。

核心特性
--------
- **AI 全权决策**：关闭活跃度/静默/顺逆势等限制，AI 输出即执行，`position_size` 直用。
- **反追涨杀跌护栏**：突破不得追第一根、回撤不砍第一根；chaotic/ranging/noise 高时禁止追价。
- **多周期输入**：30m/1h/4h/1d 特征 + 30m/1h/4h 原始 `recent_ohlc`，包含环境标签与全局温度。
- **提示特征**：`breakout_confirmed_*`/`momentum_decay_*`/`range_midzone_*` 仅用于 Prompt 引导。
- **纸盘联动**：实盘信号/止盈/止损/复评同步 `PaperBroker`，30m 内冷却一单。
- **复评与记忆**：保留 48h/10 轮上下文与跨币种共享事件，记录开仓、模式切换、复评、退出摘要。
- **通知**：飞书信号卡/观望/复评/退出/绩效卡，支持 DB 记录信号/行情/绩效。
- **GLM-4.5-air 预过滤层**：DeepSeek 前轻量判定是否需要调用，强触发（>0.3% 价格波动、结构突破、ATR 扩张、EMA 翻转、持仓 ±0.5 ATR 偏离）直接放行。

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
   - 数据源：`config/config.yaml` 里 `data.provider` 可选 `mt5_api`（默认）或 `ccxt`；MT5 API 需设置 `data.mt5_api.base_url`，符号使用 MT5 合约名（如 `BTCUSDm`、`ETHUSDm`、`XAUUSDm`）。  
   - Live 多品种：`config.live.symbols` 可定义 live 默认品种（示例：`BTCUSDm`,`ETHUSDm`,`XAUUSDm`）；CLI `--symbols` 会覆盖。  
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
- **预过滤 + DeepSeek 集成**：命中强触发直接进入 DeepSeek；GLM-4.5-Flash 返回结构化 `GlmFilterResult`（trend_consistency、volatility_status、structure_relevance、pattern_candidate、danger_flags、should_call_deepseek）；挡掉趋势冲突/ATR 极端/结构中轴或缺失/无形态候选/whipsaw/低流动性等。`glm_filter.on_error` 控制失败兜底（call_deepseek/hold）。标签会被透传到 DeepSeek Prompt 的“GLM Market Filter”段，指示大环境无需重复判断、专注形态真假与入场/风控设计；危险标签（atr_extreme/low_liquidity/wick_noise 等）会提醒无持仓偏观望、复评优先控仓。观望卡会标注“GLM 预过滤（未调用 DeepSeek）”。  
- **MT5 实时数据源**：`data.provider=mt5_api` 时，行情来自 MT5 API（`/price`、`/ohlc`），tick_volume → volume；K 线按秒级时间戳升序写入 pipeline/特征；PaperBroker 开仓价取最新 bid/ask（多头用 ask，空头用 bid），不再依赖 CCXT。
- **本地事件触发层**：`event_triggers.enabled=true` 时，仅在检测到本地波动/均线翻转/结构突破等事件后才进入 GLM / DeepSeek；默认 false 保持现有流程，便于在盘整期节约模型调用。
- **GLM 机会初筛器**：`glm_filter.enabled=true` 时，在调用 DeepSeek 前使用 GLM 快速判定是否值得继续；包含重试/超时/解析兜底，失败会放行 DeepSeek。

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
- 2025-11-24：`pytest --maxfail=1 --disable-warnings` · passed  
- 预过滤层：GLM 异常/解析错误按 `glm_filter.on_error` 兜底（默认放行 DeepSeek）；GLM 标签在决策记录中以 `glm_snapshot` 保存，便于前端/日志展示

注意
----
- AI 全权决策需自行风控，可能带来较大收益波动。  
- 数据缺失/价格为零会被过滤。  
- 纸盘映射当前未跨进程持久化，如需重启续跑请自行保存或扩展持久化。  
- risk/quality 仅作 Prompt 引导，不会阻塞执行链路。  

更多文档
--------
- 详见 `Coin Dash se.md` 获取流程细节、指标与目录说明。
- GLM 预过滤结构与规则：`docs/glm_filter.md`

日志前端与 API
---------------
- 后端日志接口：`uvicorn coin_dash.api:app --reload --port 8000`，Swagger：`http://127.0.0.1:8000/docs`，支持 `/api/decisions`、`/api/system-events`、`/api/stats` 等（时间窗+分页）。
- 前端日志面板：`cd frontend && npm install && npm run dev`，浏览器访问 `http://127.0.0.1:5173`；后端地址不同可在 `frontend/.env` 配置 `VITE_API_BASE`。
- 表格布局：固定列宽、单行省略（摘要/描述悬浮 Tooltip 查看全文），行高统一；列示例（决策表）：时间160/品种100/类型100/置信度80/Tokens120/延迟120/摘要300/run_id120/操作80。
- 使用建议：运行 live/backtest 时带 `--run-id`，便于前端筛选（未指定会自动生成 `hostname-<timestamp>`）；时间范围必填。
- 预过滤（GLM）：`ZHIPUAI_API_KEY` 配置后启用，模型可由 `ZHIPUAI_MODEL` 指定（如 `glm-4.5-air`）；预过滤请求默认超时 8s，内置 2 次重试（总 3 次），失败 fallback 放行 DeepSeek。
