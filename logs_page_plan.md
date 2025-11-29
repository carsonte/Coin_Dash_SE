# 日志页面与 run_id 实施说明

## 后端状态（已实现）
- CLI 增加 `--run-id`（backtest/live），默认自动生成 `hostname-<timestamp>`。示例：`python -m coin_dash.cli live --symbols BTCUSDm --loop --run-id my-vps-a`。
- 数据库：`ai_decisions`、`signals`、`trades`、`system_events` 均新增 `run_id` 列，已加 symbol/time、run_id/time 索引；system_events 有标准事件枚举，非枚举标记为 `CUSTOM`。
- 写入：决策日志、信号/交易、系统事件都会写入 run_id；老库会自动尝试补列。

## API（FastAPI，见 `coin_dash/api.py`）
- 启动：`uvicorn coin_dash.api:app --reload --port 8000`（先 `pip install -e .`），浏览器 `http://127.0.0.1:8000/docs` 调试。
- 统一规则：列表接口需 `start`、`end`（ISO），`limit/offset` 分页；过滤支持 symbol/run_id/decision_type/event_type/keyword。
- 接口速览：`/api/decisions`（轻量） + `/api/decisions/{id}`（详情）、`/api/system-events` + `/api/system-events/{id}`、`/api/trades`、`/api/signals`、`/api/stats`、`/api/enums/system-events`。
- 性能：先时间过滤再分页，列表只返摘要，详情接口再返完整 JSON。

## 前端（Arco Design）结构与方案
- 布局：顶部统计（Card+Statistic，可加折线）、筛选区（Form + RangePicker 必填 + Select/Input）、Tabs（决策/事件/交易/信号），列表 + Drawer 详情。
- 列宽固定、单行省略，横向滚动。摘要/描述列截断，悬浮 Tooltip 查看全文。
- 交互：默认最近 24h；关键词匹配 reason/description；run_id 可下拉或手输；可扩展导出接口返回 CSV。

## 本地查看前端
1) 启动后端：`uvicorn coin_dash.api:app --reload --port 8000`
2) 启动前端：`cd frontend && npm install`（首次需要），然后 `npm run dev`
3) 浏览器访问 `http://127.0.0.1:5173`；如后端地址不同，在 `frontend/.env` 设置 `VITE_API_BASE` 后重启前端。

## 运行与筛选提示
- 生成数据：跑 live/backtest 时尽量带 `--run-id`，便于筛选（不带会自动生成 `hostname-<timestamp>`）。
- 前端筛选：填时间窗（必填），run_id/品种/类型按需选择，点击查询；点“详情”再拉完整 JSON。

## 更新记录（近期）
- 表格布局：覆盖 `.arco-table-element` 强制 `table-layout: fixed`，th/td 单行省略；`.logs-table` 行高 48px，`rowClassName=log-row` 固定 padding/行高。
- 列宽（决策表）：时间160 / 品种100 / 类型100 / 置信度80 / Tokens120 / 延迟120 / 理由摘要300 / run_id120 / 操作80；事件表：时间160 / 事件140 / 级别80 / 描述300 / run_id120。
- 文案：符号改为“品种”，统计卡为“按品种数”。
- Tooltip：摘要/描述悬浮显示全文，行内保持单行省略。
- 构建：`npm run build` 已执行。
