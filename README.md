Coin Dash — AI 自主决策版
========================

这版把所有人工规则与保护阈值都放开了，交易由 AI 全权决定：止盈/止损、盈亏比、仓位大小、顺逆势与否，全由 DeepSeek（或 Mock）输出控制，系统不再做限制，只在数据为空时才会跳过。

快速启动
--------

1) 依赖（Python 3.10+）
```bash
pip install -r requirements.txt  # 如未生成，可按 pyproject/poetry.lock 安装
```

2) 配置
- 复制 `.env.example` 为 `.env`，设置至少 `DEEPSEEK_API_KEY`，可选 `LARK_WEBHOOK`/`LARK_SIGNING_SECRET`。
- `config/config.yaml` 仍然提供数据源等基础参数，但风险/阈值类参数已基本失效（AI 自主决策）。

3) 示例
- 回测示例：`python -m coin_dash.cli backtest --symbol BTCUSDT --csv data/sample/BTCUSDT_30m_2025-10_11.csv`
- 实时单次：`python -m coin_dash.cli live --symbols BTCUSDT`
- 飞书卡片自检：`python -m coin_dash.cli cards-test --symbol BTCUSDT`

更新记录（当前版）
--------
- DeepSeek token 预算拦截与警告已移除，调用量不再限制。
- 飞书信号卡片时间改为 UTC+8 展示，便于本地查看。
- 盈亏比（RR）在决策对象与卡片展示中统一按入场/止盈/止损实算，避免模型返回与价格不一致。

关键改动
--------
- 删除市场活跃度过滤、静默、RR/止损距离/仓位倍率等校验，AI 输出即执行。
- AI 返回新增 `position_size` 字段，直接用作下单仓位。
- 同向信号冷却与仓位大小限制移除；趋势守护、逆势禁止等逻辑移除。
- 飞书信号卡片标注“🤖 AI完全自主决策版本”，展示 AI 决定的仓位。

注意
----
- 因为完全放开规则，请确保 DeepSeek 提供合理的风控，否则结果可能高度波动。
- 数据缺失或价格为零时仍会跳过，以避免明显的坏数据。
- 本目录为主工程，`old/` 仅保留迁移前备份，可随时删除。***
