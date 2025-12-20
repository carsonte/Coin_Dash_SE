Coin Dash · AI 自主决策 SE
==========================

概览
----
Coin Dash 是一套多周期数字货币/黄金的自动化交易决策链，核心思路是“AI 全权 + 多模型委员会 + 数据与执行安全带”。系统负责数据管线、特征提取、决策记录、纸盘实盘同步与通知；模型只产出方向/价格/风控 JSON，避免手工规则干预。

近期更新
--------
- 多模型委员会：默认开启 `enable_multi_model_committee`，DeepSeek + gpt-4o-mini（Aizex）+ Qwen 共同投票；DeepSeek 权重最高（0.5），gpt-4o-mini 0.3，Qwen 0.2，可在开关关闭时回退到单 DeepSeek。
- 前置双模型门卫（B1）：gpt-4o-mini 0.6 + Qwen 0.4 快速判定“要不要调 DeepSeek”，冲突或低置信度直接返回 `no-trade`，理由写入决策元信息。
- 预过滤已是 Qwen（字段沿用 glm 兼容名）：`ai/filter_adapter.py` 用 Qwen 轻量判断是否进入后续链路（失败自动放行），配置使用 `QWEN_API_KEY/QWEN_API_BASE/QWEN_MODEL`，支持 fallback（`glm_fallback`）。
- LLM 客户端：新增 `call_gpt4omini`（Aizex）与 `call_qwen`；`scripts/smoke_llm_clients_smoke.py` 提供连通性冒烟；缺 Key 时测试自动跳过。
- 决策持久化：`ai_decisions` 记录增加 `model_name/committee_id/weight/is_final`，会落三条模型记录 + 委员会结果。
- 通知：飞书卡片推送失败会记录 warning，发送时显式使用 UTF-8。
- 通知：修复卡片中文乱码与异常控制字符（发送前统一清理/规范化）。
- 绩效卡片：交易类型输出本地化（顺势/逆小势/逆大势/未分类）。
- MT5 行情源：默认启用 `mt5_api`（price/ohlc），tick_volume 替换 volume，时间戳按秒对齐。
- 行情兜底：MT5 连续 3 次失败自动降级到 CCXT 备用源（Binance USDT-M），仅用于行情/纸盘，不触发实盘；备源成功 5 轮探活后自动切回 MT5，XAU 不在备源，异常会推飞书卡片。
- 备源安全：备源默认不新开仓，可配置 `backup_policy.allow_backup_open`；价差护栏 `deviation_pct`（默认 0.25%）超阈值时，新开仓/自动平仓都会暂停并仅提醒，卡片会标注当前源与点差风险。
- 卡片源标签：信号/复评/观望/价差提醒卡片会携带 `source=MT5` 或 `source=CCXT-Binance`，备源时提示可能存在点差，仅供决策/纸盘。
- 测试现状：`python -m pytest --disable-warnings` 全量通过；若需加载 .env，可用 `python -m dotenv run -- python -m pytest tests/test_llm_clients_smoke.py --disable-warnings --maxfail=1` 运行 LLM 冒烟。
- 绩效统计：实时/复评平仓会写入 performance 表；StateManager 基准权益来自 `backtest.initial_equity` 并持久化，重启后统计不漂移。

决策流程（不讲代码）
------------------
1. 数据与特征：管线按 30m/1h/4h/1d 采样行情，生成多周期特征、结构、趋势、市场模式标签，并附近期 OHLC 片段。
2. 预过滤（Qwen）：快速判定当前行情是否值得深度推理。失败默认放行；明确给出 `should_call_deepseek=False` 时跳过本轮。
3. 前置门卫（B1）：gpt-4o-mini + Qwen 小委员会投票是否调用 DeepSeek，冲突或置信度不足直接返回 `no-trade`，同时写入 `committee_front` 元信息。
4. 深度决策与终局委员会：DeepSeek 产出结构化执行方案；若开启多模型委员会，再由 DeepSeek + gpt-4o-mini + Qwen 复核投票，输出最终方向/置信/冲突等级。
5. 安全检查：基础合法性与安全护栏（价格顺序、RR 下限等）。
6. 执行与同步：写入 StateManager，推送飞书卡片，记录共享记忆；纸盘/实盘按配置同步持仓与复评。
7. 回测：与实盘共用同一决策链（含预过滤/前置门卫/委员会），用模拟撮合统计绩效。

配置要点
--------
- 环境变量：复制 `.env.example` 到 `.env`，至少设置
  - DeepSeek：`DEEPSEEK_API_KEY`（可选 `DEEPSEEK_API_BASE`）
  - gpt-4o-mini（Aizex）：`AIZEX_API_KEY`，`AIZEX_API_BASE`
  - Qwen 预过滤（兼容字段名 glm）：`QWEN_API_KEY`，`QWEN_API_BASE`（默认 `https://api.ezworkapi.top/v1/chat/completions`），`QWEN_MODEL`（默认 `qwen-turbo-2025-07-15`）
  - 飞书：`LARK_WEBHOOK`（可选 `LARK_SIGNING_SECRET`）
  - 数据源：如用 MT5，配置 `data.mt5_api.base_url`，符号用 MT5 合约名（`BTCUSDm`/`ETHUSDm`/`XAUUSDm`）
- 品种规格：`symbol_settings` 显式写合约大小/最小手数/步长/最大手数/杠杆与保证金缓冲；默认全品种 0.01 手步长、1:200 杠杆、margin_buffer=1.2（XAU 合约大小 100）。
- 行情与预热：基于 MT5 API 拉最小周期（如 15m/30m）时，会自动拉足高周期所需的底层 K 线（约等于最高周期 20 根所需的 bars，15m 基准约 2000 根），并且直接拉取 1h/4h/1d 周期作为高周期输入，避免数据不足导致交易类型 unknown；若行情为空/过旧/底层不足，会推飞书异常卡片并跳过开仓。
- 行情备源：主源 MT5，备源 CCXT Binance USDT-M。符号映射 BTCUSDm/ETHUSDm → `BTC/USDT:USDT`/`ETH/USDT:USDT`，XAU 无 USDT-M 合约会跳过。主源连续 3 次失败自动切备，备源连续 5 轮探活成功后切回主源，切换/失败都会推送飞书异常；备源默认不开新仓，价差超 `backup_policy.deviation_pct`（默认 0.25%）时仅提醒不执行。
- 开关：`enable_multi_model_committee` 控制是否使用三模型委员会；预过滤开关在 `config/config.yaml` 的 `glm_filter.enabled`（兼容字段名，实际 Qwen）。
- CLI 示例
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
- 全量：`python -m pytest --disable-warnings`
- LLM 冒烟（需 .env）：`python -m dotenv run -- python scripts/smoke_llm_clients.py`

注意
----
- 模型决策直接影响交易，请自备风控与额度限制。
- 数据缺口/无效价格会被过滤；预过滤异常默认放行 DeepSeek。
- 纸盘持久化暂未跨进程保留，长期运行需自行扩展。
- API 默认无鉴权且 CORS="*"，生产务必加鉴权/白名单。

更多文档
--------
- `config/config.yaml`：关键参数示例
- `docs/glm_filter.md`：预过滤结构说明（字段名沿用 glm，模型为 Qwen）

Position policy
---------------
- 实盘/回测均限制同一币种同时仅保留一单：发现已有持仓/信号会跳过新开仓，避免多单叠加。

Testing status
--------------
- 当前 16 项测试全部通过：`python -m pytest --disable-warnings`（LLM 冒烟在缺 Key 时自动跳过）
