Coin Dash · AI 自主决策版
========================

当前 SE 版本彻底放开了人工风控：DeepSeek（或 Mock）负责所有开仓、止盈/止损、RR、仓位决策，系统仅负责数据校验、记忆记录与通知推送。

快速启动
--------
1. 环境准备（Python 3.10+）  
   ```bash
   pip install -r requirements.txt  # 或依据 pyproject/poetry.lock 安装
   ```
2. 配置  
   - 复制 `.env.example` 为 `.env`，至少设置 `DEEPSEEK_API_KEY`，可选 `LARK_WEBHOOK` / `LARK_SIGNING_SECRET`。  
   - `config/config.yaml` 仍提供时间框架、数据源、DeepSeek、数据库、日志等基础参数，风险阈值仅作兜底。  
3. 常用命令  
   - 回测：`python -m coin_dash.cli backtest --symbol BTCUSDT --csv data/sample/BTCUSDT_30m_2025-10_11.csv --deepseek`  
   - 实时单次：`python -m coin_dash.cli live --symbols BTCUSDT`  
   - 循环实时：`python -m coin_dash.cli live --symbols BTCUSDT,ETHUSDT --loop`  
   - 飞书卡片自检：`python -m coin_dash.cli cards-test --symbol BTCUSDT`  
   - 一键平仓：`python -m coin_dash.cli close-all --symbols BTCUSDT,ETHUSDT`

核心特性（摘自 `Coin Dash se.md`）
--------------------------------
- **AI 全权决策**：关闭市场活跃度/静默/顺逆势等限制；AI 说开仓就开，观望则推送观望卡。  
- **AI 定仓**：DeepSeek 返回 `position_size` 直接用于下单；未提供时按兜底风险百分比计算。  
- **多周期原始序列输入**：`compute_feature_context` 输出 `recent_ohlc`（30m×50、1h×40、4h×30 根，价格保留两位小数，成交量取 log10），回测/Live/复评都会把它与环境标签、全局温度一起传给 DeepSeek，Prompt 要求 AI 参考原始走势判断趋势/突破/止损。  
- **共享记忆**：保留 48h/10 轮上下文并在币种间共享模式切换、复评、退出摘要，帮助 AI 获取场景感知。  
- **通知 & 复评**：飞书信号卡标注“⚠AI完全自主决策版本”并展示 AI 仓位；观望/复评/退出卡片同步推送；`close-all` 会提示“请手动市价平仓”。  
- **状态管理**：`SignalManager` 无冷却限制；`StateManager` 持久化持仓、市场模式、安全模式、日结状态；`PerformanceTracker` 实时汇总盈亏并配合飞书绩效卡。

更新记录（当前版本）
------------------
- DeepSeek token 预算拦截/警告移除，调用量不再受限。  
- 飞书信号卡片时间改为 UTC+8 展示，便于本地查看。  
- RR 统一按入场/止盈/止损实算，保证卡片与执行一致。  
- 新增多周期 `recent_ohlc` 输入并写入 DeepSeek Prompt 与 CLI 示例，帮助 AI 看到“盘面”。  
- DeepSeek Prompt 升级为“终极版本”：明确原始 30m/1h/4h 序列最高优先级，指标/趋势/模式仅作参考；强调结构止损、动能、假突破与 RR 合理性。

关键改动
--------
- 移除市场活跃度过滤、静默、RR/止损距离/仓位倍率等约束，AI 输出即执行。  
- 同向信号冷却、仓位大小限制、趋势守护、逆势禁止等逻辑全部关闭。  
- 飞书信号卡展示 AI 仓位、RR、理由；复评/观望卡片同样标注“AI完全自主决策版本”。  
- 回测/Live/复评共享 48h/10 轮上下文与共享记忆，记录开仓、模式切换、复评、退出摘要。

测试
----
- 2025-11-21：`pytest --maxfail=1 --disable-warnings`（4 passed）

注意
----
- 完全放开规则意味着需要 DeepSeek 自行做好风控，否则收益波动可能极大。  
- 数据缺失或价格为零仍会被过滤，避免坏数据干扰。  
- 本目录为主工程，`old/` 仅保留迁移前备份，可按需清理。

更多文档
--------
- 更详细的流程、指标、目录结构，请参见 `Coin Dash se.md`（当前 SE 版本的完整说明）。***
