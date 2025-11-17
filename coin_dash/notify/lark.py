from __future__ import annotations

import base64
import hmac
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Sequence

import requests

if TYPE_CHECKING:
    from ..signals.manager import SignalRecord


@dataclass
class ReviewClosePayload:
    symbol: str
    side: str
    entry_price: float
    close_price: float
    pnl: float
    rr: float
    reason: str
    context: str
    confidence: float
    action: str = "提前平仓"


@dataclass
@dataclass
class WatchPayload:
    symbol: str
    reason: str
    market_note: str
    confidence: float | None = None
    next_check: datetime | None = None


@dataclass
class ReviewAdjustPayload:
    symbol: str
    side: str
    entry_price: float
    old_stop: float
    new_stop: float
    old_take: float
    new_take: float
    old_rr: float
    new_rr: float
    reason: str
    market_update: str
    next_review: datetime


@dataclass
class ExitEventPayload:
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    pnl: float
    rr: float
    duration: str
    reason: str
    exit_type: str  # take_profit | stop_loss


@dataclass
class ModeSwitchAlertPayload:
    symbol: str
    from_mode: str
    to_mode: str
    confidence: float
    affected_symbols: Sequence[str]
    risk_level: str
    suggestion: str
    indicators: str


@dataclass
class AnomalyAlertPayload:
    event_type: str
    severity: str
    occurred_at: datetime
    impact: str
    status: str
    actions: str


MODE_LABELS: Dict[str, str] = {
    "trending": "趋势",
    "channeling": "通道",
    "ranging": "区间",
    "breakout": "突破",
    "reversal": "反转",
    "mixed": "混合",
}


def _column(title: str, value: str) -> Dict:
    return {
        "tag": "column",
        "elements": [
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**{title}**\n{value}"},
            }
        ],
    }


_SIGNING_SECRET = os.getenv("LARK_SIGNING_SECRET", "")


def configure_lark_signing(secret: str | None) -> None:
    global _SIGNING_SECRET
    _SIGNING_SECRET = secret or ""


def _sign_payload(secret: str) -> Dict[str, str]:
    ts = str(int(time.time()))
    string_to_sign = f"{ts}\n{secret}"
    digest = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"), digestmod="sha256").digest()
    signature = base64.b64encode(digest).decode("utf-8")
    return {"timestamp": ts, "sign": signature}


def _post(webhook: str, card: Dict) -> None:
    if not webhook:
        return
    payload: Dict[str, Any] = {"msg_type": "interactive", "card": card}
    secret = _SIGNING_SECRET
    if secret:
        payload.update(_sign_payload(secret))
    try:
        resp = requests.post(
            webhook,
            json=payload,
            timeout=5,
        )
        resp.raise_for_status()
    except Exception:
        # 通知失败不阻塞主流程
        pass


def _fmt_local(dt: datetime, fmt: str = "%m-%d %H:%M") -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone(timedelta(hours=8))).strftime(fmt)






def send_signal_card(webhook: str, record: "SignalRecord", correlated: bool = False) -> None:
    decision = record.decision
    trend = record.trend
    mode = record.market_mode
    mode_name = MODE_LABELS.get(mode.name.lower(), mode.name)
    if getattr(mode, "trend_direction", "neutral") != "neutral" and mode.name.lower() == "trending":
        arrow = "UP" if mode.trend_direction == "up" else "DOWN"
        mode_name = f"{mode_name}{arrow}"
    trade_type = record.trade_type
    direction = "多头" if decision.decision == "open_long" else "空头"
    trade_labels = {
        "trend": "顺势",
        "reverse_minor": "逆小势",
        "reverse_major": "逆大势",
        "unknown": "未分类",
    }
    position_hint = {
        "trend": "标准仓位",
        "reverse_minor": "轻仓",
        "reverse_major": "试探仓",
        "unknown": "谨慎",
    }.get(trade_type, "标准仓位")

    body_lines = [
        "🤖 **AI完全自主决策版本**：无人工规则限制，AI 自主设定止盈/止损/仓位",
        f"🎯 **方向**：{direction}",
        f"📈 **市场模式**：{mode_name} · {mode.confidence * 100:.1f}%",
        f"📊 **趋势一致性**：{trend.grade} · {trend.score:.1f}%",
        f"🧭 **交易类型**：{trade_labels.get(trade_type, trade_type)}",
        f"⚡ **AI仓位**：{getattr(decision, 'position_size', 0.0):.4f}",
        f"💡 **建议仓位**：{position_hint}",
    ]
    if correlated:
        body_lines.append("⚠️ **高相关风险：与其他币种同向信号重合**")

    elements: list[dict] = [
        {"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(body_lines)}},
        {
            "tag": "column_set",
            "flex_mode": "none",
            "columns": [
                _column("RR", f"{decision.risk_reward:.2f}"),
                _column("置信度", f"{decision.confidence:.1f}"),
                _column("有效期", record.expires_at.strftime("%m-%d %H:%M UTC")),
                _column("AI仓位", f"{getattr(decision, 'position_size', 0.0):.4f}"),
            ],
        },
        {
            "tag": "column_set",
            "columns": [
                _column("入场价", f"{decision.entry_price:.2f}"),
                _column("止损价", f"{decision.stop_loss:.2f}"),
                _column("止盈价", f"{decision.take_profit:.2f}"),
            ],
        },
    ]

    if record.notes:
        notes = "\n".join(f"- {n}" for n in record.notes)
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"📝 **附注**：\n{notes}"}})

    elements.extend(
        [
            {"tag": "hr"},
            {
                "tag": "note",
                "elements": [
                    {"tag": "plain_text", "content": "🤖 AI完全自主决策版本 · 无人工规则限制"},
                    {"tag": "plain_text", "content": f"🧠 理由：{decision.reason}"},
                ],
            },
        ]
    )

    card = {
        "config": {"wide_screen_mode": True, "enable_forward": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"🤖 AI完全自主决策版本 | {record.symbol} {direction} 信号"},
            "template": "blue",
        },
        "elements": elements,
    }
    _post(webhook, card)

