Coin Dash · AI 自主决策 SE
=========================

概览
----
Coin Dash 是一套多周期数字货币/黄金的自动化交易决策链，核心思路是“AI 全权 + 多模型委员会 + 数据与执行安全带”。系统负责数据管线、特征提取、决策记录、纸盘/实盘同步与通知；模型只产出方向/价格/风控 JSON，避免手工规则干扰。

近期更新
--------
- 多模型委员会：默认开启 `enable_multi_model_committee`，DeepSeek + gpt-4o-mini（Aizex）+ Qwen 共同投票；DeepSeek 权重最高（0.5），gpt-4o-mini 0.3，Qwen 0.2，可在开关关闭时回退到单 DeepSeek。
- 前置双模型门卫（B1）：gpt-4o-mini 0.6 + Qwen 0.4 快速判定“要不要走 DeepSeek”，冲突或低置信度直接 `no-trade`，理由会写入决策元信息。
- 预过滤改为 Qwen：`ai/filter_adapter.py` 使用 Qwen 轻量判定是否值得进入后续链路（失败自动放行），配置使用 `QWEN_API_KEY/QWEN_API_BASE/QWEN_MODEL`，并支持 fallback 配置（`glm_fallback`）。
- LLM 客户端：新增 `call_gpt4omini`（Aizex）与 `call_qwen`；`scripts/smoke_llm_clients_smoke.py` 提供连通性冒烟；缺 Key 时测试自动跳过。
- 决策持久化：`ai_decisions` 记录增加 `model_name/committee_id/weight/is_final`，会落三条模型记录 + 一条委员会最终结果（或前置委员会总结）。
- 通知：飞书卡片推送失败会记录 warning，便于排障；发送时显式使用 UTF-8。
- MT5 行情源：默认启用 `mt5_api`（/price /ohlc），tick_volume 替换 volume，时间戳按秒对齐。
- 测试现状：`python -m pytest --disable-warnings` 全量通过；若需加载 .env，可用 `python -m dotenv run -- python -m pytest tests/test_llm_clients_smoke.py --disable-warnings --maxfail=1` 运行 LLM 冒烟。

决策流程（不讲代码）
------------------
1. 数据与特征：管线按 30m/1h/4h/1d 采样行情，生成多周期特征、结构、趋势、市场模式标签，并附近期 OHLC 片段。
2. 预过滤（Qwen）：快速判断当次行情是否值得深度推理。失败默认放行；明确给出 `should_call_deepseek=False` 时跳过本轮。
3. 前置门卫（B1）：gpt-4o-mini + Qwen 小委员会投票是否调用 DeepSeek，冲突或置信度不足直接返回 `no-trade`，同时写入 `committee_front` 元信息。
4. 深度决策与终局委员会：DeepSeek 产出结构化执行方案；若开启多模型委员会，再由 DeepSeek + gpt-4o-mini + Qwen 复核投票，输出最终方向/置信度/冲突等级。
5. 安全检查：基础合法性与安全兜底（价格顺序、RR 下限等）。
6. 执行与同步：写入 StateManager，推送飞书卡片，记录共享记忆；纸盘/实盘按配置同步持仓与复评。
7. 回测：与实盘共用同一决策链（含预过滤/前置门卫/委员会），用模拟撮合统计绩效。

配置要点
--------
- 环境变量：复制 `.env.example` 到 `.env`，至少设置  
  - DeepSeek：`DEEPSEEK_API_KEY`（可选 `DEEPSEEK_API_BASE`）  
  - gpt-4o-mini（Aizex）：`AIZEX_API_KEY`，`AIZEX_API_BASE`（Aizex 控制台给出的 base）  
  - Qwen：`QWEN_API_KEY`，`QWEN_API_BASE`（默认 `https://api.ezworkapi.top/v1/chat/completions`），`QWEN_MODEL`（默认 `qwen-turbo-2025-07-15`）  
  - 飞书：`LARK_WEBHOOK`（可选 `LARK_SIGNING_SECRET`）  
  - 数据源：如使用 MT5，配置 `data.mt5_api.base_url`，符号用 MT5 合约名（`BTCUSDm`/`ETHUSDm`/`XAUUSDm`）
- 开关：`enable_multi_model_committee` 控制是否使用三模型委员会；预过滤开关在 `config/config.yaml` 的 `glm_filter.enabled`（已切到 Qwen 实现，但保留字段名兼容）。
- CLI 示例：  
  - 回测：`python -m coin_dash.cli backtest --symbol BTCUSDm --csv data/sample/BTCUSDT_30m_2025-10_11.csv --deepseek`  
  - 实时单次：`python -m coin_dash.cli live --symbols BTCUSDm`  
  - 循环实时：`python -m coin_dash.cli live --symbols BTCUSDm,ETHUSDm --loop`  
  - 飞书卡片自检：`python -m coin_dash.cli cards-test --symbol BTCUSDm`  
  - 一键平仓：`python -m coin_dash.cli close-all --symbols BTCUSDm,ETHUSDm`

目录速览
--------
- `coin_dash/data/` 数据拉取与重采样
- `coin_dash/features/` 多周期特征、结构、趋势、市场模式
- `coin_dash/ai/` DeepSeek 适配、预过滤（Qwen）、多模型委员会
- `coin_dash/runtime/orchestrator.py` 实时调度、信号/复评/纸盘/通知
- `coin_dash/backtest/engine.py` 回测主循环
- `coin_dash/exec/paper.py` 纸盘撮合
- `coin_dash/notify/lark.py` 飞书卡片
- `coin_dash/state_manager.py` 状态与绩效
- `coin_dash/db/` 数据库存取与决策持久化
- `scripts/smoke_llm_clients.py` LLM 连通性冒烟脚本

测试
----
- 全量：`python -m pytest --disable-warnings`（当前 15 项：13 通过，2 条 LLM 冒烟在缺 Key 时跳过）
- LLM 冒烟（加载 .env）：`python -m dotenv run -- python -m pytest tests/test_llm_clients_smoke.py --disable-warnings --maxfail=1`
- 冒烟脚本：`python -m dotenv run -- python scripts/smoke_llm_clients.py`

注意
----
- 模型决策直接影响交易，请自行做好风险控制与额度限制。
- 数据缺口/无效价格会被过滤；预过滤失败会放行 DeepSeek。
- 纸盘持久化暂未跨进程保留，如需长期运行请自行扩展。

更多文档
--------
- `config/config.yaml`：关键参数示例
- `docs/glm_filter.md`：预过滤结构说明（字段名沿用旧称，现由 Qwen 提供）
