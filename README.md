Coin Dash · AI 自主决策 SE
=========================

概述
----
全开放版：DeepSeek（或 Mock）负责所有开仓/止盈/止损/RR/仓位决策，系统只做数据校验、记忆记录、通知推送，并同步纸盘。新增“追涨杀跌”护栏：突破/反转必须二次确认后入场，噪声/区间禁止追价。

快速启动
--------
1. 环境（Python 3.10+）  
   ```bash
   pip install -r requirements.txt  # 或按 pyproject/poetry.lock 安装
   ```
2. 配置  
   - 复制 `.env.example` 为 `.env`，至少设置 `DEEPSEEK_API_KEY`，可选 `LARK_WEBHOOK` / `LARK_SIGNING_SECRET`。  
   - `config/config.yaml` 提供时间框架、数据源、DeepSeek、数据库、日志等基础参数。
3. 常用命令  
   - 回测：`python -m coin_dash.cli backtest --symbol BTCUSDT --csv data/sample/BTCUSDT_30m_2025-10_11.csv --deepseek`  
   - 实时单次：`python -m coin_dash.cli live --symbols BTCUSDT`  
   - 循环实时：`python -m coin_dash.cli live --symbols BTCUSDT,ETHUSDT --loop`  
   - 飞书卡片自检：`python -m coin_dash.cli cards-test --symbol BTCUSDT`  
   - 一键平仓：`python -m coin_dash.cli close-all --symbols BTCUSDT,ETHUSDT`

核心特性
--------
- **AI 全权决策**：关闭活跃度/静默/顺逆势等限制，AI 输出即执行；`position_size` 直接下单。  
- **多周期输入**：`compute_feature_context` 输出 30m/1h/4h/1d 特征与原始 `recent_ohlc`（30m×50、1h×40、4h×30），附环境标签、全局温度。  
- **反追涨杀跌**：Prompt 强制二次确认——突破不得追第一根（需回踩或 2-3 根收盘确认），回撤/反手不得砍第一根（需结构破位或动能衰减 2-3 根）；chaotic/ranging/noise 高时禁止追价，仅区间边缘入场。  
  - 辅助特征：`breakout_confirmed_*`、`momentum_decay_*`、`range_midzone_*`（30m/1h/4h）用于提示，但不硬拦截。  
  - 自评：AI 输出 `risk_score`/`quality_score`，quality<risk 默认 hold。  
- **纸盘联动**：实盘开仓/止盈/止损/复评平仓同步 `PaperBroker`，同向 30m 内冷却一单，防止频繁追价。  
- **共享记忆**：48h/10 轮上下文 + 跨币种共享事件，记录开仓、模式切换、复评、退出摘要。  
- **通知**：飞书信号/观望/复评/退出/绩效卡；RR 统一按入场/止盈/止损实算，时间展示为 UTC+8。

更新要点（近期）
---------------
- Prompt 增加二次确认硬规则、risk/quality 自评，引导避免追第一根。  
- 多周期新增确认/动能/区间中轴提示特征。  
- 实盘引入纸盘联动与同向冷却，支持风控观察。  
- DeepSeek 返回 risk_score/quality_score，决策对象兼容记录。

测试
----
- 2025-11-21：`pytest --maxfail=1 --disable-warnings`（4 passed）

注意
----
- 完全放开规则意味着需依赖 DeepSeek 自行风控，否则收益波动可能极大。  
- 数据缺失或价格为零会被兜底过滤。  
- 纸盘映射当前不跨进程持久化，如需重启续跑请额外持久化。

更多文档
--------
- 详见 `Coin Dash se.md` 获取完整流程、指标、目录说明。
