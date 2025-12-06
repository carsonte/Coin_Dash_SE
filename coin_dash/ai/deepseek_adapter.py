from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

import requests

from ..config import DeepSeekCfg, GLMFilterCfg
from .filter_adapter import GlmFilterResult, PreFilterClient
from .context import ConversationManager
from .models import Decision, ReviewDecision
if TYPE_CHECKING:
    from ..db.ai_decision_logger import AIDecisionLogger


class DeepSeekClient:
    def __init__(
        self,
        cfg: DeepSeekCfg,
        glm_cfg: Optional[GLMFilterCfg] = None,
        conversation: Optional[ConversationManager] = None,
        decision_logger: Optional["AIDecisionLogger"] = None,
    ) -> None:
        self.cfg = cfg
        self.session = requests.Session()
        self.conversation = conversation or ConversationManager()
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        self.api_base = os.getenv("DEEPSEEK_API_BASE", cfg.api_base).rstrip("/")
        self.ai_logger = decision_logger
        self.prefilter = PreFilterClient(glm_cfg)

    def enabled(self) -> bool:
        return self.cfg.enabled and bool(self.api_key)

    def record_market_event(self, event: Dict[str, object]) -> None:
        self.conversation.add_shared_event(event)

    def record_position_event(self, position_id: str, symbol: str, event: Dict[str, object]) -> None:
        self.conversation.append(position_id, symbol, "system", json.dumps(event, ensure_ascii=False))

    def record_open_pattern(self, symbol: str, event: Dict[str, object]) -> None:
        self.conversation.append(f"open:{symbol}", symbol, "system", json.dumps(event, ensure_ascii=False))
        self.conversation.add_shared_event(event)

    def decide_trade(self, symbol: str, payload: Dict[str, Any]) -> Decision:
        # Pre-filter: small/quiet market may skip DeepSeek to省调用；强触发已在 filter_adapter 兜底。
        prefilter = self._prefilter_gate(payload)
        if prefilter:
            payload["glm_filter_result"] = prefilter.model_dump_safe()
        if prefilter and not prefilter.should_call_deepseek:
            price = self._price_from_payload(payload)
            reason = prefilter.reason or "prefilter_hold"
            return Decision(
                decision="hold",
                entry_price=price,
                stop_loss=price,
                take_profit=price,
                risk_reward=0.0,
                confidence=0.0,
                reason=reason,
                meta={"adapter": "prefilter", "glm_filter": payload.get("glm_filter_result")},
            )
        context = self.conversation.get_context(f"open:{symbol}", symbol)
        shared = self.conversation.get_shared_context()
        prompt_text = self._build_trade_prompt(symbol, payload, context, shared)
        content, tokens_used, latency_ms = self._chat_completion(
            model=self.cfg.model,
            system_prompt=self._instruction_header(),
            user_content=prompt_text,
        )
        data = self._parse_json(content)
        self.conversation.append(
            f"open:{symbol}",
            symbol,
            "assistant",
            f"decision={data.get('decision')} rr={data.get('risk_reward')} pos={data.get('position_size')} reason={data.get('reason')}",
        )
        self.conversation.add_shared_event(
            {
                "type": "open_decision",
                "symbol": symbol,
                "mode": payload.get("market_mode"),
                "trend": payload.get("trend_grade"),
                "decision": data.get("decision"),
                "rr": data.get("risk_reward"),
            },
        )
        if self.ai_logger:
            self.ai_logger.log_decision(
                "decision",
                symbol,
                payload,
                data,
                tokens_used,
                latency_ms,
            )
        decision = Decision(
            decision=data.get("decision", "hold"),
            entry_price=float(data.get("entry_price", 0.0)),
            stop_loss=float(data.get("stop_loss", 0.0)),
            take_profit=float(data.get("take_profit", 0.0)),
            risk_reward=float(data.get("risk_reward", 0.0)),
            confidence=float(data.get("confidence", 0.0)),
            reason=str(data.get("reason", "")),
            position_size=self._to_float(data.get("position_size")) or 0.0,
            risk_score=self._to_float(data.get("risk_score")) or 0.0,
            quality_score=self._to_float(data.get("quality_score")) or 0.0,
            meta=data,
        )
        decision.recompute_rr()
        return decision

    def review_position(self, symbol: str, position_id: str, payload: Dict[str, Any]) -> ReviewDecision:
        note = payload.get("context_note") or f"review request for {symbol}"
        self.conversation.append(position_id, symbol, "user", note)
        context = self.conversation.get_context(position_id, symbol)
        shared = self.conversation.get_shared_context()
        # 复评同样受预过滤保护，保持 hold 返回格式一致。
        prefilter = self._prefilter_gate(payload, position_state=payload.get("position"), next_review_time=payload.get("next_review"))
        if prefilter:
            payload["glm_filter_result"] = prefilter.model_dump_safe()
        if prefilter and not prefilter.should_call_deepseek:
            return ReviewDecision(action="hold", reason=prefilter.reason or "prefilter_hold")
        review_prompt = self._build_review_prompt(symbol, payload, context, shared)
        content, tokens_used, latency_ms = self._chat_completion(
            model=self.cfg.review_model,
            system_prompt=self._instruction_header(review=True),
            user_content=review_prompt,
        )
        data = self._parse_json(content)
        self.conversation.append(
            position_id,
            symbol,
            "assistant",
            f"review_action={data.get('action')} sl={data.get('new_stop_loss')} tp={data.get('new_take_profit')} rr={data.get('new_rr')} reason={data.get('reason')}",
        )
        if self.ai_logger:
            self.ai_logger.log_decision("review", symbol, payload, data, tokens_used, latency_ms)
        if data.get("context_summary"):
            self.conversation.append(position_id, symbol, "assistant", data["context_summary"])
        return ReviewDecision(
            action=data.get("action", "hold"),
            new_stop_loss=self._to_float(data.get("new_stop_loss")),
            new_take_profit=self._to_float(data.get("new_take_profit")),
            new_rr=self._to_float(data.get("new_rr")),
            reason=str(data.get("reason", "")),
            context_summary=str(data.get("context_summary", "")),
            confidence=float(data.get("confidence", 0.0)),
        )

    def _chat_completion(self, model: str, system_prompt: str, user_content: str) -> Tuple[str, int, float]:
        if not self.enabled():
            raise RuntimeError("DeepSeek not enabled or API key missing")
        url = f"{self.api_base}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
        body = {
            "model": model,
            "messages": messages,
            "temperature": self.cfg.temperature,
            "max_tokens": self.cfg.max_tokens,
            "stream": self.cfg.stream,
            "response_format": {"type": "json_object"},
        }
        attempts = max(1, self.cfg.retry.max_attempts)
        backoff = max(0.5, self.cfg.retry.backoff_seconds)
        last_exc: Optional[Exception] = None
        for attempt in range(1, attempts + 1):
            try:
                start = time.perf_counter()
                resp = self.session.post(url, json=body, headers=headers, timeout=self.cfg.timeout)
                resp.raise_for_status()
                duration_ms = (time.perf_counter() - start) * 1000
                data = resp.json()
                tokens = data.get("usage", {}).get("total_tokens", 0)
                content = data["choices"][0]["message"]["content"]
                return content, tokens, duration_ms
            except requests.HTTPError as exc:
                last_exc = exc
                status = exc.response.status_code if exc.response is not None else None
                if status in (429, 500, 502, 503, 504) and attempt < attempts:
                    time.sleep(backoff * attempt)
                    continue
                raise
            except requests.RequestException as exc:
                last_exc = exc
                if attempt < attempts:
                    time.sleep(backoff * attempt)
                    continue
                raise
        if last_exc:
            raise last_exc
        raise RuntimeError("DeepSeek request failed unexpectedly")

    def _instruction_header(self, review: bool = False) -> str:
        if review:
            role = "复评"
            return (
                "Reply strictly in JSON and keep all explanations in Simplified Chinese.\n"
                f"当前任务：{role}。\n"
                "你是一位专业的多周期趋势交易分析师，与你对话的系统会提供完整的市场信息，包括技术指标、趋势评分、市场结构信息，以及多周期原始 OHLCV 序列。\n"
                "=== 核心规则 ===\n"
                "1. 原始多周期序列（30m/1h/4h）是最重要的信息源，具有最高优先级。\n"
                "   - 用于判断趋势方向、结构位置、突破有效性、震荡宽度、动能变化、吸筹出货、假突破与失败形态。\n"
                "   - 当指标与原始序列矛盾时，以原始序列为准。\n"
                "2. 技术指标仅作为数学总结：\n"
                "   - EMA20/60、RSI14、MACD、ATR、布林带宽、成交量等指标用于辅助理解，而不是决定方向。\n"
                "   - 指标背离、动能变化、趋势一致性，仅作为参考。\n"
                "3. 趋势评分/模式识别仅为提示性信息：\n"
                "   - 你可以参考趋势评分（strong/medium/weak/chaotic）和 market_mode（trending/ranging/breakout/reversal）。\n"
                "   - 但最终判断必须由你结合原始序列得出。\n"
                "4. 多周期执行逻辑：1h 定义主方向，30m 负责执行与入场细节，4h 仅用于风险过滤与极端背离警示，不要求完全一致。\n"
                "5. 入场确认与区间处理（硬规则，违背则默认 hold）：\n"
                "   - 突破第一根不追，第二根收盘确认或回踩确认后允许入场（可结合 breakout_confirmed_* 等特征）。\n"
                "   - 回撤/反手不得砍第一根，必须看到结构破位或动能衰减连续 2-3 根（如 momentum_decay_*），否则先持仓/复评。\n"
                "   - 区间可做小风险结构单：上沿尝试空、下沿尝试多，中轴/噪声区禁止开仓（可参考 range_midzone_* 避免中线入场）。\n"
                "强化趋势一致性执行（禁止观望）：\n"
                " - 当 trend_consistency_score >= 60% 时，不允许直接给出 hold，必须提供可执行方案：\n"
                "   1) 正常方向开仓（给出止损、RR 和 position_size）；\n"
                "   2) 或给出 20%~40% 仓位的轻仓试探单（probing entry）。\n"
                " - 趋势明确时不得选择观望。\n"
                "轻仓试探单逻辑：\n"
                " - 多周期方向偏一致但结构不完美（如 1h 明显多 / 30m 回调 / 4h 中性），必须给轻仓试探单：position_size=正常仓位的 20%~40%，止损放最近结构，RR 可 1.2~1.8，并在 reason 中注明“趋势方向明确但结构不完美，因此使用轻仓试探单等待确认”。轻仓试探单优先级高于观望。\n"
                "限制 HOLD 的条件（禁止随意观望）：\n"
                " - 仅在以下情况可 hold：多周期趋势完全冲突（4h 下/1h 上/30m 横盘）、价格处于明显噪声中轴（上下波动 <0.2 ATR）、3 根以上连续 Doji、成交量极度收缩且无结构（volume collapse）。其他情况不得给出 hold。\n"
                "观望必须结构化理由：\n"
                " - 当给出 hold 时，reason 中需包含结构化要素：导致观望的结构冲突/噪声原因、后续入场触发条件列表、当前风险提示、推荐复评时间（如 10-20 分钟）；禁止一句话含糊 hold。\n"
                "强化突破行为：\n"
                " - 突破第一根不追（保持），第二根突破确认且趋势一致性 >55% 时必须给结构单或轻仓试探单；仅当第二根出现假突破信号（长影+缩量）时可放弃。\n"
                "减少过度保守：\n"
                " - 不得因单根反向 K 线、单次影线假突破、RSI 中性、单次低波动就直接观望，这些情况需考虑轻仓试探单。\n"
                "整体倾向调整为“稳健进取”：趋势偏向明确时尽量参与，结构不完美用轻仓试探单，只有结构强冲突或噪声极重时才观望。\n"
                "# === 指标使用规则（减少观望，避免冲突） ===\n"
                "你会收到大量多周期指标（EMA/RSI/MACD/BOLL/ATR 等）。这些指标未来可能用于增强策略，但请按以下优先级和忽略规则处理：\n"
                "优先级：\n"
                " - 最高：4h 趋势方向、1h 趋势方向、30m 结构破位（HH/HL/LH/LL）、ATR 状态（扩张=可交易；收缩=轻仓或等待）。只要这些一致，必须给交易方案，不得观望。\n"
                " - 次优：MACD、RSI、BOLL 宽度、成交量变化（仅辅助，不得主导决策）。\n"
                " - 最低：任意周期 MACD 与 RSI 冲突；任意周期 EMA20/60 方向冲突；任意周期布林带尖峰（冲突时自动忽略）。\n"
                "冲突处理（不得因此观望）：\n"
                " - 30m 与 1h 趋势一致但 RSI/MACD 不一致；结构已突破但布林未张口；ATR 正常但 MACD 回调；EMA20 上穿但 RSI 不强——这些都必须尝试正常仓位或 20%~40% 轻仓试探单，不得 hold。\n"
                "观望唯一允许条件：多周期趋势完全相反（4h 与 1h/30m 全部冲突）、结构未形成（无 HH/HL 或 LL/LH）、ATR 极度收缩（明显无行情）、价格位于明确噪声中心（上下波动 <0.2 ATR）。除此之外不得 hold。\n"
                "若趋势一致 ≥60%，必须给方案：正常开仓或轻仓试探单（二选一），明确方向+止损+RR，绝不能观望。\n"
                "补充规则（优化活跃度）：\n"
                " - 当趋势为 weak 或 market_mode 为 ranging 时，如果出现微结构突破（例如：局部高点被小幅突破、有 2~3 根连续推动、短期 EMA20 出现轻微发散、或局部低点未被跌破）则应尝试给出“轻量方案”。\n"
                " - 轻量方案包括：小仓位试探（position_size 可为较小值）、RR 较低但结构合理的入场（RR=1.0~1.5 也允许），\n"
                " - 不得因为趋势弱或价格噪声稍高而完全拒绝给出方案。\n"
                " - 只要结构不反对，允许给出早期入场建议，但必须在 reason 中说明风险点。\n"
                " - 若确实无法判断方向，请在 reason 中明确说明“不确定，但给出保守方向偏好”，避免简单 hold。\n"
                "6. 噪声与波动处理：当 market_mode=chaotic/ranging 或 noise_level 高时，一般不追价；但若出现 ATR 扩张、布林张口、EMA 扩散等动能触发且有结构支撑，应给出可执行的入场方案，不得过度 HOLD。\n"
                "7. 止损逻辑：\n"
                "   - 必须基于结构位，不得使用随意的固定距离。\n"
                "   - 止损放在结构低点/高点外、之前的防守位之外，避免放在影线密集、容易被扫的位置。\n"
                "8. RR 要求：\n"
                "   - RR 不固定，但必须符合结构；若结构只支持 RR=1.0~1.5，也必须如实给出。\n"
                "   - 不得凭空给不合理的远止盈。\n"
                "9. 输出内容：\n"
                "   - 开仓/观望/调整/退出；方向（long/short）；入场价、止损价、止盈价；RR、position_size；\n"
                "   - 清晰逻辑：趋势结构 + 动能 + 风险点 + 预期行为。\n"
                "请结合以上规则，对后续的特征信息与多周期序列信息进行整体推理，以专业交易员的角度给出决策。\n"
            )
        return """角色与任务
------
你是一名专职做 BTC/ETH/XAU 等品种的多周期价格行为交易员，风格为：
- 稳健偏进攻：在风险可控、结构清晰时，倾向于给出可执行方案，而不是一味观望。
- 完全基于 K 线结构 + 多周期趋势 + 结构位 + 波动率 做决策，不依赖主观预测。
- 你的输出会被系统直接用于模拟/实盘执行，请认真决策。

系统会把你的 JSON 输出直接用于模拟/实盘执行，你负责：
- 决定 decision（open_long/open_short/hold）
- 决定入场价、止损价、止盈价（或 RR）
- 决定 position_size（用仓位大小表达信心强弱）
- 给出简明 reason、confidence 和下次复评时间（next_review_minutes）

输入数据（摘要）
-------------
系统会提供一份 `feature_context`，大致包含：
- 多周期原始 K 线：
  - 30m 最近 ~50 根
  - 1h 最近 ~40 根
  - 4h 最近 ~30 根
  这些用于你判断趋势、节奏和关键结构（突破、回踩、楔形、区间等）。
- 多周期指标与趋势评分：
  - 价格相对 EMA20/EMA60、RSI14、ATR14、MACD、布林带宽、成交量、趋势强度评分等；
  - 趋势权重大致为：1d > 4h > 1h > 30m，用于判断大方向与一致性。
- 市场模式：
  - trending / ranging / breakout / reversal / channeling 等，以及各周期权重。
- 结构位：
  - 多周期最近的支撑/阻力（价格水平），用于参考入场/止损/止盈。
- 波动与风险信息：
  - 当前 ATR、波动率是否异常扩张，量能是否异常放大等。
- 上下文与记忆：
  - 最近 48h 的开仓/复评/平仓摘要、模式切换、跨品种情绪等。

你不需要复述原始 JSON，只需要基于这些信息做出交易决策。

多周期决策框架
----------
严格按照以下思路理解多周期：

1. 1h = 主趋势与主战场方向
   - 判断 1h 是上升、下降还是震荡（结合价格相对 EMA20/60 和最近高低点结构）。
   - 默认情况下，你的多/空方向必须与 1h 主趋势保持一致；
     逆势单只能作为异常情况（RR 极佳、结构极强的反转点）。

2. 30m = 执行与入场节奏
   - 30m 用来精细化把握入场点：回踩、二次确认、假突破后的收回、结构突破后的回踩等。
   - 在 1h 上升趋势中，优先寻找 30m 的多头回调结束、向上重启的结构；
     在 1h 下降趋势中，优先寻找 30m 的反弹结束、向下重启的结构。

3. 4h（及 1d）= 风险过滤与关键位置
   - 用来识别大级别支撑/阻力、前高前低、重要区间的上沿/下沿。
   - 若当前价格紧贴 4h/1d 关键阻力/支撑，应：
     - 谨慎加仓；
     - 更偏向试探单或等待突破/假突破确认。

若 1h 与 4h 出现明显冲突：
- 若 1h 强趋势、4h 仍在趋势通道内：以 1h 为主，但减小仓位或提高 RR 要求。
- 若 4h 显示明显反转或极端区（多次测试的关键位），1h 只是最近的小级别趋势：
  优先看 4h 的信号，偏向轻仓或观望。

反追涨杀跌护栏（但不过度恐惧）
----------------------
你必须遵守以下原则，但不要因此拒绝所有机会：

1. 突破类机会
   - 对于明显的区间/趋势线/重要高低点突破：
     - 不追第一根放量突破 K 线；
     - 观察第二根/随后的 K 线是否确认（收盘站稳、放量、回踩不跌回关键位）。
     - 若确认有效，可在回踩确认结构附近或第二根确认 K 线收盘附近给出入场方案。

2. 趋势跟随
   - 在 trending 模式且趋势评分为 strong/medium 时：
     - 有合理回调 + 结构止损 + RR ≥ 2 的机会时，优先选择给出交易方案，而不是观望。
     - 可以用较小仓位（试探单）表达不确定，而不是简单 hold。

3. 区间与震荡
   - 在 ranging/chaotic 模式：
     - 仅在区间上沿附近做空、下沿附近做多，且止损紧贴区间之外；
     - 区间中部/噪声区禁止追价，只能轻仓或观望。

4. 极端波动与异常
   - ATR 或成交量出现极端 spike：
     - 若行情接近崩塌或针刺（极端单边且很可能反抽），偏向缩小仓位或观望；
     - 若是趋势放量突破且结构清晰，可以在确认后给出交易方案，但适当减小仓位。

决策优先级与“胆量”规则
------------------
为了避免过度观望，你做决定时必须按照下面的优先级进行判断：

1. 优先寻找“可接受的交易方案”
   - 满足条件：
     - 多周期趋势不严重冲突；
     - 入场点附近存在明确结构（前高/前低、区间边界、趋势线、EMA 支撑/压力等）；
     - 能给出 RR ≥ 2 的方案（止损放在合理结构外）。
   - 在满足以上条件时，你必须在下面三种中选一个：
     - 正常仓位交易；
     - 减半或更小仓位的试探单；
     - 若结构极差或 RR < 1.5 才允许放弃。

2. 试探单的使用规则
   - 当：
     - 趋势方向清晰，
     - 但入场结构不算完美（例如略微追价、上下影线较多、4h 位置尴尬），
   - 你应优先选择给出小仓位的试探单（例如标准仓位的 1/3~1/2），而不是直接观望。

3. 观望仅限这些情形
   只有当同时满足以下两类情况之一时，才允许最终 `hold`：
   - 结构混乱 + RR 不够：
     - 多周期趋势严重冲突，且找不到任何一个结构明确、RR ≥ 1.5 的交易方案。
   - 风险极端：
     - 波动率极端高，任何合理止损都需要放得很远，导致 RR 明显不划算。

在其它大部分情况下，只要能构造出一个方向明确 + 结构清晰 + RR 可接受的方案，就不要选择观望，而是通过仓位大小和 RR 要求来表达你的确定性。

输出格式与字段要求
--------------
你必须只输出一段 JSON，不要包含任何自然语言说明或 Markdown。

要求：
- 严格使用系统约定好的字段名（如 `decision`、`entry_price`、`stop_loss`、`take_profit`、`risk_reward`、`position_size`、`reason`、`confidence`、`next_review_minutes` 等），不要新增字段，也不要缺少字段。
- `decision` 只能是：`open_long`, `open_short`, `hold` 之一。
- 若为 `hold`：
  - 仍需给出 `reason` 和合理的 `next_review_minutes`，说明什么条件出现时会考虑介入（例如突破某区间、回踩某位置等）。
- 若为 `open_long` 或 `open_short`：
  - `entry_price`：基于当前价格及结构，给出合理的入场价（可以是市价附近或挂单位置）；
  - `stop_loss`：必须放在结构外，而不是随意几个点；
  - `take_profit` 和 `risk_reward`：与止损位置匹配，尽量保证 RR ≥ 2，特殊极佳结构时可拉大 RR；
  - `position_size`：结合风险偏好与行情质量，数值越大代表越有信心（系统会把该值直接映射为仓位）。

`reason` 字段请使用简洁的中文概括（1~3 句话），包括：
- 多周期的简要判断（例如“4h 多头通道，1h 多头回调结束，30m 出现上升吞没”）；
- 关键结构与入场逻辑（例如“在前高突破后的回踩支撑做多”）；
- 对风险点的说明（例如“上方 4h 压力位较近，因此减半仓位试探”）。

决策步骤（供你在内部思考使用）
------------------------
在做出最终 JSON 前，你可以按以下顺序在内部推理（不用写出来）：
1. 判断 1h/4h 趋势与市场模式（trending / ranging / breakout / reversal）。
2. 用 30m K 线找出最近的结构：高低点、区间、突破、回踩。
3. 确认是否存在顺势方向的可交易结构，并估算可行 RR。
4. 若存在可行结构：决定是正常仓位还是试探单。
5. 若完全不存在可行结构，才考虑观望，并明确“等待什么”。
6. 按照上面的字段要求，给出最终的 JSON。

现在请基于给定的 `feature_context` 做出一次完整决策，并严格按照要求输出 JSON。
"""

    def _instruction_block(self, review: bool = False) -> str:
        return "以上为决策/复评的核心规则。"

    def _trade_task_text(self) -> str:
        return (
            "请根据以上信息生成 JSON：\n"
            "- decision: open_long | open_short | hold\n"
            "- entry_price, stop_loss, take_profit, risk_reward（浮点数）\n"
            "- confidence: 0-100\n"
            "- reason: 简洁的中文决策原因\n"
            "- position_size: 若需要开仓请给出仓位大小（浮点数，未提供视为 0）\n"
            "- risk_score: 0-100，追第一根/噪声区追价/结构不清则加分\n"
            "- quality_score: 0-100，有二次确认/动能衰减过滤/区间边缘入场则加分\n"
            "务必描述风险与行情结构：若属于追第一根突破/回撤，或 quality_score 明显低于 risk_score，"
            "可以优先减少 position_size 或给出轻仓试探方案；"
            "只有在结构极差、风险远大于潜在收益时才选择 hold。不要输出除 JSON 之外的内容。"
        )

    def _review_task_text(self) -> str:
        return (
            "请根据以上信息评估当前持仓，输出 JSON：\n"
            "- action: close | adjust | hold\n"
            "- new_stop_loss, new_take_profit, new_rr（可为 null）\n"
            "- reason: 中文说明\n"
            "- context_summary: 对本次复评的简洁总结\n"
            "- confidence: 0-100\n"
            "若建议调整，请说明止损/止盈逻辑；若建议平仓，说明风险来源。"
        )

    def _build_trade_prompt(
        self,
        symbol: str,
        payload: Dict[str, Any],
        context: Optional[List[Any]],
        shared: Optional[List[Any]],
    ) -> str:
        market_bundle = {
            "symbol": symbol,
            "market_mode": payload.get("market_mode"),
            "mode_confidence": payload.get("mode_confidence"),
            "trend_score": payload.get("trend_score"),
            "trend_grade": payload.get("trend_grade"),
            "cycle_weights": payload.get("cycle_weights"),
            "features": payload.get("features"),
            "environment": payload.get("environment"),
            "global_temperature": payload.get("global_temperature"),
            "risk_score_hint": payload.get("risk_score_hint"),
            "quality_score_hint": payload.get("quality_score_hint"),
            "structure": payload.get("structure"),
            "glm_filter": payload.get("glm_filter_result"),
            "context": context or [],
            "shared_memory": shared or [],
        }
        features_json = json.dumps(market_bundle, ensure_ascii=False, indent=2)
        sequences_json = json.dumps(payload.get("recent_ohlc") or {}, ensure_ascii=False, indent=2)
        sections = [
            "=== Instruction ===",
            self._instruction_block(),
            "=== Market Features ===",
            features_json,
            "=== Multi-Timeframe Price Sequences ===",
            sequences_json,
            "=== End Sequences ===",
            "=== Task ===",
            self._trade_task_text(),
        ]
        return "\n".join(sections)

    def _build_review_prompt(
        self,
        symbol: str,
        payload: Dict[str, Any],
        context: Optional[List[Any]],
        shared: Optional[List[Any]],
    ) -> str:
        review_bundle = {
            "symbol": symbol,
            "position": payload.get("position"),
            "market": payload.get("market"),
            "environment": payload.get("environment"),
            "global_temperature": payload.get("global_temperature"),
            "glm_filter": payload.get("glm_filter_result"),
            "context": context or [],
            "shared_memory": shared or [],
        }
        features_json = json.dumps(review_bundle, ensure_ascii=False, indent=2)
        sequences_json = json.dumps(payload.get("recent_ohlc") or {}, ensure_ascii=False, indent=2)
        sections = [
            "=== Instruction ===",
            self._instruction_block(review=True),
            "=== Market Features ===",
            features_json,
            "=== Multi-Timeframe Price Sequences ===",
            sequences_json,
            "=== End Sequences ===",
            "=== Task ===",
            self._review_task_text(),
        ]
        return "\n".join(sections)

    @staticmethod
    def _parse_json(content: str) -> Dict[str, Any]:
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"无法解析 DeepSeek 返回内容为 JSON：{content}") from exc

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _prefilter_gate(
        self,
        payload: Dict[str, Any],
        position_state: Optional[Dict[str, Any]] = None,
        next_review_time: Optional[str] = None,
    ) -> Optional[GlmFilterResult]:
        try:
            if payload.get("glm_filter_result"):
                return GlmFilterResult.from_response(payload["glm_filter_result"])
            feature_context = {
                "features": payload.get("features") or {},
                "structure": payload.get("structure") or {},
                "market_mode": payload.get("market_mode"),
                "trend_grade": payload.get("trend_grade"),
                "mode_confidence": payload.get("mode_confidence"),
                "recent_ohlc": payload.get("recent_ohlc") or {},
            }
            return self.prefilter.should_call_deepseek(
                feature_context,
                position_state,
                next_review_time,
                is_review=bool(position_state),
            )
        except Exception:
            return None

    @staticmethod
    def _price_from_payload(payload: Dict[str, Any]) -> float:
        feats = payload.get("features") or {}
        for key in ("price_30m", "price_1h", "price_4h"):
            val = feats.get(key)
            if val is not None:
                try:
                    return float(val)
                except (TypeError, ValueError):
                    continue
        return 0.0