def send_performance_card(webhook: str, summary: Dict, modes: Dict, trade_types: Dict, symbols: Dict | None = None) -> None:
    columns = [
                    _column("模拟资金", f"{summary.get('equity', 0):.2f}"),
        _column("已平仓笔数", str(summary.get("closed", 0))),
        _column("总计胜率", f"{summary.get('win_rate', 0):.1%}"),
    ]
    columns2 = [
        _column("总盈亏", f"{summary.get('pnl_total', 0):.2f}"),
        _column("收益因子", f"{summary.get('profit_factor', 0):.2f}"),
        _column("触发次数", str(summary.get("trades", 0))),
    ]
    elements: List[Dict] = [
        {"tag": "column_set", "columns": columns},
        {"tag": "column_set", "columns": columns2},
    ]
    if modes:
        mode_lines = ["**按市场模式**"]
        for name, stats in modes.items():
            label = MODE_LABELS.get(str(name).lower(), name)
            mode_lines.append(
                f"- {label}: 胜率 {stats.get('win_rate', 0):.1%} | 平均RR {stats.get('avg_rr', 0):.2f} | 盈亏 {stats.get('pnl', 0):.2f}"
            )
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(mode_lines)}})
    if trade_types:
        type_lines = ["**按交易类型**"]
        for name, stats in trade_types.items():
            type_lines.append(
                f"- {name}: 胜率 {stats.get('win_rate', 0):.1%} | 平均RR {stats.get('avg_rr', 0):.2f} | 盈亏 {stats.get('pnl', 0):.2f}"
            )
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(type_lines)}})
    if symbols:
        symbol_lines = ["**按币种**"]
        for name, stats in symbols.items():
            symbol_lines.append(
                f"- {name}: 胜率 {stats.get('win_rate', 0):.1%} | 成交 {stats.get('count', 0)} | 盈亏 {stats.get('pnl', 0):.2f}"
            )
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(symbol_lines)}})

    card = {
        "config": {"wide_screen_mode": True, "enable_forward": True},
        "header": {
            "title": {"tag": "plain_text", "content": "Coin Dash 绩效概览"},
            "template": "purple",
        },
        "elements": elements,
    }
    _post(webhook, card)


def send_review_close_card(webhook: str, payload: ReviewClosePayload) -> None:
    card = {
        "config": {"wide_screen_mode": True, "enable_forward": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"⚠️ {payload.symbol} 复评：{payload.action}"},
            "template": "turquoise",
        },
        "elements": [
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"🎯 **方向**：{payload.side} · 置信度 {payload.confidence:.1f}%"},
            },
            {
                "tag": "column_set",
                "columns": [
                    _column("入场价", f"{payload.entry_price:.2f}"),
                    _column("平仓价", f"{payload.close_price:.2f}"),
                    _column("总盈亏", f"{payload.pnl:.2f}"),
                ],
            },
            {
                "tag": "column_set",
                "columns": [
                    _column("RR", f"{payload.rr:.2f}"),
                    _column("执行动作", payload.action),
                ],
            },
            {"tag": "hr"},
            {"tag": "div", "text": {"tag": "lark_md", "content": f"🧠 **决策理由**：{payload.reason}"}},
            {"tag": "note", "elements": [{"tag": "plain_text", "content": f"上下文：{payload.context}"}]},
        ],
    }
    _post(webhook, card)


def send_review_adjust_card(webhook: str, payload: ReviewAdjustPayload) -> None:
    card = {
        "config": {"wide_screen_mode": True, "enable_forward": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"🔄 {payload.symbol} 复评：止盈/止损调整"},
            "template": "turquoise",
        },
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": f"🎯 **方向**：{payload.side} · 入场 {payload.entry_price:.2f}"}},
            {
                "tag": "column_set",
                "columns": [
                    _column("原止损", f"{payload.old_stop:.2f}"),
                    _column("新止损", f"{payload.new_stop:.2f}"),
                    _column("变动", f"{payload.new_stop - payload.old_stop:+.2f}"),
                ],
            },
            {
                "tag": "column_set",
                "columns": [
                    _column("原止盈", f"{payload.old_take:.2f}"),
                    _column("新止盈", f"{payload.new_take:.2f}"),
                    _column("变动", f"{payload.new_take - payload.old_take:+.2f}"),
                ],
            },
            {
                "tag": "column_set",
                "columns": [
                    _column("原RR", f"{payload.old_rr:.2f}"),
                    _column("新RR", f"{payload.new_rr:.2f}"),
                    _column("下次复评", _fmt_local(payload.next_review)),
                ],
            },
            {"tag": "hr"},
            {"tag": "div", "text": {"tag": "lark_md", "content": f"📈 **市场变化**：{payload.market_update}"}},
            {"tag": "note", "elements": [{"tag": "plain_text", "content": f"🧠 理由：{payload.reason}"}]},
        ],
    }
    _post(webhook, card)


