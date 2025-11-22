Coin Dash · AI 自主决策 SE
=========================

项目简介
--------
一个全开放的多周期数字货币交易助手：DeepSeek 负责开仓/止盈/止损/RR/仓位等全部决策，系统只做数据校验、记忆记录、纸盘同步和通知推送。新增追涨杀跌护栏，要求突破/反转必须二次确认，噪声/区间禁止追价，防止单根冲高/回撤带来的误伤。

核心能力
--------
- **AI 全权决策**：关闭人工限制，AI 输出即执行，`position_size` 直接下单；兜底风险/校验仅做数据安全检查。  
- **多周期输入**：30m/1h/4h/1d 特征 + 30m/1h/4h 原始 `recent_ohlc`，附环境标签与全局温度。  
- **反追涨杀跌**：Prompt 硬规则：突破不得追第一根，需回踩或 2-3 根收盘确认；回撤/反手不得砍第一根，需结构破位或动能衰减；chaotic/ranging/noise 高时禁止追价，仅区间边缘入场。  
  - 辅助提示特征：`breakout_confirmed_*`、`momentum_decay_*`、`range_midzone_*`（30m/1h/4h）；AI 输出 `risk_score`/`quality_score`，若 quality < risk 则应 hold。  
- **纸盘联动**：实盘开仓/止盈/止损/复评调整/平仓同步 `PaperBroker`，同向 30m 内冷却一单，避免频繁追价。  
- **共享记忆**：48h/10 轮上下文与跨币种共享事件，记录开仓、模式切换、复评、退出摘要。  
- **通知与复评**：飞书信号/观望/复评/退出/绩效卡，RR 按入场/止盈/止损实算，时间展示为 UTC+8。

架构模块
--------
- **数据管线**：`coin_dash/data/pipeline.py` 重采样 30m/1h/4h/1d，输出对齐的多周期数据。  
- **特征/结构/模式**：`features/multi_timeframe.py` 生成常规指标与确认/动能/区间中轴提示；`features/structure.py` 计算支撑/阻力；`features/market_mode.py` 检测市场模式。  
- **AI 适配层**：`ai/deepseek_adapter.py` 组织 Prompt、风险/质量提示、解析决策；`ai/safe_fallback.py` 做价格/RR 合法性兜底。  
- **调度与状态**：`runtime/orchestrator.py` 实时调度、信号生成、复评、通知推送、纸盘同步；`state_manager.py` 管理持仓/模式/绩效。  
- **回测/纸盘**：`backtest/engine.py` 用同一决策链回测；`exec/paper.py` 纸盘撮合，实盘同步。  
- **通知**：`notify/lark.py` 飞书卡片（信号/观望/复评/退出/绩效）。  
- **数据库（可选）**：`db` 目录提供信号/行情/绩效记录。

运行方式
--------
- **实时**：`python -m coin_dash.cli live --symbols BTCUSDT,ETHUSDT --loop`（可配 webhook）；同向 30m 冷却一单，纸盘同步。  
- **回测**：`python -m coin_dash.cli backtest --symbol BTCUSDT --csv <path> --deepseek`（或用 Mock）。  
- **卡片自检**：`python -m coin_dash.cli cards-test --symbol BTCUSDT`。  
- **一键平仓**：`python -m coin_dash.cli close-all --symbols BTCUSDT,ETHUSDT`。

配置与环境
----------
- 环境：Python 3.10+。  
  ```bash
  pip install -r requirements.txt  # 或按 pyproject/poetry.lock 安装
  ```
- `.env`：至少 `DEEPSEEK_API_KEY`，可选 `LARK_WEBHOOK`、`LARK_SIGNING_SECRET`。  
- `config/config.yaml`：时间框架、数据源、DeepSeek、数据库、日志、安全模式等基础参数。

测试
----
- 2025-11-21：`pytest --maxfail=1 --disable-warnings`（4 passed）

注意
----
- 全开放规则需依赖 DeepSeek 自行风控，可能带来较大收益波动。  
- 数据缺失/价格为零会被兜底过滤。  
- 纸盘映射当前未跨进程持久化，如需重启续跑请额外保存。

更多文档
--------
- 详见 `Coin Dash se.md` 获取完整流程、指标、目录说明。
