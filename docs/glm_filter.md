# GLM 预过滤器（filter_adapter）

GLM-4.5-Flash 用作“市场状态过滤器 + 成本守门人”，在调用 DeepSeek 前先给出结构化的市场标签并决定是否放行。过滤逻辑与业务规则集中在 `coin_dash/ai/filter_adapter.py`。

## 输出结构（GlmFilterResult）

- `should_call_deepseek`: bool，最终是否允许调用 DeepSeek。
- `reason`: 简要原因，形如 `ok: ...` 或 `blocked: ...`。
- `trend_consistency`: `strong | medium | weak | conflicting`
- `volatility_status`: `low | normal | high | extreme`
- `structure_relevance`: `near_support | near_resistance | breakout_zone | mid_range | structure_missing`
- `pattern_candidate`: `none | breakout | reversal | trend_continuation`
- `danger_flags`: `["trend_conflict", "atr_extreme", "wick_noise", "whipsaw", "no_structure_edge", "structure_missing", "no_pattern_candidate", "low_liquidity", ...]`
- `met_conditions`: 命中的条件标签，如 `trend_ok / structure_ok / pattern_candidate_ok`
- `failed_conditions`: 未满足或被阻断的条件标签

调用返回的 JSON 会被解析为 `GlmFilterResult`，解析失败时按配置兜底。

## 决策逻辑（挡什么 / 放什么）

- 必挡（`should_call_deepseek = false`）：
  - `trend_consistency=conflicting`
  - `volatility_status=extreme`
  - `structure_relevance` 为 `mid_range` 或 `structure_missing`
  - `pattern_candidate=none`
  - `danger_flags` 含 `wick_noise/whipsaw/low_liquidity/chop_range` 等噪声/流动性风险
- 放行（`should_call_deepseek = true`）：
  - 趋势 `strong|medium`，波动 `normal|high`，结构在 `near_support|near_resistance|breakout_zone`，形态为 `breakout|reversal|trend_continuation`
  - 边界场景（趋势弱或波动偏高）标记为 `marginal` 可适度放行；若为复评场景（已有持仓），即使 marginal 也会放行

## 异常与兜底

- GLM 请求/解析失败时：
  - 记录 `prefilter_error`，按 `config.yaml` 的 `glm_filter.on_error` 选择兜底：
    - `call_deepseek`：放行 DeepSeek，reason 带错误标记
    - `hold`：直接观望

## 集成点

- 配置：`config/config.yaml`
  ```yaml
  glm_filter:
    enabled: true
    on_error: call_deepseek   # 或 hold
  ```
- Orchestrator：在 `_process_symbol` 中调用预过滤，拦截观望时会记录 system_event 并发送 Watch 卡；放行时把 `glm_filter_result` 透传给 DeepSeek。
- DeepSeek：`decide_trade/review_position` 在 Prompt 中包含 `glm_filter_result`（趋势一致性、波动状态、结构位置、形态候选、危险标签），用于提升决策质量。