def send_exit_card(webhook: str, payload: ExitEventPayload) -> None:
    exit_label = "🎯 止盈完成" if payload.exit_type == "take_profit" else "🛑 止损触发"
    card = {
        "config": {"wide_screen_mode": True, "enable_forward": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"{exit_label} · {payload.symbol}"},
            "template": "red",
        },
        "elements": [
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"🎯 **方向**：{payload.side} · 持仓时长 {payload.duration}"},
            },
            {
                "tag": "column_set",
                "columns": [
                    _column("入场价", f"{payload.entry_price:.2f}"),
                    _column("离场价", f"{payload.exit_price:.2f}"),
                    _column("总盈亏", f"{payload.pnl:.2f}"),
                ],
            },
            {
                "tag": "column_set",
                "columns": [
                    _column("RR", f"{payload.rr:.2f}"),
                    _column("原因", payload.reason),
                ],
            },
        ],
    }
    _post(webhook, card)


def send_watch_card(webhook: str, payload: WatchPayload) -> None:
    next_review = _fmt_local(payload.next_check) if payload.next_check else "未设定"
    card = {
        "config": {"wide_screen_mode": True, "enable_forward": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"⏸ {payload.symbol} 观望"},
            "template": "yellow",
        },
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": "🎯 **方向**：观望"}},
            {
                "tag": "column_set",
                "columns": [
                    _column("市场摘要", payload.market_note),
                    _column("置信度", f"{payload.confidence:.1f}%" if payload.confidence is not None else "—"),
                    _column("下次复评", next_review),
                ],
            },
            {"tag": "note", "elements": [{"tag": "plain_text", "content": f"🧠 理由：{payload.reason}"}]},
        ],
    }
    _post(webhook, card)


def send_mode_alert_card(webhook: str, payload: ModeSwitchAlertPayload) -> None:
    from_label = MODE_LABELS.get(payload.from_mode.lower(), payload.from_mode)
    to_label = MODE_LABELS.get(payload.to_mode.lower(), payload.to_mode)
    affected = ", ".join(payload.affected_symbols)
    card = {
        "config": {"wide_screen_mode": True, "enable_forward": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"🔄 模式切换预警 · {payload.symbol}"},
            "template": "yellow",
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"从 **{from_label}** 切换到 **{to_label}**（{payload.confidence:.1f}%）",
                },
            },
            {
                "tag": "column_set",
                "columns": [
                    _column("影响币种", affected or "全部"),
                    _column("风险等级", payload.risk_level),
                    _column("建议", payload.suggestion),
                ],
            },
            {"tag": "div", "text": {"tag": "lark_md", "content": f"📈 **关键监控指标**：{payload.indicators}"}},
        ],
    }
    _post(webhook, card)


def send_anomaly_card(webhook: str, payload: AnomalyAlertPayload) -> None:
    card = {
        "config": {"wide_screen_mode": True, "enable_forward": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"🚨 异常告警 · {payload.event_type}"},
            "template": "red",
        },
        "elements": [
            {
                "tag": "column_set",
                "columns": [
                    _column("严重级别", payload.severity),
                    _column("发生时间", _fmt_local(payload.occurred_at, "%m-%d %H:%M:%S")),
                    _column("当前状态", payload.status),
                ],
            },
            {"tag": "div", "text": {"tag": "lark_md", "content": f"📍 **影响范围**：{payload.impact}"}},
            {"tag": "div", "text": {"tag": "lark_md", "content": f"🔧 **处置动作**：{payload.actions}"}},
        ],
    }
    _post(webhook, card)


def send_healthcheck_card(webhook: str, title: str, checks: Sequence[Dict[str, Any]]) -> None:
    """
    checks: [{'name': 'Lark Webhook', 'status': True/False/None, 'detail': 'xxx'}]
    """
    if not webhook:
        return
    all_ok = all(item.get("status") is not False for item in checks)
    template = "green" if all_ok else "red"
    rows: List[Dict] = []
    for item in checks:
        status = item.get("status")
        icon = "✅" if status is True else ("❌" if status is False else "ℹ️")
        detail = item.get("detail") or ""
        rows.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"{icon} **{item.get('name','未知项')}**\n{detail}",
                },
            }
        )
    card = {
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text", "content": f"🩺 {title}"}, "template": template},
        "elements": rows,
    }
    _post(webhook, card)
